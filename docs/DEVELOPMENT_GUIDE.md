# SiYuan Bridge 开发指南

## 修改前必须完整阅读

任何 AI 或开发者在修改代码前，必须完整阅读以下文档。不能只读开头，不能只 grep 局部，不能跳过中间或后半段。

必读：

1. 根目录 `AGENTS.md`
2. `docs/ARCHITECTURE.md`
3. 本文档 `docs/DEVELOPMENT_GUIDE.md`

按任务追加阅读：

| 修改范围 | 还必须阅读 |
|---|---|
| MCP 工具 schema、参数、返回格式 | `plugins/siyuan-bridge/skills/siyuan-bridge/SKILL.md`、`README.md` |
| Workspace Index 工作流 | `plugins/siyuan-bridge/skills/siyuan-index-builder/SKILL.md` |
| 思源 API 封装 | `docs/思源API.md`、`source_code/client.py` |
| 隐私和权限 | `source_code/ignore.py`、`source_code/agent_notebook.py`、相关测试 |
| 阅读、编辑、表格、文档管理 | `source_code/mcp_server.py`、相关测试 |
| 插件前端 | `docs/FRONTEND.md`、`siyuan-plugin/` |
| 发布和安装 | `mcp_configs/` |
| 历史问题排查 | `docs/devlog.md`，优先读最近日期；不要把旧计划当当前事实 |

如果没有完整阅读这些材料，不准开始改代码。

## 文档职责

| 文档 | 职责 |
|---|---|
| `AGENTS.md` | AI 入口规则、协作约束、常用命令、强制阅读指引 |
| `docs/ARCHITECTURE.md` | 当前真实架构、工具契约、数据流、设计取舍、已知债务、未来计划 |
| `docs/architecture-map.html` | 面向人类的产品架构图；整体架构大改时必须和 `ARCHITECTURE.md` 同步 |
| `docs/DEVELOPMENT_GUIDE.md` | 开发流程、同步清单、验证清单、已知真实风险 |
| `docs/FRONTEND.md` | 思源插件前端实现细节、加载方式、配置写入、踩坑和验证 |
| `docs/IDEAS.md` | 未承诺实施的粗略想法；不作为路线图或当前债务 |
| `docs/devlog.md` | 工程日志、排障记录、阶段性结果；新记录应放最前 |
| `docs/思源API.md` | 思源底层 API 能力地图和本项目封装策略 |

文档同步规则：

- 架构结论写入 `ARCHITECTURE.md`。
- 开发流程或验证规则写入 `DEVELOPMENT_GUIDE.md`。
- 工程过程和排障写入 `devlog.md`。
- 不要把长期架构塞进 devlog。
- 不要让 README、Skill、Architecture、tool schema 互相矛盾。

## 文档新增与修改规则

默认不新建文档。只有内容有独立生命周期、篇幅会明显拖累主文档，或是短期草案时才允许新建。

修改归属：

- 当前架构、工具契约、数据流、设计取舍、已确认债务：`ARCHITECTURE.md`；整体架构大改时同步 `architecture-map.html`。
- 开发流程、验证规则、文档维护规则：`DEVELOPMENT_GUIDE.md`。
- 插件前端细节和踩坑：`FRONTEND.md`。
- 未承诺 idea：`IDEAS.md`，每条尽量 1-5 行。
- 工程过程、排障记录、验证结果：`devlog.md`，新记录放最前。
- 用户说明和常见 QA：`README.md`。

禁止：

- 不要为一次临时计划创建永久文档。
- 不要在 devlog 写长期架构事实。
- 不要让同一工具契约在多个文档重复维护。
- 设计草案定案后，迁移结论并删除草案。

## 修改工具面时必须同步

只要改 MCP 工具名称、参数、默认值、返回格式、权限边界或行为语义，必须同步检查：

