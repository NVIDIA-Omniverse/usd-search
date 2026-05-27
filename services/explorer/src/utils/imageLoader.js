/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Image loader utility for fetching images from /v3/images API
 * Each URL is only attempted ONCE - no retries on any errors
 * Handles parallel downloads with global concurrency limiting
 */

import { getHighestScoringVectorImage } from './formatUtils';
import persistentCache from './persistentImageCache';

// Global configuration
const MAX_CONCURRENT_DOWNLOADS = 20;

// Global state
const imageCache = new Map();
const activeRequests = new Map(); // Track in-flight requests to prevent duplicates
const failedUrls = new Set(); // Track URLs that have failed in this session to prevent retries

// Image download queue management
class ImageDownloadQueue {
  constructor(maxConcurrent = MAX_CONCURRENT_DOWNLOADS) {
    this.maxConcurrent = maxConcurrent;
    this.active = 0;
    this.queue = [];
  }

  async add(downloadFn, priority = false) {
    return new Promise((resolve, reject) => {
      const queueItem = { downloadFn, resolve, reject };
      
      if (priority) {
        // Add to front of queue for high priority items (visible images)
        this.queue.unshift(queueItem);
      } else {
        // Add to back of queue for normal priority items (buffer images)
        this.queue.push(queueItem);
      }
      
      this.processQueue();
    });
  }

  async processQueue() {
    if (this.active >= this.maxConcurrent || this.queue.length === 0) {
      return;
    }

    const { downloadFn, resolve, reject } = this.queue.shift();
    this.active++;

    try {
      const result = await downloadFn();
      resolve(result);
    } catch (error) {
      reject(error);
    } finally {
      this.active--;
      this.processQueue(); // Process next item in queue
    }
  }
}

// Global download queue instance
const downloadQueue = new ImageDownloadQueue();

/**
 * Cache utilities
 */
const buildApiUrl = (apiUrl, assetUrl, imgOffset = 0, vectorImageId = null) => {
  // Derive the V3 images base URL from the apiUrl
  const imagesBaseUrl = apiUrl.replace(/\/v[0-9]+\/.*/, '/v3');

  const params = new URLSearchParams();

  if (vectorImageId) {
    params.set('image_key', vectorImageId);
  } else {
    params.set('asset_url', assetUrl);
    if (imgOffset > 0) {
      params.set('img_offset', imgOffset.toString());
    }
  }

  return `${imagesBaseUrl}/images?${params.toString()}`;
};

const getCachedImage = async (cacheKey) => {
  // Check in-memory cache first (fastest)
  const memoryCache = imageCache.get(cacheKey);
  if (memoryCache) {
    return memoryCache;
  }
  
  // Check persistent cache with timeout
  try {
    const persistentPromise = persistentCache.get(cacheKey);
    const timeoutPromise = new Promise((resolve) => setTimeout(() => resolve(null), 1000)); // 1 second timeout
    const persistentResult = await Promise.race([persistentPromise, timeoutPromise]);
    
    if (persistentResult) {
      // Restore to in-memory cache for quick access
      imageCache.set(cacheKey, persistentResult);
      return persistentResult;
    }
  } catch (e) {
    console.warn('⚠️ Persistent cache error:', e.message);
  }
  
  return null;
};

const setCachedImage = async (cacheKey, imageData) => {
  // Only cache successful responses - don't store anything for errors
  if (!imageData) {
    return;
  }
  
  const cacheEntry = {
    data: imageData,
    error: null,
    timestamp: Date.now()
  };
  
  // Store in memory cache (synchronous)
  imageCache.set(cacheKey, cacheEntry);
  
  // Store in persistent cache (asynchronous, don't wait)
  persistentCache.set(cacheKey, imageData, null, 0).catch(err => {
    console.warn('Failed to store image in persistent cache:', err);
  });
};

/**
 * Fetches image from /v3/images API endpoint
 * @param {string} assetUrl - The asset URL to fetch image for
 * @param {Function} getHeaders - Function to get auth headers
 * @param {string} apiUrl - Base API URL
 * @param {number} imgOffset - Image offset (default 0)
 * @param {Object} result - Search result object (for vector image detection on offset 0)
 * @returns {Promise<string>} Base64 encoded image data URL
 */
