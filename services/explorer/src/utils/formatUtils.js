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
 * Utility functions for formatting data
 */

/**
 * Format file size in human readable format
 * @param {number} size - Size in bytes
 * @returns {string} Formatted size string
 */
export const formatFileSize = (size) => {
  if (!size || size === 0) return "0 bytes";
  
  const bytes = parseInt(size, 10);
  if (isNaN(bytes)) return "Unknown";
  
  const kb = bytes / 1024;
  const mb = kb / 1024;
  const gb = mb / 1024;
  const tb = gb / 1024;
  
  if (tb >= 1) return `${tb.toFixed(2)} TB`;
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  if (mb >= 1) return `${mb.toFixed(2)} MB`;
  if (kb >= 1) return `${kb.toFixed(2)} KB`;
  return `${bytes} bytes`;
};

/**
 * Format date string to locale string
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date string
 */
export const formatDate = (dateString) => {
  if (!dateString) return "Unknown";
  try {
    return new Date(dateString).toLocaleString();
  } catch (error) {
    return dateString;
  }
};

/**
 * Find the highest scoring vector image from search result explanations
 * @param {Object} result - Search result object
 * @returns {string|null} Image URL or null if no vector images found
 */
export const getHighestScoringVectorImage = (result) => {
  if (!result?.metadata?.explanations) {
    return null;
  }

  let highestScore = -1;
  let highestScoringImage = null;

  // Iterate through all explanations
  result.metadata.explanations.forEach(explanation => {
    // Check if this explanation has matched_vectors
    if (explanation.matched_vectors && Array.isArray(explanation.matched_vectors)) {
      explanation.matched_vectors.forEach(vectorMatch => {
        // Check if this vector match has an image attribute and a score
        if (vectorMatch.image && vectorMatch.score > highestScore) {
          highestScore = vectorMatch.score;
          highestScoringImage = vectorMatch.image;
        }
      });
    }
  });

  return highestScoringImage;
};