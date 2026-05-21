# Markpost Python Client
# Client library for Markpost API

import time

import requests


class MarkpostError(Exception):
    """Base exception for all Markpost errors"""

    pass


class MarkpostAPIError(MarkpostError):
    """API returned an error response"""

    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error {status_code}: {message}")


class MarkpostAuthError(MarkpostAPIError):
    """Authentication failed (401, 403)"""

    pass


class MarkpostNotFoundError(MarkpostAPIError):
    """Resource not found (404)"""

    pass


class MarkpostConnectionError(MarkpostError):
    """Network/connection errors"""

    pass


class Client:
    """Markpost API Client"""

    def __init__(self, base_url, username=None, password=None):
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._username = username
        self._password = password
        self._token = None
        self._refresh_token = None
        self._token_expires_at = None
        self._post_key = None

        # Auto-login if credentials provided
        if username and password:
            self.login(username, password)

    def __enter__(self):
        """Support 'with' statement"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cleanup session on exit"""
        self._session.close()

    def _build_url(self, endpoint):
        """Build full URL from endpoint"""
        return f"{self._base_url}{endpoint}"

    def _get_headers(self):
        """Get headers including auth token if available"""
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _handle_response(self, response):
        """Parse response and handle errors"""
        if 200 <= response.status_code < 300:
            return response.json()

        # Handle errors
        error_message = None
        if response.headers.get("Content-Type") == "application/json":
            try:
                data = response.json()
                error_message = data.get("error", data.get("error_message"))
            except Exception:
                pass

        if not error_message:
            error_message = response.reason or f"HTTP {response.status_code}"

        if response.status_code == 404:
            raise MarkpostNotFoundError(response.status_code, error_message)
        elif response.status_code in (401, 403):
            raise MarkpostAuthError(response.status_code, error_message)
        else:
            raise MarkpostAPIError(response.status_code, error_message)

    def _store_token(self, token_data):
        """Store token and calculate expiry"""
        self._token = token_data.get("access_token")
        self._refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        self._token_expires_at = time.time() + expires_in

    def login(self, username, password):
        """Authenticate and get JWT token"""
        url = self._build_url("/api/auth/login")
        data = {"username": username, "password": password}

        response = self._session.post(url, json=data)
        result = self._handle_response(response)
        self._store_token(result)
        return result

    def _is_token_expired(self):
        """Check if JWT token is expired or near expiry"""
        if not self._token or not self._token_expires_at:
            return True
        # Consider expired if < 60 seconds remaining
        return time.time() > (self._token_expires_at - 60)

    def refresh_token(self):
        """Refresh JWT token before expiry"""
        url = self._build_url("/api/auth/refresh")
        headers = self._get_headers()

        response = self._session.post(url, headers=headers)
        result = self._handle_response(response)
        self._store_token(result)
        return result

    def _request(self, method, endpoint, **kwargs):
        """Wrapper that handles auth and token refresh"""
        url = self._build_url(endpoint)
        headers = self._get_headers()

        # Merge headers
        if "headers" in kwargs:
            headers.update(kwargs["headers"])
        kwargs["headers"] = headers

        # Make request
        method_func = getattr(self._session, method.lower())
        response = method_func(url, **kwargs)

        # Handle 401 by refreshing token and retrying once
        if response.status_code == 401 and self._refresh_token:
            try:
                self.refresh_token()
                # Update headers with new token
                headers = self._get_headers()
                if "headers" in kwargs:
                    headers.update(kwargs["headers"])
                kwargs["headers"] = headers
                # Retry request
                response = method_func(url, **kwargs)
            except Exception:
                pass  # If refresh fails, let original 401 error propagate

        return self._handle_response(response)

    def change_password(self, current_password, new_password):
        """Change user password"""
        data = {"current_password": current_password, "new_password": new_password}
        return self._request("POST", "/api/auth/change-password", json=data)

    def create_post(self, title, body, post_key=None):
        """Create a new post with markdown content

        Args:
            title: Post title
            body: Markdown content
            post_key: Optional post key (uses stored key if not provided)

        Returns:
            dict with 'id' field (nanoid string)
        """
        key = post_key or self._post_key
        if not key:
            raise ValueError(
                "post_key is required. Call get_post_key() first or provide post_key parameter."
            )

        data = {"title": title, "body": body}
        return self._request("POST", f"/{key}", json=data)

    def get_post(self, post_id, format="html"):
        """Retrieve a post

        Args:
            post_id: Post nanoid
            format: 'html' (default) or 'raw' for markdown

        Returns:
            For HTML: full HTML page (string)
            For raw: dict with post details
        """
        if format == "raw":
            url = self._build_url(f"/{post_id}?format=raw")
            response = self._session.get(url)
            return self._handle_response(response)
        else:
            url = self._build_url(f"/{post_id}")
            response = self._session.get(url)
            if not (200 <= response.status_code < 300):
                self._handle_response(response)  # Will raise error
            return response.text

    def get_posts(self, page=1, page_size=20):
        """List user's posts with pagination

        Args:
            page: Page number (starts at 1)
            page_size: Items per page

        Returns:
            dict with posts list and pagination info
        """
        endpoint = f"/api/posts?page={page}&page_size={page_size}"
        return self._request("GET", endpoint)

    def get_post_key(self):
        """Get current user's post key

        Returns:
            str: The user's post key
        """
        result = self._request("GET", "/api/post_key")
        self._post_key = result.get("post_key")
        return self._post_key