const fetchImageFromAPI = async (url, getHeaders) => {
  // Check if this URL has already failed in this session
  if (failedUrls.has(url)) {
    const error = new Error(`URL previously failed in this session`);
    error.status = 404; // Treat as 404 to prevent further attempts
    throw error;
  }

  const response = await fetch(url, {
    method: 'GET',
    headers: getHeaders(),
  });

  if (!response.ok) {
    // Mark this URL as failed to prevent future retries in this session
    failedUrls.add(url);
    
    const error = new Error(`Failed to fetch image: ${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }

  const blob = await response.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Failed to convert image to base64'));
    reader.readAsDataURL(blob);
  });
};

/**
 * Load image with caching and queue management - only tries once per URL+offset
 * @param {string} assetUrl - Asset URL to load image for
 * @param {Function} getHeaders - Function to get auth headers  
 * @param {string} apiUrl - Base API URL
 * @param {boolean} priority - Whether to prioritize this image (add to front of queue)
 * @param {number} imgOffset - Image offset (default 0)
 * @param {Object} result - Search result object (for vector image detection on offset 0)
 * @returns {Promise<string>} Promise resolving to base64 image data URL
 */
export const loadImage = async (assetUrl, getHeaders, apiUrl, priority = false, imgOffset = 0, result = null) => {
  if (!assetUrl) {
    throw new Error('Asset URL is required');
  }

  // Build request key for deduplication and caching
  let cacheKey;
  let shouldTryVector = false;
  
  // For offset 0, try vector image first if available
  if (imgOffset === 0 && result) {
    const vectorImageId = getHighestScoringVectorImage(result);
    if (vectorImageId) {
      cacheKey = buildApiUrl(apiUrl, assetUrl, imgOffset, vectorImageId);
      shouldTryVector = true;
    }
  }
  
  // If no vector image, use normal asset URL
  if (!shouldTryVector) {
    cacheKey = buildApiUrl(apiUrl, assetUrl, imgOffset);
  }

  // Check cache first
  const cached = await getCachedImage(cacheKey);
  if (cached && cached.data) {
    return cached.data;
  }

  // Check if this request is already in progress
  if (activeRequests.has(cacheKey)) {
    return activeRequests.get(cacheKey);
  }

  // Create the download promise
  const promise = (async () => {
    try {
      if (shouldTryVector) {
        try {
          const imageDataUrl = await fetchImageFromAPI(cacheKey, getHeaders);
          await setCachedImage(cacheKey, imageDataUrl);
          return imageDataUrl;
        } catch (error) {
          // Vector image failed, try normal asset call
          const normalCacheKey = buildApiUrl(apiUrl, assetUrl, imgOffset);
          
          // Check if normal image is already cached
          const normalCached = await getCachedImage(normalCacheKey);
          if (normalCached && normalCached.data) {
            return normalCached.data;
          }
          
          // Check if normal image request is already in progress
          if (activeRequests.has(normalCacheKey)) {
            return activeRequests.get(normalCacheKey);
          }
          
          // Add normal cache key to active requests to prevent other requests
          const normalPromise = (async () => {
            const imageDataUrl = await fetchImageFromAPI(normalCacheKey, getHeaders);
            await setCachedImage(normalCacheKey, imageDataUrl);
            return imageDataUrl;
          })();
          
          activeRequests.set(normalCacheKey, normalPromise);
          
          try {
            return await normalPromise;
          } finally {
            activeRequests.delete(normalCacheKey);
          }
        }
      } else {
        // Normal image call
        const imageDataUrl = await fetchImageFromAPI(cacheKey, getHeaders);
        await setCachedImage(cacheKey, imageDataUrl);
        return imageDataUrl;
      }
    } finally {
      activeRequests.delete(cacheKey);
    }
  })();

  activeRequests.set(cacheKey, promise);
  return promise;
};

/**
 * Preload multiple images in parallel
 * @param {string[]} assetUrls - Array of asset URLs to preload
 * @param {Function} getHeaders - Function to get auth headers
 * @param {string} apiUrl - Base API URL
 * @param {Function} onProgress - Optional progress callback (loaded, total)
 * @returns {Promise<Map<string, {data: string, error: Error}>>} Map of results
 */
export const preloadImages = async (assetUrls, getHeaders, apiUrl, onProgress = null) => {
  const results = new Map();
  let loaded = 0;
  
  const promises = assetUrls.map(async (assetUrl) => {
    try {
      const imageData = await loadImage(assetUrl, getHeaders, apiUrl);
      results.set(assetUrl, { data: imageData, error: null });
    } catch (error) {
      results.set(assetUrl, { data: null, error });
    } finally {
      loaded++;
      if (onProgress) {
        onProgress(loaded, assetUrls.length);
      }
    }
  });

  await Promise.allSettled(promises);
  return results;
};

/**
 * Progressive image loader that continuously tries offsets using full parallelism until 404
 * @param {string} assetUrl - Asset URL to load images for
 * @param {Function} getHeaders - Function to get auth headers
 * @param {string} apiUrl - Base API URL
 * @param {number} startOffset - Starting offset (default 1)
 * @param {number} maxParallel - Maximum parallel requests (uses global limit)
 * @param {Object} result - Search result object (for vector image detection on offset 0)
 * @returns {Promise<{images: Map<number, string>, maxOffset: number}>}
 */
export const loadProgressiveImages = async (assetUrl, getHeaders, apiUrl, startOffset = 1, maxParallel = MAX_CONCURRENT_DOWNLOADS, result = null) => {
  const images = new Map();
  
  // Always fetch offset 0 first (this will replace any existing cache entry with vector image if available)
  try {
    const offset0Image = await loadImage(assetUrl, getHeaders, apiUrl, false, 0, result);
    images.set(0, offset0Image);
  } catch (error) {
    // Offset 0 failed, but continue with other offsets
  }
  
  // Track active downloads and results
  const activeDownloads = new Map(); // offset -> Promise
  const completedOffsets = new Set();
  let nextOffsetToTry = startOffset;
  let foundEndOfImages = false;
  let consecutiveFailures = 0;
  
  const startDownload = (offset) => {
    const promise = loadImage(assetUrl, getHeaders, apiUrl, false, offset)
      .then(imageData => {
        images.set(offset, imageData);
        completedOffsets.add(offset);
        consecutiveFailures = 0; // Reset failure count on success
        return { offset, success: true, imageData };
      })
      .catch(error => {
        completedOffsets.add(offset);
        if (error.status === 404) {
          // Found end of images
          foundEndOfImages = true;
        } else {
          consecutiveFailures++;
        }
        return { offset, success: false, error };
      })
      .finally(() => {
        activeDownloads.delete(offset);
      });
    
    activeDownloads.set(offset, promise);
    return promise;
  };
  
  // Keep downloads running until we find the end or hit limits
  while (!foundEndOfImages && nextOffsetToTry < startOffset + 200) {
    // Fill up to maxParallel concurrent downloads
    while (activeDownloads.size < maxParallel && !foundEndOfImages && nextOffsetToTry < startOffset + 200) {
      startDownload(nextOffsetToTry);
      nextOffsetToTry++;
      
      // Stop if we have too many consecutive failures (likely no more images)
      if (consecutiveFailures >= 5) {
        foundEndOfImages = true;
        break;
      }
    }
    
    // Wait for at least one download to complete before continuing
    if (activeDownloads.size > 0) {
      await Promise.race(activeDownloads.values());
    }
    
    // If no active downloads and we haven't found end, we're done
    if (activeDownloads.size === 0 && !foundEndOfImages) {
      break;
    }
  }
  
  // Wait for all remaining downloads to complete
  if (activeDownloads.size > 0) {
    await Promise.allSettled(activeDownloads.values());
  }
  
  // Find the actual max offset from loaded images
  const loadedOffsets = Array.from(images.keys()).sort((a, b) => a - b);
  const maxOffset = loadedOffsets.length > 0 ? Math.max(...loadedOffsets) : startOffset - 1;
  
  return {
    images,
    maxOffset
  };
};

/**
 * Get all cached offsets for an asset URL (synchronous, only checks in-memory cache)
 * @param {string} assetUrl - Asset URL
 * @param {string} apiUrl - API base URL
 * @returns {number[]} Array of cached offset numbers
 */
export const getCachedOffsets = (assetUrl, apiUrl = '') => {
  const offsets = [];
  
  // Only check in-memory cache for performance (this is used for UI state)
  for (const [cacheKey, value] of imageCache.entries()) {
    // Check if this cache key is for the given assetUrl
    try {
      const url = new URL(cacheKey);
      const params = new URLSearchParams(url.search);
      
      if (params.get('asset_url') === assetUrl) {
        const imgOffset = parseInt(params.get('img_offset') || '0', 10);
        offsets.push(imgOffset);
      }
    } catch (e) {
      // Ignore malformed URLs
    }
  }
  
  return offsets.sort((a, b) => a - b);
};

/**
 * Clear active requests and failed URLs to allow retries on new searches
 */
export const clearActiveRequests = () => {
  activeRequests.clear();
  failedUrls.clear();
};

/**
 * Clear image cache (both in-memory and persistent)
 */
export const clearImageCache = async () => {
  imageCache.clear();
  await persistentCache.clear();
};

/**
 * Get cache stats for debugging
 */
export const getCacheStats = async () => {
  const persistentStats = await persistentCache.getStats();
  
  return {
    memory: {
      size: imageCache.size,
      activeDownloads: downloadQueue.active,
      queueLength: downloadQueue.queue.length
    },
    persistent: persistentStats
  };
};