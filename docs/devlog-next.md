# SiYuan Bridge 工程日志

记录原则：

- 新记录写在最前面。
- 只记录工程实施、问题排查、验证结果和阶段性结论。
- 架构总览、产品理念、工具长期契约写入 `docs/ARCHITECTURE.md`。
- 开发规则、验证清单、AI 修改要求写入 `docs/DEVELOPMENT_GUIDE.md`。

## 2026-06-07：项目更名 + 拆容器层 + 废独立打包

今日两次提交解决了两个历史遗留问题：

### 项目更名：SiYuan Agent Bridge → SiYuan Bridge

- `SERVER_NAME`：`siyuan-agent-bridge` → `siyuan-bridge`
- Skill name：`siyuan-agent-bridge` → `siyuan-bridge`
- 目录：`plugins/siyuan-agent-bridge/` → `plugins/siyuan-bridge/`
- Skill 目录：`skills/siyuan-agent-bridge/` → `skills/siyuan-bridge/`
- 所有 MCP 配置模板、打包脚本、思源插件路径、文档全部更新
- `i18n.py` 中 `LEGACY_NOTEBOOK_NAMES` / `LEGACY_DOC_NAMES` 保留向后兼容
- `test_indexer.py` 保留旧名作为兼容测试数据

### 拆掉容器层，废掉独立打包

项目已从 CC Switch 独立压缩包分发转为仅通过思源集市插件发布。

- **删除** `pack_release.py`、`pack_skill.py`、`INSTALL_FOR_AI.md`
- **删除** `dist/` 中旧构建产物
- **重构** `sync_siyuan_plugin_bridge.py`：
  - `scripts/` 和 `skills/` 直接放在 `bridge/` 根下，不再嵌套 `plugins/siyuan-bridge/` 容器层
  - ROOT_FILES 移除 `INSTALL_FOR_AI.md`
  - 新增旧容器层清理逻辑
- **更新** `siyuan-plugin/index.js`、`src/index.js`、`dist/index.js`：MCP 路径从 `bridge/plugins/siyuan-bridge/scripts/run_mcp.py` 缩短为 `bridge/scripts/run_mcp.py`
- **修复** `run_mcp.py`：`REPO_ROOT` 从 `PLUGIN_ROOT.parents[1]` 改为 `PLUGIN_ROOT`（容器层拆除后 scripts/ 直接在 bridge/ 下，parents[1] 就是 bridge 根）
- **更新** `doctor.bat`、`.mcp.json`、README、AGENTS、ARCHITECTURE、DEVELOPMENT_GUIDE、PD 等全部文档

**结果**：
- 路径从 5 层嵌套 → 2 层：`siyuan-bridge/bridge/scripts/run_mcp.py`
- 205 tests passed
- 在测试工作空间端到端验证通过（`siyuan_start` 返回正确启动包）

## 2026-06-04：文档体系重整草案

本次新增三份主文档草案，不删除旧文档：

- `docs/ARCHITECTURE.md`：作为新的主架构文档，覆盖当前真实工具、参数、数据流、设计取舍、已知实现债务和未来计划。
- `docs/DEVELOPMENT_GUIDE.md`：作为开发者/AI 修改指南，记录修改前必读材料、同步清单、工具契约验证和真实已知错误模式。
- `docs/devlog-next.md`：作为工程日志倒序重写草案。

同时更新 `AGENTS.md` 的 Documentation 入口，要求改代码前完整阅读 `AGENTS.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_GUIDE.md`，不允许只读开头、只 grep 局部或跳过后半段。

验证：

- `python -m pytest tests -q`
- 结果：167 passed。

## 2026-06-04：siyuan_doc_manage 第一版实现与实测

新增 `siyuan_doc_manage` MCP 工具，第一版 action：

- `rename`
- `move`
- `delete`
- `copy`
- `export`

权限边界：

- `rename`、`move`、`delete` 需要 `confirmed=true` 和 `read_write` 权限。
- `copy`、`export` 对源文档只要求可读；`copy` 会创建新文档，因此仍需要 `confirmed=true` 和写前快照。
- `export` 导出到 `ai_workspace/exports/`，不修改思源，不创建快照。

真实思源端到端验证：

| action | 结果 | 备注 |
|--------|------|------|
| rename | 通过 | 重命名后文档标题和路径更新 |
| move | 通过 | 文档移动到目标父节点下 |
| delete | 通过 | 文档被删除 |
| copy | 通过 | 副本创建成功，内容完整 |
| export | 通过 | Markdown 导出到 `ai_workspace/exports/` |

实测问题：

- rename / move 后，MCP server 内部路径索引可能未即时同步。
- 当前临时操作建议是连续操作同一文档时沿用 `document_id`，或先刷新索引再使用新路径。
- 这只是过渡方案。后续应修复实现层路径索引同步，不能把手动刷新当成长期最终设计。

