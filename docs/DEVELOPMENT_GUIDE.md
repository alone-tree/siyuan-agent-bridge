# SiYuan Agent Bridge 开发指南

> 草案状态：本文档用于补充和强化根目录 `AGENTS.md`。当前先新增，不删除旧文档；确认后再把稳定规则合并回入口文档。

## 修改前必须完整阅读

任何 AI 或开发者在修改代码前，必须完整阅读以下文档。不能只读开头，不能只 grep 局部，不能跳过中间或后半段。

必读：

1. 根目录 `AGENTS.md`
2. `docs/ARCHITECTURE.md`
3. 本文档 `docs/DEVELOPMENT_GUIDE.md`

按任务追加阅读：

| 修改范围 | 还必须阅读 |
|---|---|
| MCP 工具 schema、参数、返回格式 | `plugins/siyuan-agent-bridge/skills/siyuan-agent-bridge/SKILL.md`、`README.md`、`INSTALL_FOR_AI.md` |
| Workspace Index 工作流 | `plugins/siyuan-agent-bridge/skills/siyuan-index-builder/SKILL.md` |
| 思源 API 封装 | `docs/思源API.md`、`source_code/client.py` |
| 隐私和权限 | `source_code/ignore.py`、`source_code/agent_notebook.py`、相关测试 |
| 阅读、编辑、表格、文档管理 | `source_code/mcp_server.py`、相关测试 |
| 发布和安装 | `pack_skill.py`、`pack_release.py`、`mcp_configs/`、`INSTALL_FOR_AI.md` |
| 历史问题排查 | `docs/devlog.md`，优先读最近日期；不要把旧计划当当前事实 |

如果没有完整阅读这些材料，不准开始改代码。

## 文档职责

| 文档 | 职责 |
|---|---|
| `AGENTS.md` | AI 入口规则、协作约束、常用命令、强制阅读指引 |
| `docs/ARCHITECTURE.md` | 当前真实架构、工具契约、数据流、设计取舍、已知债务、未来计划 |
| `docs/DEVELOPMENT_GUIDE.md` | 开发流程、同步清单、验证清单、已知真实风险 |
| `docs/devlog.md` | 工程日志、排障记录、阶段性结果；新记录应放最前 |
| `docs/思源API.md` | 思源底层 API 能力地图和本项目封装策略 |
| `docs/PD.md` | 旧产品设计文档；确认迁移前保留，当前事实以 `ARCHITECTURE.md` 为准 |

文档同步规则：

- 架构结论写入 `ARCHITECTURE.md`。
- 开发流程或验证规则写入 `DEVELOPMENT_GUIDE.md`。
- 工程过程和排障写入 `devlog.md`。
- 不要把长期架构塞进 devlog。
- 不要让 README、Skill、Architecture、tool schema 互相矛盾。

## 修改工具面时必须同步

只要改 MCP 工具名称、参数、默认值、返回格式、权限边界或行为语义，必须同步检查：

- `source_code/mcp_server.py` 的工具实现
- `tool_specs()`
- `tests/`
- `plugins/siyuan-agent-bridge/skills/siyuan-agent-bridge/SKILL.md`
- `plugins/siyuan-agent-bridge/skills/siyuan-index-builder/SKILL.md`，如果影响索引工作流
- `README.md`
- `INSTALL_FOR_AI.md`
- `docs/ARCHITECTURE.md`
- `docs/思源API.md`，如果涉及底层 API 封装
- `docs/devlog.md`，记录实现过程和验证结果

不能只改实现，不改 schema。AI 客户端看到的是 `tool_specs()`，Skill 和 README 决定 AI 怎么调用。

## 修改隐私模型时必须验证

隐私相关改动包括：

- Privacy Rules 表格解析。
- `hidden/read_only/read_write` 权限。
- 系统笔记本保护。
- 搜索、读取、创建、编辑、文档管理的权限检查。
- 本地索引生成和过滤。

必须验证：

