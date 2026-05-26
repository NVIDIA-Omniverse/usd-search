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

import React, { useState } from "react";
import {
  Box,
  VStack,
  HStack,
  Text,
  Badge,
  Collapse,
  IconButton,
  Progress,
  Tooltip,
  Wrap,
  WrapItem,
  Divider,
  Tag,
  TagLabel,
  TagLeftIcon,
  Card,
  CardBody,
  useDisclosure,
} from "@chakra-ui/react";
import { 
  ChevronDownIcon, 
  ChevronUpIcon, 
  InfoIcon,
  SearchIcon,
  ViewIcon,
} from "@chakra-ui/icons";

const getSearchTypeColor = (searchType) => {
  const colors = {
    'text': 'blue',
    'hybrid': 'green',
    'vector': 'purple',
    'image_similarity': 'orange',
    'filter_only': 'gray',
    'text_to_vector': 'teal'
  };
  return colors[searchType] || 'gray';
};

const getSearchTypeIcon = (searchType) => {
  const icons = {
    'text': SearchIcon,
    'hybrid': SearchIcon,
    'vector': ViewIcon,
    'image_similarity': ViewIcon,
    'filter_only': InfoIcon,
    'text_to_vector': SearchIcon
  };
  return icons[searchType] || InfoIcon;
};

const SearchExplanationItem = ({ explanation, maxScore = 1 }) => {
  const { isOpen, onToggle } = useDisclosure();
  const colorScheme = getSearchTypeColor(explanation.search_type);
  const Icon = getSearchTypeIcon(explanation.search_type);
  
  // Normalize score for progress bar (0-100%)
  const normalizedScore = Math.min((explanation.score / maxScore) * 100, 100);
  
  return (
    <Card size="sm" bg="gray.700" borderColor="gray.600">
      <CardBody p={3}>
        <VStack spacing={2} align="stretch">
          {/* Header */}
          <HStack justify="space-between">
            <HStack>
              <Tag size="sm" colorScheme={colorScheme} variant="solid">
                <TagLeftIcon as={Icon} />
                <TagLabel>{explanation.search_type.replace('_', ' ')}</TagLabel>
              </Tag>
              <Text fontSize="xs" color="gray.400">
                {explanation.field}
              </Text>
            </HStack>
            <HStack>
              <Text fontSize="sm" fontWeight="bold" color={`${colorScheme}.300`}>
                {explanation.score.toFixed(3)}
              </Text>
              <IconButton
                size="xs"
                variant="ghost"
                icon={isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}
                onClick={onToggle}
                aria-label="Toggle details"
              />
            </HStack>
          </HStack>

          {/* Score Progress Bar */}
          <Progress
            value={normalizedScore}
            size="sm"
            colorScheme={colorScheme}
            bg="gray.600"
            borderRadius="md"
          />

          {/* RRF Score if available */}
          {explanation.rrf_score && (
            <HStack justify="space-between">
              <Text fontSize="xs" color="gray.400">
                RRF Score:
              </Text>
              <Text fontSize="xs" fontWeight="semibold">
                {explanation.rrf_score.toFixed(3)}
              </Text>
            </HStack>
          )}

          {/* Matched Terms */}
          {explanation.matched_terms && explanation.matched_terms.length > 0 && (
            <Box>
              <Text fontSize="xs" color="gray.400" mb={1}>
                Matched terms:
              </Text>
              <Wrap spacing={1}>
                {explanation.matched_terms.map((term, index) => (
                  <WrapItem key={index}>
                    <Badge 
                      size="sm" 
                      colorScheme={colorScheme} 
                      variant="outline"
                      fontSize="xs"
                    >
                      {term}
                    </Badge>
                  </WrapItem>
                ))}
              </Wrap>
            </Box>
          )}

          {/* Vector Similarity */}
          {explanation.vector_similarity && (
            <HStack justify="space-between">
              <Text fontSize="xs" color="gray.400">
                Vector Similarity:
              </Text>
              <Text fontSize="xs" fontWeight="semibold" color="purple.300">
                {(explanation.vector_similarity * 100).toFixed(1)}%
              </Text>
            </HStack>
          )}

          {/* Expandable Details */}
          <Collapse in={isOpen}>
            <Divider my={2} />
            <VStack spacing={2} align="stretch">
              {/* RRF Rank Constant */}
              {explanation.rrf_rank_constant && (
                <HStack justify="space-between">
                  <Text fontSize="xs" color="gray.400">
                    RRF Rank Constant:
                  </Text>
                  <Text fontSize="xs">
                    {explanation.rrf_rank_constant}
                  </Text>
                </HStack>
              )}

              {/* Vector Scores */}
              {explanation.matched_vectors && explanation.matched_vectors.length > 0 && (
                <Box>
                  <Text fontSize="xs" color="gray.400" mb={1}>
                    Vector matches:
                  </Text>
                  <VStack spacing={1} align="stretch">
                    {explanation.matched_vectors.map((vectorScore, index) => (
                      <HStack key={index} justify="space-between" fontSize="xs">
                        <Text color="gray.300">
                          {vectorScore.field} (pos {vectorScore.offset})
                        </Text>
                        <Text fontWeight="semibold" color="purple.300">
                          {vectorScore.score.toFixed(3)}
                        </Text>
                      </HStack>
                    ))}
                  </VStack>
                </Box>
              )}

              {/* Additional Details */}
              {explanation.details && (
                <Box>
                  <Text fontSize="xs" color="gray.400" mb={1}>
                    Details:
                  </Text>
                  <Box 
                    fontSize="xs" 
                    p={2} 
                    bg="gray.800" 
                    borderRadius="md"
                    color="gray.300"
                    fontFamily="mono"
                    overflow="auto"
                    maxH="100px"
                  >
                    {typeof explanation.details === 'object' 
                      ? JSON.stringify(explanation.details, null, 2)
                      : explanation.details
                    }
                  </Box>
                </Box>
              )}
            </VStack>
          </Collapse>
        </VStack>
      </CardBody>
    </Card>
  );
};

