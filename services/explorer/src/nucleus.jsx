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
 * Nucleus Authentication Module
 * 
 * This module provides functions and React hooks for authenticating with
 * NVIDIA Omniverse Nucleus servers using the Device Flow (OAuth-like) pattern.
 * 
 * Usage:
 * 1. Call startDeviceFlow(serverUrl) to initiate authentication
 * 2. Display the user_code and verification_uri to the user
 * 3. Poll pollForToken() until the user completes authentication
 * 4. Optionally create a long-lived API token with createApiToken()
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import DiscoverySearch from "@omniverse/discovery";
import { DeviceFlow, Tokens, Credentials } from "@omniverse/auth";
import { AuthStatus } from "@omniverse/auth/data";
import WebSocketClient from "@omniverse/idl/connection/transport/websocket";

// Register the WebSocket transport with the ClientFactory
// This is required for the discovery service to create connections
WebSocketClient.register();

// Client ID for this application
const CLIENT_ID = "USD-Search-Explorer";

/**
 * Convert a Nucleus server URL to a discovery-compatible format
 * Strips omniverse:// prefix if present and ensures proper format
 * @param {string} serverUrl - The Nucleus server URL (e.g., "omniverse://server.com" or "server.com")
 * @returns {string} - Clean server URL for discovery
 */
