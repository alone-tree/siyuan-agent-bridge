# 遥测与反馈系统设计（未实现）

> 整合自 `docs/telemetry-design.md` 和 `docs/plugin-frontend-design.md` 中的反馈/MCP工具部分。
> 前端页面设计保留在 `docs/plugin-frontend-design.md`，本文档聚焦后端系统。

## 关联文档

- 前端页面设计：`docs/plugin-frontend-design.md`
- 架构参考：`docs/ARCHITECTURE.md`
- 开发日志（历史讨论）：`docs/devlog.md`

---

## 动机

了解用户如何使用思源桥：哪些工具最常用、哪些报错最多、哪些操作最慢。同时为愿意反馈的用户提供便捷的反馈渠道（包括前端表单和 MCP 对话内提交）。

这两个需求共享同一个远端基础设施（CF Worker + D1），因此合并为一个统一的「遥测与反馈」系统。

## 设计原则

### 遥测

- 只收集元数据，不收集内容
- Fire-and-forget，不阻塞工具调用，用户无感知
- 发不出去就丢弃，不影响用户体验
- Opt-in，默认关闭
- 数据不保存在思源笔记本中

### 反馈

- 反馈内容由用户或 AI 主动提交，不属于自动遥测
- 前端表单和 MCP 工具两种提交渠道，共用同一个 Worker 端点和 D1 表
- 反馈可能包含用户描述的文字内容，需要声明告知用户

## 概念区分

| 概念 | 来源 | 含义 |
|------|------|------|
| **索引统计** | `indexer.py` → `docs.jsonl` | 思源文档的 `block_count`、`char_count`、`word_count` 等元数据 |
| **遥测统计** | `telemetry.py` → `stats/` → D1 `events` | MCP 工具调用的次数、耗时、错误率等使用行为数据 |

两个概念在中文中都叫「统计」，但含义完全不同。本文档中的「统计」均指遥测统计。索引统计保持原有概念不变。

---

## 数据范围

### 遥测（自动收集）

收集：

- 时间戳
- 匿名用户 ID（UUID，本地生成，和任何身份信息无关）
- 系统平台（Windows / Darwin / Linux，来自 `platform.system()`）
- 思源版本（启动时从 `/api/system/version` 获取）
- MCP 版本（项目 `__version__`）
- 会话 ID（每次 MCP 进程启动时生成，用于聚合一次对话内的连续调用）
- 工具名（`siyuan_read`、`siyuan_create` 等）
- Action 名（`siyuan_edit` 的 `single_block_replace`、`siyuan_create` 的 `overwrite` 等子操作）
- 是否成功
- 报错类型（如果失败，只记预定义的错误码或异常类名，不记消息内容）
- 耗时毫秒

不收集：

- 文档路径、标题、内容、笔记本名称
- 搜索关键词
- 参数值
- API Token、配置值
- 用户 IP、系统用户名、主机名
- 应用层异常详情、堆栈跟踪

### 反馈（主动提交）

收集（由用户或 AI 填写）：

- 时间戳
- 反馈类型（bug / feature / idea）
- 标题
- 描述
- 联系方式（可选）

---

## 架构

```
用户本地环境                              远端

+-----------------------------+       +----------------------------+
| siyuan-bridge (MCP)          |       | CF Worker                  |
|                             |       |                            |
| telemetry.py ── POST ──────┼──────>│ /api/telemetry ──> D1      |
|   (工具装饰器自动采集)       |       |                            |
|                             |       | /api/feedback  ──> D1      |
| mcp_server.py               |       |                            |
|   siyuan_bridge_feedback 工具 ── POST ────>│ /api/notifications <── D1  |
|                             |       |                            |
| siyuan-plugin/              |       +----------------------------+
|   首页表单 ──── POST ───────┼──────>│ /api/feedback               |
|   首页通知 ──── GET ────────┼──────>│ /api/notifications         |
+-----------------------------+       +----------------------------+
```

**Python 端**：在每个工具实现外层包一个装饰器，统一测量时间、捕获结果、组装遥测事件。事件 POST 到配置的端点。成功失败都不影响工具本身的返回值。

**插件前端**：首页提供反馈表单和通知拉取，通过 JS fetch 直接与 Worker 通信。

**Server 端**：CF Worker 接收请求后写入 D1 数据库对应表。Worker 不做数据处理，只做简单读写。

---

## 配置设计

### 独立配置文件

遥测与反馈的配置字段与 `config.local.json`（profiles、token、language）完全不同。为避免同一文档中字段混淆，使用独立的配置文件。

**文件路径**：`bridge/telemetry.json`（与 `config.local.json` 同级，位于运行目录下）

**初始状态**：文件不存在 = 遥测完全关闭。用户在插件设置页或手动创建文件来开启。

