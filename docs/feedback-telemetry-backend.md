# 反馈与遥测 — 后端参考

> 面向开发者的后端结构、数据表、API 及运维操作文档。

## 架构概览

```
┌─────────────────────────────────────┐
│  Cloudflare Worker                  │
│  siyuan-bridge-telemetry            │
│  siyuan-bridge-telemetry            │
│      .864271839.workers.dev         │
│                                     │
│  POST /api/telemetry   → events     │
│  POST /api/feedback    → feedbacks  │
│  GET  /api/notifications ← notifications │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  D1: siyuan_bridge                  │
│  (142b11e4-52a9-4050-bbaf-...)     │
│                                     │
│  ┌─ events                           │
│  ├─ feedbacks                        │
│  └─ notifications                    │
└─────────────────────────────────────┘
```

**调用方：**

| 调用方 | 端点 | 说明 |
|--------|------|------|
| 插件前端 JS | `POST /api/feedback`, `GET /api/notifications` | 用户在思源笔记内提交反馈、查看通知 |
| Python `telemetry.py` | `POST /api/telemetry`, `POST /api/feedback` | MCP 工具调用时 fire-and-forget 上传遥测；`siyuan_bridge_feedback` 提交反馈 |

---

## 账号与域名

| 项 | 值 |
|----|-----|
| Cloudflare 账号 | alone-tree（推测，基于 repo owner） |
| Worker 名称 | `siyuan-bridge-telemetry` |
| Worker 域名 | `siyuan-bridge-telemetry.864271839.workers.dev` |
| D1 数据库名 | `siyuan_bridge` |
| D1 database_id | `142b11e4-52a9-4050-bbaf-073433b52c70` |
| 配置目录 | `worker/` |

> **注意：** `.workers.dev` 域名在中国大陆被 DNS 污染且 IP 被阻断。用户需通过代理（Clash/V2Ray 系统代理，或 TUN 模式）访问。Python 端 `_resolve_proxy()` 自动探测代理，前端 JS 走浏览器代理设置。

Worker 端点**无需认证**——所有 3 个 API 均为公开访问。

---

## API 端点

### POST /api/telemetry — 写入遥测事件

- **用途**：Python 端在每次 MCP 工具调用后 fire-and-forget 上传事件
- **Content-Type**: `application/json`
- **Body**：单条事件对象或事件数组

```json
[
  {
    "ts": "2026-06-07T05:00:00.000Z",
    "anonymous_id": "a1b2c3d4e5f6...",
    "platform": "Windows",
    "siyuan_ver": "3.6.5",
    "mcp_ver": "0.3.0",
    "session_id": "x1y2z3...",
    "tool": "siyuan_read",
    "action": null,
    "ok": 1,
    "error_type": null,
    "dur_ms": 42
  }
]
```

- **成功响应** (200): `{"ok": true, "count": 1}`
- **失败响应** (400): `{"ok": false, "error": "invalid payload"}`

### POST /api/feedback — 提交反馈

- **用途**：前端反馈表单、`siyuan_bridge_feedback` MCP 工具
- **Content-Type**: `application/json`
- **Body**：

```json
{
  "type": "bug",
  "title": "前端手动测试",
  "description": "反馈内容...",
  "contact": "邮箱或联系方式（可选）"
}
```

- `type` 必填，取值：`bug` / `feature` / `idea`
- `title`、`description` 必填
- `contact` 可选

- **成功响应** (200): `{"ok": true}`
- **失败响应** (400): `{"ok": false, "error": "missing required fields"}`

### GET /api/notifications — 通知列表

- **用途**：前端首页加载通知
- **响应** (200):

```json
{
  "notifications": [
    {"id": "v0.3.0", "title": "思源桥 v0.3.0 已发布", "url": "https://github.com/..."}
  ]
}
```

- 无通知或查询失败时返回 `{"notifications": []}`
- 通知数据由维护者在 D1 `notifications` 表中手动管理

---

## D1 数据库表结构

### `events` — 遥测事件

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | TEXT | ISO 8601 UTC 时间戳 |
| `anonymous_id` | TEXT | 匿名设备 ID（uuid4 hex） |
| `platform` | TEXT | 操作系统：Windows / Darwin / Linux |
| `siyuan_ver` | TEXT (nullable) | 思源版本号 |
| `mcp_ver` | TEXT (nullable) | Bridge 版本号 |
| `session_id` | TEXT (nullable) | MCP server 进程会话 ID |
| `tool` | TEXT | MCP 工具名 |
| `action` | TEXT (nullable) | 子操作（如 edit、create 的 action 参数） |
| `ok` | INTEGER | 1=成功, 0=失败 |
| `error_type` | TEXT (nullable) | 异常类名（失败时） |
| `dur_ms` | INTEGER (nullable) | 耗时（毫秒） |

