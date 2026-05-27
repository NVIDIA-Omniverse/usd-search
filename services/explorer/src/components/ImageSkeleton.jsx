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
import { Box, Skeleton } from '@chakra-ui/react';
import { keyframes } from '@emotion/react';

// Custom shimmer animation
const shimmer = keyframes`
  0% {
    background-position: -468px 0;
  }
  100% {
    background-position: 468px 0;
  }
`;

/**
 * Animated skeleton loader for images
 * Provides a smooth loading experience while images are being fetched
 */
const ImageSkeleton = ({ 
  width = "200px", 
  height = "150px", 
  borderRadius = "md",
  variant = "ghost" // "ghost", "pulse", or "shimmer"
}) => {
  if (variant === "shimmer") {
    return (
      <Box
        width={width}
        height={height}
        borderRadius={borderRadius}
        position="relative"
        overflow="hidden"
        bg="gray.200"
        _dark={{ bg: "gray.700" }}
      >
        <Box
          position="absolute"
          top="0"
          left="0"
          right="0"
          bottom="0"
          background={`
            linear-gradient(
              90deg,
              transparent,
              rgba(255, 255, 255, 0.4),
              transparent
            )
          `}
          _dark={{
            background: `
              linear-gradient(
                90deg,
                transparent,
                rgba(255, 255, 255, 0.1),
                transparent
              )
            `
          }}
          backgroundSize="468px 100%"
          animation={`${shimmer} 1.6s ease-in-out infinite`}
        />
      </Box>
    );
  }

  if (variant === "pulse") {
    return (
      <Skeleton
        width={width}
        height={height}
        borderRadius={borderRadius}
        startColor="gray.200"
        endColor="gray.300"
        _dark={{
          startColor: "gray.700",
          endColor: "gray.600"
        }}
      />
    );
  }

  // Default "ghost" variant with subtle animated placeholder
  return (
    <Box
      width={width}
      height={height}
      borderRadius={borderRadius}
      bg="gray.100"
      _dark={{ bg: "gray.800" }}
      display="flex"
      alignItems="center"
      justifyContent="center"
      position="relative"
      overflow="hidden"
    >
      {/* Subtle background pattern */}
      <Box
        position="absolute"
        top="0"
        left="0"
        right="0"
        bottom="0"
        opacity="0.1"
        backgroundImage={`
          radial-gradient(circle at 25% 25%, gray 2px, transparent 2px),
          radial-gradient(circle at 75% 75%, gray 2px, transparent 2px)
        `}
        backgroundSize="20px 20px"
      />
      
      {/* Animated dots indicator */}
      <Box display="flex" gap="2px">
        {[0, 1, 2].map((index) => (
          <Box
            key={index}
            width="6px"
            height="6px"
            bg="gray.400"
            _dark={{ bg: "gray.500" }}
            borderRadius="full"
            animation={`${pulse} 1.4s ease-in-out infinite`}
            style={{
              animationDelay: `${index * 0.2}s`
            }}
          />
        ))}
      </Box>
    </Box>
  );
};

// Pulse animation for dots
const pulse = keyframes`
  0%, 80%, 100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  40% {
    opacity: 1;
    transform: scale(1);
  }
`;

/**
 * Higher-order component that wraps images with loading states
 */
export const ImageWithSkeleton = ({ 
  src, 
  alt, 
  isLoading = false,
  hasError = false,
  skeletonProps = {},
  errorContent = "No Image",
  ...imageProps 
}) => {
  if (hasError) {
    return (
      <Box
        display="flex"
        alignItems="center"
        justifyContent="center"
        bg="gray.50"
        color="gray.500"
        fontSize="sm"
        fontWeight="medium"
        width={imageProps.width || imageProps.w || "200px"}
        height={imageProps.height || imageProps.h || "150px"}
        borderRadius={imageProps.borderRadius || "md"}
        border="2px dashed"
        borderColor="gray.200"
        _dark={{ bg: "gray.800", color: "gray.400", borderColor: "gray.600" }}
      >
        {errorContent}
      </Box>
    );
  }

  if (isLoading || !src) {
    return (
      <ImageSkeleton
        width={imageProps.width || imageProps.w || "200px"}
        height={imageProps.height || imageProps.h || "150px"}
        borderRadius={imageProps.borderRadius || "md"}
        {...skeletonProps}
      />
    );
  }

  return (
    <Box
      as="img"
      src={src}
      alt={alt}
      loading="lazy"
      {...imageProps}
    />
  );
};

export default ImageSkeleton;