```json
{
  "telemetry": "off",
  "telemetry_endpoint": "",
  "proxy": ""
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `telemetry` | `"off"` \| `"local"` \| `"upload"` | `"off"` | 遥测模式 |
| `telemetry_endpoint` | string | `""` | 远端端点地址。`upload` 模式下可选；不填则使用项目默认端点 |
| `proxy` | string | `""` | HTTP 代理地址。为空时自动探测环境变量和系统代理。示例：`http://127.0.0.1:7897` |

### 模式行为

| mode | 本地写入 `stats/` | 上传到远端 | 性能开销 |
|------|:---:|:---:|:---:|
| `off`（默认） | 否 | 否 | 无 |
| `local` | 是 | 否 | 极小（JSONL append） |
| `upload` | 是 | 是 | 小（本地写入 + fire-and-forget POST） |

### 与 `config.local.json` 的关系

| 文件 | 用途 | 内容 |
|------|------|------|
| `config.local.json` | 思源连接配置 | `profiles`（name/url/token）、`language` |
| `telemetry.json` | 遥测与反馈配置 | `telemetry`、`telemetry_endpoint` |

两个文件互不引用，独立加载。`telemetry.json` 不存在时，遥测系统静默不启动（等价于 `off`）。

两个文件都 Git 忽略，都不打包进 ZIP。

### 隐私声明

- telemetry 默认关闭，用户需主动在插件设置页或手动创建 `telemetry.json` 来开启
- 在系统笔记本的 AI Guide 和 About 文档中说明遥测与反馈系统的存在和所收集的数据范围
- 匿名 ID 完全随机，与用户的 GitHub、邮箱、系统用户名无关
- 用户可随时删除 `stats/` 目录或重置 ID
- 远端不收集用户 IP（Workers 默认不会记录客户端 IP，D1 也不存储）

---

## 本地数据

当 telemetry 为 `local` 或 `upload` 时，遥测数据同时写入本地 `stats/` 目录：

```
bridge/stats/
  telemetry_id          匿名用户 UUID，首次自动生成，永不变化
  events/
    2026-06-06.jsonl    每天一个文件，JSONL 格式
```

本地文件用于数据备份和用户自查。

---

## 远端数据（D1 表结构）

### 表 1：遥测事件 `events`

```sql
CREATE TABLE events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           TEXT NOT NULL,         -- ISO 8601
  anonymous_id TEXT NOT NULL,
  platform     TEXT,                  -- Windows / Darwin / Linux
  siyuan_ver   TEXT,                  -- 思源版本号
  mcp_ver      TEXT,                  -- MCP 版本号
  session_id   TEXT,                  -- 会话 ID
  tool         TEXT NOT NULL,         -- 工具名
  action       TEXT,                  -- 子操作
  ok           INTEGER NOT NULL,      -- 1 成功 0 失败
  error_type   TEXT,                  -- 错误类型（预定义错误码或异常类名）
  dur_ms       INTEGER                -- 耗时毫秒
);

CREATE INDEX idx_events_date ON events(ts);
CREATE INDEX idx_events_tool ON events(tool);
CREATE INDEX idx_events_anon ON events(anonymous_id);
```

### 表 2：用户反馈 `feedbacks`

```sql
CREATE TABLE feedbacks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL,          -- ISO 8601
  type        TEXT NOT NULL,          -- bug / feature / idea
  title       TEXT NOT NULL,
  description TEXT NOT NULL,
  contact     TEXT                    -- 联系方式（可选）
);
```

### 表 3：通知 `notifications`

