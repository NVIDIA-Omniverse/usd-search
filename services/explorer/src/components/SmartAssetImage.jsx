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

import React, { useRef, useEffect } from 'react';
import { ImageWithSkeleton } from './ImageSkeleton';

/**
 * Smart asset image component that integrates with visibility-based loading
 * Uses external loading state from useSmartImageLoader hook
 */
const SmartAssetImage = ({ 
  result,
  index,
  getLoadingState,
  registerImageElement,
  width = "100%",
  height = "120px",
  borderRadius = "md",
  ...imageProps 
}) => {
  const elementRef = useRef(null);
  
  // Register this element for intersection observation
  useEffect(() => {
    if (elementRef.current && registerImageElement) {
      registerImageElement(result, index, elementRef.current);
    }
  }, [result, index, registerImageElement]);

  // Get loading state from smart loader
  const { loading: isLoading, error, data: imageData } = getLoadingState 
    ? getLoadingState(result, index) 
    : { loading: false, error: null, data: null };
  
  // Check if we have base64 image data as fallback
  const fallbackImage = result?.source?.image;
  
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
    <div ref={elementRef}>
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
    </div>
  );
};

export default SmartAssetImage;