- `source_code/mcp_server.py` 的工具实现
- `tool_specs()`
- `tests/`
- `plugins/siyuan-bridge/skills/siyuan-bridge/SKILL.md`
- `plugins/siyuan-bridge/skills/siyuan-index-builder/SKILL.md`，如果影响索引工作流
- `README.md`
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
- 写入后需要刷新的工具必须带系统上下文刷新索引，且不得把 Privacy Rules 写入 AI 可见缓存。
- create/rename/move/copy/delete 后必须等待思源路径接口同步，返回路径同步状态。
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
- delete 会影响整棵子树，必须验证子孙文档中存在 `read_only` 或 `hidden` 时拒绝操作，且错误信息不能泄露隐藏文档名称、数量或权限分布。
- move 会移动整棵子树但不要求子孙全部可写；必须验证源文档祖先链和目标父路径都是 `read_write`。
- copy 必须使用 `target_path`，通过 `duplicateDoc` 复制源文档本身；不应退回 export + create 作为主路径。
- export 不创建快照、不写思源，只写 `ai_workspace/exports/`。
- delete 返回中提示可通过思源快照恢复。
- rename/move/copy/delete 后路径同步状态和索引状态正确。
- 连续操作同一文档时，路径和 document_id 解析一致。

已知真实问题：

