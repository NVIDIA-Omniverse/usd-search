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

import React, { useEffect, useState, useCallback } from "react";
import {
  Box,
  Wrap,
  Tag,
  TagLabel,
  TagCloseButton,
  FormControl,
  HStack,
  Select,
  Input,
  Text,
} from "@chakra-ui/react";

import {
  AutoComplete,
  AutoCompleteInput,
  AutoCompleteItem,
  AutoCompleteList,
} from "@choc-ui/chakra-autocomplete";

const OPERATORS = [">", ">=", "<", "<=", "="];

// Parse a token like "physics:mass>1.0" into { key, operator, value }
const parseToken = (token) => {
  for (const op of [">=", "<=", ">", "<", "="]) {
    const idx = token.indexOf(op);
    if (idx !== -1) {
      return {
        key: token.substring(0, idx),
        operator: op,
        value: token.substring(idx + op.length),
      };
    }
  }
  return { key: token, operator: "", value: "" };
};

// Format token parts back into a string
const formatToken = (key, operator, value) => {
  if (!key) return "";
  if (!operator || !value) return key;
  return `${key}${operator}${value}`;
};

export default function NumericPropertiesInput({
  value,
  onChange,
  apiData,
  name,
}) {
  // Internal tokens state - matches FilterByPropertiesInput pattern
  const [tokens, setTokens] = useState(() => {
    if (typeof value === "string" && value.trim()) {
      return value.split(",").filter(Boolean);
    }
    if (Array.isArray(value)) return value;
    return [];
  });

  // Current input state for building a new token
  const [keyInput, setKeyInput] = useState("");
  const [selectedOperator, setSelectedOperator] = useState(">");
  const [numericValue, setNumericValue] = useState("");
  const [suggestions, setSuggestions] = useState([]);

  // Sync tokens from parent value
  useEffect(() => {
    if (typeof value === "string" && value.trim()) {
      setTokens(value.split(",").filter(Boolean));
    } else if (Array.isArray(value)) {
      setTokens(value);
    } else if (!value) {
      setTokens([]);
    }
  }, [value]);

  // Sync tokens to parent
  const syncWithParent = useCallback(
    (newTokens) => {
      const joinedValue = newTokens.join(",");
      onChange?.({
        target: {
          name,
          value: joinedValue,
        },
      });
    },
    [onChange, name]
  );

  useEffect(() => {
    syncWithParent(tokens);
  }, [tokens, syncWithParent]);

  // Update suggestions based on keyInput - only show properties with numeric values
  useEffect(() => {
    if (!apiData) return;

    // Find keys that have numeric values by checking kv_pairs
    const kvPairs = apiData.kv_pairs ?? [];

    // Build a map of keys that have at least one numeric value
    const numericKeysMap = new Map();
    for (const pair of kvPairs) {
      // Check if the value is numeric (can be parsed as a number)
      const numValue = parseFloat(pair.value);
      if (!isNaN(numValue) && isFinite(numValue)) {
        // Accumulate asset counts for numeric keys
        const existing = numericKeysMap.get(pair.key) || 0;
        numericKeysMap.set(pair.key, existing + pair.asset_count);
      }
    }

    // Convert map to array and sort by asset count
    const numericKeys = Array.from(numericKeysMap.entries())
      .map(([key, asset_count]) => ({ key, asset_count }))
      .sort((a, b) => b.asset_count - a.asset_count);

    // Filter by user input
    const filteredKeys = numericKeys.filter((k) =>
      k.key.toLowerCase().includes(keyInput.trim().toLowerCase())
    );

    setSuggestions(
      filteredKeys.map((item) => ({
        value: item.key,
        label: `${item.key} (${item.asset_count})`,
      }))
    );
  }, [keyInput, apiData]);

  const addToken = () => {
    const key = keyInput.trim();
    if (!key || !numericValue.trim()) return;

    const newToken = formatToken(key, selectedOperator, numericValue.trim());
    if (newToken && !tokens.includes(newToken)) {
      setTokens((prev) => [...prev, newToken]);
    }

    // Reset inputs
    setKeyInput("");
    setNumericValue("");
    setSelectedOperator(">");
  };

  const handleKeySelect = (selectedValue) => {
    setKeyInput(selectedValue);
  };

  const handleKeyInputChange = (e) => {
    setKeyInput(e.target.value);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addToken();
    }
  };

  const handleValueKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addToken();
    }
  };

  const handleRemoveToken = (index) => {
    setTokens((prev) => prev.filter((_, i) => i !== index));
  };

  const customFilter = () => true;

  return (
    <FormControl>
      <Wrap mb={2}>
        {tokens.map((token, index) => {
          const parsed = parseToken(token);
          return (
            <Tag
              key={index}
              colorScheme="purple"
              variant="solid"
              borderRadius="full"
            >
              <TagLabel>
                {parsed.key}
                <Box as="span" fontWeight="bold" mx={1}>
                  {parsed.operator}
                </Box>
                {parsed.value}
              </TagLabel>
              <TagCloseButton onClick={() => handleRemoveToken(index)} />
            </Tag>
          );
        })}
      </Wrap>

      <HStack spacing={2} align="flex-end">
        {/* Property Key Autocomplete */}
        <Box flex={2}>
          <AutoComplete
            openOnFocus
            closeOnSelect={true}
            filter={customFilter}
            onSelectOption={({ item }) => handleKeySelect(item.value)}
            emptyState={
              <Box p={2} textAlign="center">
                <Text fontSize="sm" color="gray.500">
                  {!apiData ? "Loading properties..." : "No numeric properties found"}
                </Text>
              </Box>
            }
          >
            {({ isOpen }) => (
              <>
                <AutoCompleteInput
                  size="sm"
                  value={keyInput}
                  onChange={handleKeyInputChange}
                  onKeyDown={handleKeyDown}
                  placeholder="Property name"
                  autoComplete="off"
                />
                <AutoCompleteList>
                  {suggestions.slice(0, 50).map((suggestion, idx) => (
                    <AutoCompleteItem
                      key={`option-${suggestion.value}-${idx}`}
                      value={suggestion.value}
                    >
                      {suggestion.label}
                    </AutoCompleteItem>
                  ))}
                </AutoCompleteList>
              </>
            )}
          </AutoComplete>
        </Box>

        {/* Operator Select */}
        <Box flex={1}>
          <Select
            size="sm"
            value={selectedOperator}
            onChange={(e) => setSelectedOperator(e.target.value)}
          >
            {OPERATORS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </Select>
        </Box>

        {/* Numeric Value Input */}
        <Box flex={1}>
          <Input
            size="sm"
            type="number"
            step="any"
            value={numericValue}
            onChange={(e) => setNumericValue(e.target.value)}
            onKeyDown={handleValueKeyDown}
            placeholder="Value"
          />
        </Box>
      </HStack>
    </FormControl>
  );
}
