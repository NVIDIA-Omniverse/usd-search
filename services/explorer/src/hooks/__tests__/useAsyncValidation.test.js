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

import { renderHook, act, waitFor } from "@testing-library/react";
import { useAsyncValidation } from "../useAsyncValidation";
import { VALIDATION_CONFIG } from "../../config";

describe("useAsyncValidation", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = jest.fn().mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: () => Promise.resolve({ detail: "VLM unavailable" }),
      })
    );
    global.fetch = fetchMock;
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("short-circuits on first 503 and surfaces vlmUnavailable flag", async () => {
    const apiUrl = "https://example.com/api/v2";
    const getHeaders = () => ({ "Content-Type": "application/json" });

    const { result } = renderHook(() => useAsyncValidation(apiUrl, getHeaders));

    const hits = Array.from({ length: 10 }, (_, i) => ({ id: `hit-${i}` }));

    act(() => {
      result.current.startValidation(hits, "test query", null);
    });

    // Wait for vlmUnavailable to flip to true after the first 503 lands.
    await waitFor(() => {
      expect(result.current.vlmUnavailable).toBe(true);
    });

    // Initial batch fires up to MAX_CONCURRENT in parallel before any response
    // arrives; the 503 short-circuit prevents queueing the remaining hits.
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(VALIDATION_CONFIG.MAX_CONCURRENT);
    expect(fetchMock.mock.calls.length).toBeLessThan(hits.length);

    // cancelAllValidations() in the 503 branch clears validationMap, so no
    // entries should be marked "error" for the in-flight items.
    const errorEntries = Object.values(result.current.validationMap).filter(
      (entry) => entry.status === "error"
    );
    expect(errorEntries.length).toBe(0);
  });
});
