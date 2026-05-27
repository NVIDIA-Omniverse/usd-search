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

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Box, VStack } from '@chakra-ui/react';

const VirtualizedResults = ({
  items = [],
  renderItem,
  itemHeight = 200,
  containerHeight = "calc(100vh - 200px)", // Use viewport height minus space for header/controls
  overscan = 5,
  gridMode = false,
  itemsPerRow = 1,
  itemWidth = 280,
  gap = 16,
  ...props
}) => {
  const [scrollTop, setScrollTop] = useState(0);
  const [containerSize, setContainerSize] = useState({ width: 0, height: typeof containerHeight === 'string' ? 600 : containerHeight });
  const scrollElementRef = useRef(null);
  const resizeObserverRef = useRef(null);

  // Calculate dimensions based on mode
  const { 
    totalItems, 
    visibleStartIndex, 
    visibleEndIndex, 
    totalHeight,
    totalWidth 
  } = useMemo(() => {
    if (items.length === 0) {
      return {
        totalItems: 0,
        visibleStartIndex: 0,
        visibleEndIndex: 0,
        totalHeight: 0,
        totalWidth: 0
      };
    }

    const totalItems = items.length;

    if (gridMode) {
      // Grid calculations
      const availableWidth = containerSize.width;
      const effectiveItemsPerRow = Math.max(1, Math.floor((availableWidth + gap) / (itemWidth + gap)));
      const totalRows = Math.ceil(totalItems / effectiveItemsPerRow);
      const rowHeight = itemHeight + gap;
      
      const visibleRows = Math.ceil(containerSize.height / rowHeight);
      const startRow = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
      const endRow = Math.min(totalRows - 1, startRow + visibleRows + overscan * 2);
      
      const visibleStartIndex = startRow * effectiveItemsPerRow;
      const visibleEndIndex = Math.min(totalItems - 1, (endRow + 1) * effectiveItemsPerRow - 1);
      
      return {
        totalItems,
        visibleStartIndex,
        visibleEndIndex,
        totalHeight: totalRows * rowHeight,
        totalWidth: availableWidth,
        itemsPerRow: effectiveItemsPerRow,
        rowHeight
      };
    } else {
      // List calculations
      const totalHeight = totalItems * (itemHeight + gap);
      const visibleItems = Math.ceil(containerSize.height / (itemHeight + gap));
      const startIndex = Math.max(0, Math.floor(scrollTop / (itemHeight + gap)) - overscan);
      const endIndex = Math.min(totalItems - 1, startIndex + visibleItems + overscan * 2);
      
      return {
        totalItems,
        visibleStartIndex: startIndex,
        visibleEndIndex: endIndex,
        totalHeight,
        totalWidth: containerSize.width
      };
    }
  }, [items.length, scrollTop, containerSize, itemHeight, itemWidth, gap, overscan, gridMode]);

  // Handle scroll
  const handleScroll = useCallback((e) => {
    const newScrollTop = e.currentTarget.scrollTop;
    setScrollTop(newScrollTop);
  }, []);

  // Setup resize observer
  useEffect(() => {
    const element = scrollElementRef.current;
    if (!element) return;

    resizeObserverRef.current = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setContainerSize({ width, height });
      }
    });

    resizeObserverRef.current.observe(element);

    return () => {
      if (resizeObserverRef.current) {
        resizeObserverRef.current.disconnect();
      }
    };
  }, []);

  // Create visible items
  const visibleItems = useMemo(() => {
    const items_ = [];
    
    if (gridMode) {
      const availableWidth = containerSize.width;
      const effectiveItemsPerRow = Math.max(1, Math.floor((availableWidth + gap) / (itemWidth + gap)));
      const rowHeight = itemHeight + gap;

      for (let i = visibleStartIndex; i <= visibleEndIndex; i++) {
        if (i >= items.length) break;
        
        const row = Math.floor(i / effectiveItemsPerRow);
        const col = i % effectiveItemsPerRow;
        
        items_.push({
          index: i,
          item: items[i],
          style: {
            position: 'absolute',
            top: row * rowHeight,
            left: col * (itemWidth + gap),
            width: itemWidth,
            height: itemHeight
          }
        });
      }
    } else {
      for (let i = visibleStartIndex; i <= visibleEndIndex; i++) {
        if (i >= items.length) break;
        
        items_.push({
          index: i,
          item: items[i],
          style: {
            position: 'absolute',
            top: i * (itemHeight + gap),
            left: 0,
            right: 0,
            height: itemHeight
          }
        });
      }
    }
    
    return items_;
  }, [items, visibleStartIndex, visibleEndIndex, gridMode, containerSize.width, itemWidth, itemHeight, gap]);

  return (
    <Box
      ref={scrollElementRef}
      height={containerHeight}
      overflowY="auto"
      onScroll={handleScroll}
      position="relative"
      {...props}
    >
      {/* Total height container */}
      <Box
        position="relative"
        height={`${totalHeight}px`}
        width="100%"
      >
        {/* Visible items */}
        {visibleItems.map(({ index, item, style }) => (
          <Box key={index} style={style}>
            {renderItem(item, index)}
          </Box>
        ))}
      </Box>
    </Box>
  );
};

export default VirtualizedResults;