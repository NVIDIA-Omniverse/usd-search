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

import { useEffect, useRef, useCallback } from 'react';
import { useMultipleIntersectionObserver } from './useIntersectionObserver';
import { loadImage } from '../utils/imageLoader';

/**
 * Smart image loading hook that only loads visible images + next page buffer
 * @param {Array} results - Array of search results with image data
 * @param {Function} getHeaders - Function to get auth headers
 * @param {string} apiUrl - Base API URL
 * @param {Object} options - Configuration options
 * @returns {Object} - Loading states and register function
 */
export const useSmartImageLoader = (
  results = [], 
  getHeaders, 
  apiUrl,
  {
    bufferSize = 10, // Number of additional images to load beyond visible ones
    rootMargin = '200px', // How far ahead to start loading
    enabled = true
  } = {}
) => {
  const loadingStates = useRef(new Map()); // id -> { loading, error, data }
  const loadPromises = useRef(new Map()); // Track ongoing loads to prevent duplicates
  const [registerElement, visibilityMap] = useMultipleIntersectionObserver({
    rootMargin,
    threshold: 0.1
  });


  // Load image for a specific item
  const loadImageForItem = useCallback(async (result, index, priority = false) => {
    if (!getHeaders) {
      return;
    }
    
    // apiUrl can be empty string (uses relative URLs to current host)
    const effectiveApiUrl = apiUrl || '';

    const id = result.id || `result-${index}`;
    const assetUrl = result?.source?.base_key || result?.source?.url || result?.id;
    
    if (!assetUrl) return;

    // Check if already loading
    if (loadPromises.current.has(id)) return;

    // Set loading state
    loadingStates.current.set(id, { 
      loading: true, 
      error: null, 
      data: null 
    });

    // Create load promise with priority
    const loadPromise = loadImage(assetUrl, getHeaders, effectiveApiUrl, priority)
      .then(imageData => {
        loadingStates.current.set(id, {
          loading: false,
          error: null,
          data: imageData
        });
      })
      .catch(error => {
        loadingStates.current.set(id, {
          loading: false,
          error,
          data: null
        });
      })
      .finally(() => {
        loadPromises.current.delete(id);
      });

    loadPromises.current.set(id, loadPromise);
  }, [getHeaders, apiUrl]);

  // Effect to load images for visible + buffer items
  useEffect(() => {
    if (!enabled) return;

    // Separate visible items from buffer items for priority loading
    const visibleItems = [];
    const bufferItems = [];
    
    if (results.length === 0) return;

    const visibleIndices = [];
    
    // Find all currently visible items
    results.forEach((result, index) => {
      const id = result.id || `result-${index}`;
      if (visibilityMap.get(id)) {
        visibleItems.push({ result, index });
        visibleIndices.push(index);
      }
    });

    // If nothing is visible yet, treat first page as high priority
    if (visibleIndices.length === 0) {
      for (let i = 0; i < Math.min(bufferSize, results.length); i++) {
        visibleItems.push({ result: results[i], index: i });
      }
    } else {
      // Add buffer items after the last visible item (normal priority)
      const maxVisibleIndex = Math.max(...visibleIndices);
      const bufferEnd = Math.min(maxVisibleIndex + bufferSize, results.length);
      
      for (let i = maxVisibleIndex + 1; i < bufferEnd; i++) {
        bufferItems.push({ result: results[i], index: i });
      }
    }

    // Load visible items first (high priority - front of queue)
    visibleItems.forEach(({ result, index }) => {
      const id = result.id || `result-${index}`;
      const currentState = loadingStates.current.get(id);
      
      if (!currentState || (!currentState.loading && !currentState.data && !currentState.error)) {
        loadImageForItem(result, index, true); // high priority
      }
    });

    // Then load buffer items (normal priority - back of queue)
    bufferItems.forEach(({ result, index }) => {
      const id = result.id || `result-${index}`;
      const currentState = loadingStates.current.get(id);
      
      if (!currentState || (!currentState.loading && !currentState.data && !currentState.error)) {
        loadImageForItem(result, index, false); // normal priority
      }
    });
  }, [results, visibilityMap, bufferSize, loadImageForItem, enabled]);

  // Get loading state for a specific item
  const getLoadingState = useCallback((result, index) => {
    const id = result.id || `result-${index}`;
    return loadingStates.current.get(id) || { 
      loading: false, 
      error: null, 
      data: null 
    };
  }, []);

  // Register an element for intersection observation
  const registerImageElement = useCallback((result, index, element) => {
    if (!element) return;
    const id = result.id || `result-${index}`;
    registerElement(id, element);
  }, [registerElement]);

  return {
    getLoadingState,
    registerImageElement,
    visibilityMap
  };
};