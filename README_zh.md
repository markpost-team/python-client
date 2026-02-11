# Markpost Python 客户端

[English](README.md) | 简体中文

[Markpost](https://markpost.cc) API 的 Python 客户端库。

## 安装

```bash
uv add markpost
```

## 快速开始

```python
import markpost

# 创建客户端并登录
client = markpost.Client("http://localhost:7330")
client.login("admin", "changeme")

# 获取您的Post密钥
post_key = client.get_post_key()
print(f"我的Post密钥: {post_key}")

# 创建一篇Post
result = client.create_post(
    title="我的第一篇Post",
    body="# 你好世界\n\n这是 **markdown** 内容。"
)
print(f"创建Post: {result['id']}")

# 以 HTML 格式获取Post
html = client.get_post(result['id'])
print(html)

# 或以原始 markdown 格式获取
post = client.get_post(result['id'], format="raw")
print(post["title"])
print(post["body"])
```

## 认证

### 初始化时自动登录

```python
client = markpost.Client(
    base_url="http://localhost:7330",
    username="admin",
    password="changeme"
)
```

### 手动登录

```python
client = markpost.Client("http://localhost:7330")
client.login("admin", "changeme")
```

### 令牌刷新

客户端会在 JWT 令牌过期或收到 401 响应时自动刷新令牌。

```python
# 手动刷新（通常不需要）
client.refresh_token()
```

### 修改密码

```python
client.change_password("旧密码", "新密码")
```

## Post操作

### 创建Post

```python
# 使用存储的Post密钥（先调用 get_post_key()）
post_key = client.get_post_key()
result = client.create_post(
    title="API 文档",
    body="## 概述\n\n此 API 允许您..."
)

# 或显式提供Post密钥
result = client.create_post(
    title="我的Post",
    body="# 内容",
    post_key="your-post-key-here"
)
```

### 获取Post

```python
# 获取为 HTML（默认）
html = client.get_post("abc123")

# 获取为原始 markdown/JSON
post = client.get_post("abc123", format="raw")
print(post["qid"])      # "abc123"
print(post["title"])    # Post标题
print(post["body"])     # Markdown 内容
```

### 列出Post

```python
# 获取第一页（默认：20 条）
posts = client.get_posts()

# 自定义分页
posts = client.get_posts(page=2, page_size=10)

for post in posts["items"]:
    print(f"{post['qid']}: {post['title']}")
```

## 错误处理

```python
try:
    client.create_post(title="", body="")
except markpost.MarkpostAPIError as e:
    print(f"API 错误 {e.status_code}: {e.message}")
except markpost.MarkpostAuthError as e:
    print(f"认证失败: {e.message}")
except markpost.MarkpostNotFoundError as e:
    print(f"资源未找到: {e.message}")
except markpost.MarkpostConnectionError as e:
    print(f"连接错误: {e}")
```

## 上下文管理器

```python
with markpost.Client("http://localhost:7330") as client:
    client.login("admin", "password")
    posts = client.get_posts()
# 会话自动关闭
```

## API 参考

### Client

```python
Client(base_url, username=None, password=None)
```

创建一个新的 Markpost 客户端。

**参数：**

- `base_url` (str): Markpost 服务器 URL（例如 "http://localhost:7330"）
- `username` (str, 可选): 用于自动登录的用户名
- `password` (str, 可选): 用于自动登录的密码

### 认证方法

#### `login(username, password)`

使用用户名和密码进行认证。存储 JWT 令牌用于后续请求。

**返回值：** 包含令牌信息的字典

#### `refresh_token()`

刷新 JWT 令牌。通常会自动调用。

**返回值：** 包含新令牌信息的字典

#### `change_password(current_password, new_password)`

修改用户密码。

**返回值：** 包含成功消息的字典

### Post方法

#### `create_post(title, body, post_key=None)`

创建一篇包含 markdown 内容的新Post。

**参数：**

- `title` (str): Post标题
- `body` (str): Markdown 内容
- `post_key` (str, 可选): Post密钥（如未提供则使用存储的密钥）

**返回值：** 包含 `id` 字段的字典（nanoid 字符串）

#### `get_post(post_id, format='html')`

获取一篇Post。

**参数：**

- `post_id` (str): Post nanoid
- `format` (str): 'html'（默认）或 'raw'

**返回值：**

- HTML 格式：包含完整 HTML 页面的字符串
- 原始格式：包含Post详情的字典

#### `get_posts(page=1, page_size=20)`

列出用户的Post并支持分页。

**参数：**

- `page` (int): 页码（从 1 开始）
- `page_size` (int): 每页条目数

**返回值：** 包含 `items` 列表和 `total` 计数的字典

#### `get_post_key()`

获取当前用户的Post密钥。自动存储以便在 `create_post()` 中使用。

**返回值：** 包含Post密钥的字符串

## 开发

### 运行测试

```bash
uv run pytest
```

### 运行代码检查

```bash
ruff check .
```

## 许可证

MIT 许可证

## 贡献

欢迎贡献！请随时提交 Pull Request。
