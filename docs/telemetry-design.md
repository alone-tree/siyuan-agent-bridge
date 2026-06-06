# 遥测系统设计（未实现）

## 动机

了解用户如何使用思源桥：哪些工具最常用、哪些报错最多、哪些操作最慢。帮助确定优化重点和开发方向。

## 设计原则

- 只收集元数据，不收集内容
- Fire-and-forget，不阻塞工具调用，用户无感知
- 发不出去就丢弃，不影响用户体验
- Opt-in，默认关闭
- 数据不保存在思源笔记本中

## 数据范围

收集：

- 时间戳
- 匿名用户 ID（UUID，本地生成，和任何身份信息无关）
- 系统平台（Windows / Darwin / Linux，来自 platform.system()）
- 思源版本（启动时从 /api/system/version 获取）
- MCP 版本（项目 __version__）
- 会话 ID（每次 MCP 进程启动时生成，用于聚合一次对话内的连续调用）
- 工具名（siyuan_read、siyuan_create 等）
- Action 名（siyuan_edit 的 single_block_replace、siyuan_create 的 overwrite 等子操作）
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

## 架构

```
用户本地环境                          远端
+---------------+          +---------------------+
| siyuan-agent  |   POST   | CF Worker           |
| bridge (MCP)  | -------> |  /api/telemetry     |
|               |  try/    |       |              |
|               |  except  |    D1 Database       |
|               |  吞掉    |       |              |
|               |          |  SQL 查询 / 仪表盘    |
+---------------+          +---------------------+
```

Python 端：在每个工具实现外层包一个装饰器，统一测量时间、捕获结果、组装事件。事件 POST 到配置的端点。成功失败都不影响工具本身的返回值。

Server 端：CF Worker 接收到 POST 后写入 D1 数据库。Worker 不做数据处理，只做简单的写入。

## 配置模型

在 config.local.json 中增加 telemetry 字段：

```json
{
  "profiles": [...],
  "language": "zh-CN",
  "telemetry": "off"
}
```

取值：

- off（默认）：不记录、不上传任何数据，没有性能开销
- local：只写本地 stats/ 目录，不上传
- upload：写本地 + 自动 POST 到远端端点

upload 模式下，端点地址可以显式配置：

```json
{
  "telemetry": "upload",
  "telemetry_endpoint": "https://yourdomain.com/api/telemetry"
}
```

未显式配置时，使用项目的默认端点（由项目维护者提供）。

## 本地数据

当 telemetry 为 local 或 upload 时，数据同时写入本地 stats/ 目录：

```
stats/
  telemetry_id      匿名用户 UUID，首次自动生成，永不变化
  events/
    2026-06-06.jsonl  每天一个文件，JSONL 格式
```

本地文件用于数据备份和用户自查。

## 远端数据（D1 表结构）

```sql
CREATE TABLE events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL,        -- ISO 8601
  anonymous_id TEXT NOT NULL,
  platform    TEXT,                 -- Windows / Darwin / Linux
  siyuan_ver  TEXT,                 -- 思源版本号
  mcp_ver     TEXT,                 -- MCP 版本号
  session_id  TEXT,                 -- 会话 ID
  tool        TEXT NOT NULL,        -- 工具名
  action      TEXT,                 -- 子操作
  ok          INTEGER NOT NULL,     -- 1 成功 0 失败
  error_type  TEXT,                 -- 错误类型
  dur_ms      INTEGER               -- 耗时毫秒
);

CREATE INDEX idx_events_date ON events(ts);
CREATE INDEX idx_events_tool ON events(tool);
CREATE INDEX idx_events_anon ON events(anonymous_id);
```

## 典型查询

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

## 隐私与透明

- telemetry 默认关闭，用户需主动在 config.local.json 中开启
- 在系统笔记本的 AI Guide 和 About 文档中说明遥测系统的存在和所收集的数据范围
- 匿名 ID 完全随机，与用户的 GitHub、邮箱、系统用户名无关
- 用户可随时删除 stats/ 目录或重置 ID
- 远端不收集用户 IP（Workers 默认不会记录客户端 IP，D1 也不存储）

## 实现计划

第一阶段（基础框架）：

1. 新建 source_code/telemetry.py
   - generate_anonymous_id() / load_anonymous_id()
   - TelemetryEvent 数据类
   - record_event() 写入本地 JSONL
   - flush() 发往远端
   - should_collect() / should_upload() 配置判断

2. 在 mcp_server.py 的 tool_specs 外层包一个装饰器
   - 记录进入时间
   - 调用真实实现
   - 捕获返回值/异常
   - 组装事件
   - fire-and-forget POST

3. Config 加载 telemetry 配置

4. CLI 子命令：python -m source_code telemetry status

第二阶段（远端）：

1. 部署 CF Worker + D1
2. Worker 接收 POST 写入 D1
3. 配置 endpoint

第三阶段（数据分析）：

1. 建立常用 SQL 查询
2. 可选：接 Grafana 仪表盘

## 当前状态

设计阶段。尚未实现任何代码。第一阶段和第二阶段在时间充裕时实施。
