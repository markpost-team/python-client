import time
from unittest import mock

import pytest

import markpost


class TestMarkpostClient:
    def test_exception_hierarchy(self):
        """Test that exception classes exist and inherit correctly"""
        assert issubclass(markpost.MarkpostAPIError, markpost.MarkpostError)
        assert issubclass(markpost.MarkpostAuthError, markpost.MarkpostAPIError)
        assert issubclass(markpost.MarkpostNotFoundError, markpost.MarkpostAPIError)
        assert issubclass(markpost.MarkpostConnectionError, markpost.MarkpostError)

    def test_api_error_message(self):
        """Test that MarkpostAPIError formats status code and message"""
        error = markpost.MarkpostAPIError(404, "Post not found")
        assert error.status_code == 404
        assert error.message == "Post not found"
        assert str(error) == "API Error 404: Post not found"

    def test_client_init_with_base_url(self):
        """Test Client initialization with base_url only"""
        client = markpost.Client("http://localhost:7330")
        assert client._base_url == "http://localhost:7330"
        assert client._session is not None
        assert client._username is None
        assert client._password is None

    def test_client_init_with_credentials(self):
        """Test Client initialization with username and password"""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test-token",
            "refresh_token": "test-refresh",
            "expires_in": 3600,
        }

        with mock.patch("requests.Session.post", return_value=mock_response):
            client = markpost.Client(
                "http://localhost:7330", username="admin", password="secret"
            )

        assert client._username == "admin"
        assert client._password == "secret"

    def test_client_strips_trailing_slash(self):
        """Test that trailing slash is removed from base_url"""
        client = markpost.Client("http://localhost:7330/")
        assert client._base_url == "http://localhost:7330"

    def test_context_manager(self):
        """Test that Client works as context manager"""
        with markpost.Client("http://localhost:7330") as client:
            assert client is not None
            assert isinstance(client, markpost.Client)

    def test_auto_login_on_init(self):
        """Test Client auto-logs in when username/password provided"""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "auto-token",
            "refresh_token": "auto-refresh",
            "expires_in": 3600,
        }

        with mock.patch("requests.Session.post", return_value=mock_response):
            client = markpost.Client(
                "http://localhost:7330", username="admin", password="secret"
            )

        assert client._token == "auto-token"
        assert client._token_expires_at is not None