- 隐藏笔记本不会进入索引、列表、搜索、读取和写入。
- 隐藏文档及其子树不会进入索引、列表、搜索、读取和写入。
- `read_only` 可读、可 copy/export，但不可 create/edit/rename/move/delete。
- `read_write` 仍要求 `confirmed=true` 才能写。
- Privacy Rules 文档不能被 AI 读取、搜索、创建或编辑。
- 搜索 `sql` 模式也必须经过隐私过滤。
- 写入后的自动 refresh 不得把 Privacy Rules 写入 AI 可见缓存。

已知需要修补：

- 系统笔记本不能被隐藏的承诺尚未由代码强制执行。
- 写入后自动 refresh 没传系统笔记本 ID 和 Privacy Rules 文档 ID。
- Privacy Rules 按 hpath 名称硬隔离可能误挡非系统同名文档。

## 修改读取模型时必须验证

涉及 `siyuan_read`、展示块、附件、数据库、超级块、列表、表格的改动，必须验证：

- 普通阅读不显示块 ID。
- 引用阅读显示 `[index] id=... type=...`。
- 大纲始终返回，并标注标题块位置。
- `block_start`、`block_limit`、`token_budget` 不从块中间截断。
- 长文档有正确下一窗口提示。
- 普通 Markdown 表格在普通阅读中保留原始 Markdown。
- 普通 Markdown 表格在引用阅读中显示坐标视图。
- 数据库/属性视图只读渲染，不允许当普通表格编辑。
- 附件提取到 `ai_workspace/attachments/<doc-id>/assets/`。
- 返回正文中的 `assets/...` 链接改为本机绝对路径。
- 超级块普通阅读不重复渲染子块内容。

已知真实问题：

- SQL `sort` 不能可靠恢复块顺序，主路径必须继续使用 `getChildBlocks`。
- updateBlock 多块 Markdown 会截断，不要用它做多块替换。

## 修改写入模型时必须验证

涉及 `siyuan_create`、`siyuan_edit`、`siyuan_doc_manage` 的改动，必须验证：

- 写入必须要求 `confirmed=true`。
- 写入前必须创建思源快照。
- 快照失败必须拒绝写入。
- 数据仓库密钥未初始化时错误提示清晰。
- 隐藏文档不可写。
- 只读文档不可 edit/rename/move/delete。
- copy/export 对只读文档的行为符合工具契约。
- 写入后 pushMsg 失败不应影响主操作。
- 写入后需要刷新的工具必须正确刷新索引。
- 返回信息必须让 AI 确认改了什么。

`siyuan_edit` 特别要求：

- 编辑前必须先引用阅读。
- index/id 不匹配时拒绝写入。
- `single_block_replace` 只允许一块变一块。
- 可能产生多块的内容必须用 `multi_block_replace`。
- `single_block_replace` 和 `table_edit` 必须保留块属性。
- `multi_block_replace` 必须明确旧块 ID 会失效。
- 表格编辑必须使用 `row` 和 `column_index` 坐标。

已知真实问题：

- `single_block_replace` 误传多块 Markdown 会导致内容丢失，所以当前代码已拒绝。
- `updateBlock` 会清空块样式属性，所以必须保留 IAL custom attrs。
- `siyuan_edit` 成功后当前不会自动刷新字数/块数索引。

## 修改文档管理时必须验证

涉及 `siyuan_doc_manage` 的改动，必须验证：

- rename/move/delete 需要 `read_write` 和 `confirmed=true`。
- copy 源文档可以是 `read_only`，但目标路径必须 `read_write`。
- export 不创建快照、不写思源，只写 `ai_workspace/exports/`。
- delete 返回中提示可通过思源快照恢复。
- rename/move/copy/delete 后索引状态正确。
- 连续操作同一文档时，路径和 document_id 解析一致。

已知真实问题：

- rename/move 后路径索引存在同步延迟。当前操作建议是用 `document_id` 或 refresh 过渡；后续应修复实现，不应长期依赖手动刷新。

## MCP 工具契约清单

