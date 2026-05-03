# SiYuan Agent Bridge

[English README](README.en.md)

思源代理桥是一个私有、本地优先的思源笔记适配器。它让外部 AI agent 能像阅读代码仓库一样，先理解你的笔记结构，再按需读取具体文档，并在用户明确确认后写入内容。

它不是思源插件，而是AI插件。你的笔记仍然保存在思源里；这个工具只负责生成结构化索引，并通过 MCP 工具和 Skill 工作流给 AI 一个安全、可控的读写入口。

思源将本地优先和隐私优先作为主要考虑因素。本插件一脉相承。使用本插件时，思源笔记的工作空间内会生成一个专门的“思源代理桥”笔记本，人类用户可以在其中管理哪些文件对AI开放，将不想被AI发现的笔记本/文档录入“隐私规则”文档。该文档通过底层代码对AI排除，AI无法感知到被隐私规则保护的文档/笔记本。无法检索、无法阅读、无法编辑。隐私规则只有人类用户可以修改。

注：由于该MCP工具运行在本地计算机，因此AI仍然有机会通过修改底层代码来实现。但修改底层代码需要重启MCP，也就是需要重启AI才能生效，因此AI基本不具备自行破解的功能。

## 当前能力

- 扫描思源笔记本和完整文档树，包括子文档。关闭的笔记本会被自动临时打开，扫描完毕后恢复原状态。该设计的核心考虑是，关闭与否取决于人类使用的便捷性，但关闭的笔记本不代表内部资料不重要。
- 隐私规则完全由用户在思源系统笔记本 `思源代理桥` / `SiYuan Agent Bridge` 中的 `隐私规则` / `Privacy Rules` 文档通过 Markdown 表格维护。支持隐藏整个笔记本（按 ID 或名称）、单篇文档或整棵子文档树。AI 不可读取、搜索或编辑隐私规则文档。
- 隐私规则文档修改后，告诉 AI"刷新一下"即可生效。如需临时开放隐藏内容，将对应行的 `Hide` 改为 `no`，交流完毕后再改回 `yes`。
- 生成 `knowledge_base/` 下的安全索引，所有数据经隐私规则过滤。
- 统计每篇文档的块数和字符数，让 AI 可以把文档规模作为重要性信号。
- 提供 9 个 MCP 工具，让 Claude Code、Codex 等 agent 在安全索引范围内读取和写入思源资料。
- 长文档按展示块窗口分页返回，以 `block_limit` 和 `token_budget` 控制分段，不截断字符。
- 文档自动提取附件（图片、PDF、表格等）到 `ai_workspace/`，保留原始引用不变。
- 支持通过 CC Switch 导入 Skill 压缩包，并手动/JSON/deep link 注册 MCP。

## 日常怎么用

大多数时候你不需要自己使用命令行。

你主要维护这些：

- 思源系统笔记本中的 `AI 使用指南` / `AI Guide`：你在思源 UI 中编辑的 AI 持久偏好和重点笔记本指引。
- 思源系统笔记本中的 `隐私规则` / `Privacy Rules`：你在思源 UI 中通过 Markdown 表格维护的隐藏规则。
- `ai_workspace/`：AI 生成的分析、草稿和输出。

典型流程：

1. 你在思源里正常写笔记。
2. 在思源中打开 `思源代理桥` / `SiYuan Agent Bridge` 笔记本，编辑 `隐私规则` / `Privacy Rules` 文档的表格，填写要隐藏的笔记本或文档 ID，将 `Hide` 列设为 `yes`。
3. 告诉 AI"刷新一下索引"，隐藏内容即对新会话生效。

## Agent 启动流程

如果 AI 工具已经注册了 MCP，直接让它使用你的思源笔记知识库即可。它应该调用：

```text
siyuan_start
```

这个工具会做：

- 刷新安全索引，确保数据是最新的。
- 检查思源本地服务是否可用。
- 确保系统笔记本 `思源代理桥` / `SiYuan Agent Bridge` 及其四份系统文档就绪。
- 返回启动包：笔记本概览表、Workspace Index（如存在）、AI Guide、隐私规则状态、语言偏好。

