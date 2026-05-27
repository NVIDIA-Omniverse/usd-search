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

import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  Box,
  Button,
  CircularProgress,
  CircularProgressLabel,
  Collapse,
  Divider,
  Flex,
  GridItem,
  Heading,
  HStack,
  IconButton,
  Image,
  Input,
  InputGroup,
  InputLeftAddon,
  InputRightElement,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Popover,
  PopoverArrow,
  PopoverBody,
  PopoverCloseButton,
  PopoverContent,
  PopoverHeader,
  PopoverTrigger,
  Select,
  SimpleGrid,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Tooltip,
  Tr,
  useDisclosure,
  useToast,
  VStack,
  RadioGroup,
  Radio,
  Thead,
  Checkbox,
} from "@chakra-ui/react";
import { CloseIcon, LockIcon, UnlockIcon, CopyIcon, InfoIcon, RepeatIcon, ChevronDownIcon } from "@chakra-ui/icons";
import GraphVisualization from "./Graph";
import { apiUrl, IMAGE_SIZE, AUTH_CONFIG, DUPLICATE_REMOVAL_THRESHOLD } from "./config";
import FilterByPropertiesInput from "./propertiesInput";

// Shared utility function for status color mapping
const getStatusColor = (status) => {
  if (!status) return "white";
  const lowerStatus = status.toLowerCase();
  if (lowerStatus === "ok" || lowerStatus === "completed" || lowerStatus === "success") {
    return "green.400";
  } else if (lowerStatus === "processing" || lowerStatus === "pending" || lowerStatus === "running") {
    return "blue.400";
  } else if (lowerStatus === "queued") {
    return "yellow.400";
  } else {
    return "red.400";
  }
};

// Function to calculate overall index status
const calculateOverallIndexStatus = (pluginStatuses) => {
  if (!pluginStatuses || Object.keys(pluginStatuses).length === 0) {
    return { status: "Unknown", color: "gray.400" };
  }

  const statuses = Object.values(pluginStatuses);
  const hasError = statuses.some(status => 
    status && status.toLowerCase().includes("error")
  );
  const hasProcessing = statuses.some(status => 
    status && (status.toLowerCase().includes("processing") || 
               status.toLowerCase().includes("pending") || 
               status.toLowerCase().includes("running") ||
               status.toLowerCase().includes("queued") ||
               status.toLowerCase().includes("thumbnail_missing"))
  );
  const allCompleted = statuses.every(status => 
    status && (status.toLowerCase().includes("ok") || 
               status.toLowerCase().includes("completed") || 
               status.toLowerCase().includes("success") ||
               status.toLowerCase().includes("thumbnail_missing"))
  );

  if (hasError) {
    return { status: "Error", color: "red.400" };
  } else if (allCompleted) {
    return { status: "Ok", color: "green.400" };
  } else if (hasProcessing) {
    return { status: "Partial", color: "yellow.400" };
  } else {
    return { status: "Unknown", color: "gray.400" };
  }
};