同步补充：

- Privacy Rules 兼容旧 `Hide=yes/no`。
- 新增可选 `Permission` 列，支持 `hidden`、`read_only`、`read_write`。
- `copy/export` 允许 `read_only` 文档。
- `rename/move/delete` 禁止 `read_only` 文档。
- 新增 client API payload 测试。
- 新增 `siyuan_doc_manage` rename / move / delete / copy / export 测试。
- 新增 `Permission=read_only` 解析和权限判断测试。

## 2026-06-04：siyuan_doc_manage 边界记录

第一版文档管理工具只处理文档级操作：

- 重命名
- 移动
- 删除
- 复制
- 导出

不在第一版处理：

- 在指定块位置插入图片、Excel 等附件。后续可增强 `siyuan_edit`，或在附件能力变复杂后单独设计 `siyuan_asset`。

## 2026-06-04：siyuan_create 完整路径与冲突策略实现

`siyuan_create.path` 改为优先接受完整可读路径：

```text
/Notebook/Folder/Doc
```

服务端内部解析笔记本 ID 和思源内部 hpath。

兼容策略：

- 旧式 `notebook_id + /Folder/Doc` 保留。
- 当笔记本名称重名导致路径无法唯一定位时，可继续使用 `notebook_id` 消歧。

新增 `if_exists`：

- `reject`：默认策略，目标存在则拒绝。
- `overwrite`：清空已有文档展示块后追加新 Markdown，保留文档 ID。
- `create_new`：调用 `createDocWithMd` 新建同名文档。

## 2026-06-03：siyuan_create 路径语义设计记录

真实 AI 试用暴露出 `siyuan_create.path` 与 `siyuan_list` / `siyuan_read` / `siyuan_edit` 的路径语义不一致：

- read/edit/list 使用包含笔记本名的完整可读路径。
- create 当时要求思源底层的笔记本内相对路径。
- AI 复用 list/read 返回路径时，会把笔记本名当成笔记本内第一层文件夹，导致误建嵌套目录。

结论：

- create 应贴近 AI 编程工具的 Write 心智，使用和 read/edit 一致的完整可读路径。
- 当目标路径可唯一定位到笔记本时，AI 直接传 `/Notebook/Folder/Doc`。
- 只有笔记本名称重名时，才要求补充 `notebook_id`。

## 2026-06-03：0.2.0 发布前文档与版本整理

发布前工具面整理为 8 个 MCP 工具：

```text
siyuan_start
siyuan_refresh_index
siyuan_list
siyuan_find
siyuan_read
siyuan_create
siyuan_edit
siyuan_doc_manage
```

版本整理：

- Python 包 / MCP server 版本升至 `0.2.0`。
- About 模板版本从 `template_version: 2` 升至 `template_version: 3`。
- 新版 About 只介绍当前工具能力、引用阅读、结构化编辑和表格编辑。

## 2026-06-03：工具面精简与统一命名

工具面精简：

- 删除 `siyuan_edit_document`。
- 删除 `siyuan_propose_guide_update`。
- 删除 `siyuan_apply_guide_update`。
- `siyuan_find_documents` 改名为 `siyuan_find`。
- `siyuan_read_document` 改名为 `siyuan_read`。
- `siyuan_create_document` 改名为 `siyuan_create`。

当时工具清单：

```text
siyuan_start
siyuan_refresh_index
siyuan_list
siyuan_find
siyuan_read
siyuan_create
siyuan_edit
```

后续计划：

- 增加文档文件操作工具。
- 将权限模型从 `hidden/read_write` 扩展为 `hidden/read_only/read_write`。

## 2026-06-02：连接探测提示调整

思源连接失败时，MCP 工具只探测 API 是否可达，不自动启动思源，不尝试查找程序路径或模拟启动。

连接失败提示需要保留：

```text
请提示用户手动打开思源笔记后重试。
```

## 2026-06-02：siyuan_list 改为一层路径列表

`siyuan_list` 调整为列出指定路径下一层文档/目录：

- `path="/Notebook"`：列出笔记本根目录下一层。
- `path="/Notebook/Folder"`：列出该路径下一层。
- 每行返回完整可读 `document` 路径，可直接传给 `siyuan_read` / `siyuan_edit`。
- 表格列为：`document`、`document_id`、字数、块数、更新、子文档。
- 默认 `limit=100`，支持 `offset` 翻页。
- 旧参数 `notebook_id` / `notebook_name` 保留为兼容入口。

验证记录：

- `python -m pytest tests/ -q`
- 结果：147 passed。

## 2026-06-02：siyuan_read 路径参数与头部精简

`siyuan_read` 显式支持 `document` 路径参数，优先使用包含笔记本名称的路径：

```text
/Notebook/Folder/Doc
```

`document_id` 保留为路径歧义或无路径时的 fallback。

