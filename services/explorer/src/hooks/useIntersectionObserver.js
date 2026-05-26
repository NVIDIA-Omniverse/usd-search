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

import { useEffect, useRef, useState } from 'react';

/**
 * Hook to observe element intersection with viewport
 * @param {Object} options - Intersection observer options
 * @param {string|number} rootMargin - Root margin (e.g., "200px" or "50%")
 * @param {number|number[]} threshold - Intersection threshold(s)
 * @param {Element} root - Root element for intersection (null for viewport)
 * @returns {[React.RefObject, boolean]} - [ref to attach to element, isIntersecting]
 */
export const useIntersectionObserver = ({
  rootMargin = '0px',
  threshold = 0.1,
  root = null
} = {}) => {
  const [isIntersecting, setIsIntersecting] = useState(false);
  const targetRef = useRef(null);

  useEffect(() => {
    const element = targetRef.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        setIsIntersecting(entry.isIntersecting);
      },
      {
        root,
        rootMargin,
        threshold
      }
    );

    observer.observe(element);

    return () => {
      observer.unobserve(element);
    };
  }, [rootMargin, threshold, root]);

  return [targetRef, isIntersecting];
};

/**
 * Hook to get visibility status of multiple elements
 * @param {Object} options - Intersection observer options
 * @returns {[Function, Map]} - [registerElement function, visibilityMap]
 */
export const useMultipleIntersectionObserver = ({
  rootMargin = '0px',
  threshold = 0.1,
  root = null
} = {}) => {
  const [visibilityMap, setVisibilityMap] = useState(new Map());
  const observerRef = useRef(null);
  const elementsRef = useRef(new Map());

  useEffect(() => {
    observerRef.current = new IntersectionObserver(
      (entries) => {
        setVisibilityMap(prev => {
          const newMap = new Map(prev);
          entries.forEach(entry => {
            const id = entry.target.dataset.observerId;
            if (id) {
              newMap.set(id, entry.isIntersecting);
            }
          });
          return newMap;
        });
      },
      {
        root,
        rootMargin,
        threshold
      }
    );

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [rootMargin, threshold, root]);

  const registerElement = (id, element) => {
    if (!element || !observerRef.current) return;

    // Unobserve previous element with same id
    const prevElement = elementsRef.current.get(id);
    if (prevElement) {
      observerRef.current.unobserve(prevElement);
    }

    // Set data attribute for identification
    element.dataset.observerId = id;
    
    // Store and observe new element
    elementsRef.current.set(id, element);
    observerRef.current.observe(element);
  };

  return [registerElement, visibilityMap];
};