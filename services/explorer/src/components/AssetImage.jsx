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

import React from 'react';
import { useImageLoader } from '../hooks/useImageLoader';
import { ImageWithSkeleton } from './ImageSkeleton';

/**
 * Asset image component that loads images from /v3/images API
 * Falls back to base64 image data if available
 */
const AssetImage = ({ 
  result,
  getHeaders,
  apiUrl,
  width = "100%",
  height = "120px",
  borderRadius = "md",
  ...imageProps 
}) => {
  // Get asset URL for API call
  const assetUrl = result?.source?.base_key || result?.source?.url || result?.id;
  
  // Check if we have base64 image data as fallback
  const fallbackImage = result?.source?.image;
  
  // Load image from API
  const { imageData, isLoading, error } = useImageLoader(
    assetUrl, 
    getHeaders, 
    apiUrl, 
    !!assetUrl // Only enable if we have an asset URL
  );

  // Determine what to display
  let src = null;
  let hasError = false;
  let errorMessage = "No Image";

  if (imageData) {
    // Use API image data
    src = imageData;
  } else if (fallbackImage && !isLoading) {
    // Use fallback base64 image if API failed and we're not loading
    src = `data:image/png;base64,${fallbackImage}`;
  } else if (error && !fallbackImage) {
    // Show error state only if no fallback available
    hasError = true;
    
    // Customize error message based on error type
    if (error.status === 404) {
      errorMessage = "Image Not Found";
    } else if (error.status === 403) {
      errorMessage = "Access Denied";
    } else if (error.status >= 400 && error.status < 500) {
      errorMessage = "Invalid Request";
    } else if (error.status >= 500) {
      errorMessage = "Server Error";
    } else {
      errorMessage = "Load Failed";
    }
  }

  return (
    <ImageWithSkeleton
      src={src}
      alt="Asset thumbnail"
      isLoading={isLoading && !fallbackImage}
      hasError={hasError}
      width={width}
      height={height}
      borderRadius={borderRadius}
      objectFit="cover"
      skeletonProps={{
        variant: "ghost"
      }}
      errorContent={errorMessage}
      {...imageProps}
    />
  );
};

export default AssetImage;