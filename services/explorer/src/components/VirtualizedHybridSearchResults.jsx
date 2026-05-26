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

import React, { useMemo, useCallback, memo } from "react";
import {
  Box,
  VStack,
  HStack,
  Text,
  Badge,
  Card,
  CardBody,
  Divider,
  Tooltip,
  IconButton,
  Button,
  Collapse,
  Grid,
  GridItem,
  useDisclosure,
  CircularProgress,
  Alert,
  AlertIcon,
  AlertDescription,
  CloseButton,
} from "@chakra-ui/react";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CopyIcon,
  ExternalLinkIcon,
  SearchIcon,
  CheckIcon,
  CloseIcon,
  WarningIcon,
} from "@chakra-ui/icons";
import VirtualizedResults from "./VirtualizedResults";
import SearchExplanations from "../SearchExplanations";
import NavigableAssetImage from "./NavigableAssetImage";
import { useSmartImageLoader } from "../hooks/useSmartImageLoader";
import { formatFileSize, formatDate } from "../utils/formatUtils";

// Query relevance indicator component with async validation state support
const QueryRelevanceIndicator = memo(({ queryRelevance, validationState }) => {
  // Pending / validating states
  if (validationState === "pending" || validationState === "validating") {
    return (
      <Tooltip label={validationState === "validating" ? "Validating..." : "Waiting to validate"} placement="top" hasArrow>
        <Box
          position="absolute"
          top={2}
          left={2}
          zIndex={10}
          display="flex"
          alignItems="center"
          justifyContent="center"
          w={6}
          h={6}
          borderRadius="full"
          bg="gray.500"
          boxShadow="0 2px 4px rgba(0,0,0,0.4)"
          border="2px solid"
          borderColor="gray.400"
        >
          <CircularProgress isIndeterminate size="14px" color="white" trackColor="transparent" />
        </Box>
      </Tooltip>
    );
  }

  // Timeout / error states
  if (validationState === "timeout" || validationState === "error") {
    return (
      <Tooltip label={validationState === "timeout" ? "Validation timed out" : "Validation error"} placement="top" hasArrow>
        <Box
          position="absolute"
          top={2}
          left={2}
          zIndex={10}
          display="flex"
          alignItems="center"
          justifyContent="center"
          w={6}
          h={6}
          borderRadius="full"
          bg="orange.500"
          boxShadow="0 2px 4px rgba(0,0,0,0.4)"
          border="2px solid"
          borderColor="orange.300"
        >
          <WarningIcon color="white" boxSize={3} />
        </Box>
      </Tooltip>
    );
  }

  // Validated / rejected states (existing behavior)
  if (!queryRelevance || typeof queryRelevance.is_match !== 'boolean') {
    return null;
  }

  const isMatch = queryRelevance.is_match;
  const confidence = queryRelevance.confidence;
  const similarityScore = queryRelevance.similarity_score;
  const reasoning = queryRelevance.reasoning;

  const tooltipLabel = `${isMatch ? 'Match' : 'No Match'}\nConfidence: ${(confidence * 100).toFixed(0)}%\nSimilarity: ${similarityScore}%${reasoning ? `\n${reasoning}` : ''}`;

  return (
    <Tooltip label={tooltipLabel} placement="top" hasArrow whiteSpace="pre-wrap">
      <Box
        position="absolute"
        top={2}
        left={2}
        zIndex={10}
        display="flex"
        alignItems="center"
        justifyContent="center"
        w={6}
        h={6}
        borderRadius="full"
        bg={isMatch ? "green.500" : "red.500"}
        boxShadow="0 2px 4px rgba(0,0,0,0.4)"
        border="2px solid"
        borderColor={isMatch ? "green.300" : "red.300"}
      >
        {isMatch ? (
          <CheckIcon color="white" boxSize={3} />
        ) : (
          <CloseIcon color="white" boxSize={2.5} />
        )}
      </Box>
    </Tooltip>
  );
});