- 思源文件树路径更新可能有短暂延迟。当前实现用 `getHPathByID` 短轮询后再刷新索引；若等待超时，仍应在返回中提示同步状态。

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
python scripts/sync_siyuan_plugin_bridge.py
```

不再有 `pack_skill.py` 和 `pack_release.py` —— 项目已从 CC Switch 独立分发转为思源集市插件发布。

同步脚本只生成 `siyuan-plugin/bridge/`，该目录是开发/安装运行产物，不提交 Git。验证时必须确认：

- `siyuan-plugin/bridge/source_code/mcp_server.py` 存在。
- `siyuan-plugin/bridge/scripts/run_mcp.py` 存在。
- `siyuan-plugin/bridge/config.local.json` 不会被同步脚本覆盖。

## 插件导入测试流程

测试思源工作空间中的插件目录只能作为”用户安装后的落盘结果”。不要直接修改测试工作空间里的插件代码。所有修复必须先改仓库工程文件，再把整个 `siyuan-plugin/` 重新导入测试工作空间。

测试工作空间路径不要硬编码。使用 `SIYUAN_TEST_WORKSPACE` 环境变量，或在命令中传 `--workspace`。脚本接受两种常见路径：

- 工作空间根目录，例如 `D:\siyuan2\workspace`
- 包含 `workspace/` 的父目录，例如 `D:\siyuan2`

当前家用测试机示例：

```bat
set SIYUAN_TEST_WORKSPACE=D:\siyuan2
```

导入脚本默认保留测试工作空间已有的 `bridge/config.local.json` 和 `bridge/telemetry.json`。模拟新用户首次安装时加 `--fresh`，不会保留这些本地配置。

> 遥测与反馈的 Worker API、D1 表结构、运维操作详见 [反馈与遥测后端参考](./feedback-telemetry-backend.md)。用户常见问题写在 README。

### 首次安装（模拟新用户）

模拟用户第一次从零安装插件的场景。预期：导入后没有 `config.local.json`，启用插件后自动创建。

```bat
python scripts\import_siyuan_plugin.py --workspace %SIYUAN_TEST_WORKSPACE% --fresh
```

普通开发导入（保留本地配置）：

```bat
python scripts\import_siyuan_plugin.py --workspace %SIYUAN_TEST_WORKSPACE%
```

验证清单：
- [x] `bridge/source_code/mcp_server.py` 存在
- [x] `bridge/scripts/run_mcp.py` 存在
- [x] `bridge/config.local.json` **不存在**
- [x] 思源 UI 启用插件后自动创建 `config.local.json`
- [x] 用户没有点开设置页、没有点击保存的情况下，外部 MCP 客户端能正常启动并调用工具

首次安装/启用插件的真实用户流程必须额外验证：删除测试插件目录中的 `bridge/config.local.json`，整体导入仓库 `siyuan-plugin/` 后，由用户在思源 UI 启用插件。插件启用后应自动创建 `bridge/config.local.json`，写入当前工作空间名称和 Token；在用户没有点开设置页、没有点击”保存配置”的情况下，外部 MCP 客户端也应能正常启动并调用工具。

涉及 MCP 工具面、Skill、安装配置或跨 Agent 行为时，按项目规则还应调用 Claude Code 做外部验证。外部验证不是只看代码，而是让另一个 Agent 在真实 MCP 客户端环境里调用工具。

### 外部 Agent 验证

必须在当前项目目录运行：

```bat
cd /d D:\Github\siyuan-bridge
```

项目级 MCP 名称固定为 `siyuan-bridge-dev`，配置文件是根目录 `.mcp.json`，启动脚本指向：

```text
plugins/siyuan-bridge/scripts/run_mcp.py
```

先确认 Claude Code 能连接项目 MCP：

```bat
claude mcp list
claude mcp get siyuan-bridge-dev
```

外部验证应优先使用 Claude Code 的宽授权 / bypass 模式，避免工具调用被权限弹窗或 `allowedTools` 限制截断：

```bat
claude --permission-mode bypassPermissions --dangerously-skip-permissions --print "<验证任务>"
```

原则：

- 不要默认加 `--allowedTools`，除非本次就是要测试受限工具集；权限应尽可能接近真实 Agent 可自由调用 MCP 的状态。
- 验证 MCP 工具面时，至少让 Claude Code 新会话列出工具名称，并检查关键工具 description/schema 是否包含本次改动。
- 验证工具行为时，必须让 Claude Code 实际调用 `siyuan-bridge-dev` 的 MCP 工具完成最小端到端流程，而不是只复述工具说明。
- 写入类验证只能操作明确的临时测试文档；测试结束后清理本轮创建的测试文档。
- 如果验证过程中调用 `siyuan_start`，注意它会清理 `ai_workspace/` 中除 README 外的内容，不要把由此产生的本地导出文件删除误判成代码改动。

推荐命令模板：

```bat
claude --permission-mode bypassPermissions --dangerously-skip-permissions --print "Use only MCP server siyuan-bridge-dev. Call siyuan_start, then ..."
```

不同修改范围的最低外部验证：

| 修改范围 | Claude Code 外部验证 |
|---|---|
| 工具名称、schema、description | `tools/list` 可见 8 个工具；关键工具 description/schema 包含改动 |
| `siyuan_create` | create 临时文档后立刻用返回路径 `siyuan_read` |
| `siyuan_doc_manage` | 对临时文档依次验证 rename/move/copy/delete 后路径同步和索引刷新 |
| 隐私/权限 | 用临时规则或测试文档验证 hidden/read_only/read_write 行为，不读取 Privacy Rules 正文 |
| Skill/安装配置 | 让 Claude Code 按 Skill 指令调用 `siyuan_start` 并确认工具工作流可执行 |

如果 `claude --print` 因登录、网络、API 错误或 MCP 客户端故障不可用，改用本地 JSON-RPC 探针调用 `initialize` 和 `tools/list`，至少确认 server 可启动、工具数量和名称正确。行为级验证缺失时，必须在最终说明中明确标注“未完成外部行为验证”。

当前已经验证过的基线：

- `python -m pytest tests -q`：241 passed。
- 本地 JSON-RPC `tools/list`：9 个工具，server version 见 `source_code/__init__.py`。
- `python scripts/sync_siyuan_plugin_bridge.py` 可同步 bridge 到插件开发目录。

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
4. 写入后自动 refresh 必须保留系统文档排除参数，避免污染本地索引缓存。
5. `siyuan_refresh_index` 不清理 `ai_workspace` 是当前设计；旧文档中“refresh 会清理 workspace”的表述需要迁移时删除。
6. `siyuan_doc_manage` rename/move 后路径索引可能延迟，当前通过短轮询和安全刷新处理。
7. `updateBlock` 多块 Markdown 会截断。
8. `updateBlock` 会清空块样式属性，必须恢复 IAL custom attrs。
9. 旧 `siyuan_create` 路径语义曾导致 AI 把完整路径误当内部路径。
10. Windows keep-alive 曾触发 `WinError 10054`，HTTP client 必须保留 `Connection: close`。
11. 插件和安装文档存在版本/链接漂移。
12. 思源插件第一版的 `bridge/` 目录由同步脚本生成，不是发布 ZIP；不要把旧 ZIP 流程误当成当前插件实现路径。
13. 测试空间里的思源插件目录不是源码，不得直接编辑。正确流程是修改仓库 `siyuan-plugin/`，再整体导入测试空间。

## 版本号管理

版本号遵循单一事实源原则。Python 端统一从 `source_code/__init__.py` 的 `__version__` 读取，其他模块不得重复定义。

**版本号位置：**

| 位置 | 角色 | 管理方式 |
|------|------|----------|
| `source_code/__init__.py` | **唯一事实源** | 手动编辑 `__version__ = "x.y.z"` |
| `source_code/telemetry.py` | 引用 | `from source_code import __version__ as MCP_VERSION` |
| `source_code/mcp_server.py` | 引用 | `from . import __version__`（`serverInfo.version`） |
| `siyuan-plugin/plugin.json` | 独立维护 | 手动同步，与 `__version__` 保持一致 |

**升级版本号时需修改的文件：**

1. `source_code/__init__.py` — `__version__`
2. `siyuan-plugin/plugin.json` — `"version"`

`plugin.json` 是 JSON 文件，无法 import Python 模块，只能手动同步。两者必须保持一致。

**不需要改的地方：**

- 文档中的 API 示例数据（`mcp_ver` 字段）仅作示意，不需要逐版更新。
- `docs/devlog.md` 中的历史版本号是工程记录，不应修改。
- `tests/` 不硬编码版本号。

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

## 构建与发布

### 导入测试：`scripts/import_siyuan_plugin.py`

把插件导入到本地思源数据目录，用于开发测试。自动执行 bridge 同步。

```bash
# 导入到思源工作空间（写完后在思源集市 → 已下载启用插件）
python scripts/import_siyuan_plugin.py --workspace "D:\SiYuan"