```sql
CREATE TABLE notifications (
  id         TEXT PRIMARY KEY,
  title      TEXT NOT NULL,
  url        TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

通知由项目维护者手动在 D1 中 INSERT：

```sql
INSERT INTO notifications (id, title, url, created_at)
VALUES ('v0.3.0', '思源桥 v0.3.0 已发布', 'https://github.com/alone-tree/siyuan-bridge/releases/tag/v0.3.0', datetime('now'));
```

---

## Worker 端点

所有端点挂载在同一个 CF Worker 下：

| 方法 | 路径 | 用途 | 调用方 |
|------|------|------|--------|
| POST | `/api/telemetry` | 接收遥测事件，写入 D1 `events` 表 | Python `telemetry.py` |
| POST | `/api/feedback` | 接收用户反馈，写入 D1 `feedbacks` 表 | 插件前端表单 或 MCP `siyuan_bridge_feedback` |
| GET | `/api/notifications` | 返回通知列表 `{ "notifications": [...] }` | 插件前端首页 |

### POST /api/telemetry

请求体：JSON 数组（支持批量，也接受单条）

```json
[
  {
    "ts": "2026-06-07T10:30:00Z",
    "anonymous_id": "uuid-here",
    "platform": "Windows",
    "siyuan_ver": "3.1.25",
    "mcp_ver": "0.3.0",
    "session_id": "session-uuid",
    "tool": "siyuan_read",
    "action": null,
    "ok": 1,
    "error_type": null,
    "dur_ms": 234
  }
]
```

### POST /api/feedback

请求体：

```json
{
  "type": "bug",
  "title": "siyuan_edit 在 delete 后索引未刷新",
  "description": "删除文档后，下次 siyuan_list 仍显示该文档……",
  "contact": "user@example.com"
}
```

### GET /api/notifications

响应：

```json
{
  "notifications": [
    {
      "id": "v0.3.0",
      "title": "思源桥 v0.3.0 已发布",
      "url": "https://github.com/alone-tree/siyuan-bridge/releases/tag/v0.3.0"
    }
  ]
}
```

---

## MCP 工具：`siyuan_bridge_feedback`

除了插件前端的反馈表单，还应提供一个 MCP 工具，让 AI 也能通过对话提交反馈。

### 工具参数

| 参数 | 类型 | 必需 | 说明 |
|------|------|:---:|------|
| `type` | enum | 是 | `bug` / `feature` / `idea` |
| `title` | string | 是 | 反馈标题 |
| `description` | string | 是 | 详细描述 |
| `contact` | string | 否 | 联系方式 |

### 实现位置

在 `source_code/mcp_server.py` 中新增。数据流与前端反馈表单一致：POST 到同一个 Worker `/api/feedback` 端点。

---

## 典型遥测查询

查询最慢工具（按平均耗时排）：

```sql
SELECT tool, count(*) as calls, avg(dur_ms) as avg_dur, max(dur_ms) as max_dur
FROM events
GROUP BY tool
ORDER BY avg_dur DESC;
```

查询错误率：

```sql
SELECT tool, ok, count(*) as calls
FROM events
GROUP BY tool, ok
ORDER BY tool, ok;
```

查询平台占比：

```sql
SELECT platform, count(*) as calls
FROM events
GROUP BY platform
ORDER BY calls DESC;
```

按日趋势：

```sql
SELECT date(ts) as day, count(*) as calls
FROM events
GROUP BY day
ORDER BY day;
```

---

## 实现计划

### 第一阶段：Python 端基础框架

1. **新建 `source_code/telemetry.py`**
   - `generate_anonymous_id()` / `load_anonymous_id()` — 本地 stats/ 目录下的匿名 ID 管理
   - `TelemetryEvent` 数据类
   - `record_event()` — 写入本地 JSONL
   - `flush()` — POST 到远端
   - `should_collect()` / `should_upload()` — 读取 telemetry.json 配置

2. **新建 `source_code/feedback.py`**（或合入 telemetry.py）
   - `submit_feedback()` — POST 到 `/api/feedback`

3. **在 `mcp_server.py` 的工具外层包装饰器**
   - 记录进入时间
   - 调用真实实现
   - 捕获返回值/异常
   - 组装遥测事件
   - fire-and-forget 写入（本地 + 远端）

4. **在 `mcp_server.py` 新增 `siyuan_bridge_feedback` 工具**

5. **Config 加载 `telemetry.json`**

6. **CLI 子命令**：`python -m source_code telemetry status` — 显示当前遥测状态（模式、本地事件数、匿名 ID）

### 第二阶段：CF Worker + D1 部署

1. 部署 CF Worker，包含全部三个端点
2. 在 D1 中创建 `events`、`feedbacks`、`notifications` 三张表
3. 配置 Worker 绑定 D1
4. 在代码中设置默认 `telemetry_endpoint`

### 第三阶段：插件前端（独立推进）

> 详细设计见 `docs/plugin-frontend-design.md`。本阶段与前两个阶段可并行。

1. 首页改造：通知区域 + 反馈表单 + MCP 配置入口
2. 通知从 Worker GET `/api/notifications` 拉取
3. 反馈表单 POST 到 Worker `/api/feedback`
4. 在设置页增加遥测开关控制（读写 `telemetry.json`）

### 第四阶段：数据分析

1. 建立常用 SQL 查询
2. 可选：接 Grafana 仪表盘

---

## 当前状态

**第一阶段（Python 端基础框架）已实现。** 遥测收集、本地存储、代理上传、反馈提交（`siyuan_bridge_feedback` MCP 工具）、CLI 状态命令均已就绪并测试通过（242 tests）。

**默认端点**：`telemetry.py` 已添加 `DEFAULT_ENDPOINT` 常量（`https://siyuan-bridge-telemetry.864271839.workers.dev`），`should_upload()` 不再要求显式配置 `telemetry_endpoint`——只要 telemetry 为 `upload` 即可上传。

**插件前端已实现**：Home Dialog 含 4 板块（通知/MCP配置/反馈/用户体验改进），遥测开关简化为单个复选框（off/upload）。

CF Worker 后端已部署并验证可通过代理正常通信。第二阶段（自定义域名）待推进。

> 后端 API、D1 表结构、运维操作详见 [反馈与遥测后端参考](./feedback-telemetry-backend.md)。