class TestClientInternals:
    def test_build_url(self):
        """Test _build_url creates correct URLs"""
        client = markpost.Client("http://localhost:7330")
        assert client._build_url("/api/posts") == "http://localhost:7330/api/posts"
        assert client._build_url("/health") == "http://localhost:7330/health"

    def test_get_headers_without_token(self):
        """Test _get_headers returns empty dict when no token"""
        client = markpost.Client("http://localhost:7330")
        headers = client._get_headers()
        assert headers == {}

    def test_get_headers_with_token(self):
        """Test _get_headers includes Authorization when token exists"""
        client = markpost.Client("http://localhost:7330")
        client._token = "test-token-123"
        headers = client._get_headers()
        assert headers == {"Authorization": "Bearer test-token-123"}

    def test_handle_response_200(self):
        """Test _handle_response with 200 OK"""
        client = markpost.Client("http://localhost:7330")
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {"id": "abc123"}
        result = client._handle_response(response)
        assert result == {"id": "abc123"}

    def test_handle_response_201(self):
        """Test _handle_response with 201 Created"""
        client = markpost.Client("http://localhost:7330")
        response = mock.Mock()
        response.status_code = 201
        response.json.return_value = {"id": "abc123"}
        result = client._handle_response(response)
        assert result == {"id": "abc123"}

    def test_handle_response_404(self):
        """Test _handle_response raises MarkpostNotFoundError on 404"""
        client = markpost.Client("http://localhost:7330")
        response = mock.Mock()
        response.status_code = 404
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"error": "Post not found"}

        with pytest.raises(markpost.MarkpostNotFoundError) as exc_info:
            client._handle_response(response)

        assert exc_info.value.status_code == 404
        assert exc_info.value.message == "Post not found"

    def test_handle_response_401(self):
        """Test _handle_response raises MarkpostAuthError on 401"""
        client = markpost.Client("http://localhost:7330")
        response = mock.Mock()
        response.status_code = 401
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"error": "Unauthorized"}

        with pytest.raises(markpost.MarkpostAuthError):
            client._handle_response(response)

    def test_handle_response_403(self):
        """Test _handle_response raises MarkpostAuthError on 403"""
        client = markpost.Client("http://localhost:7330")
        response = mock.Mock()
        response.status_code = 403
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"error": "Forbidden"}

        with pytest.raises(markpost.MarkpostAuthError):
            client._handle_response(response)

    def test_handle_response_500(self):
        """Test _handle_response raises MarkpostAPIError on 500"""
        client = markpost.Client("http://localhost:7330")
        response = mock.Mock()
        response.status_code = 500
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"error": "Internal server error"}

        with pytest.raises(markpost.MarkpostAPIError):
            client._handle_response(response)

    def test_login_success(self):
        """Test successful login stores token"""
        client = markpost.Client("http://localhost:7330")

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "expires_in": 3600,
        }

        with mock.patch.object(client._session, "post", return_value=mock_response):
            result = client.login("admin", "password")

        assert client._token == "test-access-token"
        assert client._token_expires_at is not None
        assert result["access_token"] == "test-access-token"

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials raises error"""
        client = markpost.Client("http://localhost:7330")

        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"error": "Invalid credentials"}

        with mock.patch.object(client._session, "post", return_value=mock_response):
            with pytest.raises(markpost.MarkpostAuthError):
                client.login("admin", "wrong-password")

    def test_refresh_token_success(self):
        """Test token refresh updates stored token"""
        client = markpost.Client("http://localhost:7330")
        client._refresh_token = "old-refresh-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

        with mock.patch.object(client._session, "post", return_value=mock_response):
            result = client.refresh_token()

        assert client._token == "new-access-token"
        assert result["access_token"] == "new-access-token"

    def test_is_token_expired_no_token(self):
        """Test _is_token_expired returns True when no token"""
        client = markpost.Client("http://localhost:7330")
        assert client._is_token_expired() is True

    def test_is_token_expired_valid_token(self):
        """Test _is_token_expired returns False when token valid"""
        client = markpost.Client("http://localhost:7330")
        client._token = "test-token"
        client._token_expires_at = time.time() + 3600
        assert client._is_token_expired() is False

    def test_is_token_expired_expired_token(self):
        """Test _is_token_expired returns True when token expired"""
        client = markpost.Client("http://localhost:7330")
        client._token = "test-token"
        client._token_expires_at = time.time() - 100
        assert client._is_token_expired() is True

    def test_request_auto_refresh_on_401(self):
        """Test _request automatically refreshes token on 401"""
        client = markpost.Client("http://localhost:7330")
        client._token = "expired-token"
        client._refresh_token = "refresh-token"

        # First call returns 401
        mock_response_401 = mock.Mock()
        mock_response_401.status_code = 401
        mock_response_401.headers = {"Content-Type": "application/json"}
        mock_response_401.json.return_value = {"error": "Token expired"}

        # Refresh succeeds
        mock_refresh = mock.Mock()
        mock_refresh.status_code = 200
        mock_refresh.json.return_value = {
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

        # Retry succeeds
        mock_response_200 = mock.Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"id": "test"}

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_response_401
            return mock_response_200

        with mock.patch.object(client._session, "get", side_effect=mock_get):
            with mock.patch.object(client._session, "post", return_value=mock_refresh):
                result = client._request("GET", "/api/posts")

        assert result == {"id": "test"}
        assert client._token == "new-token"

    def test_change_password_success(self):
        """Test change_password makes correct API call"""
        client = markpost.Client("http://localhost:7330")
        client._token = "test-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Password changed"}

        with mock.patch.object(
            client._session, "post", return_value=mock_response
        ) as mock_post:
            _ = client.change_password("old-pass", "new-pass")

        # Verify correct endpoint and data
        call_args = mock_post.call_args
        assert "/api/auth/change-password" in call_args[0][0]
        assert call_args[1]["json"] == {
            "current_password": "old-pass",
            "new_password": "new-pass",
        }

    def test_create_post_with_post_key(self):
        """Test create_post uses stored post_key"""
        client = markpost.Client("http://localhost:7330")
        client._post_key = "my-post-key"

        mock_response = mock.Mock()
        mock_response = mock.Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "abc123"}

        with mock.patch.object(
            client._session, "post", return_value=mock_response
        ) as mock_post:
            result = client.create_post("My Title", "# Content")

        assert result == {"id": "abc123"}

        # Verify endpoint uses post_key
        call_url = mock_post.call_args[0][0]
        assert call_url.endswith("/my-post-key")

        # Verify payload
        assert mock_post.call_args[1]["json"] == {
            "title": "My Title",
            "body": "# Content",
        }

    def test_create_post_with_explicit_key(self):
        """Test create_post with explicit post_key parameter"""
        client = markpost.Client("http://localhost:7330")

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "xyz789"}

        with mock.patch.object(
            client._session, "post", return_value=mock_response
        ) as mock_post:
            _ = client.create_post("Title", "Body", post_key="custom-key")

        call_url = mock_post.call_args[0][0]
        assert call_url.endswith("/custom-key")

    def test_get_post_html(self):
        """Test get_post returns HTML by default"""
        client = markpost.Client("http://localhost:7330")

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body><h1>Post</h1></body></html>"

        with mock.patch.object(
            client._session, "get", return_value=mock_response
        ) as mock_get:
            result = client.get_post("abc123")

        assert result == "<html><body><h1>Post</h1></body></html>"
        call_url = mock_get.call_args[0][0]
        assert call_url.endswith("/abc123")

    def test_get_post_raw(self):
        """Test get_post with format='raw' returns JSON"""
        client = markpost.Client("http://localhost:7330")

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 1,
            "qid": "abc123",
            "title": "My Post",
            "body": "# Content",
        }

        with mock.patch.object(
            client._session, "get", return_value=mock_response
        ) as mock_get:
            result = client.get_post("abc123", format="raw")

        assert result["title"] == "My Post"
        call_url = mock_get.call_args[0][0]
        assert "format=raw" in call_url

    def test_get_post_not_found(self):
        """Test get_post raises MarkpostNotFoundError on 404"""
        client = markpost.Client("http://localhost:7330")

        mock_response = mock.Mock()
        mock_response.status_code = 404
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"error": "Post not found"}

        with mock.patch.object(client._session, "get", return_value=mock_response):
            with pytest.raises(markpost.MarkpostNotFoundError):
                client.get_post("nonexistent")

    def test_get_posts_default_pagination(self):
        """Test get_posts with default pagination"""
        client = markpost.Client("http://localhost:7330")
        client._token = "test-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {"qid": "abc1", "title": "Post 1"},
                {"qid": "abc2", "title": "Post 2"},
            ],
            "total": 2,
        }

        with mock.patch.object(
            client._session, "get", return_value=mock_response
        ) as mock_get:
            result = client.get_posts()

        assert len(result["items"]) == 2
        call_url = mock_get.call_args[0][0]
        assert "page=1" in call_url
        assert "page_size=20" in call_url

    def test_get_posts_custom_pagination(self):
        """Test get_posts with custom page and page_size"""
        client = markpost.Client("http://localhost:7330")
        client._token = "test-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": [], "total": 0}

        with mock.patch.object(
            client._session, "get", return_value=mock_response
        ) as mock_get:
            _ = client.get_posts(page=2, page_size=10)

        call_url = mock_get.call_args[0][0]
        assert "page=2" in call_url
        assert "page_size=10" in call_url

    def test_get_post_key(self):
        """Test get_post_key retrieves and stores user's post key"""
        client = markpost.Client("http://localhost:7330")
        client._token = "test-token"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"post_key": "my-secret-key"}

        with mock.patch.object(
            client._session, "get", return_value=mock_response
        ) as mock_get:
            result = client.get_post_key()

        assert result == "my-secret-key"
        assert client._post_key == "my-secret-key"

        call_url = mock_get.call_args[0][0]
        assert call_url.endswith("/api/post_key")