# 首次导入 / 清空重装（删除旧插件目录，不留旧配置）
python scripts/import_siyuan_plugin.py --workspace "D:\SiYuan" --fresh

# 直接用插件目录路径
python scripts/import_siyuan_plugin.py --plugin-dir "D:\SiYuan\data\plugins\siyuan-bridge"
```

数据流：`sync` 生成 `bridge/` → 把 `siyuan-plugin/` 整个复制到 `{workspace}/data/plugins/siyuan-bridge/`。

`--fresh` 会先删除目标目录再复制。不带 `--fresh` 时保留已有 `config.local.json` 和 `telemetry.json` 不动。

### 打包发布：`scripts/build_package.py`

生成思源集市上架的 `package.zip`。自动执行 bridge 同步。

```bash
python scripts/build_package.py
```

输出：`dist/package.zip`。

zip 包含：`plugin.json`、`icon.png`、`preview.png`、`index.js`、`index.css`、`README*.md`、`bridge/`、`dist/`、`src/`。`bridge/` 由 sync 脚本生成，包含完整 Python 运行文件。

### 文件去向

```
source_code/          ─┐
plugins/siyuan-bridge/  ┤  手写源文件（你改的）
siyuan-plugin/*         ┤  (plugin.json, index.js, 图标等)
                        ─┘
         ↓  sync_siyuan_plugin_bridge.py
siyuan-plugin/bridge/  ←  自动生成（不提交 Git，不要手动改）
         ↓  import_siyuan_plugin.py               ↓  build_package.py
{workspace}/data/plugins/siyuan-bridge/       dist/package.zip
      (本地测试用)                               (集市发布用)
```

### 版本发布流程

集市发布走 GitHub Release，bazaar 每 1-3 小时自动拉取最新 release。

**首次发布（仅一次）**：

1. Fork `siyuan-note/bazaar`
2. 在 `plugins.txt` 加一行 `alone-tree/siyuan-bridge`
3. 提 PR 到 bazaar 主仓库
4. 合并后，集市索引自动更新

**后续更新**，每次只需：

```bash
# 1. 修改 siyuan-plugin/plugin.json 里的 version 号（遵循 semver）

# 2. 打包
python scripts/build_package.py

# 3. 提交、打 tag、推送
git add -A
git commit -m "release: vX.Y.Z — <简述>"
git push origin main
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z

# 4. 创建 GitHub Release，上传 dist/package.zip
gh release create vX.Y.Z dist/package.zip --title "vX.Y.Z" --notes "<更新说明>"
```

之后 bazaar 会在 1-3 小时内自动拉取新版本，**无需再提 PR**。用户重启思源可看到更新。

如果 Stage 工作流长时间未更新，检查 <https://github.com/siyuan-note/bazaar/actions/workflows/stage.yml> 的日志。
