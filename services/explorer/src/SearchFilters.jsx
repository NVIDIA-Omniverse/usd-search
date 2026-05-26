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

import React from "react";
import {
  Box,
  VStack,
  HStack,
  Text,
  Input,
  Select,
  RadioGroup,
  Radio,
  Divider,
  Accordion,
  AccordionItem,
  AccordionButton,
  AccordionPanel,
  AccordionIcon,
  FormControl,
  FormLabel,
  Card,
  CardBody,
  Badge,
  Tooltip,
  IconButton,
  RangeSlider,
  RangeSliderTrack,
  RangeSliderFilledTrack,
  RangeSliderThumb,
  Switch,
} from "@chakra-ui/react";
import { InfoIcon, CloseIcon } from "@chakra-ui/icons";
import FilterByPropertiesInput from "./propertiesInput";
import NumericPropertiesInput from "./numericPropertiesInput";

const RangeSliderWithInput = ({ 
  label, 
  minValue, 
  maxValue, 
  min = 0, 
  max = 100, 
  step = 0.1, 
  onMinChange, 
  onMaxChange,
  unit = ""
}) => {
  // Convert string values to numbers, handle empty values specially
  const hasMinValue = minValue !== "" && !isNaN(parseFloat(minValue));
  const hasMaxValue = maxValue !== "" && !isNaN(parseFloat(maxValue));
  
  // If both are empty, don't set any value (let slider use its internal state)
  // If one is set, use it; if the other is empty, use the range boundary
  let sliderValue;
  if (!hasMinValue && !hasMaxValue) {
    // Both empty - don't control the slider, let it be free
    sliderValue = undefined;
  } else {
    const currentMin = hasMinValue ? parseFloat(minValue) : min;
    const currentMax = hasMaxValue ? parseFloat(maxValue) : max;
    sliderValue = [currentMin, currentMax];
  }

  return (
    <FormControl>
      <FormLabel fontSize="sm">{label}</FormLabel>
      <RangeSlider
        value={sliderValue}
        defaultValue={sliderValue === undefined ? [20, 80] : undefined}
        min={min}
        max={max}
        step={step}
        colorScheme="green"
        onChange={([newMin, newMax]) => {
          onMinChange(newMin.toString());
          onMaxChange(newMax.toString());
        }}
      >
        <RangeSliderTrack>
          <RangeSliderFilledTrack />
        </RangeSliderTrack>
        <RangeSliderThumb index={0} />
        <RangeSliderThumb index={1} />
      </RangeSlider>
    </FormControl>
  );
};

const FilterSection = ({ title, children, defaultOpen = false, badge = null, onClear = null }) => (
  <AccordionItem border="none">
    <AccordionButton px={0} _hover={{ bg: "transparent" }}>
      <HStack flex="1" textAlign="left" justify="space-between">
        <HStack>
          <Text fontSize="sm" fontWeight="semibold">
            {title}
          </Text>
          {badge && (
            <Badge size="sm" colorScheme="green">
              {badge}
            </Badge>
          )}
        </HStack>
        <HStack>
          {onClear && (
            <IconButton
              size="xs"
              variant="ghost"
              icon={<CloseIcon />}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onClear();
              }}
              aria-label="Clear filters"
            />
          )}
          <AccordionIcon />
        </HStack>
      </HStack>
    </AccordionButton>
    <AccordionPanel px={0} pb={4}>
      <VStack spacing={3} align="stretch">
        {children}
      </VStack>
    </AccordionPanel>
  </AccordionItem>
);

