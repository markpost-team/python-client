# Markpost Python Client

English | [简体中文](README_zh.md)

Python client library for the [Markpost](https://markpost.cc) API.

## Installation

```bash
uv add markpost
```

## Quick Start

```python
import markpost

# Create client and login
client = markpost.Client("http://localhost:7330")
client.login("admin", "changeme")

# Get your post key
post_key = client.get_post_key()
print(f"My post key: {post_key}")

# Create a post
result = client.create_post(
    title="My First Post",
    body="# Hello World\n\nThis is **markdown** content."
)
print(f"Created post: {result['id']}")

# Retrieve the post as HTML
html = client.get_post(result['id'])
print(html)

# Or retrieve as raw markdown
post = client.get_post(result['id'], format="raw")
print(post["title"])
print(post["body"])
```

## Authentication

### Auto-login on initialization

```python
client = markpost.Client(
    base_url="http://localhost:7330",
    username="admin",
    password="changeme"
)
```

### Manual login

```python
client = markpost.Client("http://localhost:7330")
client.login("admin", "changeme")
```

### Token refresh

The client automatically refreshes JWT tokens when they expire or when a 401 response is received.

```python
# Manual refresh (usually not needed)
client.refresh_token()
```

### Change password

```python
client.change_password("old-password", "new-password")
```

## Post Operations

### Create a post

```python
# Using stored post key (call get_post_key() first)
post_key = client.get_post_key()
result = client.create_post(
    title="API Documentation",
    body="## Overview\n\nThis API allows you to..."
)

# Or provide post key explicitly
result = client.create_post(
    title="My Post",
    body="# Content",
    post_key="your-post-key-here"
)
```

### Retrieve a post

```python
# Get as HTML (default)
html = client.get_post("abc123")

# Get as raw markdown/JSON
post = client.get_post("abc123", format="raw")
print(post["qid"])      # "abc123"
print(post["title"])    # Post title
print(post["body"])     # Markdown content
```

### List posts

```python
# Get first page (default: 20 items)
posts = client.get_posts()

# Custom pagination
posts = client.get_posts(page=2, page_size=10)

for post in posts["items"]:
    print(f"{post['qid']}: {post['title']}")
```

## Error Handling

```python
try:
    client.create_post(title="", body="")
except markpost.MarkpostAPIError as e:
    print(f"API Error {e.status_code}: {e.message}")
except markpost.MarkpostAuthError as e:
    print(f"Authentication failed: {e.message}")
except markpost.MarkpostNotFoundError as e:
    print(f"Resource not found: {e.message}")
except markpost.MarkpostConnectionError as e:
    print(f"Connection error: {e}")
```

## Context Manager

```python
with markpost.Client("http://localhost:7330") as client:
    client.login("admin", "password")
    posts = client.get_posts()
# Session is automatically closed
```

## API Reference

### Client

```python
Client(base_url, username=None, password=None)
```

Create a new Markpost client.

**Parameters:**

- `base_url` (str): Markpost server URL (e.g., "http://localhost:7330")
- `username` (str, optional): Username for auto-login
- `password` (str, optional): Password for auto-login

### Authentication Methods

#### `login(username, password)`

Authenticate with username and password. Stores JWT token for subsequent requests.

**Returns:** dict with token information

#### `refresh_token()`

Refresh the JWT token. Usually called automatically.

**Returns:** dict with new token information

#### `change_password(current_password, new_password)`

Change the user's password.

**Returns:** dict with success message

### Post Methods

#### `create_post(title, body, post_key=None)`

Create a new post with markdown content.

**Parameters:**

- `title` (str): Post title
- `body` (str): Markdown content
- `post_key` (str, optional): Post key (uses stored key if not provided)

**Returns:** dict with `id` field (nanoid string)

#### `get_post(post_id, format='html')`

Retrieve a post.

**Parameters:**

- `post_id` (str): Post nanoid
- `format` (str): 'html' (default) or 'raw'

**Returns:**

- For HTML format: string with full HTML page
- For raw format: dict with post details

#### `get_posts(page=1, page_size=20)`

List user's posts with pagination.

**Parameters:**

- `page` (int): Page number (starts at 1)
- `page_size` (int): Items per page

**Returns:** dict with `items` list and `total` count

#### `get_post_key()`

Get the current user's post key. Automatically stored for use in `create_post()`.

**Returns:** str with post key

## Development

### Running Tests

```bash
uv run pytest
```

### Running Linters

```bash
ruff check .
```

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