tool description 调整为强调：编辑前应先调用 `siyuan_read(include_block_ids=true)`，使用返回的 `[index] id=... type=...` 作为 `siyuan_edit` 定位参数。

验证记录：

- `python -m pytest tests/ -q`
- 结果：143 passed。

## 2026-06-02：单块 replace 多块 Markdown 截断问题

Hermes 实测发现：用思源 `updateBlock` 把单块替换成多块 Markdown 时会发生截断。

处理结论：

- `single_block_replace` 只允许单块替换成单块。
- `single_block_replace` 继续使用 `updateBlock`，以保留原块 ID 和块样式属性。
- 多块替换使用 `multi_block_replace`，通过插入新块再删除旧范围完成。
- `single_block_replace` 误传多块 Markdown 时直接拒绝，并提示改用 `multi_block_replace`。

验证记录：

- `python -m pytest tests/ -q`
- 结果：142 passed。

## 2026-06-02：siyuan_edit 返回信息增强

`siyuan_edit` 按 action 返回更详细的编辑结果。

实现要点：

- 写入完成后调用 `get_child_blocks` 重建 display blocks，获取新块全局序号。
- `replace` / `insert` / `append` 后读取新插入块，展示思源实际拆分后的块结构。
- `insert_after` / `insert_before` 返回锚点内容和写入后读回的插入块。
- Fake client 支持模拟 update / insert / append / delete 后的块列表变化。
- 新增 replace / insert_after / delete / table_edit 的详细返回断言。

验证记录：

- `python -m pytest tests/ -q`
- 结果：140 passed。

## 2026-06-02：siyuan_edit 第一版实现

新增 `siyuan_edit` MCP 工具，作为新一代结构化编辑入口。

第一版 action：

- `replace`
- `insert_after`
- `insert_before`
- `append`
- `delete`
- `table_edit`

实现方式：

- `replace` 单块替换走 `update_block`。
- 范围替换走"在起点前插入新 Markdown，再删除旧范围"。
- `insert_after` 在目标块后插入 Markdown。
- `insert_before` 通过 client 层 `insert_block_before(nextID)` 在目标块前插入 Markdown。
- `append` 追加到文档末尾。
- `table_edit` 支持普通 Markdown 表格的 `set_cell`、`insert_row_before`、`insert_row_after`、`delete_row`。
- 数据库/属性视图仍只读。

边界：

- 非 append 操作必须提供 `start_index` + `start_id`。
- 范围操作必须同时提供 `end_index` + `end_id`。
- `replace` 遇到 attachment、database、superblock、html、iframe、video、audio、widget 等复杂块时拒绝。

测试补充：

- 路径 + 块序号 + 块 ID 替换测试。
- `table_edit.set_cell` 测试。
- insert_after / insert_before / append / delete / table_edit 行操作等边界测试。
- 拒绝 attachment 块时不创建快照。

## 2026-06-02：table_edit 设计

表格编辑作为 `siyuan_edit` 的 action，命名为 `table_edit`，不使用模糊的 `table`。

第一版 operation：

- `set_cell`
- `insert_row_before`
- `insert_row_after`
- `delete_row`

普通 Markdown 表格可写；数据库/属性视图只读。

## 2026-06-02：引用阅读显示格式调整

真实测试确认，引用阅读需要服务 AI 编辑定位，而不是暴露思源底层 raw type。

调整：

- `siyuan_read` 默认仍是普通阅读。
- 引用阅读去掉 `raw_type=h level=3`、`raw_type=l list=ordered` 等冗余信息。
- 块类型使用英文语义名，例如 `heading`、`paragraph`、`list`、`table`、`attachment`、`database`、`superblock`。
- 数据库块显示为 `type=database readonly=true`，不默认暴露 `database_id` / `av-id`。
- 列表先作为一个 display block，不展开内部 list item ID。

## 2026-06-02：read 文档附件路径改为绝对路径

真实工作流测试发现，`siyuan_read` 会把文档附件提取到：

```text
ai_workspace/attachments/<doc_id>/
```

但返回正文中的 Markdown 链接仍可能是 `assets/...` 相对路径。若 AI 运行环境不在项目根目录，模型可能无法定位图片、PDF 等附件。

处理结论：

- read 返回内容中的附件路径应改为 AI 可直接访问的绝对路径。

## 2026-05-08：隐私规则空行降级为 warning

`Privacy Rules` / `隐私规则` 的 `Hide Notebooks` 表格出现空行时，曾触发 `PrivacyRulesParseError`，导致 `siyuan_start` 被阻断。

处理结论：

- 空行不应阻断整个启动流程。
- 空行应降级为 warning。

## 旧记录：HTTP Keep-Alive 连接问题

Windows 环境下曾遇到 SiYuan HTTP API 连接异常，表现为 `WinError 10054`。

处理结论：

- client 请求使用 `Connection: close`。
- 避免复用不稳定的 keep-alive 连接。
