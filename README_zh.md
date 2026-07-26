[English](README.md) | 简体中文

<div align="center">

# Markpost Python 客户端

**[Markpost](https://markpost.cc) API 的类型化 Python 客户端，提供同步与异步两套 API。**

[![PyPI version](https://img.shields.io/pypi/v/markpost.svg)](https://pypi.org/project/markpost/)
[![Python versions](https://img.shields.io/pypi/pyversions/markpost.svg)](https://pypi.org/project/markpost/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE.txt)
[![CI](https://img.shields.io/github/actions/workflow/status/markpost-team/python-client/ci.yml?label=CI)](https://github.com/markpost-team/python-client/actions/workflows/ci.yml)

</div>

---

## 安装

> 需要 Python **>=3.10**。

```bash
uv add markpost
# 或
pip install markpost
```

## 快速开始

### 同步

```python
from markpost import Markpost

with Markpost("https://markpost.cc", "alice", "secret") as client:
    created = client.create_post("你好", "# 用 **markdown** 写正文")
    print(created.id)           # "p-<nanoid>"

    html = client.get_post(created.id)               # 完整 HTML 页面（str）
    md = client.get_post(created.id, format="raw")   # "# 你好\n\n..."（str）

    page = client.list_posts(limit=20)
    for item in page.items:
        print(item.qid, item.title)
```

### 异步

```python
from markpost import AsyncMarkpost

async with AsyncMarkpost("https://markpost.cc", "alice", "secret") as client:
    created = await client.create_post("你好", "# 正文")
    html = await client.get_post(created.id)
    page = await client.list_posts(limit=20)
```

## 认证

构造时传入 `username` + `password` 即自动登录（同步立即登录；异步在首次调用
或 `__aenter__` 时延迟登录）：

```python
client = Markpost("https://markpost.cc", username="alice", password="secret")
```

或手动登录：

```python
client = Markpost("https://markpost.cc")
result = client.login("alice", "secret")
print(result.user.role, result.token)
```

access token **即将过期**或后端返回 `401` 时会**自动刷新**。并发的刷新会被
合并为一次后端调用（单飞），因为后端的 refresh token 是一次性轮转的，重用会
被检测并吊销整个会话。

## 文章

`create_post` 使用 **post_key** 认证（而非 JWT）。若不传入，客户端会自动获取
并缓存你的 post key：

```python
created = client.create_post("标题", "正文")               # 自动获取 post key
created = client.create_post("标题", "正文", post_key="mpk-...")
```

`get_post` 返回 `str`（默认 HTML，`format="raw"` 时为 markdown）。支持
`If-None-Match` 条件请求：

```python
etag = "...上一次响应的 ETag..."
result = client.get_post("p-abc", if_none_match=etag)
# 后端返回 304（未修改）时 result 为 None
```

分页为扁平结构：

```python
page = client.list_posts(page=2, limit=50)
# page.items, page.total, page.page, page.limit, page.total_pages
```

## 投递渠道与历史

```python
ch = client.create_channel(
    kind="feishu",
    name="运维告警",
    configuration={"webhook_url": "https://...", "card_link_url": "https://..."},
    keywords="",  # 可选的关键词过滤表达式
)

# PATCH 语义：只传你想改的字段。
client.update_channel(ch.id, enabled=False)

channels = client.list_channels()                        # list[Channel]（无分页）
history = client.list_delivery_history(channel_id=ch.id)  # Page[DeliveryHistoryItem]
latest = client.list_latest_delivery()                   # list[DeliveryHistoryItem]，每个渠道一条

# 发送一张诊断卡片，验证 webhook 配置是否正确。即发即弃：
# 后端同步发送，但不会写入 delivery_history 记录。
client.test_channel(ch.id)
```

## 错误处理

错误是一个以 `MarkpostError` 为根的类型化层级：

```python
from markpost import (
    MarkpostError, APIError,
    BadRequestError, AuthenticationError, PermissionDeniedError,
    NotFoundError, ConflictError, UnprocessableEntityError, RateLimitError,
    InternalServerError, APITimeoutError, APIConnectionError,
)

try:
    client.create_post("", "正文")
except UnprocessableEntityError as e:
    print(e.status_code, e.code)   # 422 "title_too_long" / "required" / ...
    for fe in e.errors:            # 解析后的字段级错误
        print(fe.field, fe.code, fe.message)
except RateLimitError as e:
    print(e.limit, e.remaining, e.reset)   # 从 RateLimit-* 头解析
except AuthenticationError as e:
    print(e.code)                  # "invalid_credentials"、"invalid_token" 等
except APIError as e:
    print(e.status_code, e.code, e.message)
```

超时与网络错误映射为 `APITimeoutError` / `APIConnectionError`（均自动重试）。
`5xx` 与 `429` 会重试；`4xx` 不会。

## 配置

```python
Markpost(
    base_url,
    username=None,
    password=None,
    *,
    timeout=None,             # float | httpx.Timeout（默认为安全的连接/读/写/池分配）
    max_retries=2,             # 0 表示禁用重试
    post_key=None,             # 预置 post key
    http_client=None,          # 注入自定义 httpx client（测试用）
    verify=True,               # e2e 自签证书容器需设为 False
)
```

## 许可证

MIT License —— 见 [LICENSE.txt](LICENSE.txt)。
