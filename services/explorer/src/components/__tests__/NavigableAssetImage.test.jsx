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

// Mock the imageLoader module so we can assert on call counts without making
// real network requests.
jest.mock("../../utils/imageLoader", () => ({
  loadImage: jest.fn(() => new Promise(() => {})), // never resolves
  getCachedOffsets: jest.fn(() => []),
  loadProgressiveImages: jest.fn(() => new Promise(() => {})),
}));

// Stub Chakra so we don't depend on @chakra-ui/utils/context resolution in jest
// (the workspace ships a broken Chakra install for tests — unrelated to MR 4).
// We only need DOM-level rendering to assert on the <img> src and on call counts.
jest.mock("@chakra-ui/react", () => {
  // eslint-disable-next-line global-require
  const ReactLib = require("react");
  const passthrough = (tag) => {
    const C = ReactLib.forwardRef(({ children, ...rest }, ref) =>
      ReactLib.createElement(tag, { ref, ...rest }, children)
    );
    C.displayName = `Stub(${tag})`;
    return C;
  };
  return {
    Box: passthrough("div"),
    IconButton: passthrough("button"),
    Spinner: passthrough("span"),
  };
});

jest.mock("@chakra-ui/icons", () => ({
  ChevronLeftIcon: () => null,
  ChevronRightIcon: () => null,
}));

// ImageSkeleton uses Chakra too; stub it to a plain <img> reflecting src.
jest.mock("../ImageSkeleton", () => ({
  __esModule: true,
  // eslint-disable-next-line global-require
  ImageWithSkeleton: ({ src, alt }) =>
    // eslint-disable-next-line global-require
    src ? require("react").createElement("img", { src, alt }) : null,
}));

// eslint-disable-next-line import/first
import React from "react";
// eslint-disable-next-line import/first
import { render, screen, waitFor } from "@testing-library/react";
// eslint-disable-next-line import/first
import NavigableAssetImage from "../NavigableAssetImage";
// eslint-disable-next-line import/first
import { loadImage } from "../../utils/imageLoader";

const baseProps = {
  result: { id: "x", source: { base_key: "s3://x" } },
  getHeaders: () => ({}),
  apiUrl: "",
};

beforeEach(() => {
  loadImage.mockClear();
});

describe("NavigableAssetImage offset-0 ownership", () => {
  test("does not call loadImage when parentLoadingState is provided", async () => {
    const parentLoadingState = {
      loading: false,
      error: null,
      data: "data:image/png;base64,abc",
    };
    render(
      <NavigableAssetImage
        {...baseProps}
        parentLoadingState={parentLoadingState}
      />
    );

    // The parent's image data should be rendered as the <img> src.
    const img = await screen.findByRole("img");
    expect(img).toHaveAttribute("src", "data:image/png;base64,abc");

    expect(loadImage).toHaveBeenCalledTimes(0);
  });

  test("calls loadImage(offset=0) when parentLoadingState is omitted", async () => {
    render(<NavigableAssetImage {...baseProps} />);

    await waitFor(() => {
      expect(loadImage).toHaveBeenCalled();
    });

    // First positional arg is assetUrl, fifth (index 4) is imgOffset.
    const offsets = loadImage.mock.calls.map((args) => args[4]);
    expect(offsets).toContain(0);
  });

  // TODO: assert loadImage(offset=1) is called on right-arrow click.
  // Skipped because the arrow only renders while the parent Box is hovered;
  // jsdom's mouseEnter simulation + Chakra's IconButton hit-testing make the
  // assertion brittle in a unit test. Covered by the existing manual /ui/ smoke
  // pass for MR 4.
});
