"""Network interceptor for browser request/response monitoring.

Provides request/response interception, filtering, modification,
and recording capabilities for browser automation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class NetworkRequest:
    """Captured network request.

    Attributes:
        request_id: Unique request identifier.
        url: Request URL.
        method: HTTP method (GET, POST, etc.).
        headers: Request headers.
        post_data: Request body/payload.
        timestamp: When the request was made.
        resource_type: Type of resource (xhr, fetch, document, script, etc.).
        redirected_from: URL this request was redirected from.
    """

    request_id: str
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    post_data: str | None = None
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    resource_type: str = "other"
    redirected_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "request_id": self.request_id,
            "url": self.url,
            "method": self.method,
            "headers": self.headers,
            "post_data": self.post_data,
            "timestamp": self.timestamp,
            "resource_type": self.resource_type,
            "redirected_from": self.redirected_from,
        }


@dataclass
class NetworkResponse:
    """Captured network response.

    Attributes:
        request_id: Matching request identifier.
        url: Response URL.
        status: HTTP status code.
        status_text: HTTP status text.
        headers: Response headers.
        content_type: Content type of the response.
        from_cache: Whether the response came from cache.
        from_service_worker: Whether the response came from a service worker.
        timestamp: When the response was received.
        body_size: Size of the response body.
    """

    request_id: str
    url: str
    status: int = 0
    status_text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    from_cache: bool = False
    from_service_worker: bool = False
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    body_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "request_id": self.request_id,
            "url": self.url,
            "status": self.status,
            "status_text": self.status_text,
            "headers": self.headers,
            "content_type": self.content_type,
            "from_cache": self.from_cache,
            "from_service_worker": self.from_service_worker,
            "timestamp": self.timestamp,
            "body_size": self.body_size,
        }


class NetworkInterceptor:
    """Intercepts and records network requests/responses.

    Provides:
    - Request/response recording
    - URL filtering (allow/block)
    - Request modification
    - Response mocking
    - Network event callbacks

    Example:
        interceptor = NetworkInterceptor()

        # Record all requests
        @interceptor.on_request
        def log_request(request):
            print(f"Request: {request.url}")

        # Block specific URLs
        interceptor.block_urls(["*.analytics.js", "*.tracking.com"])

        # Mock API responses
        @interceptor.on_response
        def mock_api(request, response):
            if "api.example.com" in response.url:
                response._mocked = True

        # Attach to page
        await interceptor.attach(page)

        # Detach when done
        await interceptor.detach(page)
    """

    def __init__(self) -> None:
        self._requests: list[NetworkRequest] = []
        self._responses: list[NetworkResponse] = []
        self._blocked_urls: list[str] = []
        self._allowed_urls: list[str] = []
        self._allowed_mimes: list[str] = []
        self._blocked_mimes: list[str] = []
        self._mock_routes: dict[str, Any] = {}
        self._request_handlers: list[Callable[[NetworkRequest], Coroutine[Any, Any, None]]] = []
        self._response_handlers: list[Callable[[NetworkRequest, NetworkResponse], Coroutine[Any, Any, None]]] = []
        self._max_history: int = 1000
        self._enabled = False

    @property
    def requests(self) -> list[NetworkRequest]:
        """Get recorded requests."""
        return list(self._requests)

    @property
    def responses(self) -> list[NetworkResponse]:
        """Get recorded responses."""
        return list(self._responses)

    @property
    def is_enabled(self) -> bool:
        """Check if interceptor is enabled."""
        return self._enabled

    @property
    def request_count(self) -> int:
        """Get number of recorded requests."""
        return len(self._requests)

    @property
    def response_count(self) -> int:
        """Get number of recorded responses."""
        return len(self._responses)

    # -- Filtering --

    def block_urls(self, patterns: list[str]) -> None:
        """Block URLs matching the given patterns.

        Args:
            patterns: URL patterns to block (supports glob-style wildcards).
        """
        self._blocked_urls.extend(patterns)

    def allow_urls(self, patterns: list[str]) -> None:
        """Only allow URLs matching the given patterns.

        Args:
            patterns: URL patterns to allow (supports glob-style wildcards).
        """
        self._allowed_urls.extend(patterns)

    def block_mimes(self, mimes: list[str]) -> None:
        """Block responses with matching MIME types.

        Args:
            mimes: MIME type patterns to block.
        """
        self._blocked_mimes.extend(mimes)

    def allow_mimes(self, mimes: list[str]) -> None:
        """Only allow responses with matching MIME types.

        Args:
            mimes: MIME type patterns to allow.
        """
        self._allowed_mimes.extend(mimes)

    def clear_filters(self) -> None:
        """Clear all URL and MIME filters."""
        self._blocked_urls.clear()
        self._allowed_urls.clear()
        self._allowed_mimes.clear()
        self._blocked_mimes.clear()

    def _is_blocked(self, url: str, content_type: str = "") -> bool:
        """Check if a URL/content type is blocked."""
        # Check blocked URLs
        for pattern in self._blocked_urls:
            if self._matches_pattern(url, pattern):
                return True

        # Check allowed URLs (if set, everything else is blocked)
        if self._allowed_urls and not any(self._matches_pattern(url, p) for p in self._allowed_urls):
            return True

        # Check blocked content types
        for mime in self._blocked_mimes:
            if mime in content_type:
                return True

        # Check allowed content types
        if self._allowed_mimes and not any(mime in content_type for mime in self._allowed_mimes):
            return True

        return False

    @staticmethod
    def _matches_pattern(url: str, pattern: str) -> bool:
        """Check if a URL matches a glob pattern."""
        import fnmatch
        return fnmatch.fnmatch(url, pattern)

    # -- Mocking --

    def mock_response(self, url_pattern: str, response: dict[str, Any]) -> None:
        """Mock a response for URLs matching a pattern.

        Args:
            url_pattern: URL pattern to match.
            response: Mock response data {status, headers, body}.
        """
        self._mock_routes[url_pattern] = response

    def remove_mock(self, url_pattern: str) -> None:
        """Remove a mock route."""
        self._mock_routes.pop(url_pattern, None)

    def clear_mocks(self) -> None:
        """Clear all mock routes."""
        self._mock_routes.clear()

    # -- Callbacks --

    def on_request(self, handler: Callable[[NetworkRequest], Coroutine[Any, Any, None]]) -> None:
        """Register a request callback.

        Args:
            handler: Async function called with NetworkRequest.
        """
        self._request_handlers.append(handler)

    def on_response(self, handler: Callable[[NetworkRequest, NetworkResponse], Coroutine[Any, Any, None]]) -> None:
        """Register a response callback.

        Args:
            handler: Async function called with NetworkRequest and NetworkResponse.
        """
        self._response_handlers.append(handler)

    # -- Attach/Detach --

    async def attach(self, page: Any) -> None:
        """Attach the interceptor to a Playwright page.

        Args:
            page: Playwright Page object.
        """
        if self._enabled:
            return

        self._enabled = True
        logger.info("NetworkInterceptor attached")

        # Use Playwright's request/response events
        async def _on_request(request: Any) -> None:
            req = NetworkRequest(
                request_id=request.request_id if hasattr(request, "request_id") else id(request),
                url=request.url,
                method=request.method,
                headers=dict(request.headers) if hasattr(request, "headers") else {},
                post_data=request.post_data.decode() if hasattr(request, "post_data") and request.post_data else None,
                resource_type=request.resource.type if hasattr(request, "resource") else "other",
            )
            self._requests.append(req)
            if len(self._requests) > self._max_history:
                self._requests.pop(0)

            # Call registered handlers
            for handler in self._request_handlers:
                try:
                    await handler(req)
                except Exception as e:
                    logger.warning(f"Request handler error: {e}")

            # Check if blocked
            if self._is_blocked(request.url):
                await request.abort()
                logger.debug(f"Blocked request: {request.url}")

        async def _on_response(response: Any) -> None:
            resp = NetworkResponse(
                request_id=response.request.request_id if hasattr(response, "request") and hasattr(response.request, "request_id") else "",
                url=response.url,
                status=response.status,
                status_text=response.status_text if hasattr(response, "status_text") else "",
                headers=dict(response.headers) if hasattr(response, "headers") else {},
                content_type=response.headers.get("content-type", "") if hasattr(response, "headers") else "",
                from_cache=response.from_cache if hasattr(response, "from_cache") else False,
                from_service_worker=response.from_service_worker if hasattr(response, "from_service_worker") else False,
            )
            self._responses.append(resp)
            if len(self._responses) > self._max_history:
                self._responses.pop(0)

            # Call registered handlers
            req = None
            for r in reversed(self._requests):
                if r.request_id == resp.request_id:
                    req = r
                    break
            if req and self._response_handlers:
                for handler in self._response_handlers:
                    try:
                        await handler(req, resp)
                    except Exception as e:
                        logger.warning(f"Response handler error: {e}")

        # Register event listeners (using Playwright's event system)
        page.on("request", _on_request)
        page.on("response", _on_response)

        logger.info("NetworkInterceptor listeners registered")

    async def detach(self, page: Any) -> None:
        """Detach the interceptor from a page.

        Args:
            page: Playwright Page object.
        """
        self._enabled = False
        logger.info("NetworkInterceptor detached")

    # -- Querying --

    def get_requests(
        self,
        url_pattern: str | None = None,
        method: str | None = None,
        resource_type: str | None = None,
    ) -> list[NetworkRequest]:
        """Query recorded requests.

        Args:
            url_pattern: Filter by URL pattern.
            method: Filter by HTTP method.
            resource_type: Filter by resource type.

        Returns:
            Matching requests.
        """
        results = self._requests
        if url_pattern:
            results = [r for r in results if url_pattern in r.url]
        if method:
            results = [r for r in results if r.method == method]
        if resource_type:
            results = [r for r in results if r.resource_type == resource_type]
        return results

    def get_responses(
        self,
        url_pattern: str | None = None,
        status_code: int | None = None,
        content_type: str | None = None,
    ) -> list[NetworkResponse]:
        """Query recorded responses.

        Args:
            url_pattern: Filter by URL pattern.
            status_code: Filter by HTTP status code.
            content_type: Filter by content type.

        Returns:
            Matching responses.
        """
        results = self._responses
        if url_pattern:
            results = [r for r in results if url_pattern in r.url]
        if status_code is not None:
            results = [r for r in results if r.status == status_code]
        if content_type:
            results = [r for r in results if content_type in r.content_type]
        return results

    def get_api_calls(self) -> list[dict[str, Any]]:
        """Get all API (XHR/fetch) calls.

        Returns:
            List of API call dicts with request and response info.
        """
        api_calls = []
        for resp in self._responses:
            if resp.content_type and ("json" in resp.content_type or "xml" in resp.content_type):
                api_calls.append(resp.to_dict())
        return api_calls

    def get_network_timeline(self) -> list[dict[str, Any]]:
        """Get a timeline of all network activity.

        Returns:
            List of timeline entries sorted by timestamp.
        """
        timeline: dict[str, dict[str, Any]] = {}
        for req in self._requests:
            timeline[req.request_id] = {
                "type": "request",
                "timestamp": req.timestamp,
                "method": req.method,
                "url": req.url,
            }
        for resp in self._responses:
            if resp.request_id in timeline:
                timeline[resp.request_id]["response"] = {
                    "status": resp.status,
                    "timestamp": resp.timestamp,
                }
        return sorted(timeline.values(), key=lambda x: x["timestamp"])

    def clear(self) -> None:
        """Clear all recorded data."""
        self._requests.clear()
        self._responses.clear()
        self.clear_filters()
        self.clear_mocks()
        logger.info("Interceptor data cleared")

    def export_data(self) -> dict[str, Any]:
        """Export all interceptor data as a dictionary."""
        return {
            "requests": [r.to_dict() for r in self._requests],
            "responses": [r.to_dict() for r in self._responses],
            "blocked_urls": list(self._blocked_urls),
            "allowed_urls": list(self._allowed_urls),
            "mock_routes": dict(self._mock_routes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkInterceptor:
        """Create an interceptor from exported data.

        Args:
            data: Exported interceptor data.

        Returns:
            New NetworkInterceptor instance.
        """
        interceptor = cls()
        for req_data in data.get("requests", []):
            interceptor._requests.append(NetworkRequest(**req_data))
        for resp_data in data.get("responses", []):
            interceptor._responses.append(NetworkResponse(**resp_data))
        interceptor._blocked_urls = list(data.get("blocked_urls", []))
        interceptor._allowed_urls = list(data.get("allowed_urls", []))
        return interceptor