如果 MCP 不可用，请先注册或修复 MCP。Python CLI 只作为开发诊断入口，不作为正常 AI 使用入口。

## MCP 工具

当前 MCP 提供 9 个工具（默认只读，明确确认后可写入）：

- `siyuan_start`：刷新安全索引并返回启动包（含笔记本概览表、Workspace Index（如存在）、AI Guide、隐私规则状态、语言偏好）。始终最先调用。
- `siyuan_refresh_index`：手动刷新安全索引并清理 `ai_workspace/`（保留 README.md）。
- `siyuan_list`：无参数时列出所有可见笔记本；给定 `notebook_id` 或 `notebook_name` 时返回文档树，含字数、块数和更新时间。
- `siyuan_find_documents`：通过思源搜索 API 检索，返回前应用隐私规则过滤；搜索时会临时打开关闭的笔记本并在结束后恢复。支持 4 种模式（`keyword`/`query`/`regex`/`sql`）、2 种范围（`headings`/`full`），可选限定笔记本。同一文档默认展示前 5 个命中块，可用 `max_snippets_per_doc` 调整。
- `siyuan_read_document`：读取可见文档，始终返回大纲（标题→block 位置映射）。默认按展示块窗口返回（`block_limit=200`、`token_budget=50000`），不截断字符。用 `block_start=N` 翻页。`include_block_ids=true` 进入引用阅读模式，自动插入 `<!-- siyuan:block id=... -->` HTML 注释，用于跨文档块引用和精确定位编辑。附件自动提取到 `ai_workspace/attachments/`，保留原始引用不变。
- `siyuan_create_document`：在可见笔记本中创建新文档。写入前自动创建思源工作空间快照；快照失败拒绝写入。必须 `confirmed=true`。用户可手动通过思源快照回滚。
- `siyuan_edit_document`：用 `old_text` → `new_text` 文本锚点在可见文档中编辑。`old_text=""` 追加到末尾，`new_text=""` 删除匹配文本。仅支持单块编辑，跨块文本返回错误需拆成多次调用。写入前自动创建快照。必须 `confirmed=true`。
- `siyuan_propose_guide_update`：把建议的指南更新保存到 `ai_workspace/`，不直接修改 AI Guide。
- `siyuan_apply_guide_update`：只有在用户明确批准后，才追加或替换思源系统笔记本中的 `AI 使用指南` / `AI Guide`（需 `confirmed=true`）。

## 长文档

长文档通过块窗口分页返回。默认窗口是 200 个展示块，50,000 token 预算。用 `block_start=N` 翻页，用 `block_limit`（1-1000）和 `token_budget`（1,000-200,000）调整窗口大小。

`siyuan_read_document` 始终先返回文档大纲（标题→block 位置映射）。标题少于 5 个且总展示块超过 100 时，会自动提供每 50 块的原文窗口预览片段。

## 隐私规则

隐私规则完全由用户在思源 UI 中维护，存放在系统笔记本 `思源代理桥` / `SiYuan Agent Bridge` 中的 `隐私规则` / `Privacy Rules` 文档，使用 Markdown 表格。

两张表格：

- `## 隐藏笔记本` / `## Hide Notebooks`：按 Notebook ID（优先）或 Notebook Name 隐藏整个笔记本。
- `## 隐藏文档` / `## Hide Documents`：按 Document ID 精确隐藏文档及其所有子文档。

`Hide` 列填 `yes` 启用，`no` 暂不启用。Reason 列仅供人类参考。

隐私规则文档修改后，告诉 AI"刷新一下"或在下次 `siyuan_start` / `siyuan_refresh_index` 时自动生效。如需临时开放，将对应行的 `Hide` 改为 `no`，交流完毕后再改回 `yes`。

> AI 不可读取、搜索、编辑或总结隐私规则文档。该文档被系统硬编码隔离。

## 系统笔记本

