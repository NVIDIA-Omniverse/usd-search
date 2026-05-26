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

import { useState, useEffect } from 'react';
import { loadImage } from '../utils/imageLoader';

/**
 * Custom hook for loading images with state management
 * @param {string} assetUrl - Asset URL to load image for
 * @param {Function} getHeaders - Function to get auth headers
 * @param {string} apiUrl - Base API URL
 * @param {boolean} enabled - Whether to start loading immediately
 * @returns {Object} - { imageData, isLoading, error }
 */
export const useImageLoader = (assetUrl, getHeaders, apiUrl, enabled = true) => {
  const [imageData, setImageData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [attemptedUrls] = useState(new Set());

  useEffect(() => {
    // Only load if we haven't attempted this exact URL before
    if (!assetUrl || !enabled || attemptedUrls.has(assetUrl)) {
      return;
    }
    
    if (!getHeaders) {
      return;
    }

    // apiUrl can be empty string (uses relative URLs to current host)
    const effectiveApiUrl = apiUrl || '';

    // Mark this URL as attempted immediately to prevent re-runs
    attemptedUrls.add(assetUrl);
    setIsLoading(true);
    setError(null);

    loadImage(assetUrl, getHeaders, effectiveApiUrl)
      .then(data => {
        setImageData(data);
      })
      .catch(err => {
        setError(err);
        setImageData(null);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [assetUrl, enabled]); // Removed getHeaders and apiUrl from deps to prevent re-runs

  return {
    imageData,
    isLoading,
    error
  };
};

/**
 * Hook for managing multiple image loads
 * @param {string[]} assetUrls - Array of asset URLs
 * @param {Function} getHeaders - Function to get auth headers
 * @param {string} apiUrl - Base API URL
 * @returns {Object} - { images: Map, loadingStates: Map, errors: Map, progress }
 */
export const useMultipleImageLoader = (assetUrls, getHeaders, apiUrl) => {
  const [images, setImages] = useState(new Map());
  const [loadingStates, setLoadingStates] = useState(new Map());
  const [errors, setErrors] = useState(new Map());
  const [progress, setProgress] = useState({ loaded: 0, total: 0 });

  useEffect(() => {
    if (!assetUrls || assetUrls.length === 0) {
      setImages(new Map());
      setLoadingStates(new Map());
      setErrors(new Map());
      setProgress({ loaded: 0, total: 0 });
      return;
    }

    // Initialize loading states
    const initialLoadingStates = new Map();
    assetUrls.forEach(url => {
      if (url) {
        initialLoadingStates.set(url, true);
      }
    });
    setLoadingStates(initialLoadingStates);
    setProgress({ loaded: 0, total: assetUrls.filter(Boolean).length });

    // Load all images
    const loadPromises = assetUrls
      .filter(Boolean)
      .map(async (assetUrl) => {
        try {
          const imageData = await loadImage(assetUrl, getHeaders, apiUrl);
          
          // Update state atomically
          setImages(prev => new Map(prev).set(assetUrl, imageData));
          setLoadingStates(prev => new Map(prev).set(assetUrl, false));
          setProgress(prev => ({ ...prev, loaded: prev.loaded + 1 }));
          
        } catch (error) {
          console.error(`Failed to load image for ${assetUrl}:`, error);
          
          setErrors(prev => new Map(prev).set(assetUrl, error));
          setLoadingStates(prev => new Map(prev).set(assetUrl, false));
          setProgress(prev => ({ ...prev, loaded: prev.loaded + 1 }));
        }
      });

    // Wait for all images to complete (success or failure)
    Promise.allSettled(loadPromises);

  }, [assetUrls, getHeaders, apiUrl]);

  return {
    images,
    loadingStates,
    errors,
    progress
  };
};