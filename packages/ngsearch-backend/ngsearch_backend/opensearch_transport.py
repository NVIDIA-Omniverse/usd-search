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

import asyncio
from asyncio import get_running_loop

import urllib3  # type: ignore
from opensearchpy import AIOHttpConnection
from opensearchpy._async._extra_imports import aiohttp, aiohttp_exceptions, yarl
from opensearchpy._async.compat import get_running_loop
from opensearchpy._async.http_aiohttp import OpenSearchClientResponse
from opensearchpy._async.transport import AsyncTransport
from opensearchpy.compat import reraise_exceptions, urlencode
from opensearchpy.exceptions import ConnectionError, ConnectionTimeout, SSLError
from opentelemetry import trace
from opentelemetry.instrumentation.aiohttp_client import create_trace_config

tracer = trace.get_tracer(__name__)
aiohttp_trace_config = create_trace_config()


class InstrumentedAIOHttpConnectionClass(AIOHttpConnection):
    async def perform_request(self, method, url, params=None, body=None, timeout=None, ignore=(), headers=None):
        with tracer.start_as_current_span("os_connection_perform_request"):
            if self.session is None:
                await self._create_aiohttp_session()
            assert self.session is not None

            orig_body = body
            url_path = self.url_prefix + url
            if params:
                query_string = urlencode(params)
            else:
                query_string = ""

            # There is a bug in aiohttp that disables the re-use
            # of the connection in the pool when method=HEAD.
            # See: aio-libs/aiohttp#1769
            is_head = False
            if method == "HEAD":
                method = "GET"
                is_head = True

            # Top-tier tip-toeing happening here. Basically
            # because Pip's old resolver is bad and wipes out
            # strict pins in favor of non-strict pins of extras
            # our [async] extra overrides aiohttp's pin of
            # yarl. yarl released breaking changes, aiohttp pinned
            # defensively afterwards, but our users don't get
            # that nice pin that aiohttp set. :( So to play around
            # this super-defensively we try to import yarl, if we can't
            # then we pass a string into ClientSession.request() instead.
            if yarl:
                # Provide correct URL object to avoid string parsing in low-level code
                url = yarl.URL.build(
                    scheme=self.scheme,
                    host=self.hostname,
                    port=self.port,
                    path=url_path,
                    query_string=query_string,
                    encoded=True,
                )
            else:
                url = self.url_prefix + url
                if query_string:
                    url = "%s?%s" % (url, query_string)
                url = self.host + url

            timeout = aiohttp.ClientTimeout(total=timeout if timeout is not None else self.timeout)

            req_headers = self.headers.copy()
            if headers:
                req_headers.update(headers)

            if self.http_compress and body:
                body = self._gzip_compress(body)
                req_headers["content-encoding"] = "gzip"

            start = self.loop.time()
            try:
                async with self.session.request(
                    method,
                    url,
                    data=body,
                    headers=req_headers,
                    timeout=timeout,
                    fingerprint=self.ssl_assert_fingerprint,
                ) as response:
                    if is_head:  # We actually called 'GET' so throw away the data.
                        await response.release()
                        raw_data = ""
                    else:
                        with tracer.start_as_current_span("get_response_text") as span:
                            raw_data = await response.text()
                            span.set_attribute("response_text_len", len(raw_data))
                            span.set_attribute(
                                "response_content_encoding",
                                response.headers.get("Content-Encoding", ""),
                            )
                    duration = self.loop.time() - start

            # We want to reraise a cancellation or recursion error.
            except reraise_exceptions:
                raise
            except Exception as e:
                self.log_request_fail(
                    method,
                    str(url),
                    url_path,
                    orig_body,
                    self.loop.time() - start,
                    exception=e,
                )
                if isinstance(e, aiohttp_exceptions.ServerFingerprintMismatch):
                    raise SSLError("N/A", str(e), e)
                if isinstance(e, (asyncio.TimeoutError, aiohttp_exceptions.ServerTimeoutError)):
                    raise ConnectionTimeout("TIMEOUT", str(e), e)
                raise ConnectionError("N/A", str(e), e)

            # raise warnings if any from the 'Warnings' header.
            warning_headers = response.headers.getall("warning", ())
            self._raise_warnings(warning_headers)

            # raise errors based on http status codes, let the client handle those if needed
            if not (200 <= response.status < 300) and response.status not in ignore:
                with tracer.start_as_current_span("log_request_fail"):
                    self.log_request_fail(
                        method,
                        str(url),
                        url_path,
                        orig_body,
                        duration,
                        status_code=response.status,
                        response=raw_data,
                    )
                    self._raise_error(response.status, raw_data)

            self.log_request_success(
                method,
                str(url),
                url_path,
                orig_body,
                response.status,
                raw_data,
                duration,
            )

            return response.status, response.headers, raw_data

    async def _create_aiohttp_session(self):
        """Creates an aiohttp.ClientSession(). This is delayed until
        the first call to perform_request() so that AsyncTransport has
        a chance to set AIOHttpConnection.loop
        """
        if self.loop is None:
            self.loop = get_running_loop()
        self.session = aiohttp.ClientSession(
            headers=self.headers,
            skip_auto_headers=("accept", "accept-encoding"),
            auto_decompress=True,
            loop=self.loop,
            cookie_jar=aiohttp.DummyCookieJar(),
            response_class=OpenSearchClientResponse,
            connector=aiohttp.TCPConnector(limit=self._limit, use_dns_cache=True, ssl=self._ssl_context),
            trace_configs=[aiohttp_trace_config],
        )


class InstrumentedAsyncTransport(AsyncTransport):
    DEFAULT_CONNECTION_CLASS = InstrumentedAIOHttpConnectionClass

    async def perform_request(
        self,
        *args,
        **kwargs,
    ):
        with tracer.start_as_current_span("os_perform_request"):
            return await super().perform_request(*args, **kwargs)

    def get_connection(self):
        with tracer.start_as_current_span("get_connection_from_pool"):
            return super().get_connection()