| 工具 | 是否写思源 | 是否需要 confirmed | 是否快照 | 主要权限 |
|---|---:|---:|---:|---|
| `siyuan_start` | 可能创建/更新系统文档 | 否 | 否 | 内部系统操作 |
| `siyuan_refresh_index` | 可能创建/更新系统文档 | 否 | 否 | 内部系统操作 |
| `siyuan_list` | 否 | 否 | 否 | 只返回可见索引 |
| `siyuan_find` | 否 | 否 | 否 | 返回前隐私过滤 |
| `siyuan_read` | 否 | 否 | 否 | hidden 不可读 |
| `siyuan_create` | 是 | 是 | 是 | 目标路径 read_write |
| `siyuan_edit` | 是 | 是 | 是 | 文档 read_write |
| `siyuan_doc_manage:rename` | 是 | 是 | 是 | 文档 read_write |
| `siyuan_doc_manage:move` | 是 | 是 | 是 | 文档 read_write |
| `siyuan_doc_manage:delete` | 是 | 是 | 是 | 文档 read_write |
| `siyuan_doc_manage:copy` | 是 | 是 | 是 | 源可读，目标 read_write |
| `siyuan_doc_manage:export` | 否，只写本地导出 | 否 | 否 | 源可读 |

## 测试与验证清单

每次代码修改后至少运行：

```bash
python -m pytest tests -q
```

涉及 MCP 工具面、schema、Skill、安装配置或跨 Agent 行为时，还必须做 MCP 工具列表验证：

```text
JSON-RPC initialize
JSON-RPC tools/list
确认工具数量和名称符合预期
```

涉及发布或安装材料时运行：

```bash
python pack_skill.py --check
python pack_release.py --check
```

涉及 MCP 工具面、Skill、安装配置或跨 Agent 行为时，按项目规则还应调用 Claude Code 做外部验证。如果 `claude -p` 因登录、网络或 API 错误不可用，改用本地 JSON-RPC 探针调用 `initialize` 和 `tools/list`。

当前已经验证过的基线：

- `python -m pytest tests -q`：167 passed。
- 本地 JSON-RPC `tools/list`：8 个工具，server version `0.2.0`。
- `pack_skill.py --check` 和 `pack_release.py --check` 可列出清单。

## 自动化验证计划

后续应新增统一验证入口，例如：

```bash
python scripts/verify.py
```

目标覆盖：

1. 单元测试。
2. MCP JSON-RPC `initialize + tools/list`。
3. 打包清单检查。
4. 可选外部 Claude Code 验证。

在该脚本落地前，不要声称已经有全自动验证；仍按上面的命令手动运行。

## 已知真实错误模式

这里只记录已从当前代码、测试或 devlog 中确认过的问题，不写泛泛的假想风险。

1. 旧文档仍含旧工具名和旧 exact text anchor 方案，AI 只读 devlog 开头会被误导。
2. `mcp_server.py` 体积过大，局部修改容易漏同步 `tool_specs()`、Skill 或测试。
3. Privacy Rules 文档硬隔离和系统笔记本保护存在实现差距。
4. 写入后自动 refresh 没有传系统文档排除参数，可能污染本地索引缓存。
5. `siyuan_refresh_index` 是否清理 `ai_workspace` 的文档和实现不一致。
6. `siyuan_doc_manage` rename/move 后路径索引可能延迟。
7. `updateBlock` 多块 Markdown 会截断。
8. `updateBlock` 会清空块样式属性，必须恢复 IAL custom attrs。
9. 旧 `siyuan_create` 路径语义曾导致 AI 把完整路径误当内部路径。
10. Windows keep-alive 曾触发 `WinError 10054`，HTTP client 必须保留 `Connection: close`。
11. `docs/siyuan-api-doc.md` 是网页抓取噪音，不应作为开发参考。
12. 插件和安装文档存在版本/链接漂移。

## Windows 命令与编码

在 Windows 上读取中文、搜索中文或运行复杂命令时，优先使用 CMD UTF-8 包装：

```bash
cmd /d /s /c "chcp 65001 >nul && <command>"
```

不要把终端乱码误判为文件损坏。

## Git 与工作区

工作区可能有用户未提交变更。修改前先查看：

```bash
git status --short
```

规则：

- 不要回滚用户变更。
- 不要使用 `git reset --hard` 或 `git checkout --`，除非用户明确要求。
- 与任务无关的未跟踪文件不要擅自删除。
- 生成文件、缓存、导出文件要注意 `.gitignore`。