const SearchExplanations = ({ 
  explanations = [], 
  totalScore = 0, 
  rrfRank = null,
  originalRanks = {},
  showSummary = true,
  maxItems = 5 
}) => {
  const [showAll, setShowAll] = useState(false);
  
  if (!explanations || explanations.length === 0) {
    return null;
  }

  // Sort explanations by score (highest first)
  const sortedExplanations = [...explanations].sort((a, b) => b.score - a.score);
  const maxScore = Math.max(...explanations.map(e => e.score));
  
  // Show limited items unless expanded
  const displayedExplanations = showAll 
    ? sortedExplanations 
    : sortedExplanations.slice(0, maxItems);

  return (
    <Box>
      {showSummary && (
        <VStack spacing={2} mb={4} align="stretch">
          {/* Summary Header */}
          <HStack justify="space-between">
            <Text fontSize="sm" fontWeight="bold" color="gray.300">
              Search Explanations
            </Text>
            <HStack>
              {rrfRank && (
                <Tooltip label="Reciprocal Rank Fusion ranking position">
                  <Badge colorScheme="yellow" size="sm">
                    RRF #{rrfRank}
                  </Badge>
                </Tooltip>
              )}
              <Text fontSize="sm" fontWeight="bold" color="green.300">
                Total: {totalScore.toFixed(3)}
              </Text>
            </HStack>
          </HStack>

          {/* Search Type Summary */}
          <Wrap spacing={2}>
            {Array.from(new Set(explanations.map(e => e.search_type))).map(type => {
              const typeExplanations = explanations.filter(e => e.search_type === type);
              const typeScore = typeExplanations.reduce((sum, e) => sum + e.score, 0);
              const colorScheme = getSearchTypeColor(type);
              
              return (
                <WrapItem key={type}>
                  <Badge colorScheme={colorScheme} size="sm">
                    {type.replace('_', ' ')}: {typeScore.toFixed(2)}
                  </Badge>
                </WrapItem>
              );
            })}
          </Wrap>

          {/* Original Rankings */}
          {Object.keys(originalRanks).length > 0 && (
            <Box>
              <Text fontSize="xs" color="gray.400" mb={1}>
                Original rankings:
              </Text>
              <Wrap spacing={2}>
                {Object.entries(originalRanks).map(([method, rank]) => (
                  <WrapItem key={method}>
                    <Badge variant="outline" size="sm">
                      {method}: #{rank}
                    </Badge>
                  </WrapItem>
                ))}
              </Wrap>
            </Box>
          )}
        </VStack>
      )}

      {/* Individual Explanations */}
      <VStack spacing={2} align="stretch">
        {displayedExplanations.map((explanation, index) => (
          <SearchExplanationItem
            key={`${explanation.field}-${explanation.search_type}-${index}`}
            explanation={explanation}
            maxScore={maxScore}
          />
        ))}
      </VStack>

      {/* Show More/Less Button */}
      {explanations.length > maxItems && (
        <HStack justify="center" mt={3}>
          <IconButton
            size="sm"
            variant="ghost"
            onClick={() => setShowAll(!showAll)}
            icon={showAll ? <ChevronUpIcon /> : <ChevronDownIcon />}
            aria-label={showAll ? "Show less" : "Show more"}
          />
          <Text fontSize="xs" color="gray.400">
            {showAll ? "Show less" : `Show ${explanations.length - maxItems} more`}
          </Text>
        </HStack>
      )}
    </Box>
  );
};

export default SearchExplanations;