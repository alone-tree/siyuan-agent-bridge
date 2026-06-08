# Ideas

这里放未承诺实施的粗略想法。每条尽量 1-5 行；一旦决定实施，迁移到 `ARCHITECTURE.md`、`DEVELOPMENT_GUIDE.md` 或具体 issue，不在这里维护路线图。

## 待评估

- 设计 `siyuan_import`：把外部 Markdown、PDF、图片等导入为思源文档或资源。
- 设计资产写入能力：上传图片/附件并插入到指定块附近。
- 多平台支持：验证 Mac/Linux 的 Python、路径、编码、MCP 注册和思源端口行为。

- 处理历史遗留代码：knowledge_base文件夹、思源插件导入后不git（因为都是同一个代码）、readme维护一份

## sync push — MCP 工具触发思源云端同步

- 思源内核提供 `POST /api/sync/performSync` 端点，支持程序化触发同步
  - 参数：`app`（必需）、`pushMode`（"" 正常双向 / "force-push" / "force-pull"）、`force`、`cloudName`
  - 异步执行，需 admin 权限，调用本地内核端口（默认 6806）
- 做成 MCP 工具的两种方案待评估：
  - **独立工具 `siyuan_sync_push`**：调用即触发一次同步到云端
  - **合入写入操作**：`siyuan_create` / `siyuan_edit` 成功后可选自动附带 push（可配置开关）
- 前提：用户必须在思源设置里配好云端同步（S3/WebDAV/官方云），否则 push 失败
- 需确认同步锁机制：频繁调用是否冲突？push 间隔限制？

## 重构 refresh 为通用操作工具（暂名 `siyuan_op`）

- 把 `siyuan_refresh_index` 改为 `siyuan_op`，提供三个操作：`refresh`、`sync`、`help`
- `refresh` = 现有刷新功能，`sync` = 触发云端同步（默认模式），`help` = 思源桥操作 tips
- 所有报错信息都加一句"可用 op=help 获取更多技巧"
- help 是否支持 `tool=xx`、`action=xx` 针对性参数？还是只返回通用技巧？
- start 要不要合进来？
- 命名未定（siyuan_op / siyuan_operate / 其他）

## 遥测看板（公开页面）

- Worker 加 dashboard API，个人网站前端 JS fetch Worker 直连，不需要 API key
- 时间窗口未定（30天/14天/7天？）
- 想统计：活跃用户数、总调用次数、总体成功率、每日调用量曲线、每日成功率曲线、各工具调用及 action、各工具失败次数及场景