export function normalizeServerUrl(serverUrl) {
  if (!serverUrl) return '';
  
  // Remove omniverse:// prefix if present
  let normalized = serverUrl.replace(/^omniverse:\/\//, '');
  
  // Remove any trailing slashes
  while (normalized.endsWith('/')) {
    normalized = normalized.slice(0, -1);
  }
  
  return normalized;
}

/**
 * Get the HTTPS URL for a Nucleus server (for browser navigation)
 * @param {string} serverUrl - The Nucleus server URL
 * @returns {string} - HTTPS URL
 */
export function getServerHttpsUrl(serverUrl) {
  const normalized = normalizeServerUrl(serverUrl);
  return `https://${normalized}`;
}

/**
 * Connect to a Nucleus service via the discovery service
 * @param {string} serverUrl - The Nucleus server URL
 * @param {Function} clientType - The client type to connect to (DeviceFlow, Tokens, Credentials)
 * @param {Object} capabilities - Optional capabilities object
 * @returns {Promise<Object>} - Connected client instance
 */
async function connectToService(serverUrl, clientType, capabilities = {}) {
  const normalizedUrl = normalizeServerUrl(serverUrl);
  const discovery = new DiscoverySearch(normalizedUrl);
  
  try {
    const client = await discovery.find(
      clientType, 
      { deployment: "external" }, 
      undefined, 
      capabilities
    );
    
    if (!client) {
      throw new Error(`Failed to find ${clientType.name || 'service'} on ${normalizedUrl}`);
    }
    
    return client;
  } finally {
    discovery.close();
  }
}

/**
 * Start the Device Flow authentication process
 * @param {string} serverUrl - The Nucleus server URL
 * @returns {Promise<Object>} - Device flow authorization result containing:
 *   - user_code: Code the user needs to enter
 *   - device_code: Code used to poll for token
 *   - verification_uri: URL where user enters the code
 *   - interval: Polling interval in seconds
 *   - expires_in: Expiration time in seconds
 */
export async function startDeviceFlow(serverUrl) {
  const deviceFlow = await connectToService(serverUrl, DeviceFlow);
  
  try {
    const result = await deviceFlow.authorize({ client_id: CLIENT_ID });
    
    if (result.status && result.status !== AuthStatus.OK) {
      throw new Error(`Authorization failed with status: ${result.status}`);
    }
    
    return {
      user_code: result.user_code,
      device_code: result.device_code,
      verification_uri: result.verification_uri,
      interval: result.interval || 5,
      expires_in: result.expires_in || 900,
      serverUrl: normalizeServerUrl(serverUrl),
    };
  } finally {
    if (deviceFlow?.transport?.close) {
      await deviceFlow.transport.close();
    }
  }
}

/**
 * Poll for token after user enters the device code
 * @param {string} serverUrl - The Nucleus server URL
 * @param {string} deviceCode - The device code from startDeviceFlow
 * @returns {Promise<Object>} - Token result or pending status:
 *   - status: AuthStatus (OK, Pending, Expired, etc.)
 *   - access_token: Access token (if status is OK)
 *   - refresh_token: Refresh token (if status is OK)
 *   - profile: User profile (if status is OK)
 */
export async function pollForToken(serverUrl, deviceCode) {
  const deviceFlow = await connectToService(serverUrl, DeviceFlow);
  
  try {
    const result = await deviceFlow.token({
      client_id: CLIENT_ID,
      device_code: deviceCode,
    });
    
    return {
      status: result.status,
      access_token: result.access_token,
      refresh_token: result.refresh_token,
      profile: result.profile,
      username: result.username,
    };
  } finally {
    if (deviceFlow?.transport?.close) {
      await deviceFlow.transport.close();
    }
  }
}

/**
 * Create a long-lived API token
 * @param {string} serverUrl - The Nucleus server URL
 * @param {string} accessToken - A valid access token
 * @param {string} tokenName - Name for the API token
 * @param {string} expireAt - ISO-8601 date string for expiration (e.g., "2026-01-01T00:00:00Z")
 * @returns {Promise<Object>} - API token result:
 *   - api_token: The created API token
 *   - name: Token name
 */
export async function createApiToken(serverUrl, accessToken, tokenName, expireAt = null) {
  const tokens = await connectToService(serverUrl, Tokens);
  
  try {
    // Build request object, only including expire_at if it's set (for permanent tokens, omit it)
    const request = {
      access_token: accessToken,
      name: tokenName,
      client_id: CLIENT_ID,
    };
    if (expireAt) {
      request.expire_at = expireAt;
    }
    
    const result = await tokens.createApiToken(request);
    
    if (result.status && result.status !== AuthStatus.OK) {
      throw new Error(`Failed to create API token: ${result.status}`);
    }
    
    // Note: The response field is 'token', not 'api_token'
    return {
      api_token: result.token,
      name: tokenName,
    };
  } finally {
    if (tokens?.transport?.close) {
      await tokens.transport.close();
    }
  }
}

/**
 * Refresh an access token using a refresh token
 * @param {string} serverUrl - The Nucleus server URL
 * @param {string} refreshToken - The refresh token
 * @returns {Promise<Object>} - New tokens
 */
export async function refreshAccessToken(serverUrl, refreshToken) {
  const tokens = await connectToService(serverUrl, Tokens);
  
  try {
    const result = await tokens.refresh({
      refresh_token: refreshToken,
      client_id: CLIENT_ID,
    });
    
    if (result.status === AuthStatus.OK) {
      return {
        status: result.status,
        access_token: result.access_token,
        refresh_token: result.refresh_token,
      };
    } else {
      throw new Error(`Token refresh failed: ${result.status}`);
    }
  } finally {
    if (tokens?.transport?.close) {
      await tokens.transport.close();
    }
  }
}

/**
 * Authenticate with username/password credentials
 * @param {string} serverUrl - The Nucleus server URL
 * @param {string} username - Username
 * @param {string} password - Password
 * @returns {Promise<Object>} - Authentication result
 */
export async function authenticateWithCredentials(serverUrl, username, password) {
  const credentials = await connectToService(serverUrl, Credentials, { auth: 0 });
  
  try {
    const result = await credentials.auth({
      username,
      password,
      client_id: CLIENT_ID,
    });
    
    return {
      status: result.status,
      access_token: result.access_token,
      refresh_token: result.refresh_token,
      profile: result.profile,
      username: result.username,
    };
  } finally {
    if (credentials?.transport?.close) {
      await credentials.transport.close();
    }
  }
}

// ============================================================================
// React Hooks
// ============================================================================

/**
 * Hook for managing Device Flow authentication
 * @returns {Object} - Device flow state and methods
 */
export function useDeviceFlowAuth() {
  const [state, setState] = useState({
    isLoading: false,
    isPolling: false,
    error: null,
    deviceFlowData: null,
    authResult: null,
  });
  
  const pollingRef = useRef(null);
  const abortRef = useRef(false);

  // Start the device flow
  const startAuth = useCallback(async (serverUrl) => {
    setState(prev => ({ ...prev, isLoading: true, error: null, deviceFlowData: null, authResult: null }));
    abortRef.current = false;
    
    try {
      const result = await startDeviceFlow(serverUrl);
      setState(prev => ({ 
        ...prev, 
        isLoading: false, 
        deviceFlowData: result,
      }));
      return result;
    } catch (error) {
      setState(prev => ({ 
        ...prev, 
        isLoading: false, 
        error: error.message || 'Failed to start device flow',
      }));
      throw error;
    }
  }, []);

  // Poll for token
  const startPolling = useCallback(async (serverUrl, deviceCode, interval = 5) => {
    setState(prev => ({ ...prev, isPolling: true, error: null }));
    abortRef.current = false;
    
    const poll = async () => {
      if (abortRef.current) {
        setState(prev => ({ ...prev, isPolling: false }));
        return;
      }
      
      try {
        const result = await pollForToken(serverUrl, deviceCode);
        
        if (result.status === AuthStatus.OK) {
          setState(prev => ({ 
            ...prev, 
            isPolling: false, 
            authResult: result,
          }));
          return result;
        } else if (result.status === AuthStatus.Pending) {
          // Continue polling
          if (!abortRef.current) {
            pollingRef.current = setTimeout(poll, interval * 1000);
          }
        } else if (result.status === AuthStatus.Expired) {
          setState(prev => ({ 
            ...prev, 
            isPolling: false, 
            error: 'Device code expired. Please try again.',
          }));
        } else {
          setState(prev => ({ 
            ...prev, 
            isPolling: false, 
            error: `Authentication failed: ${result.status}`,
          }));
        }
      } catch (error) {
        if (!abortRef.current) {
          setState(prev => ({ 
            ...prev, 
            isPolling: false, 
            error: error.message || 'Polling failed',
          }));
        }
      }
    };
    
    return poll();
  }, []);

  // Stop polling
  const stopPolling = useCallback(() => {
    abortRef.current = true;
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      pollingRef.current = null;
    }
    setState(prev => ({ ...prev, isPolling: false }));
  }, []);

  // Reset state
  const reset = useCallback(() => {
    stopPolling();
    setState({
      isLoading: false,
      isPolling: false,
      error: null,
      deviceFlowData: null,
      authResult: null,
    });
  }, [stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current = true;
      if (pollingRef.current) {
        clearTimeout(pollingRef.current);
      }
    };
  }, []);

  return {
    ...state,
    startAuth,
    startPolling,
    stopPolling,
    reset,
  };
}

