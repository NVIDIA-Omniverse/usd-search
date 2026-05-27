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

import { useState, useCallback, useRef } from "react";
import { VALIDATION_CONFIG } from "../config";

/**
 * Hook for asynchronous per-result VLM validation.
 *
 * Instead of blocking on all validations before showing results,
 * this fires independent validation requests (throttled to VALIDATION_CONFIG.MAX_CONCURRENT)
 * and updates each result as its response arrives.
 *
 * @param {string} apiUrl - The base API URL (v2 format, will be converted to v3)
 * @param {function} getHeaders - Returns auth/content-type headers for fetch
 */
export function useAsyncValidation(apiUrl, getHeaders) {
  const [validationMap, setValidationMap] = useState({});
  const [validatedCount, setValidatedCount] = useState(0);
  const [totalToValidate, setTotalToValidate] = useState(0);
  const [isValidating, setIsValidating] = useState(false);
  const [vlmUnavailable, setVlmUnavailable] = useState(false);

  const generationRef = useRef(0);
  const abortControllerRef = useRef(null);
  const vlmUnavailableRef = useRef(false);

  const cancelAllValidations = useCallback(() => {
    generationRef.current += 1;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    vlmUnavailableRef.current = false;
    setIsValidating(false);
    setValidatedCount(0);
    setTotalToValidate(0);
    setValidationMap({});
    setVlmUnavailable(false);
  }, []);

  const startValidation = useCallback(
    (hits, queryText, queryImage) => {
      if (!hits || hits.length === 0) return;
      // Skip validation when there's no query to validate against (e.g. filter-only searches)
      if (!queryText && !queryImage) return;

      cancelAllValidations();

      const currentGeneration = generationRef.current;
      const batchAbort = new AbortController();
      abortControllerRef.current = batchAbort;

      const initialMap = {};
      hits.forEach((hit) => {
        const id = hit.id || hit.source?.base_key;
        if (id) {
          initialMap[id] = { status: "pending", result: null };
        }
      });
      setValidationMap(initialMap);
      setTotalToValidate(hits.length);
      setValidatedCount(0);
      setIsValidating(true);

      const v3Url = apiUrl.replace("v2", "v3");

      // Build work items
      const workItems = hits
        .map((hit) => {
          const id = hit.id || hit.source?.base_key;
          if (!id) return null;

          let imageKey = null;
          if (hit.metadata?.explanations) {
            for (const exp of hit.metadata.explanations) {
              for (const mv of exp.matched_vectors || []) {
                if (mv.image) {
                  imageKey = mv.image;
                  break;
                }
              }
              if (imageKey) break;
            }
          }

          const body = {
            query_text: queryText || undefined,
            query_image: queryImage || undefined,
          };
          if (imageKey) {
            body.image_key = imageKey;
          } else {
            body.asset_url = hit.source?.base_key || id;
          }

          return { id, body };
        })
        .filter(Boolean);

      // Concurrency-limited queue
      let completed = 0;
      let nextIndex = 0;

      const processNext = () => {
        if (vlmUnavailableRef.current) return;
        if (batchAbort.signal.aborted) return;
        if (generationRef.current !== currentGeneration) return;
        if (nextIndex >= workItems.length) return;

        const idx = nextIndex++;
        const { id, body } = workItems[idx];

        // Mark as validating
        setValidationMap((prev) => ({
          ...prev,
          [id]: { status: "validating", result: null },
        }));

        const attemptValidation = (retriesLeft) => {
          if (batchAbort.signal.aborted) return;
          if (generationRef.current !== currentGeneration) return;

          fetch(`${v3Url}/vlm_validate/search_result`, {
            method: "POST",
            headers: getHeaders(),
            body: JSON.stringify(body),
            signal: batchAbort.signal,
          })
            .then((response) => {
              if (response.status === 503) {
                // VLM unavailable — stop the batch immediately, surface a single banner.
                cancelAllValidations();
                vlmUnavailableRef.current = true;
                setVlmUnavailable(true);
                return null;
              }
              if ((response.status === 429 || response.status === 504) && retriesLeft > 0) {
                // Rate limited or gateway timeout — retry after delay
                setTimeout(() => attemptValidation(retriesLeft - 1), VALIDATION_CONFIG.RETRY_DELAY_MS);
                return null;
              }
              if (!response.ok) throw new Error(`HTTP ${response.status}`);
              return response.json();
            })
            .then((data) => {
              if (data === null) return; // Retry scheduled
              if (generationRef.current !== currentGeneration) return;
              const status = data.is_match ? "validated" : "rejected";
              setValidationMap((prev) => ({
                ...prev,
                [id]: { status, result: data },
              }));

              completed += 1;
              setValidatedCount(completed);
              if (completed >= workItems.length) setIsValidating(false);
              processNext();
            })
            .catch((err) => {
              if (generationRef.current !== currentGeneration) return;
              if (err.name === "AbortError") return;

              setValidationMap((prev) => ({
                ...prev,
                [id]: { status: "error", result: null },
              }));

              completed += 1;
              setValidatedCount(completed);
              if (completed >= workItems.length) setIsValidating(false);
              processNext();
            });
        };

        attemptValidation(VALIDATION_CONFIG.MAX_RETRIES);
      };

      // Kick off initial batch (up to MAX_CONCURRENT)
      const initialBatch = Math.min(VALIDATION_CONFIG.MAX_CONCURRENT, workItems.length);
      for (let i = 0; i < initialBatch; i++) {
        processNext();
      }
    },
    [apiUrl, getHeaders, cancelAllValidations]
  );

  return {
    validationMap,
    isValidating,
    validatedCount,
    totalToValidate,
    startValidation,
    cancelAllValidations,
    vlmUnavailable,
  };
}
