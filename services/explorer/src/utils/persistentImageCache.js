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
 * Persistent image cache using IndexedDB for browser storage
 * Stores image data URLs and metadata for offline access
 */

const DB_NAME = 'DeepSearchImageCache';
const DB_VERSION = 1;
const STORE_NAME = 'images';
const MAX_CACHE_SIZE = 1024 * 1024 * 1024; // 1GB limit
const CLEANUP_THRESHOLD = 0.8; // Clean up when 80% full

class PersistentImageCache {
  constructor() {
    this.db = null;
    this.initPromise = null;
  }

  async init() {
    if (this.initPromise) {
      return this.initPromise;
    }

    this.initPromise = new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        console.warn('IndexedDB not supported, falling back to memory-only cache');
        resolve(false);
        return;
      }

      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onerror = () => {
        console.error('Failed to open IndexedDB:', request.error);
        resolve(false);
      };

      request.onsuccess = () => {
        this.db = request.result;
        resolve(true);
      };

      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        
        // Create object store if it doesn't exist
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'key' });
          store.createIndex('timestamp', 'timestamp', { unique: false });
          store.createIndex('size', 'size', { unique: false });
        }
      };
    });

    return this.initPromise;
  }

  async get(key) {
    await this.init();
    if (!this.db) return null;

    return new Promise((resolve) => {
      const transaction = this.db.transaction([STORE_NAME], 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.get(key);

      request.onsuccess = () => {
        const result = request.result;
        if (result) {
          // Update access timestamp
          this.updateAccessTime(key);
          resolve({
            data: result.data,
            error: result.error,
            timestamp: result.timestamp,
            attempted: true,
            offset: result.offset
          });
        } else {
          resolve(null);
        }
      };

      request.onerror = () => {
        console.error('Failed to get from persistent cache:', request.error);
        resolve(null);
      };
    });
  }

  async set(key, imageData, error = null, offset = 0) {
    await this.init();
    if (!this.db) return false;

    // Calculate approximate size
    const dataSize = imageData ? new Blob([imageData]).size : 0;
    const errorSize = error ? JSON.stringify(error).length : 0;
    const totalSize = dataSize + errorSize + key.length + 100; // Additional metadata overhead

    const entry = {
      key,
      data: imageData,
      error: error ? JSON.stringify(error) : null,
      timestamp: Date.now(),
      accessTime: Date.now(),
      size: totalSize,
      offset,
      attempted: true
    };

    return new Promise(async (resolve) => {
      // Check if we need to clean up space
      await this.cleanupIfNeeded(totalSize);

      const transaction = this.db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.put(entry);

      request.onsuccess = () => {
        resolve(true);
      };

      request.onerror = () => {
        console.error('Failed to store in persistent cache:', request.error);
        resolve(false);
      };
    });
  }

  async updateAccessTime(key) {
    if (!this.db) return;

    const transaction = this.db.transaction([STORE_NAME], 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    const getRequest = store.get(key);

    getRequest.onsuccess = () => {
      const result = getRequest.result;
      if (result) {
        result.accessTime = Date.now();
        store.put(result);
      }
    };
  }

  async getCacheSize() {
    await this.init();
    if (!this.db) return 0;

    return new Promise((resolve) => {
      const transaction = this.db.transaction([STORE_NAME], 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.getAll();

      request.onsuccess = () => {
        const totalSize = request.result.reduce((sum, entry) => sum + (entry.size || 0), 0);
        resolve(totalSize);
      };

      request.onerror = () => {
        resolve(0);
      };
    });
  }

  async cleanupIfNeeded(newEntrySize = 0) {
    const currentSize = await this.getCacheSize();
    const projectedSize = currentSize + newEntrySize;

    if (projectedSize > MAX_CACHE_SIZE * CLEANUP_THRESHOLD) {
      await this.cleanup();
    }
  }

  async cleanup() {
    await this.init();
    if (!this.db) return;

    return new Promise((resolve) => {
      const transaction = this.db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      const index = store.index('timestamp');
      const request = index.getAll();

      request.onsuccess = () => {
        const entries = request.result;
        
        // Sort by access time (oldest first)
        entries.sort((a, b) => (a.accessTime || a.timestamp) - (b.accessTime || b.timestamp));
        
        // Calculate how much to remove (remove oldest 25% of entries)
        const entriesToRemove = Math.floor(entries.length * 0.25);
        
        // Remove oldest entries
        const deletePromises = entries.slice(0, entriesToRemove).map(entry => {
          return new Promise((deleteResolve) => {
            const deleteRequest = store.delete(entry.key);
            deleteRequest.onsuccess = () => deleteResolve();
            deleteRequest.onerror = () => deleteResolve(); // Continue even if delete fails
          });
        });

        Promise.all(deletePromises).then(() => {
          console.log(`Cleaned up ${entriesToRemove} cache entries`);
          resolve();
        });
      };

      request.onerror = () => {
        resolve();
      };
    });
  }

  async clear() {
    await this.init();
    if (!this.db) return;

    return new Promise((resolve) => {
      const transaction = this.db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.clear();

      request.onsuccess = () => {
        console.log('Persistent image cache cleared');
        resolve();
      };

      request.onerror = () => {
        console.error('Failed to clear persistent cache:', request.error);
        resolve();
      };
    });
  }

  async getAllKeys() {
    await this.init();
    if (!this.db) return [];

    return new Promise((resolve) => {
      const transaction = this.db.transaction([STORE_NAME], 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.getAllKeys();

      request.onsuccess = () => {
        resolve(request.result || []);
      };

      request.onerror = () => {
        resolve([]);
      };
    });
  }

  async getStats() {
    await this.init();
    if (!this.db) {
      return { supported: false, size: 0, count: 0 };
    }

    return new Promise((resolve) => {
      const transaction = this.db.transaction([STORE_NAME], 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.getAll();

      request.onsuccess = () => {
        const entries = request.result;
        const totalSize = entries.reduce((sum, entry) => sum + (entry.size || 0), 0);
        
        resolve({
          supported: true,
          size: totalSize,
          count: entries.length,
          maxSize: MAX_CACHE_SIZE
        });
      };

      request.onerror = () => {
        resolve({ supported: true, size: 0, count: 0, maxSize: MAX_CACHE_SIZE });
      };
    });
  }
}

// Create singleton instance
const persistentCache = new PersistentImageCache();

export default persistentCache;