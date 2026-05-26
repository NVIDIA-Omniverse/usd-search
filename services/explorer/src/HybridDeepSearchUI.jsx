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

import React, { useEffect, useState, useCallback, useMemo } from "react";
import {
  Box,
  VStack,
  HStack,
  Input,
  InputGroup,
  InputRightElement,
  Button,
  Text,
  IconButton,
  Image,
  useToast,
  useDisclosure,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
  Switch,
  FormControl,
  FormLabel,
  Badge,
  Tooltip,
  Grid,
  GridItem,
} from "@chakra-ui/react";
import {
  SearchIcon,
  CloseIcon,
  InfoIcon,
  ViewIcon,
  HamburgerIcon,
  LinkIcon,
  ChevronRightIcon,
  ChevronLeftIcon,
  AddIcon,
  MinusIcon,
} from "@chakra-ui/icons";

import { apiUrl as defaultApiUrl, defaultEmbeddingConfig, AUTH_CONFIG, IS_HTTPS, FEATURE_FLAGS, SERVER_MAPPING } from "./config";
import HybridSearchConfig, { DEFAULT_HYBRID_CONFIG } from "./HybridSearchConfig";
import SearchFilters from "./SearchFilters";
import HybridSearchResults from "./HybridSearchResults";
import VirtualizedHybridSearchResults from "./components/VirtualizedHybridSearchResults";
import AssetDetailsModal from "./AssetDetailsModal";
import { useAsyncValidation } from "./hooks/useAsyncValidation";
import { readAuth, buildAuthHeaders, isAuthSatisfied, writeCredential } from "./utils/authStorage";

// Memoized results component to prevent re-renders when modal opens/closes
const MemoizedResults = React.memo(({
  results,
  showOnlyWithPreviews,
  showOnlyMatching,
  validationMap,
  isValidating,
  validatedCount,
  totalToValidate,
  vlmUnavailable,
  onItemClick,
  copyToClipboard,
  onFindSimilar,
  showScores,
  viewMode,
  gridSize,
  isLoading,
  lastSearchQuery,
  getHeaders,
  apiUrl,
  useVirtualization = true
}) => {
  // Merge validation state into results and sort: validated matches first (by score), then pending, then errors, then rejected
  const resultsWithValidation = useMemo(() => {
    if (!validationMap || Object.keys(validationMap).length === 0) return results;

    const merged = results.map((hit, idx) => {
      const id = hit.id || hit.source?.base_key;
      const entry = id ? validationMap[id] : null;
      if (!entry) return { ...hit, _originalIndex: idx };
      const m = { ...hit, _validationState: entry.status, _originalIndex: idx };
      if (entry.result) {
        m.query_relevance = entry.result;
      }
      return m;
    });

    // Sort priority: validated match (0) > pending/validating (1) > timeout/error (2) > rejected (3)
    const priority = (item) => {
      const s = item._validationState;
      if (s === "validated") return 0;
      if (!s || s === "pending" || s === "validating") return 1;
      if (s === "timeout" || s === "error") return 2;
      if (s === "rejected") return 3;
      return 1;
    };

    return merged.sort((a, b) => {
      const pa = priority(a);
      const pb = priority(b);
      if (pa !== pb) return pa - pb;
      // Within same priority, sort by search score descending
      if (pa === 0 || pa === 3) return (b.score || 0) - (a.score || 0);
      // Pending/validating/error: keep original order
      return (a._originalIndex || 0) - (b._originalIndex || 0);
    });
  }, [results, validationMap]);

  let filteredResults = showOnlyWithPreviews
    ? resultsWithValidation.filter(item => item.thumbnail_exists === true)
    : resultsWithValidation;
  if (showOnlyMatching && totalToValidate > 0) {
    // Only apply filter when validation is actually running/completed.
    // When no validation (e.g. filter-only search), show all results regardless.
    filteredResults = filteredResults.filter(item => item._validationState !== "rejected");
  }

  const ResultsComponent = useVirtualization && filteredResults.length > 50
    ? VirtualizedHybridSearchResults
    : HybridSearchResults;

  return (
    <ResultsComponent
      results={filteredResults}
      onItemClick={onItemClick}
      copyToClipboard={copyToClipboard}
      onFindSimilar={onFindSimilar}
      showScores={showScores}
      viewMode={viewMode}
      gridSize={gridSize}
      isLoading={isLoading}
      isEmpty={filteredResults.length === 0 && !isLoading && !isValidating}
      searchQuery={lastSearchQuery}
      getHeaders={getHeaders}
      apiUrl={apiUrl}
      isValidating={isValidating}
      validatedCount={validatedCount}
      totalToValidate={totalToValidate}
      vlmUnavailable={vlmUnavailable}
    />
  );
});