/**
 * Hook for creating API tokens
 * @returns {Object} - API token creation state and methods
 */
export function useCreateApiToken() {
  const [state, setState] = useState({
    isLoading: false,
    error: null,
    apiToken: null,
  });

  const createToken = useCallback(async (serverUrl, accessToken, tokenName, expireAt) => {
    setState({ isLoading: true, error: null, apiToken: null });
    
    try {
      const result = await createApiToken(serverUrl, accessToken, tokenName, expireAt);
      setState({ isLoading: false, error: null, apiToken: result.api_token });
      return result;
    } catch (error) {
      setState({ isLoading: false, error: error.message || 'Failed to create API token', apiToken: null });
      throw error;
    }
  }, []);

  const reset = useCallback(() => {
    setState({ isLoading: false, error: null, apiToken: null });
  }, []);

  return {
    ...state,
    createToken,
    reset,
  };
}

// ============================================================================
// Auth Status Constants (re-exported for convenience)
// ============================================================================

export { AuthStatus };

// ============================================================================
// Default Export
// ============================================================================

export default {
  // Functions
  normalizeServerUrl,
  getServerHttpsUrl,
  startDeviceFlow,
  pollForToken,
  createApiToken,
  refreshAccessToken,
  authenticateWithCredentials,
  
  // Hooks
  useDeviceFlowAuth,
  useCreateApiToken,
  
  // Constants
  AuthStatus,
  CLIENT_ID,
};