// Memoized components for better performance
const HighlightedText = memo(({ text, matchedTerms = [], isValue = false }) => {
  if (!matchedTerms || matchedTerms.length === 0 || !text) {
    return (
      <Text fontSize="xs" wordBreak="break-word" color={isValue ? "gray.200" : "inherit"}>
        {text}
      </Text>
    );
  }

  const pattern = new RegExp(`(${matchedTerms.map(term => 
    term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  ).join('|')})`, 'gi');

  const parts = text.split(pattern);
  
  return (
    <Text fontSize="xs" wordBreak="break-word">
      {parts.map((part, index) => {
        const isMatch = matchedTerms.some(term => 
          part.toLowerCase() === term.toLowerCase()
        );
        return isMatch ? (
          <Text as="mark" key={index} bg="yellow.300" color="gray.800" px={1} borderRadius="sm" fontWeight="bold">
            {part}
          </Text>
        ) : (
          <Text as="span" key={index} color={isValue ? "gray.200" : "inherit"}>
            {part}
          </Text>
        );
      })}
    </Text>
  );
});

const QueryMatchBadges = memo(({ explanations = [], showScores = false }) => {
  if (!explanations || explanations.length === 0) {
    return null;
  }

  // Helper function to truncate text
  const truncateText = (text, maxLength = 25) => {
    if (!text || text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  return (
    <VStack spacing={2} align="stretch">
      {explanations.map((explanation, index) => {
        const { search_type, matched_terms = [], matched_vectors = [] } = explanation;
        
        if (search_type === 'text_to_vector' || search_type === 'image_to_vector' || search_type === 'vector') {
          return (
            <HStack key={index} spacing={2}>
              <Badge colorScheme="purple" size="sm">
                Vector Match
              </Badge>
              {showScores && (
                <Text fontSize="xs" color="gray.300">
                  {search_type} (score: {explanation.score?.toFixed(3)})
                </Text>
              )}
            </HStack>
          );
        }
        
        if (matched_terms && matched_terms.length > 0) {
          return (
            <HStack key={index} spacing={1} wrap="wrap">
              <Badge colorScheme="blue" size="sm">
                {truncateText(search_type, 15)}:
              </Badge>
              {matched_terms.slice(0, 5).map((term, termIndex) => (
                <Tooltip key={termIndex} label={term} placement="top">
                  <Badge colorScheme="green" size="sm" variant="outline" maxW="150px">
                    <Text fontSize="xs" noOfLines={1}>
                      {truncateText(term, 20)}
                    </Text>
                  </Badge>
                </Tooltip>
              ))}
              {matched_terms.length > 5 && (
                <Badge colorScheme="gray" size="sm" variant="outline">
                  +{matched_terms.length - 5} more
                </Badge>
              )}
            </HStack>
          );
        }
        
        return null;
      })}
    </VStack>
  );
});

const SmartHighlightedContent = memo(({ result, searchQuery = "" }) => {
  const highlightableContent = useMemo(() => {
    if (!result.source) {
      return [];
    }

    const explanations = result.metadata?.explanations || [];
    const matchedFields = new Set();
    const textTermsToHighlight = [];

    explanations.forEach(explanation => {
      if (explanation.matched_terms) {
        explanation.matched_terms.forEach(term => {
          if (term.includes('usd_properties.value_field') || term.includes('property_')) {
            matchedFields.add('usd_properties');
          }
          if (term.includes('path.tree_field') || term.includes('path_field')) {
            matchedFields.add('path');
          }
          if (term.includes('name_field')) {
            matchedFields.add('name');
          }
          
          if (!term.includes('.') && !term.includes('_field')) {
            textTermsToHighlight.push(term);
          }
        });
      }
    });

    if (searchQuery) {
      const queryTerms = searchQuery.toLowerCase().split(/\s+/).filter(term => term.length > 2);
      textTermsToHighlight.push(...queryTerms);
    }

    const content = [];

    if (matchedFields.has('path') && result.source.path) {
      content.push({
        label: "Path",
        content: result.source.path,
        color: "cyan"
      });
    }

    if (matchedFields.has('name') && result.source.name) {
      content.push({
        label: "Name", 
        content: result.source.name,
        color: "orange"
      });
    }

    if (matchedFields.has('usd_properties') && result.source.usd_properties) {
      result.source.usd_properties.slice(0, 3).forEach(prop => {
        if (prop.value && textTermsToHighlight.some(term =>
          String(prop.value).toLowerCase().includes(term.toLowerCase())
        )) {
          content.push({
            label: "Property",
            content: `${prop.name}: ${prop.value}`,
            color: "teal"
          });
        }
      });
    }

    return { content, textTermsToHighlight };
  }, [result, searchQuery]);

  if (highlightableContent.content.length === 0) {
    return null;
  }

  return (
    <HStack spacing={2} wrap="wrap" align="start">
      {highlightableContent.content.slice(0, 3).map((item, index) => (
        <Tooltip key={index} label={`${item.label}: ${item.content}`} placement="top">
          <Badge 
            colorScheme={item.color} 
            size="sm" 
            variant="outline"
            px={3}
            py={2}
            borderRadius="md"
            display="flex"
            alignItems="center"
            gap={2}
            flexShrink={0}
            maxW="250px"
          >
            <Text fontSize="xs" fontWeight="bold" color={`${item.color}.400`} whiteSpace="nowrap">
              {item.label}:
            </Text>
            <Box maxW="150px" overflow="hidden">
              <HighlightedText 
                text={item.content.length > 30 ? item.content.substring(0, 30) + '...' : item.content}
                matchedTerms={highlightableContent.textTermsToHighlight}
                isValue={true}
              />
            </Box>
          </Badge>
        </Tooltip>
      ))}
      {highlightableContent.content.length > 3 && (
        <Badge colorScheme="gray" size="sm" variant="outline">
          +{highlightableContent.content.length - 3} more
        </Badge>
      )}
    </HStack>
  );
});

const VirtualizedResultGridItem = memo(({
  result,
  index,
  onItemClick,
  copyToClipboard,
  onFindSimilar,
  showScores = false,
  gridSize = "L",
  searchQuery = "",
  getHeaders,
  apiUrl,
  getLoadingState
}) => {
  const baseKey = result.source?.base_key || result.source?.url || result.id;
  const filename = baseKey?.split('/').pop() || 'Unknown';

  const handleItemClick = useCallback(() => {
    onItemClick?.(result);
  }, [onItemClick, result]);

  const handleCopy = useCallback((e) => {
    e.stopPropagation();
    copyToClipboard?.(baseKey);
  }, [copyToClipboard, baseKey]);

  const handleFindSimilar = useCallback((e) => {
    e.stopPropagation();
    onFindSimilar?.(baseKey);
  }, [onFindSimilar, baseKey]);

  return (
    <Card
      bg="gray.800"
      borderColor={result._validationState === "rejected" ? "red.800" : "gray.600"}
      opacity={result._validationState === "rejected" ? 0.5 : 1}
      _hover={{ borderColor: "green.500", shadow: "lg" }}
      transition="all 0.3s ease"
      cursor="pointer"
      onClick={handleItemClick}
      h="100%"
    >
      <CardBody p={gridSize === "S" ? 2 : 3}>
        <VStack spacing={gridSize === "S" ? 2 : 3} align="stretch" h="100%">
          <Box position="relative">
            <QueryRelevanceIndicator queryRelevance={result.query_relevance} validationState={result._validationState} />
            <NavigableAssetImage
              result={result}
              index={index}
              getHeaders={getHeaders}
              apiUrl={apiUrl}
              parentLoadingState={getLoadingState?.(result, index)}
              width="100%"
              height={gridSize === "S" ? "128px" : "256px"}
              borderRadius="md"
            />
          </Box>

          <VStack spacing={gridSize === "S" ? 1 : 2} align="stretch" flex={1}>
            <Tooltip label={baseKey} placement="top">
              <Text 
                fontSize={gridSize === "S" ? "xs" : "sm"}
                fontWeight="semibold" 
                noOfLines={gridSize === "S" ? 1 : 2}
                lineHeight="1.2"
              >
                {filename}
              </Text>
            </Tooltip>

            {showScores && (
              <HStack spacing={1} wrap="wrap">
                <Badge colorScheme="green" size="xs">
                  {result.score.toFixed(2)}
                </Badge>
                <Badge colorScheme="blue" size="xs">
                  RRF: {result.rrf_score.toFixed(2)}
                </Badge>
                {result.metadata?.rrf_rank && (
                  <Badge colorScheme="yellow" size="xs">
                    #{result.metadata.rrf_rank}
                  </Badge>
                )}
              </HStack>
            )}

            {gridSize !== "S" && (
              <QueryMatchBadges explanations={result.metadata?.explanations} showScores={showScores} />
            )}

            <VStack spacing={1} align="stretch" fontSize="2xs" color="gray.300" flex={1}>
              {result.source?.size && (
                <Text>Size: {formatFileSize(result.source.size)}</Text>
              )}
              {gridSize !== "S" && result.source?.modified_timestamp && (
                <Text>Modified: {new Date(result.source.modified_timestamp).toLocaleDateString()}</Text>
              )}
            </VStack>

            <HStack justify={gridSize === "S" ? "center" : "space-between"} pt={gridSize === "S" ? 1 : 2}>
              {gridSize === "S" ? (
                <Tooltip label="View details">
                  <IconButton
                    size="xs"
                    variant="ghost"
                    icon={<ExternalLinkIcon />}
                    onClick={handleItemClick}
                    aria-label="View details"
                  />
                </Tooltip>
              ) : (
                <>
                  <HStack spacing={1}>
                    {copyToClipboard && (
                      <Tooltip label="Copy URL">
                        <IconButton
                          size="xs"
                          variant="ghost"
                          icon={<CopyIcon />}
                          onClick={handleCopy}
                          aria-label="Copy URL"
                        />
                      </Tooltip>
                    )}
                    <Tooltip label="Find similar assets">
                      <IconButton
                        size="xs"
                        variant="ghost"
                        icon={<SearchIcon />}
                        onClick={handleFindSimilar}
                        aria-label="Find similar assets"
                        colorScheme="purple"
                      />
                    </Tooltip>
                  </HStack>
                  <Tooltip label="View details">
                    <IconButton
                      size="xs"
                      variant="ghost"
                      icon={<ExternalLinkIcon />}
                      onClick={handleItemClick}
                      aria-label="View details"
                    />
                  </Tooltip>
                </>
              )}
            </HStack>
          </VStack>
        </VStack>
      </CardBody>
    </Card>
  );
});

const VirtualizedResultListItem = memo(({
  result,
  index,
  onItemClick,
  copyToClipboard,
  onFindSimilar,
  showScores = false,
  maxScore = 1,
  minScore = 0,
  searchQuery = "",
  getHeaders,
  apiUrl,
  getLoadingState
}) => {
  const { isOpen, onToggle } = useDisclosure();
  
  const allMatchedTerms = useMemo(() => {
    return result.metadata?.explanations?.flatMap(exp => exp.matched_terms || []) || [];
  }, [result.metadata?.explanations]);
  
  const baseKey = result.source?.base_key || result.source?.url || result.id;
  const filename = baseKey?.split('/').pop() || 'Unknown';

  const handleItemClick = useCallback(() => {
    onItemClick?.(result);
  }, [onItemClick, result]);

  const handleCopy = useCallback((e) => {
    e.stopPropagation();
    copyToClipboard?.(baseKey);
  }, [copyToClipboard, baseKey]);

  const handleFindSimilar = useCallback((e) => {
    e.stopPropagation();
    onFindSimilar?.(baseKey);
  }, [onFindSimilar, baseKey]);

  const handleToggle = useCallback((e) => {
    e.stopPropagation();
    onToggle();
  }, [onToggle]);

  return (
    <Card
      bg="gray.800"
      borderColor={result._validationState === "rejected" ? "red.800" : "gray.600"}
      opacity={result._validationState === "rejected" ? 0.5 : 1}
      _hover={{ borderColor: "green.500", shadow: "lg" }}
      transition="all 0.3s ease"
      cursor="pointer"
      onClick={handleItemClick}
    >
      <CardBody p={4}>
        <Grid templateColumns="200px 1fr auto" gap={4} alignItems="start">
          <GridItem>
            <Box position="relative">
              <QueryRelevanceIndicator queryRelevance={result.query_relevance} validationState={result._validationState} />
              <NavigableAssetImage
                result={result}
                index={index}
                getHeaders={getHeaders}
                apiUrl={apiUrl}
                parentLoadingState={getLoadingState?.(result, index)}
                width="200px"
                height="150px"
                borderRadius="md"
              />
            </Box>
          </GridItem>

          <GridItem>
            <VStack spacing={3} align="stretch">
              <HStack justify="space-between">
                <VStack align="start" spacing={1} flex={1}>
                  <Tooltip label={baseKey} placement="top">
                    <HighlightedText 
                      text={filename}
                      matchedTerms={allMatchedTerms}
                    />
                  </Tooltip>
                  {showScores && (
                    <HStack>
                      <Badge colorScheme="green" size="sm">
                        Score: {result.score.toFixed(3)}
                      </Badge>
                      <Badge colorScheme="blue" size="sm">
                        RRF: {result.rrf_score.toFixed(3)}
                      </Badge>
                      {result.metadata?.rrf_rank && (
                        <Badge colorScheme="yellow" size="sm">
                          Rank #{result.metadata.rrf_rank}
                        </Badge>
                      )}
                    </HStack>
                  )}
                </VStack>
                
                <HStack>
                  {copyToClipboard && (
                    <Tooltip label="Copy URL">
                      <IconButton
                        size="sm"
                        variant="ghost"
                        icon={<CopyIcon />}
                        onClick={handleCopy}
                        aria-label="Copy URL"
                      />
                    </Tooltip>
                  )}
                  <Tooltip label="Find similar assets">
                    <IconButton
                      size="sm"
                      variant="ghost"
                      icon={<SearchIcon />}
                      onClick={handleFindSimilar}
                      aria-label="Find similar assets"
                      colorScheme="purple"
                    />
                  </Tooltip>
                  <Tooltip label="View details">
                    <IconButton
                      size="sm"
                      variant="ghost"
                      icon={<ExternalLinkIcon />}
                      onClick={handleItemClick}
                      aria-label="View details"
                    />
                  </Tooltip>
                </HStack>
              </HStack>

              <QueryMatchBadges explanations={result.metadata?.explanations} showScores={showScores} />
              <SmartHighlightedContent result={result} searchQuery={searchQuery} />

              {result.source && (
                <VStack spacing={1} align="stretch" fontSize="sm" color="gray.300">
                  {result.source.size && (
                    <Text>Size: {formatFileSize(result.source.size)}</Text>
                  )}
                  {result.source.modified_timestamp && (
                    <Text>Modified: {new Date(result.source.modified_timestamp).toLocaleDateString()}</Text>
                  )}
                </VStack>
              )}
            </VStack>
          </GridItem>

          <GridItem>
            <VStack>
              <IconButton
                size="sm"
                variant="ghost"
                icon={isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}
                onClick={handleToggle}
                aria-label="Toggle explanations"
              />
              <Text fontSize="xs" color="gray.300" textAlign="center">
                Why this matched
              </Text>
            </VStack>
          </GridItem>
        </Grid>

        <Collapse in={isOpen} animateOpacity>
          <Divider my={4} />
          <SearchExplanations
            explanations={result.metadata?.explanations || []}
            totalScore={result.score}
            rrfRank={result.metadata?.rrf_rank}
            originalRanks={result.metadata?.original_ranks || {}}
            showSummary={false}
            maxItems={3}
          />
        </Collapse>
      </CardBody>
    </Card>
  );
});

const VirtualizedHybridSearchResults = ({
  results = [],
  onItemClick,
  copyToClipboard,
  onFindSimilar,
  showScores = false,
  viewMode = "list",
  gridSize = "L",
  isLoading = false,
  isEmpty = false,
  searchQuery = "",
  getHeaders,
  apiUrl,
  isValidating = false,
  validatedCount = 0,
  totalToValidate = 0,
  vlmUnavailable = false
}) => {
  const [vlmBannerDismissed, setVlmBannerDismissed] = React.useState(false);
  React.useEffect(() => {
    if (vlmUnavailable) setVlmBannerDismissed(false);
  }, [vlmUnavailable]);
  // Calculate score range for normalization
  const { maxScore, minScore } = useMemo(() => {
    if (results.length === 0) return { maxScore: 1, minScore: 0 };
    const scores = results.map(r => r.score);
    return {
      maxScore: Math.max(...scores),
      minScore: Math.min(...scores)
    };
  }, [results]);

  // Centralized offset-0 image loading. NavigableAssetImage consumes this via
  // `parentLoadingState` so it does not self-load offset 0.
  const { getLoadingState } = useSmartImageLoader(results, getHeaders, apiUrl);

  // Grid item renderer
  const renderGridItem = useCallback((result, index) => (
    <VirtualizedResultGridItem
      result={result}
      index={index}
      onItemClick={onItemClick}
      copyToClipboard={copyToClipboard}
      onFindSimilar={onFindSimilar}
      showScores={showScores}
      gridSize={gridSize}
      searchQuery={searchQuery}
      getHeaders={getHeaders}
      apiUrl={apiUrl}
      getLoadingState={getLoadingState}
    />
  ), [onItemClick, copyToClipboard, onFindSimilar, showScores, gridSize, searchQuery, getHeaders, apiUrl, getLoadingState]);

  // List item renderer
  const renderListItem = useCallback((result, index) => (
    <VirtualizedResultListItem
      result={result}
      index={index}
      onItemClick={onItemClick}
      copyToClipboard={copyToClipboard}
      onFindSimilar={onFindSimilar}
      showScores={showScores}
      maxScore={maxScore}
      minScore={minScore}
      searchQuery={searchQuery}
      getHeaders={getHeaders}
      apiUrl={apiUrl}
      getLoadingState={getLoadingState}
    />
  ), [onItemClick, copyToClipboard, onFindSimilar, showScores, maxScore, minScore, searchQuery, getHeaders, apiUrl, getLoadingState]);

  const handleCopyAllUrls = useCallback(() => {
    const allUrls = results.map((result) => 
      result.source?.base_key || result.source?.url || result.id
    ).filter(Boolean).join("\n");
    copyToClipboard?.(allUrls);
  }, [results, copyToClipboard]);

  if (isLoading) {
    return (
      <Box textAlign="center" py={8}>
        <CircularProgress isIndeterminate color="green.400" />
        <Text mt={4} color="gray.300">Searching...</Text>
      </Box>
    );
  }

  if (isEmpty) {
    return (
      <Box textAlign="center" py={8}>
        <Text fontSize="md" color="gray.300">
          No results found. Try adjusting your search terms or configuration.
        </Text>
      </Box>
    );
  }

  return (
    <VStack spacing={4} align="stretch">
      {vlmUnavailable && !vlmBannerDismissed && (
        <Alert status="warning" borderRadius="md">
          <AlertIcon />
          <AlertDescription fontSize="sm">
            VLM validation unavailable — showing all results without relevance scoring.
          </AlertDescription>
          <CloseButton
            position="absolute"
            right="8px"
            top="8px"
            onClick={() => setVlmBannerDismissed(true)}
          />
        </Alert>
      )}
      {/* Results Summary */}
      <HStack justify="space-between" wrap="wrap">
        <HStack spacing={4}>
          <Text fontSize="sm" color="gray.300">
            {results.length} results found
          </Text>
          {!vlmUnavailable && (isValidating || validatedCount > 0) && totalToValidate > 0 && (
            <HStack spacing={2}>
              {isValidating && <CircularProgress isIndeterminate size="16px" color="green.400" />}
              <Text fontSize="xs" color="gray.400">
                Validated {validatedCount}/{totalToValidate}
              </Text>
            </HStack>
          )}
          {copyToClipboard && (
            <Button
              size="sm"
              leftIcon={<CopyIcon />}
              onClick={handleCopyAllUrls}
              variant="outline"
              colorScheme="blue"
            >
              Copy All URLs
            </Button>
          )}
        </HStack>
        <HStack>
          <Text fontSize="xs" color="gray.500">
            Score range: {minScore.toFixed(3)} - {maxScore.toFixed(3)}
          </Text>
        </HStack>
      </HStack>

      {/* Virtualized Results */}
      <VirtualizedResults
        items={results}
        renderItem={viewMode === "grid" ? renderGridItem : renderListItem}
        itemHeight={viewMode === "grid" ? (gridSize === "S" ? 200 : 400) : 250}
        containerHeight="calc(100vh - 300px)" // Full height minus space for header, controls, and summary
        overscan={5}
        gridMode={viewMode === "grid"}
        itemWidth={gridSize === "S" ? 140 : 280}
        gap={viewMode === "grid" ? (gridSize === "S" ? 8 : 16) : 16}
      />
    </VStack>
  );
};

export default VirtualizedHybridSearchResults;