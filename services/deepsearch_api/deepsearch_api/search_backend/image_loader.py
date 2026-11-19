# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional

from opensearchpy import AsyncOpenSearch
from opensearchpy.exceptions import NotFoundError
from opensearchpy.helpers import async_scan

from .exceptions import ImageCacheReadError

logger = logging.getLogger(__name__)


class BaseImageLoader(ABC):
    """Abstract base class for image loaders."""

    @abstractmethod
    async def load_image(self, image_id: str) -> Optional[str]:
        """Load an image by ID and return base64 encoded image data."""
        pass

    @abstractmethod
    async def load_images(self, image_ids: List[str]) -> Dict[str, Optional[str]]:
        """Load multiple images by their IDs."""
        pass

    async def fetch_image(self, image_id: str) -> Optional[str]:
        """Like ``load_image``, but raises ``ImageCacheReadError`` when the read fails; ``None`` means absent."""
        return await self.load_image(image_id)


class OpenSearchImageLoader(BaseImageLoader):
    """Image loader that fetches images from OpenSearch image cache index."""

    def __init__(self, client: AsyncOpenSearch, image_cache_index: str):
        """
        Initialize OpenSearch image loader.

        Args:
            client: AsyncOpenSearch client
            image_cache_index: Name of the image cache index (e.g., "ds-ci-rc-r15-ov-clip-ver4.0-image-cache")
        """
        self.client = client
        self.image_cache_index = image_cache_index

    async def load_image(self, image_id: str) -> Optional[str]:
        """
        Load a single image by ID from the image cache index.

        Args:
            image_id: The image ID to load

        Returns:
            Base64 encoded image data or None if not found (or the read failed)
        """
        try:
            return await self.fetch_image(image_id)
        except ImageCacheReadError as e:
            logger.warning(f"Failed to load image {image_id}: {e}")
            return None

    async def fetch_image(self, image_id: str) -> Optional[str]:
        try:
            response = await self.client.get(index=self.image_cache_index, id=image_id)
        except NotFoundError as e:
            # Only a missing document means "absent"; a missing index (index_not_found_exception) is also a 404 but
            # means the cache itself is unavailable.
            if isinstance(e.info, dict) and e.info.get("found") is False:
                logger.warning(f"Image not found: {image_id}")
                return None
            raise ImageCacheReadError(f"Image cache read failed for image ID {image_id}: {e}") from e
        except Exception as e:
            raise ImageCacheReadError(f"Image cache read failed for image ID {image_id}: {e}") from e

        # Look for common image field names
        source = response.get("_source", {})
        for field_name in ["siglip2-embedding-ver3.0-image", "image", "image_data"]:
            if field_name in source:
                return source[field_name]

        logger.warning(f"No image data found for image ID {image_id}")
        return None

    async def load_images(self, image_ids: List[str]) -> Dict[str, Optional[str]]:
        """
        Load multiple images by their IDs using mget for efficiency.

        Args:
            image_ids: List of image IDs to load

        Returns:
            Dictionary mapping image ID to base64 encoded image data
        """
        if not image_ids:
            return {}

        try:
            logger.debug("Loading images with IDs: %s", image_ids)
            response = await self.client.mget(index=self.image_cache_index, body={"ids": image_ids})
            logger.debug("Received response for image IDs: %s", image_ids)

            result = {}
            for doc in response.get("docs", []):
                image_id = doc.get("_id")
                if doc.get("found", False):
                    source = doc.get("_source", {})

                    # Look for common image field names
                    image_data = None
                    for field_name in [
                        "siglip2-embedding-ver3.0-image",
                        "image",
                        "image_data",
                    ]:
                        if field_name in source:
                            image_data = source[field_name]
                            break

                    result[image_id] = image_data
                else:
                    result[image_id] = None
                    logger.warning(f"Image not found: {image_id}")

            return result

        except Exception as e:
            logger.error(f"Failed to load images {image_ids}: {e}")
            return {image_id: None for image_id in image_ids}

    async def image_count(self) -> int:
        """How many images the image cache index holds."""
        response = await self.client.count(index=self.image_cache_index)
        return int(response["count"])

    async def image_ids(self, page: int = 500) -> AsyncIterator[str]:
        """Every image id of the image cache index, in index order (a scroll that reads no image data)."""
        async for hit in async_scan(
            self.client,
            query={"query": {"match_all": {}}, "_source": False},
            index=self.image_cache_index,
            size=page,
            scroll="5m",
        ):
            yield hit["_id"]


class MockImageLoader(BaseImageLoader):
    """Mock image loader for testing purposes."""

    def __init__(self, mock_image_data: Optional[str] = None):
        """
        Initialize mock image loader.

        Args:
            mock_image_data: Mock base64 encoded image data to return
        """
        if mock_image_data is None:
            mock_image_data = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUGBgYFBgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQICAgICAgUDAwUKBwYHCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgr/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD9/KKKKAP/2Q=="
        self.mock_image_data = mock_image_data

    async def load_image(self, image_id: str) -> Optional[str]:
        """Return mock image data for any image ID."""
        return self.mock_image_data

    async def load_images(self, image_ids: List[str]) -> Dict[str, Optional[str]]:
        """Return mock image data for all requested image IDs."""
        return {image_id: self.mock_image_data for image_id in image_ids}