const SearchFilters = ({ 
  searchParams, 
  handleChange, 
  setSearchParams, 
  propertiesData,
  onClearAll 
}) => {
  const hasActiveFilters = Object.entries(searchParams).some(([key, value]) => {
    if (key === 'limit' || key === 'embedding_knn_search_method') return false;
    return value !== "" && value !== null && value !== undefined;
  });

  const clearFileFilters = () => {
    setSearchParams({
      ...searchParams,
      file_name: "",
      exclude_file_name: "",
      file_extension_include: "usd*",
      file_extension_exclude: ""
    });
  };

  const clearPathFilters = () => {
    setSearchParams({
      ...searchParams,
      search_path: "",
      exclude_search_path: "",
      search_in_scene: "",
      filter_url_regexp: ""
    });
  };

  const clearPropertyFilters = () => {
    setSearchParams({
      ...searchParams,
      filter_by_properties: "",
      filter_by_properties_numeric: "",
      vision_metadata: "",
      filter_by_tags: "",
    });
  };

  const clearFileSizeFilters = () => {
    setSearchParams({
      ...searchParams,
      file_size_greater_than: "",
      file_size_less_than: ""
    });
  };

  const clearDimensionFilters = () => {
    setSearchParams({
      ...searchParams,
      min_bbox_x: "",
      min_bbox_y: "",
      min_bbox_z: "",
      max_bbox_x: "",
      max_bbox_y: "",
      max_bbox_z: "",
      bbox_use_scaled_dimensions: true
    });
  };

  const clearDateFilters = () => {
    setSearchParams({
      ...searchParams,
      created_before: "",
      created_after: "",
      modified_before: "",
      modified_after: ""
    });
  };

  const clearUserFilters = () => {
    setSearchParams({
      ...searchParams,
      created_by: "",
      exclude_created_by: "",
      modified_by: "",
      exclude_modified_by: ""
    });
  };

  const clearAdvancedFilters = () => {
    setSearchParams({
      ...searchParams,
      similarity_threshold: "",
      cutoff_threshold: ""
    });
  };

  const getActiveFilterCount = (filterKeys) => {
    return filterKeys.filter(key => {
      const value = searchParams[key];
      return value !== "" && value !== null && value !== undefined;
    }).length;
  };

  return (
    <Card bg="gray.800" borderColor="gray.600" h="fit-content" minW="320px">
      <CardBody p={4}>
        <VStack spacing={4} align="stretch">
          {/* Header */}
          <HStack justify="space-between">
            <Text fontSize="lg" fontWeight="bold">
              Search Filters
            </Text>
            {hasActiveFilters && (
              <IconButton
                size="sm"
                variant="ghost"
                icon={<CloseIcon />}
                onClick={onClearAll}
                aria-label="Clear all filters"
                colorScheme="red"
              />
            )}
          </HStack>

          <Divider />

          {/* Filter Sections */}
          <Accordion allowMultiple defaultIndex={[]}>
            {/* File & Name Filters (Most Common - First) */}
            <FilterSection
              title="File & Name Filters"
              badge={getActiveFilterCount(['file_name', 'exclude_file_name', 'file_extension_include', 'file_extension_exclude']) || null}
              onClear={clearFileFilters}
            >
              <FormControl>
                <FormLabel fontSize="sm">File Name</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="file_name"
                  value={searchParams.file_name}
                  onChange={handleChange}
                  placeholder="Supports wildcards (*,?)"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Exclude File Names</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="exclude_file_name"
                  value={searchParams.exclude_file_name}
                  onChange={handleChange}
                  placeholder="Exclude patterns"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Include Extensions</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="file_extension_include"
                  value={searchParams.file_extension_include}
                  onChange={handleChange}
                  placeholder="e.g., usd*,jpg,png"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Exclude Extensions</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="file_extension_exclude"
                  value={searchParams.file_extension_exclude}
                  onChange={handleChange}
                  placeholder="e.g., tmp,bak"
                />
              </FormControl>

            </FilterSection>

            {/* Path & Location Filters (Second) */}
            <FilterSection
              title="Path & Location Filters"
              badge={getActiveFilterCount(['search_path', 'exclude_search_path', 'search_in_scene', 'filter_url_regexp']) || null}
              onClear={clearPathFilters}
            >
              <FormControl>
                <FormLabel fontSize="sm">Search Path</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="search_path"
                  value={searchParams.search_path}
                  onChange={handleChange}
                  placeholder="Include path (e.g., /Projects)"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Exclude Search Path</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="exclude_search_path"
                  value={searchParams.exclude_search_path}
                  onChange={handleChange}
                  placeholder="Exclude paths"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Search in Scene</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="search_in_scene"
                  value={searchParams.search_in_scene}
                  onChange={handleChange}
                  placeholder="Full scene URL"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">
                  URL Regex Filter
                  <Tooltip label="Lucene regex format for URL filtering">
                    <InfoIcon boxSize={3} ml={1} />
                  </Tooltip>
                </FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="filter_url_regexp"
                  value={searchParams.filter_url_regexp}
                  onChange={handleChange}
                  placeholder="Regex pattern"
                />
              </FormControl>
            </FilterSection>

            {/* Content & Properties Filters (Third) */}
            <FilterSection
              title="Content & Properties Filters"
              badge={getActiveFilterCount(['filter_by_properties', 'filter_by_properties_numeric', 'vision_metadata']) || null}
              onClear={clearPropertyFilters}
            >
              <FormControl>
                <FormLabel fontSize="sm">USD Properties</FormLabel>
                <FilterByPropertiesInput
                  value={searchParams.filter_by_properties}
                  onChange={handleChange}
                  apiData={propertiesData}
                  name="filter_by_properties"
                  size="sm"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">
                  Numeric Properties
                  <Tooltip label="Filter by numeric USD attributes with comparison operators (e.g., physics:mass > 1.0)">
                    <InfoIcon boxSize={3} ml={1} />
                  </Tooltip>
                </FormLabel>
                <NumericPropertiesInput
                  value={searchParams.filter_by_properties_numeric}
                  onChange={handleChange}
                  apiData={propertiesData}
                  name="filter_by_properties_numeric"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Vision Metadata</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="vision_metadata"
                  value={searchParams.vision_metadata}
                  onChange={handleChange}
                  placeholder="AI-generated tags"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Tags</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="filter_by_tags"
                  value={searchParams.filter_by_tags}
                  onChange={handleChange}
                  placeholder="Tags"
                />
              </FormControl>
            </FilterSection>

            {/* File Size Filters (Fourth) */}
            <FilterSection
              title="File Size Filters"
              badge={getActiveFilterCount(['file_size_greater_than', 'file_size_less_than']) || null}
              onClear={clearFileSizeFilters}
            >
              <FormControl>
                <FormLabel fontSize="sm">Minimum Size</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="file_size_greater_than"
                  value={searchParams.file_size_greater_than}
                  onChange={handleChange}
                  placeholder="e.g., 5MB, 1GB"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Maximum Size</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="file_size_less_than"
                  value={searchParams.file_size_less_than}
                  onChange={handleChange}
                  placeholder="e.g., 100MB, 2GB"
                />
              </FormControl>
            </FilterSection>

            {/* Object Dimension Filters (Fifth) */}
            <FilterSection
              title="Object Dimension Filters"
              badge={getActiveFilterCount(['min_bbox_x', 'min_bbox_y', 'min_bbox_z', 'max_bbox_x', 'max_bbox_y', 'max_bbox_z']) || null}
              onClear={clearDimensionFilters}
            >
              <FormControl>
                <HStack justify="space-between" align="center">
                  <FormLabel fontSize="sm" mb={0}>Use Scaled Dimensions</FormLabel>
                  <Switch
                    size="sm"
                    isChecked={searchParams.bbox_use_scaled_dimensions}
                    onChange={(e) => setSearchParams({
                      ...searchParams,
                      bbox_use_scaled_dimensions: e.target.checked
                    })}
                  />
                </HStack>
                <Text fontSize="xs" color="gray.400" mt={1}>
                  {searchParams.bbox_use_scaled_dimensions 
                    ? "Search using transformed object dimensions (includes scaling, rotation)" 
                    : "Search using original object dimensions (raw geometry size)"}
                </Text>
              </FormControl>

              <Divider />

              {/* X Dimension */}
              <FormControl>
                <FormLabel fontSize="sm">X Dimension Range (units)</FormLabel>
                <HStack spacing={2}>
                  <Box flex={1}>
                    <Input
                      size="sm"
                      type="number"
                      step="0.1"
                      name="min_bbox_x"
                      value={searchParams.min_bbox_x}
                      onChange={handleChange}
                      placeholder="Min X"
                    />
                  </Box>
                  <Text fontSize="sm" color="gray.400">to</Text>
                  <Box flex={1}>
                    <Input
                      size="sm"
                      type="number"
                      step="0.1"
                      name="max_bbox_x"
                      value={searchParams.max_bbox_x}
                      onChange={handleChange}
                      placeholder="Max X"
                    />
                  </Box>
                </HStack>
              </FormControl>

              {/* Y Dimension */}
              <FormControl>
                <FormLabel fontSize="sm">Y Dimension Range (units)</FormLabel>
                <HStack spacing={2}>
                  <Box flex={1}>
                    <Input
                      size="sm"
                      type="number"
                      step="0.1"
                      name="min_bbox_y"
                      value={searchParams.min_bbox_y}
                      onChange={handleChange}
                      placeholder="Min Y"
                    />
                  </Box>
                  <Text fontSize="sm" color="gray.400">to</Text>
                  <Box flex={1}>
                    <Input
                      size="sm"
                      type="number"
                      step="0.1"
                      name="max_bbox_y"
                      value={searchParams.max_bbox_y}
                      onChange={handleChange}
                      placeholder="Max Y"
                    />
                  </Box>
                </HStack>
              </FormControl>

              {/* Z Dimension */}
              <FormControl>
                <FormLabel fontSize="sm">Z Dimension Range (units)</FormLabel>
                <HStack spacing={2}>
                  <Box flex={1}>
                    <Input
                      size="sm"
                      type="number"
                      step="0.1"
                      name="min_bbox_z"
                      value={searchParams.min_bbox_z}
                      onChange={handleChange}
                      placeholder="Min Z"
                    />
                  </Box>
                  <Text fontSize="sm" color="gray.400">to</Text>
                  <Box flex={1}>
                    <Input
                      size="sm"
                      type="number"
                      step="0.1"
                      name="max_bbox_z"
                      value={searchParams.max_bbox_z}
                      onChange={handleChange}
                      placeholder="Max Z"
                    />
                  </Box>
                </HStack>
              </FormControl>
            </FilterSection>

            {/* Date Filters (Sixth) */}
            <FilterSection
              title="Date Filters"
              badge={getActiveFilterCount(['created_before', 'created_after', 'modified_before', 'modified_after']) || null}
              onClear={clearDateFilters}
            >
              <FormControl>
                <FormLabel fontSize="sm">Created After</FormLabel>
                <Input
                  size="sm"
                  type="date"
                  name="created_after"
                  value={searchParams.created_after}
                  onChange={handleChange}
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Created Before</FormLabel>
                <Input
                  size="sm"
                  type="date"
                  name="created_before"
                  value={searchParams.created_before}
                  onChange={handleChange}
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Modified After</FormLabel>
                <Input
                  size="sm"
                  type="date"
                  name="modified_after"
                  value={searchParams.modified_after}
                  onChange={handleChange}
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Modified Before</FormLabel>
                <Input
                  size="sm"
                  type="date"
                  name="modified_before"
                  value={searchParams.modified_before}
                  onChange={handleChange}
                />
              </FormControl>
            </FilterSection>


            {/* User Filters (Seventh) */}
            <FilterSection
              title="User Filters"
              badge={getActiveFilterCount(['created_by', 'exclude_created_by', 'modified_by', 'exclude_modified_by']) || null}
              onClear={clearUserFilters}
            >
              <FormControl>
                <FormLabel fontSize="sm">Created By</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="created_by"
                  value={searchParams.created_by}
                  onChange={handleChange}
                  placeholder="Username or email"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Exclude Created By</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="exclude_created_by"
                  value={searchParams.exclude_created_by}
                  onChange={handleChange}
                  placeholder="Username or email to exclude"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Modified By</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="modified_by"
                  value={searchParams.modified_by}
                  onChange={handleChange}
                  placeholder="Username or email"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Exclude Modified By</FormLabel>
                <Input
                  size="sm"
                  autoComplete="off"
                  name="exclude_modified_by"
                  value={searchParams.exclude_modified_by}
                  onChange={handleChange}
                  placeholder="Username or email to exclude"
                />
              </FormControl>
            </FilterSection>

            {/* Advanced Filters (Eighth) */}
            <FilterSection
              title="Advanced Filters"
              badge={getActiveFilterCount(['similarity_threshold', 'cutoff_threshold']) || null}
              onClear={clearAdvancedFilters}
            >
              <FormControl>
                <FormLabel fontSize="sm">
                  Similarity Threshold
                  <Tooltip label="Filter duplicates by cosine distance (0-2 range)">
                    <InfoIcon boxSize={3} ml={1} />
                  </Tooltip>
                </FormLabel>
                <Input
                  size="sm"
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  name="similarity_threshold"
                  value={searchParams.similarity_threshold}
                  onChange={handleChange}
                  placeholder="0.5"
                />
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">
                  Cutoff Threshold
                  <Tooltip label="Set minimum similarity score for results">
                    <InfoIcon boxSize={3} ml={1} />
                  </Tooltip>
                </FormLabel>
                <Input
                  size="sm"
                  type="number"
                  step="0.1"
                  min="0"
                  name="cutoff_threshold"
                  value={searchParams.cutoff_threshold}
                  onChange={handleChange}
                  placeholder="0.1"
                />
              </FormControl>
            </FilterSection>

            {/* Search Settings */}
            <FilterSection title="Search Settings">
              <FormControl>
                <FormLabel fontSize="sm">Results Per Page</FormLabel>
                <Select
                  size="sm"
                  name="limit"
                  value={searchParams.limit}
                  onChange={handleChange}
                >
                  <option value="10">10</option>
                  <option value="20">20</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                  <option value="250">250</option>
                  <option value="500">500</option>
                  <option value="1000">1000</option>
                </Select>
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">
                  Search Method
                  <Tooltip label="Approximate is faster but less accurate">
                    <InfoIcon boxSize={3} ml={1} />
                  </Tooltip>
                </FormLabel>
                <RadioGroup
                  value={searchParams.embedding_knn_search_method}
                  onChange={(value) =>
                    setSearchParams({
                      ...searchParams,
                      embedding_knn_search_method: value,
                    })
                  }
                >
                  <VStack align="start" spacing={2}>
                    <Radio value="exact" size="sm">
                      Exact
                    </Radio>
                    <Radio value="approximate" size="sm">
                      Approximate
                    </Radio>
                  </VStack>
                </RadioGroup>
              </FormControl>
            </FilterSection>
          </Accordion>
        </VStack>
      </CardBody>
    </Card>
  );
};

export default SearchFilters;