### `feedbacks` — 用户反馈

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `ts` | TEXT | ISO 8601 UTC 时间戳 |
| `type` | TEXT | bug / feature / idea |
| `title` | TEXT | 反馈标题 |
| `description` | TEXT | 反馈内容 |
| `contact` | TEXT (nullable) | 联系方式 |

### `notifications` — 通知消息

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键（如版本号） |
| `title` | TEXT | 通知标题 |
| `url` | TEXT | 点击跳转链接 |
| `created_at` | TEXT | 创建时间 |

---

## 连接方式

### 前端 JS → Worker

插件前端 `index.js` 中硬编码默认端点，通过 `getEffectiveEndpoint()` 解析：

```javascript
const DEFAULT_ENDPOINT = "https://siyuan-bridge-telemetry.864271839.workers.dev";

async function getEffectiveEndpoint() {
  try {
    const text = await getFile(TELEMETRY_PATH);    // 读 telemetry.json
    const cfg = JSON.parse(text);
    if (cfg && cfg.telemetry_endpoint) return cfg.telemetry_endpoint;
  } catch (_) {}
  return DEFAULT_ENDPOINT;                          // 兜底
}
```

- 通知：`fetch(GET ${endpoint}/api/notifications)`
- 反馈：`fetch(POST ${endpoint}/api/feedback, {body: ...})`
- 不直接调用遥测上传（由 Python 端负责）

### Python → Worker

`source_code/telemetry.py` 中硬编码默认端点，通过 `get_effective_endpoint()` 解析（与前端同名但独立实现）：

```python
DEFAULT_ENDPOINT = "https://siyuan-bridge-telemetry.864271839.workers.dev"

def get_effective_endpoint(root: Path) -> str:
    cfg = load_telemetry_config(root)
    explicit = str(cfg.get("telemetry_endpoint", "")).strip()
    return explicit if explicit else DEFAULT_ENDPOINT
```

- 遥测上传：`_fire_upload(endpoint, proxy, event)` → `POST /api/telemetry`
- 反馈提交：`submit_feedback(endpoint, proxy, payload)` → `POST /api/feedback`
- 使用 `urllib.request` + `ProxyHandler`，代理从 `_resolve_proxy()` 自动探测

### 代理探测（Python 端）

优先级：
1. `telemetry.json` 中显式 `proxy` 字段
2. 环境变量 `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`
3. 系统代理（`urllib.request.getproxies()`）
4. 以上都没有则直连

---

## 开发者运维

### 前置条件

1. 安装 [Node.js](https://nodejs.org/)（包含 npx）
2. 登录 Cloudflare 账号：`npx wrangler login`
3. 在 `worker/` 目录下操作（含 `wrangler.toml`）

### 查询远端数据库

```bash
cd worker

# 查询反馈列表（最新 5 条）
npx wrangler d1 execute siyuan_bridge --remote \
  --command "SELECT * FROM feedbacks ORDER BY ts DESC LIMIT 5;"

# 查询遥测事件
npx wrangler d1 execute siyuan_bridge --remote \
  --command "SELECT ts, tool, action, ok, dur_ms FROM events ORDER BY ts DESC LIMIT 20;"

# 按工具统计成功率
npx wrangler d1 execute siyuan_bridge --remote \
  --command "SELECT tool, COUNT(*) as n, SUM(ok) as successes FROM events GROUP BY tool;"

# 查询通知列表
npx wrangler d1 execute siyuan_bridge --remote \
  --command "SELECT * FROM notifications ORDER BY created_at DESC;"
```

`--remote` 是必须的，不加会读取本地空的 SQLite 副本。

### 添加通知

```bash
npx wrangler d1 execute siyuan_bridge --remote \
  --command "INSERT INTO notifications (id, title, url, created_at) VALUES ('v0.3.0', '思源桥 v0.3.0 已发布', 'https://github.com/alone-tree/siyuan-bridge/releases', '2026-06-07T00:00:00Z');"
```

### 部署 Worker

```bash
cd worker
npx wrangler deploy
```

### 表结构迁移

当前 Worker 代码中没有自动建表逻辑（表是通过 D1 dashboard 或 `wrangler d1 execute` 手动创建的）。如需初始化表：

```sql
CREATE TABLE IF NOT EXISTS events (
  ts TEXT NOT NULL,
  anonymous_id TEXT NOT NULL,
  platform TEXT,
  siyuan_ver TEXT,
  mcp_ver TEXT,
  session_id TEXT,
  tool TEXT NOT NULL,
  action TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  error_type TEXT,
  dur_ms INTEGER
);

CREATE TABLE IF NOT EXISTS feedbacks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  contact TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

---

## 相关文档

- [遥测与反馈功能设计](./telemetry-design.md)
- [插件前端设计](./plugin-frontend-design.md)
- [架构文档](./ARCHITECTURE.md)
- [开发指南](./DEVELOPMENT_GUIDE.md)