// Utility function to format file size in human-readable format
const formatFileSize = (bytes) => {
  if (bytes === 0) return '0 Bytes';
  
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

// Reusable status display component
const StatusDisplay = ({ url, fetchStatusFunction, title }) => {
  const [indexingStatus, setIndexingStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    if (url && fetchStatusFunction) {
      setIsLoading(true);
      try {
        const status = await fetchStatusFunction(url);
        setIndexingStatus(status);
      } finally {
        setIsLoading(false);
      }
    }
  }, [url, fetchStatusFunction]);

  // Automatically fetch status when component mounts (popover opens)
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  if (isLoading) {
    return <Text>Loading indexing status...</Text>;
  }

  if (!indexingStatus) {
    return (
      <VStack spacing={2}>
        <Text>No indexing status available</Text>
        <Button size="sm" onClick={fetchStatus}>
          Refresh Status
        </Button>
      </VStack>
    );
  }

  return (
    <VStack align="stretch" spacing={2}>
      <Table variant="simple" size="sm">
        <Thead>
          <Tr>
            <Th>Plugin Name</Th>
            <Th>Status</Th>
            <Th>Timestamp</Th>
          </Tr>
        </Thead>
        <Tbody>
          {indexingStatus.split(', ').map((status, index) => {
            const [pluginName, statusWithTimestamp] = status.split(': ');
            const statusMatch = statusWithTimestamp.match(/^([^(]+)(\([^)]+\))?$/);
            const statusValue = statusMatch ? statusMatch[1].trim() : statusWithTimestamp;
            const rawTimestamp = statusMatch && statusMatch[2] ? statusMatch[2].replace(/[()]/g, '') : '';
            
            // Format timestamp to remove seconds and milliseconds
            let formattedTimestamp = rawTimestamp;
            if (rawTimestamp) {
              try {
                const date = new Date(rawTimestamp);
                if (!isNaN(date.getTime())) {
                  // Format as YYYY-MM-DD HH:MM
                  formattedTimestamp = date.toISOString().slice(0, 16).replace('T', ' ');
                }
              } catch (e) {
                // If parsing fails, keep original timestamp
                formattedTimestamp = rawTimestamp;
              }
            }
            
            return (
              <Tr key={index}>
                <Td fontSize="sm" color="white">{pluginName}</Td>
                <Td>
                  <Text fontSize="sm" color={getStatusColor(statusValue)}>{statusValue}</Text>
                </Td>
                <Td fontSize="sm" color="white">{formattedTimestamp || '-'}</Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
      <Button size="sm" onClick={fetchStatus}>
        Refresh Status
      </Button>
    </VStack>
  );
};

const VisionMetadataTable = ({ data, url, fetchIndexingStatus, triggerVisionMetadataReindex, refreshVisionMetadata, plugins }) => {
  // Check if there are active vision metadata plugins
  const hasVisionMetadataPlugins = plugins?.active?.some(plugin => plugin.name.includes("vision_metadata")) || false;

  if (typeof data !== "object") {
    return <>{data}</>;
  }
  if (data === null || Object.keys(data).length === 0) {
    return (
      <>
        <Tr>
          <Th colSpan={2}
            borderBottom="1px solid" 
            borderColor="gray.300" 
            pb={2} 
            mb={2}
          >
            <HStack justify="space-between" align="center" spacing={4}>
              <Text 
                fontSize="lg" 
                fontWeight="bold" 
              >
                Vision Generated Metadata
              </Text>
            </HStack>
          </Th>
        </Tr>
        <Tr>
          <Th></Th>
          <Td>
            {!hasVisionMetadataPlugins ? (
              <Text>Vision metadata extraction is not enabled for this instance (check with your system administrator)</Text>
            ) : (
              <Text>No Vision Generated Metadata.</Text>
            )}
          </Td>
        </Tr>
      </>
    );
  }

  return (
    <>
      <Tr>
        <Th colSpan={2}>
          <Box 
            width="90vw"
            borderBottom="1px solid" 
            borderColor="gray.300" 
            pb={2} 
            mb={2}
          >
            <HStack justify="space-between" align="center" spacing={4}>
              <Text 
                fontSize="lg" 
                fontWeight="bold" 
              >
                Vision Generated Metadata
              </Text>
            </HStack>
          </Box>
        </Th>
      </Tr>
      {Object.entries(data).map(([key, value], index) => {
        const prefixes = [
          "vision_generated_rendering_to_vision_metadata_",
          "vision_generated_thumbnail_to_vision_metadata_",
          "vision_generated_image_to_vision_metadata_",
        ];

        let displayKey = key;

        prefixes.forEach((prefix) => {
          if (displayKey.startsWith(prefix)) {
            displayKey = displayKey.slice(prefix.length);
          }
        });

        return (
          <Tr key={index}>
            <Th>{displayKey}</Th>
            <Td>{value}</Td>
          </Tr>
        );
      })}
    </>
  );
};

const USDPropertiesTable = ({ usdProperties, url, fetchUSDPropertiesIndexingStatus, expandedGroups, setExpandedGroups }) => {
  if (!usdProperties || typeof usdProperties !== "object" || Object.keys(usdProperties).length === 0) {
    return (
      <Tr>
        <Td colSpan={2} p={0}>
          <Text p={4}>No USD properties available.</Text>
        </Td>
      </Tr>
    );
  }

  return (
    <Tr>
      <Td colSpan={2} p={0}>
        {(() => {
          // Group properties by the part before the first colon
          const groupedProperties = {};
          Object.entries(usdProperties).forEach(([key, value]) => {
            const colonIndex = key.indexOf(':');
            const groupName = colonIndex !== -1 ? key.substring(0, colonIndex) : 'Other';
            const propertyName = colonIndex !== -1 ? key.substring(colonIndex + 1) : key;
            
            if (!groupedProperties[groupName]) {
              groupedProperties[groupName] = [];
            }
            groupedProperties[groupName].push({ name: propertyName, value });
          });

          return Object.entries(groupedProperties).map(([groupName, properties], groupIndex) => (
            <Box key={groupIndex} mb={2}>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setExpandedGroups(prev => ({
                  ...prev,
                  [groupName]: !prev[groupName]
                }))}
                mb={1}
                width="100%"
                justifyContent="flex-start"
              >
                {expandedGroups[groupName] ? "▼" : "▶"} {groupName} ({properties.length} properties)
              </Button>
              <Collapse startingHeight={0} in={expandedGroups[groupName]}>
                <Box>
                  <Table variant="striped" size="sm" width="full">
                    <Tbody>
                      {properties.map(({ name, value }, index) => (
                        <Tr key={index}>
                          <Th>{name}</Th>
                          <Td style={{ wordBreak: "break-all" }}>
                            {typeof value === "object" ? JSON.stringify(value) : value}
                          </Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                </Box>
              </Collapse>
            </Box>
          ));
        })()}
      </Td>
    </Tr>
  );
};

const PluginStatusTable = ({ url, plugins, triggerReindexIndividualPlugin, getHeaders, onStatusChange }) => {
  const [pluginStatuses, setPluginStatuses] = useState({});
  const [pluginStatusDetails, setPluginStatusDetails] = useState({});
  const [isLoading, setIsLoading] = useState(false);

  const fetchPluginStatuses = useCallback(async () => {
    if (!url) return;
    
    setIsLoading(true);
    try {
      const headers = getHeaders();
      const response = await fetch(`${apiUrl}/info/indexing/asset/status?url=${encodeURIComponent(url)}`, { headers });
      
      if (response.status === 200) {
        const data = await response.json();
        const statuses = {};
        const statusDetails = {};
        
        if (data.plugins_statuses) {
          Object.entries(data.plugins_statuses).forEach(([pluginName, pluginData]) => {
            if (pluginData.plugin_status_history && pluginData.plugin_status_history.length > 0) {
              const firstStatus = pluginData.plugin_status_history[0];
              const status = firstStatus.status || 'Unknown';
              statuses[pluginName] = status;
              
              // Store detailed information for tooltip
              statusDetails[pluginName] = {
                status: status,
                timestamp: firstStatus.processing_timestamp || null,
                exception: firstStatus.exception || null
              };
            } else {
              statuses[pluginName] = 'No status';
              statusDetails[pluginName] = {
                status: 'No status',
                timestamp: null,
                exception: null
              };
            }
          });
        }
        
        setPluginStatuses(statuses);
        setPluginStatusDetails(statusDetails);
        // Call the callback with updated statuses
        if (onStatusChange) {
          onStatusChange(statuses);
        }
      }
    } catch (err) {
      console.error("Error fetching plugin statuses:", err);
    } finally {
      setIsLoading(false);
    }
  }, [url, getHeaders, onStatusChange]);

  useEffect(() => {
    fetchPluginStatuses();
  }, [fetchPluginStatuses]);

  // Helper function to format timestamp
  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'No timestamp available';
    
    try {
      const date = new Date(timestamp);
      if (isNaN(date.getTime())) {
        return timestamp; // Return original if parsing fails
      }
      // Format as YYYY-MM-DD HH:MM:SS
      return date.toISOString().slice(0, 19).replace('T', ' ');
    } catch (e) {
      return timestamp;
    }
  };

  // Helper function to create tooltip content
  const createTooltipContent = (pluginName) => {
    const details = pluginStatusDetails[pluginName];
    if (!details) return 'No status information available';
    
    let content = `Status: ${details.status}`;
    
    if (details.timestamp) {
      content += `\nTimestamp: ${formatTimestamp(details.timestamp)}`;
    }
    
    if (details.exception) {
      content += `\nException: ${details.exception}`;
    }
    
    return content;
  };

  // Filter active plugins to only include those that have status information
  const pluginsWithStatus = plugins.active?.filter(plugin => 
    pluginStatuses.hasOwnProperty(plugin.name)
  ) || [];

  if (!plugins.active || plugins.active.length === 0) {
    return (
      <Text fontSize="sm" color="gray.500">
        No active plugins available
      </Text>
    );
  }

  if (pluginsWithStatus.length === 0 && !isLoading) {
    return (
      <VStack spacing={3} align="stretch">
        <HStack justify="space-between">
          <Text fontSize="sm" fontWeight="bold">Plugin Status</Text>
          <Button size="sm" onClick={fetchPluginStatuses} isLoading={isLoading}>
            Refresh
          </Button>
        </HStack>
        <Text fontSize="sm" color="gray.500">
          No plugins with status information available for this asset
        </Text>
      </VStack>
    );
  }

  return (
    <VStack spacing={3} align="stretch">
      <HStack justify="space-between">
        <Text fontSize="sm" fontWeight="bold">Plugin Status</Text>
        <Button size="sm" onClick={fetchPluginStatuses} isLoading={isLoading}>
          Refresh
        </Button>
      </HStack>
      <Table variant="simple" size="sm">
        <Thead>
          <Tr>
            <Th>Plugin Name</Th>
            <Th>Status</Th>
            <Th>Action</Th>
          </Tr>
        </Thead>
        <Tbody>
          {pluginsWithStatus.map((plugin, index) => (
            <Tr key={index}>
              <Td fontSize="sm">
                {plugin.description ? (
                  <Tooltip 
                    label={plugin.description}
                    placement="top"
                    hasArrow
                    bg="gray.800"
                    color="white"
                    fontSize="sm"
                  >
                    <Text cursor="help">{plugin.name}</Text>
                  </Tooltip>
                ) : (
                  plugin.name
                )}
              </Td>
              <Td>
                <Tooltip 
                  label={createTooltipContent(plugin.name)}
                  placement="top"
                  hasArrow
                  bg="gray.800"
                  color="white"
                  fontSize="sm"
                  whiteSpace="pre-line"
                >
                  <Text fontSize="sm" color={getStatusColor(pluginStatuses[plugin.name])} cursor="help">
                    {pluginStatuses[plugin.name] || 'Loading...'}
                  </Text>
                </Tooltip>
              </Td>
              <Td>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => triggerReindexIndividualPlugin(url, plugin.name)}
                >
                  Re-index
                </Button>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </VStack>
  );
};

const ItemDetailsModal = ({ 
  isOpen, 
  onClose, 
  selectedItem, 
  modalExpanded, 
  show, 
  handleToggle, 
  copyToClipboard, 
  assetDependencies, 
  assetInverseDependencies, 
  usdProperties, 
  expandedGroups, 
  setExpandedGroups,
  fetchIndexingStatus,
  fetchUSDPropertiesIndexingStatus,
  triggerReindex,
  triggerVisionMetadataReindex,
  refreshUSDProperties,
  refreshDependencies,
  refreshVisionMetadata,
  triggerReindexAllPlugins,
  triggerReindexIndividualPlugin,
  getHeaders,
  plugins,
  showScores
}) => {
  const [pluginStatuses, setPluginStatuses] = useState({});
  const overallStatus = calculateOverallIndexStatus(pluginStatuses);

  return (
    <Modal
      size={modalExpanded ? "full" : "xl"}
      isOpen={isOpen}
      onClose={onClose}
    >
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Item Details</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          <Flex width={"100%"} direction={"horizontal"} justify={"center"}>
            <Image
              src={`data:image/png;base64,${selectedItem.image}`}
              alt="Detailed View"
              width="256"
            />
          </Flex>
          
          {/* Re-index buttons at the top */}
          <HStack justify="center" spacing={4} mt={4} mb={4}>
            <HStack spacing={2} align="center">
              <Text fontSize="sm" fontWeight="bold">Index Status</Text>
              <Text fontSize="sm" color={overallStatus.color} fontWeight="bold">
                {overallStatus.status}
              </Text>
            </HStack>
            <IconButton
              size="sm"
              icon={<RepeatIcon />}
              aria-label="Refresh"
              onClick={() => {
                // Refresh all data types
                refreshUSDProperties(selectedItem.url);
                refreshDependencies(selectedItem.url);
                refreshVisionMetadata(selectedItem.url);
              }}
            />
            <Button
              size="sm"
              // colorScheme="blue"
              onClick={() => triggerReindexAllPlugins(selectedItem.url)}
            >
              Re-index
            </Button>
            <Popover>
              <PopoverTrigger>
                <IconButton
                  size="sm"
                  icon={<ChevronDownIcon />}
                  aria-label="Re-index individual plugins"
                />
              </PopoverTrigger>
              <PopoverContent width="600px">
                <PopoverArrow size="sm" />
                <PopoverCloseButton />
                <PopoverHeader>Re-index Individual Plugins</PopoverHeader>
                <PopoverBody>
                  <PluginStatusTable 
                    url={selectedItem.url}
                    plugins={plugins}
                    triggerReindexIndividualPlugin={triggerReindexIndividualPlugin}
                    getHeaders={getHeaders}
                    onStatusChange={setPluginStatuses}
                  />
                </PopoverBody>
              </PopoverContent>
            </Popover>
          </HStack>
          
          <TableContainer>
            <Table variant="striped" size="sm" width="full">
              <Tbody>
                <Collapse startingHeight={120} in={show}>
                  {showScores && (
                    <Tr>
                      <Th>Score</Th>
                      <Td style={{ wordBreak: "break-all" }}>
                        {selectedItem.score}
                      </Td>
                    </Tr>
                  )}
                  <Tr>
                    <Th>URL</Th>
                    <Td style={{ wordBreak: "break-all" }}>
                      <IconButton
                        mr={2}
                        size="sm"
                        variant="outline"
                        icon={<CopyIcon />}
                        aria-label="Copy URL"
                        onClick={() => copyToClipboard(selectedItem.url)}
                      />
                      {selectedItem.url}
                    </Td>
                  </Tr>
                  <Tr>
                    <Th>Created By</Th>
                    <Td style={{ wordBreak: "break-all" }}>
                      {selectedItem.metadata.created_by}
                    </Td>
                  </Tr>
                  <Tr>
                    <Th>Modified</Th>
                    <Td style={{ wordBreak: "break-all" }}>
                      {selectedItem.metadata.modified}
                    </Td>
                  </Tr>
                  <Tr>
                    <Th>Size</Th>
                    <Td style={{ wordBreak: "break-all" }}>
                      {formatFileSize(selectedItem.metadata.size)}
                    </Td>
                  </Tr>
                  <Tr>
                    <Th>Etag</Th>
                    <Td style={{ wordBreak: "break-all" }}>
                      {selectedItem.metadata.etag}
                    </Td>
                  </Tr>
                  {typeof selectedItem.vision_generated_metadata ===
                  "object" ? (
                    <VisionMetadataTable
                      data={selectedItem.vision_generated_metadata}
                      url={selectedItem.url}
                      fetchIndexingStatus={fetchIndexingStatus}
                      triggerVisionMetadataReindex={triggerVisionMetadataReindex}
                      refreshVisionMetadata={refreshVisionMetadata}
                      plugins={plugins}
                    />
                  ) : (
                    selectedItem.vision_generated_metadata
                  )}
                  <Tr>
                    <Th colSpan={2}>
                      <Box 
                        width="90vw"
                        borderBottom="1px solid" 
                        borderColor="gray.300" 
                        pb={2} 
                        mb={2}
                      >
                        <HStack justify="space-between" align="center" spacing={4}>
                         <Text 
                            fontSize="lg" 
                            fontWeight="bold" 
                          >
                            Dependencies
                          </Text>
                        </HStack>
                      </Box>
                    </Th>
                  </Tr>
                  <GraphVisualization
                    data={assetDependencies}
                  ></GraphVisualization>
                  <Tr>
                    <Th colSpan={2}>Inverse Dependencies</Th>
                  </Tr>
                  <GraphVisualization
                    data={assetInverseDependencies}
                    isInverse={true}
                  ></GraphVisualization>
                  <Tr>
                    <Th colSpan={2}>
                      <Box 
                        width="90vw"
                        borderBottom="1px solid" 
                        borderColor="gray.300" 
                        pb={2} 
                        mb={2}
                      >
                        <HStack justify="space-between" align="center" spacing={4}>
                         <Text 
                            fontSize="lg" 
                            fontWeight="bold" 
                          >
                            USD Properties
                          </Text>
                        </HStack>
                      </Box>
                    </Th>
                  </Tr>
                  <USDPropertiesTable
                    usdProperties={usdProperties}
                    url={selectedItem.url}
                    fetchUSDPropertiesIndexingStatus={fetchUSDPropertiesIndexingStatus}
                    expandedGroups={expandedGroups}
                    setExpandedGroups={setExpandedGroups}
                  />
                </Collapse>
              </Tbody>
            </Table>
          </TableContainer>
          <Button size="sm" onClick={handleToggle} mt="3rem">
            Show {show ? "Less" : "More"}
          </Button>
        </ModalBody>
        <ModalFooter></ModalFooter>
      </ModalContent>
    </Modal>
  );
};

function SearchApp() {
  const [searchParams, setSearchParams] = useState({
    description: "",
    file_name: "",
    exclude_file_name: "",
    file_extension_include: "usd*",
    file_extension_exclude: "",
    created_before: "",
    created_after: "",
    modified_before: "",
    modified_after: "",
    file_size_greater_than: "",
    file_size_less_than: "",
    created_by: "",
    exclude_created_by: "",
    modified_by: "",
    exclude_modified_by: "",
    search_path: "",
    search_in_scene: "",
    cutoff_threshold: 0.0,
    similarity_threshold: "",
    limit: 20,
    image_similarity_search: null,
    vision_metadata: "",
    filter_url_regexp: null,
    filter_by_properties: "",
    filter_by_tags: "",
    embedding_knn_search_method: "exact",
  });

  const [removeDuplicates, setRemoveDuplicates] = useState(false);

  const [auth, setAuth] = useState({
    api_key: "",
    nucleus_api_token: "",
    username: "",
    password: "",
    isAuthenticated: false
  });

  const [results, setResults] = useState([]);
  const [propertiesData, setPropertiesData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isResponseEmpty, setIsResponseEmpty] = useState(false);
  const [error, setError] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);
  const { isOpen: isWelcomeOpen, onOpen: onWelcomeOpen, onClose: onWelcomeClose } = useDisclosure();
  const { isOpen: isDetailsOpen, onOpen: onDetailsOpen, onClose: onDetailsClose } = useDisclosure();
  const [modalExpanded, setModalExpanded] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);
  const toast = useToast();
  const observer = useRef();
  const [imageBase64, setImageBase64] = useState("");
  const [assetDependencies, setAssetDependencies] = useState(null);
  const [assetInverseDependencies, setAssetInverseDependencies] =
    useState(null);
  const [usdProperties, setUSDProperties] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  const [backend, setBackend] = useState(null);
  const [plugins, setPlugins] = useState({});

  // Helper function to check if backend is S3
  const isS3Backend = (backendString) => {
    return backendString && backendString.toLowerCase().includes('s3');
  };

  const lastElementRef = useRef();

  // Helper function to generate headers based on authentication state
  const getHeaders = useCallback(() => {
    const headers = {
      "Content-Type": "application/json",
    };

    // Priority: Basic Auth first, then API Key, then Nucleus
    if (auth.username && (auth.password || AUTH_CONFIG.DEFAULT_PASSWORD)) {
      const basicAuth = btoa(auth.username + ":" + (auth.password || AUTH_CONFIG.DEFAULT_PASSWORD));
      headers["Authorization"] = "Basic " + basicAuth;
    }
    else if (auth.api_key !== "") {
      headers["x-api-key"] = auth.api_key;
    }
    else if (auth.nucleus_api_token !== "") {
      const basicAuth = btoa("$omni-api-token:" + auth.nucleus_api_token);
      headers["Authorization"] = "Basic " + basicAuth;
    }

    return headers;
  }, [auth.nucleus_api_token, auth.api_key, auth.username, auth.password]);

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      toast({
        title: "Copied to clipboard!",
        status: "success",
        duration: 2000,
        isClosable: true,
      });
    } catch (err) {
      console.error("Failed to copy text: ", err);
      toast({
        title: "Error",
        description: "Failed to copy text to clipboard. Make sure you are using https.",
        status: "error",
        duration: 2000,
        isClosable: true,
      });
    }
  };

  const handleSearchBtnClick = () => {
    setResults([]); // Clear existing results
    handleSearch();
  };

  useEffect(() => {
    async function fetchPropertiesData() {
      try {
        const response = await fetch(`${apiUrl}/search/stats/usd_properties`, { headers: getHeaders() });
        const data = await response.json();
        setPropertiesData(data);
      } catch (error) {
        console.error("Error fetching property data", error);
      }
    }
    if (propertiesData === null) {
      fetchPropertiesData();
    }
  }, [propertiesData]);

  useEffect(() => {
    const apiKey = localStorage.getItem("api_key") || AUTH_CONFIG.DEFAULT_API_KEY;
    const nucleusToken = localStorage.getItem("nucleus_api_token") || AUTH_CONFIG.DEFAULT_NUCLEUS_TOKEN;
    const username = localStorage.getItem("username") !== null ? localStorage.getItem("username") : AUTH_CONFIG.DEFAULT_USERNAME;
    const password = localStorage.getItem("password") !== null ? localStorage.getItem("password") : AUTH_CONFIG.DEFAULT_PASSWORD;
    
    // Check if any enabled authentication method has credentials
    const hasValidAuth = 
      (AUTH_CONFIG.ENABLE_NUCLEUS_AUTH && nucleusToken) ||
      (AUTH_CONFIG.ENABLE_API_KEY_AUTH && apiKey) ||
      (AUTH_CONFIG.ENABLE_BASIC_AUTH && username && password);

    if (hasValidAuth) {
      setAuth({
        api_key: apiKey,
        nucleus_api_token: nucleusToken,
        username: username,
        password: password,
        isAuthenticated: true
      });
      // Fetch backend and plugin information after authentication
      fetchBackendInfo();
      fetchPluginsInfo();
    } else {
      // Allow users to use navbar auth instead of modal
      // onWelcomeOpen();
    }
  }, []);

  // Update username to empty when S3 backend is detected (only if it's still the default)
  useEffect(() => {
    if (backend && isS3Backend(backend)) {
      if (localStorage.getItem("username") === null && auth.username === AUTH_CONFIG.DEFAULT_USERNAME) {
        setAuth(prev => ({ ...prev, username: "" }));
      }
    }
  }, [backend]);

  const handleUsernameChange = (e) => {
    setAuth({
      ...auth,
      username: e.target.value,
    });
    localStorage.setItem("username", e.target.value);
  };

  const handlePasswordChange = (e) => {
    setAuth({
      ...auth,
      password: e.target.value,
    });
    localStorage.setItem("password", e.target.value);
  };

  const handleAuthSubmit = () => {
    if (auth.api_key || auth.nucleus_api_token || (auth.username && (auth.password || AUTH_CONFIG.DEFAULT_PASSWORD))) {
      setAuth({
        ...auth,
        isAuthenticated: true
      });
      onWelcomeClose();
      // Fetch backend and plugin information after successful authentication
      fetchBackendInfo();
      fetchPluginsInfo();
    }
  };

  const handleSearch = async () => {
    setIsLoading(true);
    setError("");
    setIsResponseEmpty(false);

    const activeParams = Object.entries(searchParams).reduce(
      (acc, [key, value]) => {
        if (value !== "") {
          acc[key] = value;
        }
        return acc;
      },
      {},
    );

    try {
      let payload = {
        ...activeParams,
        cutoff_threshold:
          activeParams.cutoff_threshold != 0
            ? activeParams.cutoff_threshold
            : null,
        return_images: true,
        return_metadata: true,
        return_vision_generated_metadata: true,
        image_similarity_search:
          imageBase64 !== "" ? [imageBase64.split(",")[1]] : null,
      };
      if (searchParams.description === "" && !imageBase64 == "") {
        payload = { ...payload, description: " " };
      }
      if (searchParams.description && payload.image_similarity_search) {
        toast({
          title: "Warning",
          description:
            "Multimodal search is not supported yet. Only the image input will be used for search.",
          status: "warning",
          duration: 9000,
          isClosable: true,
        });
      }
      const headers = getHeaders();
      const requestOptions = {
        method: "POST",
        headers: headers,
        body: JSON.stringify(payload),
      };
      const response = await fetch(`${apiUrl}/search`, requestOptions);
      if (response.status == 401) {
        console.log("Unauthorized");
        setError("Unauthorized");
        toast({
          title: "Error",
          description: "Unauthorized. Please enter a valid API Key",
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      }
      if (response.status != 200) {
        console.log("Error: ", response.status);
        setError("Error");
        toast({
          title: "Error",
          description: "Error fetching results: " + response.status,
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      } else {
        const data = await response.json();
        const sortedData = data.slice().sort((a, b) => b.score - a.score);
        setResults(sortedData || []);
        setIsResponseEmpty(data.length === 0);
      }
    } catch (err) {
      setError("Failed to fetch results");
      console.error(err);
      toast({
        title: "Error",
        description: "Failed to fetch results.",
        status: "error",
        duration: 9000,
        isClosable: true,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const fetchDependencies = async (url, inverse) => {
    try {
      const payload = {
        root_node_url: url,
        limit: 10000,
      };
      const headers = getHeaders();
      const requestOptions = {
        method: "GET",
        headers: headers,
        searchParams: payload,
      };
      let endpoint = "";
      if (inverse) {
        endpoint = `${apiUrl}/dependency_graph/inverse/graph?`;
      } else {
        endpoint = `${apiUrl}/dependency_graph/graph?`;
      }
      const response = await fetch(
        endpoint + new URLSearchParams(payload).toString(),
        requestOptions,
      );
      if (response.status == 401) {
        console.log("Unauthorized");
        setError("Unauthorized");
        toast({
          title: "Error",
          description: "Unauthorized. Please enter a valid API Key",
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      } else {
        return await response.json();
      }
    } catch (err) {
      console.error(err);
      toast({
        title: "Error",
        description: "Failed to fetch asset dependencies.",
        status: "error",
        duration: 9000,
        isClosable: true,
      });
    }
  };

  const fetchUSDProperties = async (url) => {
    try {
      const payload = {
        scene_url: url
      };
      const headers = getHeaders();
      const requestOptions = {
        method: "GET",
        headers: headers,
        searchParams: payload,
      };
      let endpoint = `${apiUrl}/asset_graph/usd/scene_summary/?`;
      const response = await fetch(
        endpoint + new URLSearchParams(payload).toString(),
        requestOptions,
      );
      if (response.status == 401) {
        console.log("Unauthorized");
        setError("Unauthorized");
        toast({
          title: "Error",
          description: "Unauthorized. Please enter a valid API Key",
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      } else {
        return await response.json();
      }
    } catch (err) {
      console.error(err);
      toast({
        title: "Error",
        description: "Failed to fetch asset dependencies.",
        status: "error",
        duration: 9000,
        isClosable: true,
      });
    }
  };

  const fetchBackendInfo = async () => {
    try {
      const headers = getHeaders();
      
      const response = await fetch(`${apiUrl}/info/backend/storage`, { headers });
      if (response.status === 200) {
        const data = await response.json();
        setBackend(Object.keys(data.backends).join(', '));
      } else {
        console.log("Failed to fetch backend info:", response.status);
      }
    } catch (err) {
      console.error("Error fetching backend info:", err);
    }
  };

  const fetchPluginsInfo = async () => {
    try {
      const headers = getHeaders();
      
      const response = await fetch(`${apiUrl}/info/plugins`, { headers });
      if (response.status === 200) {
        const data = await response.json();
        const activePlugins = [];
        const inactivePlugins = [];
        
        data.forEach(plugin => {
          if (plugin.name) {
            const pluginInfo = {
              name: plugin.name,
              active: plugin.active || false,
              description: plugin.description || null
            };
            
            if (pluginInfo.active) {
              activePlugins.push(pluginInfo);
            } else {
              inactivePlugins.push(pluginInfo);
            }
          }
        });
        
        setPlugins({
          active: activePlugins,
          inactive: inactivePlugins
        });
      } else {
        console.log("Failed to fetch plugins info:", response.status);
      }
    } catch (err) {
      console.error("Error fetching plugins info:", err);
    }
  };

  // Helper function to fetch indexing status for specific plugin types
  const fetchIndexingStatusForPlugins = useCallback(async (url, pluginFilter, errorMessage) => {
    try {
      const headers = getHeaders();
      
      const response = await fetch(`${apiUrl}/info/indexing/asset/status?url=${encodeURIComponent(url)}`, { headers });
      if (response.status === 200) {
        const data = await response.json();
        
        if (data.plugins_statuses) {
          const statuses = [];
          
          Object.entries(data.plugins_statuses).forEach(([pluginName, pluginData]) => {
            if (pluginFilter(pluginName) && pluginData.plugin_status_history && pluginData.plugin_status_history.length > 0) {
              const firstStatus = pluginData.plugin_status_history[0];
              if (firstStatus.status) {
                const timestamp = firstStatus.processing_timestamp ? ` (${firstStatus.processing_timestamp})` : '';
                statuses.push(`${pluginName}: ${firstStatus.status}${timestamp}`);
              }
            }
          });
          
          return statuses.join(', ');
        }
      } else {
        console.log(`Failed to fetch ${errorMessage}:`, response.status);
      }
    } catch (err) {
      console.error(`Error fetching ${errorMessage}:`, err);
    }
    return null;
  }, [getHeaders, apiUrl]);

  const fetchIndexingStatus = useCallback(async (url) => {
    return fetchIndexingStatusForPlugins(
      url, 
      (pluginName) => pluginName.includes("vision_metadata"),
      "vision metadata indexing status"
    );
  }, [fetchIndexingStatusForPlugins]);

  const fetchUSDPropertiesIndexingStatus = useCallback(async (url) => {
    return fetchIndexingStatusForPlugins(
      url, 
      (pluginName) => pluginName.includes("asset_graph_generation"),
      "USD properties indexing status"
    );
  }, [fetchIndexingStatusForPlugins]);

  const triggerReindex = useCallback(async (url) => {
    try {
      const headers = getHeaders();
      
      const params = new URLSearchParams();
      params.append('url', url);
      params.append('plugins', 'asset_graph_generation');
      
      const response = await fetch(`${apiUrl}/process/asset?${params.toString()}`, {
        method: "GET",
        headers: headers
      });
      
      if (response.status === 200) {
        toast({
          title: "Re-indexing triggered",
          description: "Asset graph generation re-indexing has been started.",
          status: "success",
          duration: 3000,
          isClosable: true,
        });
      } else {
        toast({
          title: "Error",
          description: "Failed to trigger re-indexing.",
          status: "error",
          duration: 3000,
          isClosable: true,
        });
      }
    } catch (err) {
      console.error("Error triggering re-indexing:", err);
      toast({
        title: "Error",
        description: "Failed to trigger re-indexing.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  }, [getHeaders]);

  const triggerVisionMetadataReindex = useCallback(async (url) => {
    try {
      // Get active plugins that have vision_metadata in their name
      const visionMetadataPlugins = plugins.active
        ?.filter(plugin => plugin.name.includes("vision_metadata"))
        .map(plugin => plugin.name) || [];

      if (visionMetadataPlugins.length === 0) {
        toast({
          title: "No vision metadata plugins available",
          description: "No active plugins found for vision metadata processing.",
          status: "warning",
          duration: 3000,
          isClosable: true,
        });
        return;
      }

      const headers = getHeaders();
      
      const params = new URLSearchParams();
      params.append('url', url);
      visionMetadataPlugins.forEach(plugin => {
        params.append('plugins', plugin);
      });
      
      const response = await fetch(`${apiUrl}/process/asset?${params.toString()}`, {
        method: "GET",
        headers: headers
      });
      
      if (response.status === 200) {
        toast({
          title: "Re-indexing triggered",
          description: "Vision metadata re-indexing has been started.",
          status: "success",
          duration: 3000,
          isClosable: true,
        });
      } else {
        toast({
          title: "Error",
          description: "Failed to trigger re-indexing.",
          status: "error",
          duration: 3000,
          isClosable: true,
        });
      }
    } catch (err) {
      console.error("Error triggering vision metadata re-indexing:", err);
      toast({
        title: "Error",
        description: "Failed to trigger re-indexing.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  }, [getHeaders, plugins.active]);

  const refreshUSDProperties = useCallback(async (url) => {
    try {
      const props = await fetchUSDProperties(url);
      setUSDProperties(props.default_prim.properties ? props.default_prim.properties : {});
      toast({
        title: "USD Properties refreshed",
        description: "USD properties have been updated.",
        status: "success",
        duration: 3000,
        isClosable: true,
      });
    } catch (err) {
      console.error("Error refreshing USD properties:", err);
      toast({
        title: "Error",
        description: "Failed to refresh USD properties.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  }, [fetchUSDProperties]);

  const refreshDependencies = useCallback(async (url) => {
    try {
      // Refresh both regular and inverse dependencies
      const [deps, inverseDeps] = await Promise.all([
        fetchDependencies(url, false),
        fetchDependencies(url, true)
      ]);
      
      setAssetDependencies(deps ? deps : []);
      setAssetInverseDependencies(inverseDeps ? inverseDeps : []);
      
      toast({
        title: "Dependencies refreshed",
        description: "Asset dependencies have been updated.",
        status: "success",
        duration: 3000,
        isClosable: true,
      });
    } catch (err) {
      console.error("Error refreshing dependencies:", err);
      toast({
        title: "Error",
        description: "Failed to refresh dependencies.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  }, [fetchDependencies]);

  const refreshVisionMetadata = useCallback(async (url) => {
    try {
      const payload = {
        filter_url_regexp: url,
        return_vision_generated_metadata: true,
        return_images: false,
        return_metadata: false
      };
      
      const headers = getHeaders();
      const requestOptions = {
        method: "POST",
        headers: headers,
        body: JSON.stringify(payload),
      };
      
      const response = await fetch(`${apiUrl}/search`, requestOptions);
      
      if (response.status === 200) {
        const data = await response.json();
        if (data && data.length > 0) {
          // Update the selected item with new vision metadata
          setSelectedItem(prevItem => ({
            ...prevItem,
            vision_generated_metadata: data[0].vision_generated_metadata || {}
          }));
          
          toast({
            title: "Vision metadata refreshed",
            description: "Vision generated metadata has been updated.",
            status: "success",
            duration: 3000,
            isClosable: true,
          });
        } else {
          toast({
            title: "No data found",
            description: "No vision metadata found for this asset.",
            status: "warning",
            duration: 3000,
            isClosable: true,
          });
        }
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      console.error("Error refreshing vision metadata:", err);
      toast({
        title: "Error",
        description: "Failed to refresh vision metadata.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  }, [getHeaders]);

  const triggerReindexAllPlugins = useCallback(async (url) => {
    try {
      const headers = getHeaders();
      
      const params = new URLSearchParams();
      params.append('url', url);
      // Don't specify plugins parameter to trigger all plugins
      
      const response = await fetch(`${apiUrl}/process/asset?${params.toString()}`, {
        method: "GET",
        headers: headers
      });
      
      if (response.status === 200) {
        toast({
          title: "Re-indexing triggered",
          description: "All plugins re-indexing has been started.",
          status: "success",
          duration: 3000,
          isClosable: true,
        });
      } else {
        toast({
          title: "Error",
          description: "Failed to trigger re-indexing for all plugins.",
          status: "error",
          duration: 3000,
          isClosable: true,
        });
      }
    } catch (err) {
      console.error("Error triggering re-indexing for all plugins:", err);
      toast({
        title: "Error",
        description: "Failed to trigger re-indexing for all plugins.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  }, [getHeaders]);

  const triggerReindexIndividualPlugin = useCallback(async (url, pluginName) => {
    try {
      const headers = getHeaders();
      
      const params = new URLSearchParams();
      params.append('url', url);
      params.append('plugins', pluginName);
      
      const response = await fetch(`${apiUrl}/process/asset?${params.toString()}`, {
        method: "GET",
        headers: headers
      });
      
      if (response.status === 200) {
        toast({
          title: "Re-indexing triggered",
          description: `${pluginName} re-indexing has been started.`,
          status: "success",
          duration: 3000,
          isClosable: true,
        });
      } else {
        toast({
          title: "Error",
          description: `Failed to trigger re-indexing for ${pluginName}.`,
          status: "error",
          duration: 3000,
          isClosable: true,
        });
      }
    } catch (err) {
      console.error(`Error triggering re-indexing for ${pluginName}:`, err);
      toast({
        title: "Error",
        description: `Failed to trigger re-indexing for ${pluginName}.`,
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  }, [getHeaders]);

  const handleChange = (e) => {
    setSearchParams({
      ...searchParams,
      [e.target.name]: e.target.value,
    });
  };

  const handleRemoveDuplicatesChange = (e) => {
    const isChecked = e.target.checked;
    setRemoveDuplicates(isChecked);
    setSearchParams({
      ...searchParams,
      similarity_threshold: isChecked ? DUPLICATE_REMOVAL_THRESHOLD : "",
    });
  };

  const handleExpandClick = () => {
    setIsExpanded(!isExpanded);
  };

  const handleItemClick = (item) => {
    setAssetDependencies(null);
    setAssetInverseDependencies(null);
    setUSDProperties(null);
    setSelectedItem(item);
    onDetailsOpen();
    fetchDependencies(item.url, false).then((deps) =>
      setAssetDependencies(deps ? deps : []),
    );
    fetchDependencies(item.url, true).then((deps) =>
      setAssetInverseDependencies(deps ? deps : []),
    );
    fetchUSDProperties(item.url).then((props) => {
      setUSDProperties(props.default_prim.properties ? props.default_prim.properties : {});
    });
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  const downscaleImage = (base64String) => {
    return new Promise((resolve) => {
      const img = new window.Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        
        // Calculate new dimensions maintaining aspect ratio
        let width = IMAGE_SIZE;
        let height = IMAGE_SIZE;
        const aspectRatio = img.width / img.height;
        
        if (aspectRatio > 1) {
          // Image is wider than tall
          height = width / aspectRatio;
        } else {
          // Image is taller than wide
          width = height * aspectRatio;
        }
        
        canvas.width = width;
        canvas.height = height;
        
        // Draw image with white background
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        
        // Convert to base64
        const resizedBase64 = canvas.toDataURL('image/jpeg', 0.9);
        resolve(resizedBase64);
      };
      img.src = base64String;
    });
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      const file = files[0];
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = async (readEvent) => {
          const base64StringWithScheme = readEvent.target.result;
          const resizedImage = await downscaleImage(base64StringWithScheme);
          setImageBase64(resizedImage);
        };
        reader.readAsDataURL(file);
      }
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file && file.type.startsWith("image/")) {
      const reader = new FileReader();
      reader.onload = async (readEvent) => {
        const base64StringWithScheme = readEvent.target.result;
        const resizedImage = await downscaleImage(base64StringWithScheme);
        setImageBase64(resizedImage);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleClearImage = () => {
    setImageBase64("");
  };

  const handleAPIKeyChange = (e) => {
    setAuth({
      ...auth,
      api_key: e.target.value,
    });
    localStorage.setItem("api_key", e.target.value);
  };

  const handleNucleusTokenChange = (e) => {
    setAuth({
      ...auth,
      nucleus_api_token: e.target.value,
    });
    localStorage.setItem("nucleus_api_token", e.target.value);
  };

  const maxScore = 1.15;
  const minScore = 1.1;

  const [show, setShow] = React.useState(false);
  const [showScores, setShowScores] = React.useState(false);
  const handleToggle = () => {
    setShow(!show);
    setModalExpanded(!modalExpanded);
  };

  return (
    <Box maxW="full" padding="4">
      <Modal isOpen={isWelcomeOpen} onClose={onWelcomeClose} closeOnOverlayClick={false}>
        <ModalOverlay />
        <ModalContent maxW="800px">
          <ModalHeader>Welcome to USD Search Explorer</ModalHeader>
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Text>Please authenticate to continue using the application.</Text>
              <Divider />
              {AUTH_CONFIG.ENABLE_BASIC_AUTH && (
                <>
                  <Text fontWeight="bold">
                    {AUTH_CONFIG.DEFAULT_PASSWORD ? "Username Authentication" : "Username/Password Authentication"}
                  </Text>
                  <HStack spacing={4}>
                    <Text width="120px">Username:</Text>
                    <Input
                      id="username"
                      name="username"
                      value={auth.username}
                      onChange={handleUsernameChange}
                      placeholder="Username"
                    />
                  </HStack>
                  {isS3Backend(backend) && (
                    <Text fontSize="sm" color="gray.500" mt={2}>
                      Please set your username - it helps us with statistics to improve the product.
                    </Text>
                  )}
                  {!AUTH_CONFIG.DEFAULT_PASSWORD && (
                    <HStack spacing={4}>
                      <Text width="120px">Password:</Text>
                      <Input
                        id="password"
                        name="password"
                        type="password"
                        value={auth.password}
                        onChange={handlePasswordChange}
                        placeholder="Password"
                      />
                    </HStack>
                  )}
                  <Divider />
                </>
              )}
              {AUTH_CONFIG.ENABLE_API_KEY_AUTH && (
                <>
                  <Text fontWeight="bold">API Key Authentication</Text>
                  <HStack spacing={4}>
                    <Text width="120px">API Key:</Text>
                    <Input
                      id="api_key"
                      name="api_key"
                      value={auth.api_key}
                      onChange={handleAPIKeyChange}
                      placeholder="API Key"
                    />
                  </HStack>
                  <Divider />
                </>
              )}
              {AUTH_CONFIG.ENABLE_NUCLEUS_AUTH && (
                <>
                  <Text fontWeight="bold">
                    Nucleus Authentication [
                    <a href="https://docs.omniverse.nvidia.com/nucleus/latest/config-and-info/api_tokens.html" target="_blank" rel="noopener noreferrer" style={{ color: '#3182ce' }}>
                      Learn how to get a token
                    </a>
                    ]
                  </Text>
                  <HStack spacing={4}>
                    <Text width="120px">Nucleus Token:</Text>
                    <Input
                      id="nucleus_api_token"
                      name="nucleus_api_token"
                      value={auth.nucleus_api_token}
                      onChange={handleNucleusTokenChange}
                      placeholder="Nucleus API Token"
                    />
                  </HStack>
                  <Divider />
                </>
              )}
            </VStack>
          </ModalBody>
          <ModalFooter>
            <Button 
              colorScheme="brand" 
              onClick={handleAuthSubmit}
              isDisabled={
                !(AUTH_CONFIG.ENABLE_NUCLEUS_AUTH && auth.nucleus_api_token) &&
                !(AUTH_CONFIG.ENABLE_API_KEY_AUTH && auth.api_key) &&
                !(AUTH_CONFIG.ENABLE_BASIC_AUTH && auth.username && (auth.password || AUTH_CONFIG.DEFAULT_PASSWORD))
              }
            >
              Continue
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      {auth.isAuthenticated ? (
        <VStack spacing={4}>
          <HStack width={"100%"}>
            <InputGroup
              size="lg"
              width={"100%"}
              as="form"
              onSubmit={(e) => {
                e.preventDefault();
                handleSearchBtnClick();
              }}
            >
              <Input
                pr="5rem"
                id="description"
                name="description"
                value={searchParams.description}
                onChange={handleChange}
                placeholder="Enter description"
                autoComplete="off"
              />
              <InputRightElement width="4.5rem" mr="0.5rem"></InputRightElement>
            </InputGroup>
            <Heading
              size={"sm"}
              style={{
                color: "rgba(255,255,255,0.24)",
                marginLeft: 15,
                marginRight: 15,
              }}
            >
              OR
            </Heading>
            <Button
              variant="outline"
              size="lg"
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              minWidth={"400px"}
              style={{ color: "rgba(255,255,255,0.24)" }}
            >
              <p>Drag and drop image here or click to upload</p>
              <input
                id="fileInput"
                type="file"
                accept="image/*"
                onChange={handleFileChange}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: "100%",
                  opacity: 0,
                  cursor: "pointer",
                }}
              />
            </Button>
            <Button
              ml={15}
              minWidth={200}
              size="lg"
              type="submit"
              isLoading={isLoading}
              colorScheme="brand"
              onClick={(e) => {
                e.preventDefault();
                handleSearchBtnClick();
              }}
            >
              Search
            </Button>
            <Popover>
              <PopoverTrigger>
                <IconButton
                  ml={15}
                  minWidth={50}
                  size="lg"
                  icon={auth.api_key === "" && auth.nucleus_api_token === "" && !(auth.username && auth.password) ? <UnlockIcon /> : <LockIcon />}
                />
              </PopoverTrigger>
              <PopoverContent width="420px">
                <PopoverArrow />
                <PopoverCloseButton />
                <PopoverHeader>Authentication Options</PopoverHeader>
                <PopoverBody>
                  <VStack spacing={4}>
                    {AUTH_CONFIG.ENABLE_BASIC_AUTH && (
                      <>
                        <Divider />
                        <Text fontWeight="bold">
                          {AUTH_CONFIG.DEFAULT_PASSWORD ? "Username Authentication" : "Username/Password Authentication"}
                        </Text>
                        <HStack spacing={4}>
                          <Text width="120px">Username:</Text>
                          <Input
                            id="username"
                            name="username"
                            value={auth.username}
                            onChange={handleUsernameChange}
                            placeholder="Username"
                          />
                        </HStack>
                        {isS3Backend(backend) && (
                          <Text fontSize="sm" color="gray.500" mt={2}>
                            Please set your username - it helps us with statistics to improve the product.
                          </Text>
                        )}
                        {!AUTH_CONFIG.DEFAULT_PASSWORD && (
                          <HStack spacing={4}>
                            <Text width="120px">Password:</Text>
                            <Input
                              id="password"
                              name="password"
                              type="password"
                              value={auth.password}
                              onChange={handlePasswordChange}
                              placeholder="Password"
                            />
                          </HStack>
                        )}
                      </>
                    )}
                    {AUTH_CONFIG.ENABLE_API_KEY_AUTH && (
                      <>
                        <Divider />
                        <Text fontWeight="bold">API Key Authentication</Text>
                        <HStack spacing={4}>
                          <Text width="120px">API Key:</Text>
                          <Input
                            id="api_key"
                            name="api_key"
                            value={auth.api_key}
                            onChange={handleAPIKeyChange}
                            placeholder="API Key"
                          />
                        </HStack>
                      </>
                    )}
                    {AUTH_CONFIG.ENABLE_NUCLEUS_AUTH && (
                      <>
                        <Divider />
                        <Text fontWeight="bold">Nucleus Authentication</Text>
                        <Text fontSize="sm" color="gray.500">
                          <a href="https://docs.omniverse.nvidia.com/nucleus/latest/config-and-info/api_tokens.html" target="_blank" rel="noopener noreferrer" style={{ color: '#3182ce' }}>
                            Learn how to get a token
                          </a>
                        </Text>
                        <HStack spacing={4}>
                          <Text width="120px">Nucleus Token:</Text>
                          <Input
                            id="nucleus_api_token"
                            name="nucleus_api_token"
                            value={auth.nucleus_api_token}
                            onChange={handleNucleusTokenChange}
                            placeholder="Nucleus API Token"
                          />
                        </HStack>
                      </>
                    )}
                  </VStack>
                </PopoverBody>
              </PopoverContent>
            </Popover>
            <Popover>
              <PopoverTrigger>
                <IconButton
                  ml={15}
                  minWidth={50}
                  size="lg"
                  icon={<InfoIcon />}
                />
              </PopoverTrigger>
              <PopoverContent width="600px">
                <PopoverArrow />
                <PopoverCloseButton />
                <PopoverHeader>Instance Information</PopoverHeader>
                <PopoverBody>
                  <VStack spacing={4} align="stretch">
                    <Box>
                      <Text fontWeight="bold" mb={2}>Storage Backend</Text>
                      {backend ? (
                        <Text fontSize="sm" color="white">
                          {backend}
                        </Text>
                      ) : (
                        <Text fontSize="sm" color="gray.500">No backend information available</Text>
                      )}
                    </Box>
                    <Divider />
                    <Box>
                      <Text fontWeight="bold" mb={2}>Supported Plugins</Text>
                      {plugins && (plugins.active?.length > 0 || plugins.inactive?.length > 0) ? (
                        <Box maxH="300px" overflowY="auto">
                          {/* Active Plugins */}
                          {plugins.active && plugins.active.length > 0 && (
                            <Box mb={3}>
                              <Text fontWeight="semibold" color="green.400" mb={2}>Active Plugins ({plugins.active.length})</Text>
                              {plugins.active.map((plugin, index) => (
                                <Box key={index} mb={2}>
                                  <Text fontSize="sm" color="white" fontWeight="medium">
                                    {plugin.name}
                                  </Text>
                                  {plugin.description && (
                                    <Text fontSize="xs" color="gray.400" ml={2} mt={1}>
                                      {plugin.description}
                                    </Text>
                                  )}
                                </Box>
                              ))}
                            </Box>
                          )}
                          
                          {/* Inactive Plugins */}
                          {plugins.inactive && plugins.inactive.length > 0 && (
                            <Box mb={3}>
                              <Text fontWeight="semibold" color="gray.400" mb={2}>Inactive Plugins ({plugins.inactive.length})</Text>
                              {plugins.inactive.map((plugin, index) => (
                                <Box key={index} mb={2}>
                                  <Text fontSize="sm" color="white" fontWeight="medium">
                                    {plugin.name}
                                  </Text>
                                  {plugin.description && (
                                    <Text fontSize="xs" color="gray.400" ml={2} mt={1}>
                                      {plugin.description}
                                    </Text>
                                  )}
                                </Box>
                              ))}
                            </Box>
                          )}
                        </Box>
                      ) : (
                        <Text fontSize="sm" color="gray.500">No plugins information available</Text>
                      )}
                    </Box>
                  </VStack>
                </PopoverBody>
              </PopoverContent>
            </Popover>
          </HStack>

          <Text align={"right"} style={{ width: "100%", height: 24 }}>
            {(auth.username && (auth.password || AUTH_CONFIG.DEFAULT_PASSWORD)) ? 
             (AUTH_CONFIG.DEFAULT_PASSWORD ? "Authenticated with Username" : "Authenticated with Username/Password") :
             auth.api_key !== "" ? "Authenticated with API Key" :
             auth.nucleus_api_token !== "" ? "Authenticated with Nucleus API Token" : ""}
          </Text>
          {imageBase64 && (
            <Box mt={4} position="relative" display="inline-block">
              <img
                src={imageBase64}
                alt="Uploaded"
                style={{ maxWidth: "300px", maxHeight: "300px" }}
              />
              <IconButton
                aria-label="Clear image"
                icon={<CloseIcon />}
                size="sm"
                variant="outline"
                position="absolute"
                top={1}
                right={1}
                onClick={handleClearImage}
              />
            </Box>
          )}
          <Button onClick={handleExpandClick} size="sm" mt="2">
            {isExpanded ? "Less Options" : "More Options"}
          </Button>

          <Collapse style={{ overflow: "unset" }} width="100%" in={isExpanded}>
            <SimpleGrid columns={[2, 2, 2, 3, 4, 5]} gap="4px" mt="4">
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="file_name"
                  name="file_name"
                  value={searchParams.file_name}
                  onChange={handleChange}
                  placeholder="File Name (supports wildcards)"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="exclude_file_name"
                  name="exclude_file_name"
                  value={searchParams.exclude_file_name}
                  onChange={handleChange}
                  placeholder="Exclude File Names"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="filter_url_regexp"
                  name="filter_url_regexp"
                  value={searchParams.filter_url_regexp}
                  onChange={handleChange}
                  placeholder="Regexp filter for asset URL"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="file_size_greater_than"
                  name="file_size_greater_than"
                  value={searchParams.file_size_greater_than}
                  onChange={handleChange}
                  placeholder="File Size Greater Than (e.g., 5MB)"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="file_size_less_than"
                  name="file_size_less_than"
                  value={searchParams.file_size_less_than}
                  onChange={handleChange}
                  placeholder="File Size Less Than (e.g., 1GB)"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="created_by"
                  name="created_by"
                  value={searchParams.created_by}
                  onChange={handleChange}
                  placeholder="Created By"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="modified_by"
                  name="modified_by"
                  value={searchParams.modified_by}
                  onChange={handleChange}
                  placeholder="Modified By"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <InputGroup size="sm">
                  <InputLeftAddon width="50%">Created Before</InputLeftAddon>
                  <Input
                    autoComplete="off"
                    id="created_before"
                    name="created_before"
                    type="date"
                    value={searchParams.created_before}
                    onChange={handleChange}
                  />
                </InputGroup>
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <InputGroup size="sm">
                  <InputLeftAddon width="50%">Created After</InputLeftAddon>
                  <Input
                    autoComplete="off"
                    id="created_after"
                    name="created_after"
                    type="date"
                    value={searchParams.created_after}
                    onChange={handleChange}
                  />
                </InputGroup>
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <InputGroup size="sm">
                  <InputLeftAddon width="50%">Modified Before</InputLeftAddon>
                  <Input
                    autoComplete="off"
                    id="modified_before"
                    name="modified_before"
                    type="date"
                    value={searchParams.modified_before}
                    onChange={handleChange}
                  />
                </InputGroup>
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <InputGroup size="sm">
                  <InputLeftAddon width="50%">Modified After</InputLeftAddon>
                  <Input
                    autoComplete="off"
                    id="modified_after"
                    name="modified_after"
                    type="date"
                    value={searchParams.modified_after}
                    onChange={handleChange}
                  />
                </InputGroup>
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="file_extension_include"
                  name="file_extension_include"
                  value={searchParams.file_extension_include}
                  onChange={handleChange}
                  placeholder="Include File Extensions"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="file_extension_exclude"
                  name="file_extension_exclude"
                  value={searchParams.file_extension_exclude}
                  onChange={handleChange}
                  placeholder="Exclude File Extensions"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="search_path"
                  name="search_path"
                  value={searchParams.search_path}
                  onChange={handleChange}
                  placeholder="Search Path (relative)"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="search_in_scene"
                  name="search_in_scene"
                  value={searchParams.search_in_scene}
                  onChange={handleChange}
                  placeholder="Search In a Specific Scene (full URL)"
                />
              </GridItem>
              <GridItem width="260px" flexGrow={1}>
                <Input
                  size="sm"
                  autoComplete="off"
                  id="vision_metadata"
                  name="vision_metadata"
                  value={searchParams.vision_metadata}
                  onChange={handleChange}
                  placeholder="Search Vision Generated Metadata"
                />
              </GridItem>
              {/* <GridItem width="260px" flexGrow={1}>
                <InputGroup size="sm">
                  <InputLeftAddon width="50%">Similarity Cutoff</InputLeftAddon>
                  <Input
                    autoComplete="off"
                    size="sm"
                    id="cutoff_threshold"
                    name="cutoff_threshold"
                    value={searchParams.cutoff_threshold}
                    onChange={handleChange}
                    placeholder="Similarity Cutoff Threshold"
                  />
                </InputGroup>
              </GridItem> */}
              {/* <GridItem width="260px" flexGrow={1}>
                <InputGroup size="sm">
                  <Input
                    autoComplete="off"
                    size="sm"
                    id="similarity_threshold"
                    name="similarity_threshold"
                    value={searchParams.similarity_threshold}
                    onChange={handleChange}
                    placeholder="Similarity Threshold"
                  />
                </InputGroup>
              </GridItem> */}

              <GridItem width="260px" flexGrow={1}>
                <InputGroup size="sm">
                  <InputLeftAddon width="50%">Page Size</InputLeftAddon>
                  <Select
                    id="limit"
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
                    <option value="10000">10000</option>
                  </Select>
                </InputGroup>
              </GridItem>
              <GridItem width="420px" flexGrow={1} colSpan={2}>
                <FilterByPropertiesInput
                  value={searchParams.filter_by_properties}
                  onChange={handleChange}
                  apiData={propertiesData}
                  id="filter_by_properties"
                  name="filter_by_properties"
                ></FilterByPropertiesInput>
              </GridItem>
              <GridItem width="420px" flexGrow={1} colSpan={2}>
                <FilterByPropertiesInput
                  value={searchParams.filter_by_tags}
                  onChange={handleChange}
                  apiData={propertiesData}
                  id="filter_by_tags"
                  name="filter_by_tags"
                ></FilterByPropertiesInput>
              </GridItem>
            </SimpleGrid>

            <SimpleGrid pt={2}>
              <HStack spacing={4}>
                <GridItem width="300px" flexGrow={1}>
                  <RadioGroup
                    value={searchParams.embedding_knn_search_method}
                    onChange={(value) =>
                      setSearchParams({
                        ...searchParams,
                        embedding_knn_search_method: value,
                      })
                    }
                  >
                    <HStack spacing={4}>
                      <Text width="120px">Search Method:</Text>
                      <HStack spacing={4}>
                        <Radio value="approximate">Approximate</Radio>
                        <Radio value="exact">Exact</Radio>
                      </HStack>
                    </HStack>
                  </RadioGroup>
                </GridItem>
                <GridItem width="200px" flexGrow={1}>
                  <Checkbox
                    id="removeDuplicates"
                    isChecked={removeDuplicates}
                    onChange={handleRemoveDuplicatesChange}
                  >
                    Remove duplicates
                  </Checkbox>
                </GridItem>
              </HStack>
            </SimpleGrid>
          </Collapse>
        </VStack>
      ) : null}

      <Divider mt="1rem" mb="1rem" />

      {results && results.length > 0 && (
        <HStack spacing={4} mb="1rem">
          <Text fontSize="sm" fontWeight="bold">
            Showing {results.length} results
          </Text>
          <Button
            size="sm"
            leftIcon={<CopyIcon />}
            onClick={() => {
              // Copy all URLs as comma-separated
              const allUrls = results.map((item) => item.url).join("\n");
              copyToClipboard(allUrls);
            }}
          >
            Copy All URLs
          </Button>
          <Button
            size="sm"
            onClick={() => setShowScores(!showScores)}
          >
            {showScores ? "Hide Scores" : "Show Scores"}
          </Button>
        </HStack>
      )}

      {isResponseEmpty && (
        <Text fontSize="md" mb="1rem" fontWeight="bold">
          No suitable matches found. Try reducing "Similarity Cutoff" parameter
          value to see more examples.
        </Text>
      )}

      <SimpleGrid minChildWidth="256px" spacing="4">
        {results.map((item, index) => (
          <Box
            key={index}
            cursor="pointer"
            borderWidth="1px"
            width="256px"
            height="256px"
            onClick={() => handleItemClick(item)}
            position="relative"
          >
            {showScores && (
              <CircularProgress
                value={Math.max(
                  ((item.score - minScore) / (maxScore - minScore)) * 100,
                  0,
                )}
                color="#76B900"
                size="36px"
                position="absolute"
                top="1"
                right="1"
                capIsRound
                trackColor="gray.800"
              >
                <CircularProgressLabel
                  textShadow="0px 0px 1px black"
                  fontWeight="bold"
                >
                  {item.score.toFixed(2)}
                </CircularProgressLabel>
              </CircularProgress>
            )}
            <Image
              src={`data:image/png;base64,${item.image}`}
              alt="Search Result"
              width="256px"
              height="256px"
              objectFit="cover"
            />
            <Box
              position="absolute"
              bottom="0"
              width="100%"
              p="2"
              bgColor="rgba(0, 0, 0, 0.5)"
            >
              <Tooltip label={item.url} placement="top">
                <Text
                  fontSize="sm"
                  fontWeight="bold"
                  color="white"
                  isTruncated
                  _hover={{ textDecoration: "underline", cursor: "pointer" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    copyToClipboard(item.url);
                  }}
                >
                  {item.url.split('/').pop()}
                </Text>
              </Tooltip>
            </Box>
          </Box>
        ))}
        {results.length > 0 && (
          <Box ref={lastElementRef} width="100%" height="20px"></Box>
        )}
      </SimpleGrid>

      {selectedItem && (
        <ItemDetailsModal
          isOpen={isDetailsOpen}
          onClose={onDetailsClose}
          selectedItem={selectedItem}
          modalExpanded={modalExpanded}
          show={show}
          handleToggle={handleToggle}
          copyToClipboard={copyToClipboard}
          assetDependencies={assetDependencies}
          assetInverseDependencies={assetInverseDependencies}
          usdProperties={usdProperties}
          expandedGroups={expandedGroups}
          setExpandedGroups={setExpandedGroups}
          fetchIndexingStatus={fetchIndexingStatus}
          fetchUSDPropertiesIndexingStatus={fetchUSDPropertiesIndexingStatus}
          triggerReindex={triggerReindex}
          triggerVisionMetadataReindex={triggerVisionMetadataReindex}
          refreshUSDProperties={refreshUSDProperties}
          refreshDependencies={refreshDependencies}
          refreshVisionMetadata={refreshVisionMetadata}
          triggerReindexAllPlugins={triggerReindexAllPlugins}
          triggerReindexIndividualPlugin={triggerReindexIndividualPlugin}
          getHeaders={getHeaders}
          plugins={plugins}
          showScores={showScores}
        />
      )}
    </Box>
  );
}

export default SearchApp;
