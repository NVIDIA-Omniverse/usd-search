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
  Spinner,
  FormControl,
} from "@chakra-ui/react";

import {
  AutoComplete,
  AutoCompleteInput,
  AutoCompleteItem,
  AutoCompleteList,
} from "@choc-ui/chakra-autocomplete";

export default function FilterByPropertiesInput({
  value,
  onChange,
  apiData,
  loading,
  name,
}) {
  const [tokens, setTokens] = useState(() => {
    if (Array.isArray(value)) return value;
    return [];
  });

  const [currentInput, setCurrentInput] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [isTypingValue, setIsTypingValue] = useState(false);

  useEffect(() => {
    if (Array.isArray(value)) {
      setTokens(value);
    } else if (!value) {
      setTokens([]);
    }
  }, [value]);

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
    [onChange, name],
  );

  useEffect(() => {
    syncWithParent(tokens);
  }, [tokens, syncWithParent]);

  const [keyPart = "", valuePart = ""] = currentInput.split("=");

  const handleInputChange = (e) => {
    setCurrentInput(e.target.value);
  };

  useEffect(() => {
    setIsTypingValue(currentInput.includes("="));

    if (!apiData) return;

    // Sort keys & values by asset_count descending
    const sortedKeys = [...(apiData.unique_keys ?? [])].sort(
      (a, b) => b.asset_count - a.asset_count,
    );
    const sortedPairs = [...(apiData.kv_pairs ?? [])].sort(
      (a, b) => b.asset_count - a.asset_count,
    );

    if (!isTypingValue) {
      // Currently typing a key
      const filteredKeys = sortedKeys.filter((k) =>
        k.key.toLowerCase().includes(keyPart.trim().toLowerCase()),
      );
      setSuggestions(
        filteredKeys.map((item) => ({
          value: item.key,
          label: `${item.key} (${item.asset_count})`,
        })),
      );
    } else {
      // Currently typing a value
      const typedKey = keyPart.trim().toLowerCase();
      const typedValue = valuePart.trim().toLowerCase();

      let matchingPairs =
        typedKey.length > 0
          ? sortedPairs.filter((p) => p.key.toLowerCase() === typedKey)
          : sortedPairs;

      if (typedValue) {
        matchingPairs = matchingPairs.filter((p) =>
          p.value.toLowerCase().includes(typedValue),
        );
      }

      const encounteredValues = new Set();
      const uniquePairs = [];

      for (const p of matchingPairs) {
        if (!encounteredValues.has(p.value)) {
          encounteredValues.add(p.value);
          uniquePairs.push(p);
        }
      }

      setSuggestions(
        uniquePairs.map((p) => ({
          value: p.value,
          label: `${p.value} (${p.asset_count})`,
        })),
      );
    }
  }, [currentInput, apiData, isTypingValue, keyPart, valuePart]);

  const finalizeToken = (inputStr) => {
    const trimmed = inputStr.trim();
    if (!trimmed) return;
    setTokens((prev) => [...prev, trimmed]);
    setCurrentInput("");
  };

  const handleSelectSuggestion = (selectedValue) => {
    if (!isTypingValue) {
      setCurrentInput(`${selectedValue}=`);
    } else {
      finalizeToken(`${keyPart}=${selectedValue}`);
    }
  };

  const handleKeyDownOpen = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      // finalizeToken(currentInput);
    }
  };

  const handleKeyDownClosed = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      finalizeToken(currentInput);
    }
  };

  const customFilter = () => true;

  const handleRemoveToken = (index) => {
    setTokens((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <FormControl>
      <Wrap>
        {tokens.map((token, index) => (
          <Tag
            key={index}
            colorScheme="blue"
            variant="solid"
            borderRadius="full"
          >
            <TagLabel>{token}</TagLabel>
            <TagCloseButton onClick={() => handleRemoveToken(index)} />
          </Tag>
        ))}
      </Wrap>

      <AutoComplete
        // openOnFocus
        closeOnSelect={false}
        filter={customFilter}
        onSelectOption={({ item }) => handleSelectSuggestion(item.value)}
      >
                  {({ isOpen }) => (
                    <>
        <AutoCompleteInput
          size="sm"
          value={currentInput}
          onChange={handleInputChange}
          onKeyDown={isOpen ? handleKeyDownOpen : handleKeyDownClosed}
          placeholder="USD Properties Search. Type key=value then press Enter"
          autoComplete="off"
        />
        <AutoCompleteList>
          {suggestions.slice(0, 100).map((suggestion, idx) => (
            <AutoCompleteItem
              key={`option-${suggestion.value}-${idx}`}
              value={suggestion.value}
              textTransform="capitalize"
            >
              {suggestion.label}
            </AutoCompleteItem>
          ))}
        </AutoCompleteList>
        </>
    )}
      </AutoComplete>

      {loading && (
        <Box position="relative" top="5px">
          <Spinner size="sm" />
        </Box>
      )}
    </FormControl>
  );
}
