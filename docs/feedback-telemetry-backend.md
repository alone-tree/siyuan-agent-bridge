# 反馈与遥测 — 后端参考

> 面向开发者的后端结构、数据表、API 及运维操作文档。

## 架构概览

```
┌─────────────────────────────────────┐
│  Cloudflare Worker                  │
│  siyuan-bridge-telemetry            │
│  siyuanbridgetelemetry              │
│      .zingerplayground.top          │
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
| Python `telemetry.py` | `POST /api/telemetry`, `POST /api/feedback` | MCP 工具调用时 fire-and-forget 上传遥测（可选择在本地保留副本）；`siyuan_bridge_feedback` 提交反馈 |

---

## 账号与域名

| 项 | 值 |
|----|-----|
| Cloudflare 账号 | alone-tree（推测，基于 repo owner） |
| Worker 名称 | `siyuan-bridge-telemetry` |
| Worker 域名 | `siyuanbridgetelemetry.zingerplayground.top` |
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
| `error_type` | TEXT (nullable) | 错误码（失败时），`category:detail` 两级编码，详见错误码参考 |
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

## 遥测错误码参考

`error_type` 字段采用 `category:detail` 两级编码。**category** 用于聚合看板，**detail** 用于下钻诊断。

失败时优先取异常对象上的 `error_code` 属性；若不存在则退回到 Python 异常类名（如 `SiYuanConnectionError`、`FileNotFoundError`）。

### 错误码总览

#### validation — AI 传参错误

参数无效、缺失、类型错误或语义冲突，通常意味着 AI 对工具的理解有偏差，需要改进工具描述或 prompt。

| error_type | 触发场景 |
|------------|----------|
| `validation:missing_param` | 必填参数为空（keyword / title / markdown / document / action / new_title / target_parent / target_path / table_edit 对象等） |
| `validation:invalid_enum` | 枚举参数取值不在允许列表中（mode / scope / if_exists / action / type / table_edit.operation 等） |
| `validation:invalid_type` | 参数类型错误（start_index 非整数、cell 非对象、cells 非数组、values 非数组） |
| `validation:out_of_range` | 数值越界（row / column_index / block 索引超出范围） |
| `validation:wrong_shape` | 操作与目标块数量不匹配（single_block_replace 选了多个块、table_edit 选了多个块、markdown 会拆成多块） |
| `validation:wrong_target_type` | 操作作用在不支持的块类型上（table_edit 用在非 table 块、replace 用在不支持复杂块类型上） |
| `validation:invalid_table` | Markdown 表格格式无法解析（缺表头或分隔行） |
| `validation:operation_order` | 操作顺序违反语义约束（在表头前插入数据行、删除最后一列、start_index > end_index） |
| `validation:mismatch` | 多个参数不一致（path 中的笔记本名称与 notebook_id 不匹配） |
| `validation:missing_edit_range` | 编辑操作缺少块定位参数（start_index/start_id 或 end_index/end_id） |

#### permission — 权限不足或未确认

用户设置的隐私规则限制了对特定文档/笔记本的访问，或 AI 未取得用户确认。

| error_type | 触发场景 |
|------------|----------|
| `permission:not_confirmed` | confirmed=false，未取得用户明确确认 |
| `permission:not_read_write` | 目标文档/路径的权限不是 read_write，不允许写入 |
| `permission:privacy_rules` | 尝试访问 Privacy Rules 文档（该文档属于人类，AI 不可读写） |
| `permission:sql_admin` | SQL 搜索需要思源管理员权限 |
| `permission:subtree_blocked` | delete 操作的目标子树中含有只读或隐藏文档 |
| `permission:ancestor_blocked` | move 操作的源文档祖先路径中有非 read_write 节点 |

#### not_found — 目标不存在

指定的文档、笔记本、路径或块引用在索引中不存在。

| error_type | 触发场景 |
|------------|----------|
| `not_found:document` | 文档路径在索引中不存在，可能被隐藏、未索引或定位符有误 |
| `not_found:notebook` | 笔记本名称/ID 在可见笔记本列表中未匹配到 |
| `not_found:parent` | move/copy 的 target_parent 不存在 |
| `not_found:block_index` | start_index/end_index 在当前文档中不存在（文档可能已变化） |

#### conflict — 状态不一致

请求与当前文档状态之间存在冲突，通常需要 AI 重新读取后再操作。

| error_type | 触发场景 |
|------------|----------|
| `conflict:already_exists` | 目标文档/路径已存在（create 时 if_exists=reject，或 copy 时目标已存在） |
| `conflict:ambiguous_path` | 文档路径/笔记本名称存在歧义，匹配到多个结果 |
| `conflict:stale_block_id` | 引用的块 ID 与当前文档中该位置的块 ID 不匹配（索引过期） |
| `conflict:stale_cell_value` | table_edit 的 expected_old_value 与当前单元格值不匹配（索引过期） |
| `conflict:multi_doc_overwrite` | 目标路径下有多个同名文档且 if_exists=overwrite，无法确定保留哪个文档 ID |

#### api — 思源 API 层错误

思源服务端返回的错误，非 AI 能直接修复。

| error_type | 触发场景 |
|------------|----------|
| `api:snapshot_key` | 数据仓库密钥未初始化，无法创建快照 |
| `api:snapshot_failed` | 快照创建因其他原因失败 |
| `api:duplicate_no_id` | duplicateDoc 操作未返回新文档 ID |

#### 类名兜底

以下异常没有 `error_code` 属性，遥测直接记录 Python 类名：

| 类名 | 含义 |
|------|------|
| `SiYuanConnectionError` | 无法连接思源（未启动、端口不对、Token 不可用） |
| `SiYuanApiError` | 思源 API 返回的错误（由 client.py 直接抛出，未经 tool_error 转换） |
| `FileNotFoundError` | siyuan_list 中路径完全不存在且无子孙文档 |
| `RuntimeError` | 系统笔记本创建失败等内部错误 |

### 典型遥测查询

```sql
-- 看板：按大类聚合错误率
SELECT
  tool,
  CASE
    WHEN error_type LIKE 'validation:%' THEN 'validation'
    WHEN error_type LIKE 'permission:%' THEN 'permission'
    WHEN error_type LIKE 'not_found:%' THEN 'not_found'
    WHEN error_type LIKE 'conflict:%' THEN 'conflict'
    WHEN error_type LIKE 'api:%' THEN 'api'
    ELSE error_type
  END AS category,
  COUNT(*) AS n
FROM events
WHERE ok = 0
GROUP BY tool, category
ORDER BY tool, n DESC;

-- 下钻：validation 类中具体哪种错误最多
SELECT tool, action, error_type, COUNT(*) AS n
FROM events
WHERE ok = 0 AND error_type LIKE 'validation:%'
GROUP BY tool, action, error_type
ORDER BY n DESC
LIMIT 20;

-- 某个工具的全部失败细节
SELECT ts, action, error_type, dur_ms
FROM events
WHERE tool = 'siyuan_edit' AND ok = 0
ORDER BY ts DESC
LIMIT 20;
```

---

## 连接方式

### 前端 JS → Worker

插件前端 `index.js` 中硬编码默认端点，通过 `getEffectiveEndpoint()` 解析：

```javascript
const DEFAULT_ENDPOINT = "https://siyuanbridgetelemetry.zingerplayground.top";

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
DEFAULT_ENDPOINT = "https://siyuanbridgetelemetry.zingerplayground.top"

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