const HybridDeepSearchUI = () => {

  // State
  const [searchQuery, setSearchQuery] = useState("");
  const [lastSearchQuery, setLastSearchQuery] = useState(""); // Store the query used for the current results
  const [apiUrl, setApiUrl] = useState(defaultApiUrl);
  const [embeddingConfig, setEmbeddingConfig] = useState(() => {
    // Get initial embedding config from server mapping based on URL param or first server
    const urlParams = new URLSearchParams(window.location.search);
    const serverParam = urlParams.get('server');

    if (serverParam && SERVER_MAPPING[serverParam]?.embedding_config) {
      return SERVER_MAPPING[serverParam].embedding_config;
    }

    // Fall back to first server in mapping if available
    const servers = Object.keys(SERVER_MAPPING);
    if (servers.length > 0 && SERVER_MAPPING[servers[0]]?.embedding_config) {
      return SERVER_MAPPING[servers[0]].embedding_config;
    }

    return defaultEmbeddingConfig;
  });

  // Listen for server selection changes from the header
  useEffect(() => {
    const handleServerChange = (event) => {
      console.log("Received new server selection:", event.detail.server); // Debug log
      if (event.detail.server) {
        // Set the selected backend
        setSelectedBackend(event.detail.server);
        setEmbeddingConfig(event.detail.embeddingConfig || defaultEmbeddingConfig);
        setResults([]);

        // Update auth state with server-specific credentials (storage helper
        // also runs the legacy `$omni-api-token` → nucleus_api_token migration).
        const stored = readAuth(event.detail.server);
        setAuth({
          ...stored,
          isAuthenticated: isAuthSatisfied(event.detail.server, null),
        });

        // Reset and refetch properties data for the new server
        setPropertiesData(null);
        const fetchData = async () => {
          try {
            // Only fetch if authenticated
            if (!isAuthSatisfied(event.detail.server, null)) {
              console.log("Skipping properties fetch after server change - not authenticated");
              return;
            }
            const headers = getHeaders();
            const response = await fetch(`${apiUrl}/search/stats/usd_properties`, {
              method: 'GET',
              headers: headers
            });
            const data = await response.json();
            setPropertiesData(data);
          } catch (error) {
            console.error("Error fetching property data after server change:", error);
          }
        };
        fetchData();
      }
    };
    window.addEventListener('server-changed', handleServerChange);
    return () => {
      window.removeEventListener('server-changed', handleServerChange);
    };
  }, []);
  const [imageBase64, setImageBase64] = useState("");
  const [similarSearchAsset, setSimilarSearchAsset] = useState(null);
  const [hybridConfig, setHybridConfig] = useState(DEFAULT_HYBRID_CONFIG);

  // Update hybridConfig when embeddingConfig changes
  useEffect(() => {
    if (embeddingConfig?.field_name) {
      setHybridConfig(prevConfig => {
        // Remove old vector fields and add the new one with the correct embedding config
        const newVectorFields = {
          [embeddingConfig.field_name]: {
            enabled: true,
            weight: 1.0,
            field_name: embeddingConfig.field_name,
            dimension: embeddingConfig.dimension || 1024,
          }
        };
        return {
          ...prevConfig,
          vector_fields: newVectorFields
        };
      });
    }
  }, [embeddingConfig]);
  const [configCollapsed, setConfigCollapsed] = useState(true);
  const [results, setResults] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [showScores, setShowScores] = useState(false);
  const [filtersCollapsed, setFiltersCollapsed] = useState(true);
  const [viewMode, setViewMode] = useState("list"); // "list" or "grid"
  const [gridSize, setGridSize] = useState("L"); // "L" (large) or "S" (small/compact)
  const [selectedItem, setSelectedItem] = useState(null);
  const [propertiesData, setPropertiesData] = useState(null);
  const [isInitialized, setIsInitialized] = useState(false);
  const [shouldAutoSearch, setShouldAutoSearch] = useState(false);
  const [showOnlyWithPreviews, setShowOnlyWithPreviews] = useState(true); // New state for preview toggle
  const [showOnlyMatching, setShowOnlyMatching] = useState(true); // Default to showing only matching results

  // Additional modal data
  const [assetDependencies, setAssetDependencies] = useState(null);
  const [assetInverseDependencies, setAssetInverseDependencies] = useState(null);
  const [usdProperties, setUSDProperties] = useState(null);
  const [plugins, setPlugins] = useState({ active: [], inactive: [], isLoading: false });
  const [backend, setBackend] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});

  // Feedback popup state (only if feature is enabled)
  const [searchCount, setSearchCount] = useState(() => {
    if (!FEATURE_FLAGS.ENABLE_FEEDBACK_MODAL) return 0;
    const saved = localStorage.getItem('searchCount');
    return saved ? parseInt(saved) : 0;
  });
  const [showFeedbackPopup, setShowFeedbackPopup] = useState(false);
  const [feedbackDismissed, setFeedbackDismissed] = useState(() => {
    if (!FEATURE_FLAGS.ENABLE_FEEDBACK_MODAL) return true;
    return localStorage.getItem('feedbackDismissed') === 'true';
  });
  const [feedbackShownThisSession, setFeedbackShownThisSession] = useState(false);

  // Search parameters (legacy filters)
  const [searchParams, setSearchParams] = useState({
    // File & Name Filters (Most Common)
    file_name: "",
    exclude_file_name: "",
    file_extension_include: "usd*",
    file_extension_exclude: "",

    // Path & Location Filters
    search_path: "",
    exclude_search_path: "",
    search_in_scene: "",
    filter_url_regexp: "",

    // Content & Properties Filters
    filter_by_properties: "",
    filter_by_properties_numeric: "",
    filter_by_tags: "",
    vision_metadata: "",

    // Size & Dimension Filters
    file_size_greater_than: "",
    file_size_less_than: "",
    min_bbox_x: "",
    min_bbox_y: "",
    min_bbox_z: "",
    max_bbox_x: "",
    max_bbox_y: "",
    max_bbox_z: "",
    bbox_use_scaled_dimensions: true,

    // Date Filters
    created_after: "",
    created_before: "",
    modified_after: "",
    modified_before: "",

    // User Filters
    created_by: "",
    exclude_created_by: "",
    modified_by: "",
    exclude_modified_by: "",

    // Advanced Filters
    similarity_threshold: "",
    cutoff_threshold: "",
    deduplicate_by_hash: false,

    // Search Settings
    limit: 20,
    embedding_knn_search_method: "exact",
  });

  // Helper function to check if backend is S3
  const isS3Backend = (backendString) => {
    return backendString && backendString.toLowerCase().includes('s3');
  };

  // State for selected storage backend. Declared before `auth` so the auth
  // initializer can read per-server credentials directly.
  const [selectedBackend, setSelectedBackend] = useState(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const serverParam = urlParams.get('server');
    if (serverParam && Object.keys(SERVER_MAPPING).includes(serverParam)) return serverParam;
    const servers = Object.keys(SERVER_MAPPING);
    return servers.length > 0 ? servers[0] : "";
  });

  // Auth state mirrors the persisted per-server selection; isAuthenticated
  // tracks whether the credential tied to the chosen method is populated.
  const [auth, setAuth] = useState(() => ({
    ...readAuth(selectedBackend),
    isAuthenticated: isAuthSatisfied(selectedBackend, null),
  }));

  // Listen for auth updates from header component. The effect re-binds when
  // either the selected backend (server key) or the resolved backend type
  // changes so the closure always sees current values.
  useEffect(() => {
    const refresh = () => {
      const stored = readAuth(selectedBackend);
      setAuth({ ...stored, isAuthenticated: isAuthSatisfied(selectedBackend, backend) });
    };

    window.addEventListener('auth-updated', refresh);
    window.addEventListener('storage', refresh);

    return () => {
      window.removeEventListener('auth-updated', refresh);
      window.removeEventListener('storage', refresh);
    };
  }, [backend, selectedBackend]);

  // Disclosures
  const { isOpen: isDetailsOpen, onClose: onDetailsClose, onOpen: onDetailsOpen } = useDisclosure();
  const { isOpen: isWelcomeOpen, onClose: onWelcomeClose, onOpen: onWelcomeOpen } = useDisclosure();

  const toast = useToast();

  // Memoized serialized values to avoid expensive JSON.stringify on every render
  const serializedSearchParams = useMemo(() => JSON.stringify(searchParams), [searchParams]);
  const serializedHybridConfig = useMemo(() => JSON.stringify(hybridConfig), [hybridConfig]);

  // URL serialization functions
  const serializeToURL = (backendOverride = null) => {
    const params = new URLSearchParams();

    // Basic search parameters
    if (searchQuery) params.set('q', searchQuery);
    if (imageBase64) params.set('img', imageBase64);
    if (showScores) params.set('scores', 'true');
    if (viewMode !== 'list') params.set('view', viewMode);
    if (gridSize !== 'L') params.set('gridSize', gridSize);
    if (!configCollapsed) params.set('config_open', 'true');
    if (!showOnlyWithPreviews) params.set('with_previews', 'false');
    if (!showOnlyMatching) params.set('only_matching', 'false');

    // Add selected backend to URL parameters
    if (backendOverride) {
        params.set('server', backendOverride);
    } else if (selectedBackend) {
      params.set('server', selectedBackend);
    }

    // Search filters
    Object.entries(searchParams).forEach(([key, value]) => {
      if (value !== "" && value !== null && value !== undefined) {
        if (key === 'limit' && value === 50) return; // Skip default limit
        if (key === 'embedding_knn_search_method' && value === 'exact') return; // Skip default method
        if (key === 'file_extension_include' && value === 'usd*') return; // Skip default extension
        if (key === 'bbox_use_scaled_dimensions' && value === true) return; // Skip default
        if (key === 'deduplicate_by_hash' && value === false) return; // Skip default
        params.set(key, value.toString());
      }
    });

    // Hybrid config serialization
    if (JSON.stringify(hybridConfig) !== JSON.stringify(DEFAULT_HYBRID_CONFIG)) {
      const encodedConfig = btoa(JSON.stringify(hybridConfig));
      params.set('hybrid_config', encodedConfig);
    }

    // Update browser URL without reloading the page
    const url = new URL(window.location);
    url.search = params.toString();
    window.history.replaceState({}, '', url);
  };

  const deserializeFromURL = () => {
    const urlParams = new URLSearchParams(window.location.search);

    // Basic search parameters
    const query = urlParams.get('q');
    if (query) {
      setSearchQuery(query);
      setLastSearchQuery(query); // If loading from URL, treat this as the last search query
    }

    const img = urlParams.get('img');
    if (img) setImageBase64(img);

    const scores = urlParams.get('scores');
    if (scores === 'true') setShowScores(true);

    const view = urlParams.get('view');
    if (view) setViewMode(view);

    const gridSizeParam = urlParams.get('gridSize');
    if (gridSizeParam) setGridSize(gridSizeParam);

    const configOpen = urlParams.get('config_open');
    if (configOpen === 'true') setConfigCollapsed(false);

    const withPreviews = urlParams.get('with_previews');
    if (withPreviews === 'false') setShowOnlyWithPreviews(false);

    const onlyMatching = urlParams.get('only_matching');
    if (onlyMatching === 'false') setShowOnlyMatching(false);

    // Handle server parameter - only update if explicitly changing servers
    const serverParam = urlParams.get('server');
    if (serverParam && SERVER_MAPPING[serverParam] && !selectedBackend) {
      setSelectedBackend(serverParam);
    }

    // Search filters
    const newSearchParams = { ...searchParams };
    Object.keys(newSearchParams).forEach(key => {
      const value = urlParams.get(key);
      if (value !== null) {
        // Handle boolean values
        if (key === 'bbox_use_scaled_dimensions' || key === 'deduplicate_by_hash') {
          newSearchParams[key] = value === 'true';
        }
        // Handle numeric values
        else if (key === 'limit') {
          newSearchParams[key] = parseInt(value) || 50;
        }
        // Handle string values
        else {
          newSearchParams[key] = value;
        }
      }
    });
    setSearchParams(newSearchParams);

    // Hybrid config deserialization
    const hybridConfigParam = urlParams.get('hybrid_config');
    if (hybridConfigParam) {
      try {
        const decodedConfig = JSON.parse(atob(hybridConfigParam));
        setHybridConfig(decodedConfig);
      } catch (error) {
        console.error('Error deserializing hybrid config from URL:', error);
      }
    }

    // Auto-search if we have search parameters
    return query || img; // Return true if we should auto-search
  };

  // Initialize from URL on component mount
  useEffect(() => {
    // Add a small delay to ensure all state is initialized
    const timer = setTimeout(() => {
      const hasAutoSearchParams = deserializeFromURL();
      setIsInitialized(true);

      // Set flag to trigger auto-search after state updates
      if (hasAutoSearchParams) {
        setShouldAutoSearch(true);
      }
    }, 100);

    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-search when URL parameters are loaded and ready
  useEffect(() => {
    if (shouldAutoSearch && isInitialized && (searchQuery || imageBase64)) {
      // Add a small delay to ensure all state updates are fully applied
      const timer = setTimeout(() => {
        handleSearch();
        setShouldAutoSearch(false); // Reset flag
      }, 200);

      return () => clearTimeout(timer);
    }
  }, [shouldAutoSearch, isInitialized, searchQuery, imageBase64]);

  // Update URL when parameters change (only after initialization)
  // Note: searchQuery is excluded to avoid URL updates on every keystroke
  useEffect(() => {
    if (!isInitialized) return;

    const timeoutId = setTimeout(() => {
      serializeToURL();
    }, 300); // Debounce URL updates

    return () => clearTimeout(timeoutId);
  }, [
    isInitialized,
    imageBase64,
    showScores,
    showOnlyWithPreviews,
    viewMode,
    configCollapsed,
    serializedSearchParams, // Memoized to avoid expensive JSON.stringify on every render
    serializedHybridConfig  // Memoized to avoid expensive JSON.stringify on every render
  ]);


  // Auth check — runs once at mount so isAuthenticated reflects current storage.
  useEffect(() => {
    const isAuthRequired = false; // Allow users to use navbar auth instead of modal
    const hasValidAuth = isAuthSatisfied(selectedBackend, null);

    if (hasValidAuth || !isAuthRequired) {
      setAuth(prev => ({ ...prev, isAuthenticated: hasValidAuth }));
    } else if (isAuthRequired) {
      onWelcomeOpen();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch properties data and plugins info
  useEffect(() => {
    const fetchPropertiesData = async () => {
      try {
        const headers = getHeaders();
        const response = await fetch(`${apiUrl}/search/stats/usd_properties`, {
          method: 'GET',
          headers: headers
        });
        if (response.ok) {
          const data = await response.json();
          setPropertiesData(data);
        } else {
          console.log("Properties fetch failed:", response.status);
        }
      } catch (error) {
        console.error("Error fetching property data", error);
      }
    };

    // Attempt to fetch properties data if not already loaded
    if (!propertiesData) {
      fetchPropertiesData();
    }

    // Fetch additional info only when authenticated
    if (auth.isAuthenticated) {
      fetchPluginsInfo();
      fetchBackendInfo();
    }
  }, [auth.isAuthenticated, propertiesData, selectedBackend]);

  // S3-default convenience: pre-fill an empty username + dummy password when
  // nothing is stored yet so the first request can be sent without a manual
  // step. Nucleus no longer hijacks the basic-auth slot — the dedicated
  // `nucleus_token` method owns that flow now.
  useEffect(() => {
    if (!backend) return;
    const stored = readAuth(selectedBackend);
    if (stored.username || stored.password) return;
    if (isS3Backend(backend)) {
      writeCredential(selectedBackend, "username", "");
      writeCredential(selectedBackend, "password", "test");
      setAuth(prev => ({ ...prev, username: "", password: "test" }));
    }
  }, [backend, selectedBackend]);


  // Helper functions
  const getHeaders = useCallback(() => {
    const headers = { "Content-Type": "application/json" };
    if (selectedBackend) {
      headers["x-usdsearch-storage-backend"] = selectedBackend;
    }
    return { ...headers, ...buildAuthHeaders(selectedBackend, backend) };
  }, [selectedBackend, backend]);

  // Async validation hook
  const {
    validationMap,
    isValidating,
    validatedCount,
    totalToValidate,
    startValidation,
    cancelAllValidations,
    vlmUnavailable,
  } = useAsyncValidation(apiUrl, getHeaders);

  // Data fetching functions
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
      if (response.status === 401) {
        console.log("Unauthorized");
        toast({
          title: "Error",
          description: "Unauthorized. Please enter a valid API Key",
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      } else if (response.ok) {
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
      };
      let endpoint = `${apiUrl}/asset_graph/usd/scene_summary/?`;
      const response = await fetch(
        endpoint + new URLSearchParams(payload).toString(),
        requestOptions,
      );
      if (response.status === 401) {
        console.log("Unauthorized");
        toast({
          title: "Error",
          description: "Unauthorized. Please enter a valid API Key",
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      } else if (response.ok) {
        return await response.json();
      }
    } catch (err) {
      console.error(err);
      toast({
        title: "Error",
        description: "Failed to fetch USD properties.",
        status: "error",
        duration: 9000,
        isClosable: true,
      });
    }
  };

  const fetchPluginsInfo = async () => {
    try {
      setPlugins(prev => ({ ...prev, isLoading: true }));
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
          inactive: inactivePlugins,
          isLoading: false
        });
      } else {
        console.log("Failed to fetch plugins info:", response.status);
        setPlugins(prev => ({ ...prev, isLoading: false }));
      }
    } catch (err) {
      console.error("Error fetching plugins info:", err);
      setPlugins(prev => ({ ...prev, isLoading: false }));
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

  // Re-indexing functions
  const triggerReindexAllPlugins = async (url) => {
    try {
      const headers = getHeaders();
      const params = new URLSearchParams();
      params.append('url', url);

      const response = await fetch(`${apiUrl}/process/asset?${params.toString()}`, {
        method: "GET",
        headers: headers
      });

      if (response.status === 401) {
        toast({
          title: "Error",
          description: "Unauthorized. Please enter a valid API Key",
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      } else if (response.ok) {
        toast({
          title: "Re-indexing started",
          description: "All plugins will re-index this asset",
          status: "success",
          duration: 3000,
          isClosable: true,
        });
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      console.error("Error triggering re-index:", err);
      toast({
        title: "Error",
        description: "Failed to trigger re-indexing",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  };

  const triggerReindexIndividualPlugin = async (url, pluginName) => {
    try {
      const headers = getHeaders();
      const params = new URLSearchParams();
      params.append('url', url);
      params.append('plugins', pluginName);

      const response = await fetch(`${apiUrl}/process/asset?${params.toString()}`, {
        method: "GET",
        headers: headers
      });

      if (response.status === 401) {
        toast({
          title: "Error",
          description: "Unauthorized. Please enter a valid API Key",
          status: "error",
          duration: 9000,
          isClosable: true,
        });
      } else if (response.ok) {
        toast({
          title: "Re-indexing started",
          description: `${pluginName} will re-index this asset`,
          status: "success",
          duration: 3000,
          isClosable: true,
        });
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      console.error("Error triggering plugin re-index:", err);
      toast({
        title: "Error",
        description: `Failed to trigger ${pluginName} re-indexing`,
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  };

  // Refresh functions
  const refreshDependencies = useCallback(async (url) => {
    try {
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
  }, []);

  const refreshUSDProperties = useCallback(async (url) => {
    try {
      const props = await fetchUSDProperties(url);
      setUSDProperties(props?.default_prim?.properties ? props.default_prim.properties : {});

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
  }, []);

  const refreshVisionMetadata = useCallback(async (url) => {
    // For hybrid search, the vision metadata is part of the search result
    // We don't need to refresh it separately like in the original UI
    toast({
      title: "Vision metadata up to date",
      description: "Vision metadata is included in search results.",
      status: "info",
      duration: 3000,
      isClosable: true,
    });
  }, []);

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    toast({
      title: "Copied to clipboard",
      status: "success",
      duration: 2000,
    });
  };

  const shareCurrentSearch = () => {
    const currentUrl = window.location.href;
    copyToClipboard(currentUrl);
    toast({
      title: "Search URL copied!",
      description: "Share this URL to reproduce the exact same search",
      status: "success",
      duration: 3000,
      isClosable: true,
    });
  };

  // Helper function to handle feedback after successful search
  const handleSearchComplete = useCallback(() => {
    // Only handle feedback if feature is enabled
    if (!FEATURE_FLAGS.ENABLE_FEEDBACK_MODAL) return;

    // Increment search counter
    const newCount = searchCount + 1;
    setSearchCount(newCount);
    localStorage.setItem('searchCount', newCount.toString());

    // Check if we should show feedback popup (only if not already shown in this session)
    if (newCount >= 10 && !feedbackDismissed && !feedbackShownThisSession && !showFeedbackPopup) {
      setFeedbackShownThisSession(true);
      setShowFeedbackPopup(true);
    }
  }, [searchCount, feedbackDismissed, feedbackShownThisSession, showFeedbackPopup]);

  const handleFindSimilar = useCallback(async (assetUrl) => {
    cancelAllValidations();
    // Clear text search and set up image search using the asset URL
    setSearchQuery("");
    setLastSearchQuery(""); // Clear the last search query since this is a similarity search
    setImageBase64(""); // Clear any existing image

    // Store the asset information for display
    const filename = assetUrl?.split('/').pop() || 'Unknown Asset';
    setSimilarSearchAsset({
      url: assetUrl,
      filename: filename
    });

    // Trigger image search using the asset URL
    // We'll use the vector_queries with the asset URL instead of base64
    const requestBody = {
      limit: parseInt(searchParams.limit),
      return_images: true,
      validate_results: false,
      return_metadata: true,
      return_vision_generated_metadata: true,
      return_usd_properties: true,
      return_tags: true,

      // Hybrid search configuration
      scoring_config: hybridConfig,

      // Vector queries using asset URL for image similarity
      vector_queries: [{
        field_name: embeddingConfig.field_name,
        query_type: "image",
        query: assetUrl
      }],

      // Legacy filters
      ...Object.fromEntries(
        Object.entries(searchParams).filter(([_, value]) => value !== "" && value !== null && value !== undefined)
      ),
    };

    // Clear existing results and start loading
    setIsLoading(true);
    setError("");
    setResults([]);

    // Clear active image requests to allow retries on new search
    const { clearActiveRequests } = await import('./utils/imageLoader');
    clearActiveRequests();

    // Update URL after state changes
    setTimeout(() => serializeToURL(), 0);

    // Perform the search
    fetch(`${apiUrl.replace('v2', 'v3')}/search_hybrid`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify(requestBody),
    })
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.json();
      })
      .then(data => {
        const hits = data.hits || data || [];
        if (data.hits) {
          setResults(data.hits);
        } else {
          setResults(hits);
        }

        // Start async VLM validation for each result (find similar uses asset URL as query image)
        startValidation(hits, null, assetUrl);

        // Handle feedback popup after successful search
        handleSearchComplete();

        if (data.total === 0 || (Array.isArray(data) && data.length === 0)) {
          toast({
            title: "No similar assets found",
            description: "Try adjusting your search configuration",
            status: "info",
            duration: 3000,
          });
        } else {
          toast({
            title: "Similar assets found",
            description: `Found ${data.hits?.length || data.length} similar assets`,
            status: "success",
            duration: 3000,
          });
        }
      })
      .catch(error => {
        console.error("Similar search error:", error);
        setError(error.message);
        toast({
          title: "Similar search failed",
          description: error.message,
          status: "error",
          duration: 5000,
        });
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [searchParams, hybridConfig, apiUrl, getHeaders, serializeToURL, handleSearchComplete, toast, cancelAllValidations, startValidation]);

  // Image handling
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setImageBase64(event.target.result);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("image/")) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setImageBase64(event.target.result);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  // Remove duplicates handler
  const handleRemoveDuplicatesChange = (e) => {
    const isChecked = e.target.checked;
    setSearchParams({
      ...searchParams,
      deduplicate_by_hash: isChecked,
    });
  };

  const handleClearImage = () => {
    setImageBase64("");
    setSimilarSearchAsset(null);
  };

  // Search handling
  const handleSearch = async () => {
    cancelAllValidations();
    setIsLoading(true);
    setError("");
    setResults([]);
    setSimilarSearchAsset(null); // Clear similar search when doing regular search
    setLastSearchQuery(searchQuery); // Store the query being used for this search

    // Clear active image requests to allow retries on new search
    const { clearActiveRequests } = await import('./utils/imageLoader');
    clearActiveRequests();

    // Update URL with the current search parameters, but don't trigger a backend change
    const currentBackend = selectedBackend; // Save current backend
    serializeToURL();
    console.log("currentBackend", currentBackend);
    setSelectedBackend(currentBackend); // Restore backend after URL update

    try {
      // Build the V3 API request
      const requestBody = {
        // Basic search parameters
        limit: parseInt(searchParams.limit),
        return_images: true,
        validate_results: false,
        return_metadata: true,
        return_vision_generated_metadata: true,
        return_usd_properties: true,
        return_tags: true,

        // Hybrid search configuration
        scoring_config: hybridConfig,

        // Main search query
        hybrid_text_query: searchQuery || null,

        // Vector queries (for image and text-to-vector search)
        vector_queries: (() => {
          const vectorQueries = [];

          // Add image vector query if present
          if (imageBase64) {
            vectorQueries.push({
              field_name: embeddingConfig.field_name,
              query_type: "image",
              query: imageBase64.split(",")[1] // Remove data URL prefix
            });
          }

          // Add text-to-vector queries if we have a text query
          if (searchQuery) {
            if (hybridConfig.vector_text_expansion?.enabled) {
              // With expansion enabled: send full query + individual words (avoid duplicates)
              const words = searchQuery.trim().split(/\s+/).filter(word => word.length > 0);

              // Always add the full query
              vectorQueries.push({
                field_name: embeddingConfig.field_name,
                query_type: "text",
                query: searchQuery
              });

              // Add individual words only if there are multiple words
              if (words.length > 1) {
                words.forEach(word => {
                  vectorQueries.push({
                    field_name: embeddingConfig.field_name,
                    query_type: "text",
                    query: word
                  });
                });
              }
            } else {
              // With expansion disabled: send only the full query
              vectorQueries.push({
                field_name: embeddingConfig.field_name,
                query_type: "text",
                query: searchQuery
              });
            }
          }

          return vectorQueries;
        })(),

        // Legacy filters
        ...Object.fromEntries(
          Object.entries(searchParams).filter(([_, value]) => value !== "" && value !== null && value !== undefined)
        ),
      };

      // Remove empty or default values
      Object.keys(requestBody).forEach(key => {
        if (requestBody[key] === "" || requestBody[key] === null || requestBody[key] === undefined) {
          delete requestBody[key];
        }
      });

      const response = await fetch(`${apiUrl.replace('v2', 'v3')}/search_hybrid`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();

      // Handle V3 response format
      const hits = data.hits || data || [];
      if (data.hits) {
        setResults(data.hits);
      } else {
        setResults(hits);
      }

      // Start async VLM validation for each result
      const queryImageForValidation = imageBase64 ? imageBase64.split(",")[1] : null;
      startValidation(hits, searchQuery || null, queryImageForValidation);

      // Handle feedback popup after successful search
      handleSearchComplete();

      if (data.total === 0 || (Array.isArray(data) && data.length === 0)) {
        toast({
          title: "No results found",
          description: "Try adjusting your search terms or filters",
          status: "info",
          duration: 3000,
        });
      }

    } catch (error) {
      console.error("Search error:", error);
      setError(error.message);
      toast({
        title: "Search failed",
        description: error.message,
        status: "error",
        duration: 5000,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    setSearchParams(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleClearAllFilters = () => {
    setSearchParams({
      file_name: "",
      exclude_file_name: "",
      file_extension_include: "usd*",
      file_extension_exclude: "",
      created_after: "",
      created_before: "",
      modified_after: "",
      modified_before: "",
      file_size_greater_than: "",
      file_size_less_than: "",
      created_by: "",
      modified_by: "",
      search_path: "",
      search_in_scene: "",
      filter_url_regexp: "",
      filter_by_properties: "",
      filter_by_properties_numeric: "",
      filter_by_tags: "",
      vision_metadata: "",
      deduplicate_by_hash: false,
      limit: 20,
      embedding_knn_search_method: "exact",
    });
  };

  const handleItemClick = useCallback((item) => {
    // Reset data
    setAssetDependencies(null);
    setAssetInverseDependencies(null);
    setUSDProperties(null);
    setPlugins({ active: [], inactive: [], isLoading: true }); // Reset plugins state with loading
    setSelectedItem(item);
    onDetailsOpen();

    // Get the URL from the item (base_key, url, or id)
    const url = item.source?.base_key || item.source?.url || item.id;

    if (url) {
      // Fetch dependencies
      fetchDependencies(url, false).then((deps) =>
        setAssetDependencies(deps ? deps : []),
      );
      fetchDependencies(url, true).then((deps) =>
        setAssetInverseDependencies(deps ? deps : []),
      );

      // Fetch USD properties
      fetchUSDProperties(url).then((props) => {
        setUSDProperties(props?.default_prim?.properties ? props.default_prim.properties : {});
      });

      // Fetch plugins info
      fetchPluginsInfo();
      fetchBackendInfo();
    }
  }, [fetchDependencies, fetchUSDProperties, fetchPluginsInfo, fetchBackendInfo, onDetailsOpen]);

  const handleAuthSubmit = () => {
    // Mirror the user-edited values into per-server storage; isAuthenticated
    // is recomputed from whichever method's slot is now populated.
    writeCredential(selectedBackend, "api_key", auth.api_key);
    writeCredential(selectedBackend, "nucleus_api_token", auth.nucleus_api_token);
    writeCredential(selectedBackend, "username", auth.username);
    writeCredential(selectedBackend, "password", auth.password);
    const ok = isAuthSatisfied(selectedBackend, backend);
    setAuth(prev => ({ ...prev, isAuthenticated: ok }));
    if (ok) onWelcomeClose();
  };


  // Feedback popup handlers (only if feature is enabled)
  const handleFeedbackLater = () => {
    if (!FEATURE_FLAGS.ENABLE_FEEDBACK_MODAL) return;
    setShowFeedbackPopup(false);
    setFeedbackShownThisSession(false); // Allow it to show again after more searches
    // Set counter to -15 so it will show again after 25 more searches (25 - 15 = 10)
    const newCount = searchCount - 15;
    setSearchCount(newCount);
    localStorage.setItem('searchCount', newCount.toString());
  };

  const handleFeedbackDismiss = () => {
    if (!FEATURE_FLAGS.ENABLE_FEEDBACK_MODAL) return;
    setShowFeedbackPopup(false);
    setFeedbackDismissed(true);
    localStorage.setItem('feedbackDismissed', 'true');
  };

  const handleFeedbackSubmit = () => {
    if (!FEATURE_FLAGS.ENABLE_FEEDBACK_MODAL) return;
    window.open('https://forms.gle/u2UnicMwyFDtFRZc9', '_blank');
    handleFeedbackDismiss();
  };

  // Feedback popup component (only render if feature is enabled)
  const FeedbackPopup = () => {
    if (!FEATURE_FLAGS.ENABLE_FEEDBACK_MODAL) return null;

    return (
      <Modal isOpen={showFeedbackPopup} onClose={() => {}} closeOnOverlayClick={false}>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Help us improve!</ModalHeader>
          <ModalCloseButton onClick={handleFeedbackLater} />
          <ModalBody>
            <VStack spacing={4}>
              <Text>
                We'd love to hear about your USD asset discovery workflows. Your feedback helps us make USD Search better!
              </Text>
              <Text
                fontSize="xs"
                color="gray.500"
                textAlign="center"
                cursor="pointer"
                onClick={handleFeedbackDismiss}
                _hover={{ color: "gray.400", textDecoration: "underline" }}
              >
                Don't show again
              </Text>
            </VStack>
          </ModalBody>
          <ModalFooter>
            <HStack spacing={3}>
              <Button variant="ghost" onClick={handleFeedbackLater}>
                Later
              </Button>
              <Button colorScheme="green" onClick={handleFeedbackSubmit}>
                Take Survey
              </Button>
            </HStack>
          </ModalFooter>
        </ModalContent>
      </Modal>
    );
  };

  // Only show auth modal if authentication is actually required
  const isAuthRequired = AUTH_CONFIG.ENABLE_NUCLEUS_AUTH ||
                        AUTH_CONFIG.ENABLE_API_KEY_AUTH ||
                        AUTH_CONFIG.ENABLE_BASIC_AUTH;

  // if (!auth.isAuthenticated && isAuthRequired) {
  //   return <AuthModal />;
  // }

  return (
    <Box minH="100vh" bg="gray.900" color="white" p={4}>
      <VStack spacing={6} align="stretch" maxW="100%" mx="auto">
        {/* Header */}
        <HStack justify="flex-end">
          <HStack spacing={6}>
            {IS_HTTPS && (
              <Tooltip label="Share current search configuration">
                <IconButton
                  size="sm"
                  variant="ghost"
                  icon={<LinkIcon />}
                  onClick={shareCurrentSearch}
                  aria-label="Share search"
                  colorScheme="blue"
                />
              </Tooltip>
            )}
          </HStack>
        </HStack>

        {/* Main Search Area */}
        <VStack spacing={4} align="stretch">
          {/* Search Input */}
          <HStack>
            <InputGroup size="lg" flex={1}>
              <Input
                placeholder="Search for assets using natural language..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyPress={(e) => e.key === "Enter" && handleSearch()}
                bg="gray.800"
                borderColor="gray.600"
                _hover={{ borderColor: "green.500" }}
                _focus={{ borderColor: "green.500", boxShadow: "0 0 0 1px var(--chakra-colors-green-500)" }}
              />
              <InputRightElement>
                <SearchIcon color="gray.400" />
              </InputRightElement>
            </InputGroup>

            <Text color="gray.400" fontSize="sm">OR</Text>

            <Button
              variant="outline"
              size="lg"
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              minW="200px"
              color="gray.400"
              borderColor="gray.600"
              _hover={{ borderColor: "green.500", color: "green.400" }}
            >
              Drag image or click to upload
              <input
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
              size="lg"
              colorScheme="green"
              onClick={handleSearch}
              isLoading={isLoading}
              loadingText="Searching..."
              leftIcon={<SearchIcon />}
              minW="120px"
            >
              Search
            </Button>
          </HStack>

          {/* Controls under search button */}
          <HStack justify="flex-end" spacing={8}>
            <FormControl display="flex" alignItems="center" size="sm" w="auto">
              <HStack spacing={1}>
                <FormLabel htmlFor="remove-duplicates" mb="0" fontSize="sm">
                  Remove Duplicates
                </FormLabel>
                <Tooltip label="Removes duplicates based on file hash" placement="top">
                  <InfoIcon color="gray.400" boxSize={3} />
                </Tooltip>
              </HStack>
              <Switch
                id="remove-duplicates"
                isChecked={searchParams.deduplicate_by_hash}
                onChange={handleRemoveDuplicatesChange}
                colorScheme="green"
                ml={3}
              />
            </FormControl>
            <FormControl display="flex" alignItems="center" size="sm" w="auto">
              <HStack spacing={1}>
                <FormLabel htmlFor="only-matching" mb="0" fontSize="sm">
                  Only Matching Results
                </FormLabel>
                <Tooltip label="Show only VLM-validated results" placement="top">
                  <InfoIcon color="gray.400" boxSize={3} />
                </Tooltip>
              </HStack>
              <Switch
                id="only-matching"
                isChecked={showOnlyMatching}
                onChange={(e) => setShowOnlyMatching(e.target.checked)}
                colorScheme="green"
                ml={3}
              />
            </FormControl>
            <FormControl display="flex" alignItems="center" size="sm" w="auto">
              <HStack spacing={1}>
                <FormLabel htmlFor="with-previews" mb="0" fontSize="sm">
                  With Previews
                </FormLabel>
                <Tooltip label="Show only assets with thumbnail previews" placement="top">
                  <InfoIcon color="gray.400" boxSize={3} />
                </Tooltip>
              </HStack>
              <Switch
                id="with-previews"
                isChecked={showOnlyWithPreviews}
                onChange={(e) => setShowOnlyWithPreviews(e.target.checked)}
                colorScheme="green"
                ml={3}
              />
            </FormControl>
            <FormControl display="flex" alignItems="center" size="sm" w="auto">
              <FormLabel htmlFor="show-scores" mb="0" fontSize="sm" mr={3}>
                Show Scores
              </FormLabel>
              <Switch
                id="show-scores"
                isChecked={showScores}
                onChange={(e) => setShowScores(e.target.checked)}
                colorScheme="green"
              />
            </FormControl>
            <FormControl display="flex" alignItems="center" size="sm" w="auto">
              <FormLabel htmlFor="view-mode" mb="0" fontSize="sm" mr={3}>
                View
              </FormLabel>
              <HStack spacing={1} bg="gray.700" borderRadius="md" p={1}>
                <IconButton
                  size="xs"
                  variant={viewMode === "list" ? "solid" : "ghost"}
                  colorScheme={viewMode === "list" ? "green" : "gray"}
                  icon={<HamburgerIcon />}
                  onClick={() => setViewMode("list")}
                  aria-label="List view"
                />
                <IconButton
                  size="xs"
                  variant={viewMode === "grid" ? "solid" : "ghost"}
                  colorScheme={viewMode === "grid" ? "green" : "gray"}
                  icon={<ViewIcon />}
                  onClick={() => setViewMode("grid")}
                  aria-label="Grid view"
                />
                {viewMode === "grid" && (
                  <IconButton
                    size="xs"
                    variant="ghost"
                    colorScheme="gray"
                    icon={gridSize === "L" ? <MinusIcon /> : <AddIcon />}
                    onClick={() => setGridSize(gridSize === "L" ? "S" : "L")}
                    aria-label="Toggle grid size"
                    title={gridSize === "L" ? "Switch to compact grid (-)" : "Switch to large grid (+)"}
                  />
                )}
              </HStack>
            </FormControl>
          </HStack>

          {/* Image Preview */}
          {imageBase64 && (
            <HStack>
              <Box position="relative" display="inline-block">
                <Image
                  src={imageBase64}
                  alt="Search image"
                  maxW="200px"
                  maxH="150px"
                  objectFit="cover"
                  borderRadius="md"
                />
                <IconButton
                  size="sm"
                  icon={<CloseIcon />}
                  position="absolute"
                  top={1}
                  right={1}
                  onClick={handleClearImage}
                  aria-label="Remove image"
                  colorScheme="red"
                  variant="solid"
                />
              </Box>
              <Text fontSize="sm" color="gray.400">
                Image search active
              </Text>
            </HStack>
          )}

          {/* Similar Search Asset Preview */}
          {similarSearchAsset && (
            <HStack>
              <Box position="relative" display="inline-block">
                <Image
                  src={`${apiUrl}/images?asset_url=${encodeURIComponent(similarSearchAsset.url)}`}
                  alt={similarSearchAsset.filename}
                  width="200px"
                  height="150px"
                  objectFit="cover"
                  borderRadius="md"
                  bg="gray.700"
                  fallback={
                    <Box
                      width="200px"
                      height="150px"
                      bg="gray.700"
                      borderRadius="md"
                      display="flex"
                      alignItems="center"
                      justifyContent="center"
                      color="gray.400"
                      fontSize="sm"
                    >
                      No Preview
                    </Box>
                  }
                />
                <IconButton
                  size="sm"
                  icon={<CloseIcon />}
                  position="absolute"
                  top={1}
                  right={1}
                  onClick={() => setSimilarSearchAsset(null)}
                  aria-label="Clear similar search"
                  colorScheme="red"
                  variant="solid"
                />
              </Box>
              <VStack align="start" spacing={1}>
                <Text fontSize="sm" color="purple.400" fontWeight="semibold">
                  Finding similar to:
                </Text>
                <Text fontSize="xs" color="gray.400" maxW="300px" noOfLines={2}>
                  {similarSearchAsset.filename}
                </Text>
                <Text fontSize="xs" color="gray.400" maxW="600px" noOfLines={1}>
                  {similarSearchAsset.url}
                </Text>
              </VStack>
            </HStack>
          )}

          {/* Hybrid Search Configuration */}
          <HybridSearchConfig
            value={hybridConfig}
            onChange={setHybridConfig}
            isCollapsed={configCollapsed}
            embeddingConfig={embeddingConfig}
          />
        </VStack>

        {/* Main Content Grid */}
        <Grid templateColumns={filtersCollapsed ? "auto 1fr" : "320px 1fr"} gap={6} align="start" minH="calc(100vh - 350px)">
          {/* Left Sidebar - Filters or Collapsed Toggle */}
          <GridItem>
            {filtersCollapsed ? (
              <Box
                position="sticky"
                top="4"
                bg="gray.800"
                borderRadius="md"
                p={3}
                w="60px"
                border="1px solid"
                borderColor="gray.600"
                minH="200px"
                display="flex"
                flexDirection="column"
                alignItems="center"
                justifyContent="flex-start"
              >
                <VStack spacing={3}>
                  <Tooltip label="Show filters" placement="right">
                    <IconButton
                      size="sm"
                      variant="ghost"
                      icon={<ChevronRightIcon />}
                      onClick={() => setFiltersCollapsed(false)}
                      aria-label="Show filters sidebar"
                      colorScheme="green"
                    />
                  </Tooltip>

                  {/* Show active filter count if any */}
                  {(() => {
                    const activeFilters = Object.entries(searchParams).filter(([key, value]) => {
                      if (value === "" || value === null || value === undefined) return false;
                      // Exclude default values
                      if (key === 'limit' && value === 50) return false;
                      if (key === 'embedding_knn_search_method' && value === 'exact') return false;
                      if (key === 'file_extension_include' && value === 'usd*') return false;
                      if (key === 'bbox_use_scaled_dimensions' && value === true) return false;
                      if (key === 'deduplicate_by_hash' && value === false) return false;
                      return true;
                    });
                    return activeFilters.length > 0 && (
                      <Badge colorScheme="green" fontSize="xs" borderRadius="full" px={2}>
                        {activeFilters.length}
                      </Badge>
                    );
                  })()}

                  {/* Spacer to push text lower */}
                  <Box h="4" />

                  {/* Vertical "Search Filters" Text - Clickable */}
                  <Box
                    transform="rotate(-90deg)"
                    whiteSpace="nowrap"
                    cursor="pointer"
                    onClick={() => setFiltersCollapsed(false)}
                    _hover={{ opacity: 0.8 }}
                    transition="opacity 0.2s"
                  >
                    <Text fontSize="sm" color="white" fontWeight="medium">
                      Search Filters
                    </Text>
                  </Box>
                </VStack>
              </Box>
            ) : (
              <VStack spacing={2} align="stretch">
                {/* Collapse Button Above Filters */}
                <HStack justify="flex-end">
                  <Tooltip label="Hide filters" placement="left">
                    <IconButton
                      size="sm"
                      variant="ghost"
                      icon={<ChevronLeftIcon />}
                      onClick={() => setFiltersCollapsed(true)}
                      aria-label="Hide filters sidebar"
                      colorScheme="gray"
                    />
                  </Tooltip>
                </HStack>
                {/* Filters Sidebar */}
                <SearchFilters
                  searchParams={searchParams}
                  handleChange={handleFilterChange}
                  setSearchParams={setSearchParams}
                  propertiesData={propertiesData}
                  onClearAll={handleClearAllFilters}
                />
              </VStack>
            )}
          </GridItem>

          {/* Right Content - Results */}
          <GridItem>
            <MemoizedResults
              results={results}
              showOnlyWithPreviews={showOnlyWithPreviews}
              showOnlyMatching={showOnlyMatching}
              validationMap={validationMap}
              isValidating={isValidating}
              validatedCount={validatedCount}
              totalToValidate={totalToValidate}
              vlmUnavailable={vlmUnavailable}
              onItemClick={handleItemClick}
              copyToClipboard={IS_HTTPS ? copyToClipboard : null}
              onFindSimilar={handleFindSimilar}
              showScores={showScores}
              viewMode={viewMode}
              gridSize={gridSize}
              isLoading={isLoading}
              lastSearchQuery={lastSearchQuery}
              getHeaders={getHeaders}
              apiUrl={apiUrl}
            />
          </GridItem>
        </Grid>
      </VStack>

      {/* Asset Details Modal */}
      {selectedItem && (
        <AssetDetailsModal
          isOpen={isDetailsOpen}
          onClose={onDetailsClose}
          selectedItem={selectedItem}
          copyToClipboard={copyToClipboard}
          showScores={showScores}
          assetDependencies={assetDependencies}
          assetInverseDependencies={assetInverseDependencies}
          usdProperties={usdProperties}
          expandedGroups={expandedGroups}
          setExpandedGroups={setExpandedGroups}
          plugins={plugins}
          getHeaders={getHeaders}
          apiUrl={apiUrl}
          triggerReindexAllPlugins={triggerReindexAllPlugins}
          triggerReindexIndividualPlugin={triggerReindexIndividualPlugin}
          refreshDependencies={refreshDependencies}
          refreshUSDProperties={refreshUSDProperties}
          refreshVisionMetadata={refreshVisionMetadata}
        />
      )}

      {/* Feedback Popup */}
      <FeedbackPopup />
    </Box>
  );
};

export default HybridDeepSearchUI;