在思源中自动创建和维护 `思源代理桥` / `SiYuan Agent Bridge` 笔记本，包含四份系统文档：

| 文档 | 说明 |
|------|------|
| `AI 使用指南` / `AI Guide` | AI 的持久使用规则和偏好，用户在思源 UI 中编辑。不存在时自动创建，存在后不覆盖。 |
| `工作空间索引` / `Workspace Index` | AI 生成的语义导航索引，不自动创建。由 `siyuan-index-builder` skill 创建和更新。 |
| `关于 SiYuan Agent Bridge` / `About SiYuan Agent Bridge` | 给人看的工具说明，模板版本更新时自动覆盖。 |
| `隐私规则` / `Privacy Rules` | 人类维护的隐藏规则配置，MCP 内部解析，AI 不可读取。 |

## CC Switch 使用

Skill 可以用压缩包导入。运行以下命令打包：

```bash
python pack_skill.py
```

生成的 zip 在 `dist/` 目录下。

MCP 可以在 CC Switch 的"新增 MCP / 自定义"界面里填入：

```json
{
  "type": "stdio",
  "command": "python",
  "args": [
    "D:\\Github\\siyuan-agent-bridge\\plugins\\siyuan-agent-bridge\\scripts\\run_mcp.py"
  ],
  "env": {
    "PYTHONUTF8": "1"
  }
}
```

也可以参考：

```text
dist/siyuan-agent-bridge-mcp.json
dist/siyuan-agent-bridge-mcp-deeplink.txt
```

## 项目结构

```text
siyuan-agent-bridge/
  AGENTS.md                  # 项目开发指南（面向维护者）
  README.md                  # 中文说明（主版本）
  README.en.md               # 英文说明
  config.example.json        # 配置示例
  config.local.json          # 本机 token，已被 Git 忽略
  source_code/               # Python 工具代码
    client.py                #   思源 API client（读写）
    indexer.py               #   索引生成（tree.md + docs.jsonl）
    ignore.py                #   隐私规则解析（Markdown 表格）与过滤
    i18n.py                  #   多语言解析、系统名称映射、默认模板
    agent_notebook.py        #   系统笔记本服务层
    cli.py                   #   开发诊断入口
    mcp_server.py            #   MCP stdio server（9 tools）
  plugins/siyuan-agent-bridge/     # Skill 和 MCP 插件（含 skills/、scripts/、MCP 配置）
  knowledge_base/            # 生成的安全索引（tree.md, docs.jsonl, notebooks.json, privacy_rules.json）
  ai_workspace/              # AI 工作区（分析、草稿、附件）
  tests/                     # 测试
  dist/                      # 发布产物（Skill zip + MCP 配置）
```

`knowledge_base/` 里主要有：

- `tree.md`：两层文档树（笔记本概览表 + 各笔记本文档树），程序生成，每次 refresh 覆盖。
- `docs.jsonl`：文档级结构化数据（AI 不应直接读取）。
- `notebooks.json`：笔记本索引。
- `privacy_rules.json`：隐私规则缓存，从思源 Markdown 表格解析，每次 refresh 覆盖。

> AI Guide 和 Workspace Index 的主副本存放在思源系统笔记本中，跟随工作空间切换。`knowledge_base/` 中的本地文件是索引缓存，不包含用户偏好和导航索引。

## 隐私边界

这个项目按 private project 设计。

- 不要提交 token。
- 不要公开 `knowledge_base/` 和 `ai_workspace/`，除非你已经清理个人内容。
- AI 不应主动读取 `config.local.json`，除非你明确要求。
- AI 不应读取、搜索、编辑或总结隐私规则文档。
- AI 不应直接调用底层思源写 API（`updateBlock`、`appendBlock` 等）。只有在用户明确要求写入时，才使用 `siyuan_create_document` 或 `siyuan_edit_document`。
- 写入工具需要 `confirmed=true` 保护。写入前会自动创建思源工作空间快照，快照失败则拒绝写入。

如果未来要公开这个项目，需要重新设计隐私策略，并清理所有个人笔记索引和工作区材料。
