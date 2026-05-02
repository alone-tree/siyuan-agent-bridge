# SiYuan Agent Bridge

[English README](README.en.md)

SiYuan Agent Bridge 是一个私有、本地优先的思源笔记适配器。它让外部 AI agent 能像阅读代码仓库一样，先理解你的笔记结构，再按需读取具体文档。

它不是思源插件，不是公开项目，也不是向量检索系统。你的笔记仍然保存在思源里；这个工具只负责生成结构化索引，并通过 MCP 工具和 Skill 工作流给 AI 一个安全、可控的只读入口。

## 当前能力

- 扫描思源笔记本和完整文档树，包括子文档。
- **特别提示：关闭的笔记本会被自动临时打开，扫描完毕后恢复原状态。如果不想让AI看到，请使用隐藏规则进行管理。**该设计的核心考虑是，关闭与否取决于人类使用的便捷性，但关闭的笔记本不代表内部资料不重要，因此在建立和使用知识库时，仍然应当完整呈现。
- 按 `siyuan.ignore.local.json` 隐藏笔记本、单篇文档或整棵子文档树。
- 通过 `siyuan.allow.local.json` 临时开放隐藏内容，到期后自动失效。
- 生成 `knowledge_base/` 下的安全索引、总览和笔记本地图。
- 对可见文档计算完整字数，让 AI 可以把文档长度作为重要性信号。
- 提供 MCP 工具，让 Claude Code、Codex、OpenCode 等 agent 在安全索引范围内读取思源资料。**搜索和阅读时也会临时打开关闭的笔记本，以保持资料完整性。**
- 图文混排文档会保留 Markdown 图片引用，AI 可以按分段读取图片前后的文字上下文。
- 支持通过 CC Switch 导入 Skill 压缩包，并手动/JSON/deep link 注册 MCP。

## 日常怎么用

大多数时候你不需要自己使用命令行。

你主要维护这些文件：

- `knowledge_base/guide.md`：你维护的知识库阅读指南，告诉 AI 哪些主题、路径、笔记本最重要。
- `siyuan.ignore.local.json`：长期隐藏规则。
- `siyuan.allow.local.json`：临时开放规则。

典型流程：

1. 你在思源里正常写笔记。
2. 如果某些内容要隐藏，告诉 AI：“隐藏xx笔记本/xx文档”。对于文档，建议告诉AI文档ID而非文档名称，因为名称可能重复但ID不会。
3. AI会将指定内容加入隐藏规则，在AI看来，被隐藏的内容几乎相当于不存在。

**当前隐私保护功能缺陷：**不在文档树列表、检索会提示无结果、使用文档ID强制阅读会提示不存在。但如果可见文档中引用了该隐藏的文档，会留下引用痕迹，比如引用的块ID或者文档ID等。AI通过拿到隐藏文档的ID直接读取是不可行的。但在极端情况下，AI可能拿到文档ID并自行解除隐藏（通过使用MCP工具），进而能够阅读。目前暂时没有想到很好的办法，未来可能会开发图形化界面，将文档隐藏功能转为人工设定，不对AI开放任何接口（但现在还没有将其提上日程）。

## Agent 启动流程

如果 AI 工具已经注册了 MCP，直接让它使用你的思源笔记知识库即可。它应该调用：

```text
siyuan_start
```

这个工具会做三件事：

- 刷新安全索引，确保数据是最新的。
- 检查思源本地服务是否可用。
- 返回入口材料，包括笔记本概览表、`index.md`（如果存在）和 `knowledge_base/guide.md`。

如果 MCP 不可用，请先注册或修复 MCP。Python CLI 只作为开发诊断入口，不作为正常 AI 使用入口。

## MCP 工具

当前 MCP 提供这些只读工具：

- `siyuan_start`：刷新安全索引并返回启动包（含笔记本概览表、index.md（如存在）、guide.md）。始终最先调用。
- `siyuan_refresh_index`：在用户明确要求时，在会话中途刷新安全索引（siyuan_start 已在启动时刷新）。
- `siyuan_list`：无参数时列出所有可见笔记本；给定 `notebook_id` 时返回文档树，含字数和更新时间。
- `siyuan_find_documents`：通过思源搜索 API 检索标题/大纲/正文块，返回前应用隐藏规则过滤；搜索时会临时打开关闭的笔记本并在结束后恢复。支持 4 种模式（`keyword`/`query`/`regex`/`sql`）、2 种范围（`headings`/`full`），可选限定笔记本。同一文档默认展示前 5 个命中块，可用 `max_snippets_per_doc` 调整，并会报告总命中块数。
- `siyuan_read_document`：读取可见文档，始终返回大纲。隐藏文档即使已知 ID 也不会被读取，除非先显式临时开放。短文档返回全文，长文档每次返回一个分段，用 `chunk=N` 跳转。自动提取文档中的附件（图片、PDF、表格等）到 `ai_workspace/`，保留原始引用不变。
- `siyuan_propose_guide_update`：把建议的指南更新保存到 `ai_workspace/`，不直接修改指南。
- `siyuan_apply_guide_update`：只有在用户明确批准后，才追加或替换 `knowledge_base/guide.md`（需 `confirmed=true`）。
- `siyuan_privacy`：管理持久隐藏规则。`action="hide"` 隐藏，`action="unhide"` 取消，需 `confirmed=true`。隐藏 `document` 会隐藏该文档及其所有子文档。
- `siyuan_temporary_allow`：管理临时开放规则。`action="open"`（N分钟后过期，需 `confirmed=true`），`action="close"`（清除全部）。临时开放 `document` 会开放该文档及其所有子文档。

## 长文档

长文档不会再一次性完整返回，避免 MCP 客户端或模型界面在中间截断。

默认分段长度是：

```text
10,000 字符
```

AI 可以通过 `max_chars` 调整，当前允许范围是 2,000 到 30,000 字符。

`siyuan_read_document` 始终先返回文档大纲（标题→分段映射）。长文档用 `chunk=0` 读取第一段，或用 `chunk=N` 跳转到指定分段。

## 隐藏规则

打开：

```text
siyuan.ignore.local.json
```

隐藏整个笔记本：

```json
{
  "scope": "notebook",
  "name": "笔记本名称",
  "reason": "隐藏整个笔记本"
}
```

隐藏单篇文档：

```json
{
  "scope": "document",
  "id": "文档ID",
  "reason": "隐藏这一篇文档"
}
```

隐藏某篇文档和它下面所有子文档：

```json
{
  "scope": "subtree",
  "id": "父文档ID",
  "reason": "隐藏这篇文档和它下面的所有子文档"
}
```

改完后让 AI 刷新索引即可。旧索引里之前可见、现在被隐藏的内容会从新的 `knowledge_base/` 索引里移除。

## CC Switch 使用

Skill 可以用压缩包导入。当前最新生成的包在：

```text
dist/siyuan-agent-bridge-skill-latest.zip
```

MCP 可以在 CC Switch 的“新增 MCP / 自定义”界面里填入：

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
  siyuan.ignore.local.json   # 长期隐藏规则
  siyuan.allow.local.json    # 临时开放规则
  source_code/               # Python 工具代码
  plugins/siyuan-agent-bridge/  # Skill 和 MCP 插件材料
  knowledge_base/            # 生成的安全索引
  ai_workspace/              # AI 工作区
  tests/                     # 测试
```

`knowledge_base/` 里主要有：

- `guide.md`：你维护的知识库指南。
- `tree.md`：两层文档树（笔记本概览表 + 各笔记本文档树），默认不要让 AI 全扫第二层。
- `docs.jsonl`：文档级结构化数据（AI 不应直接读取）。
- `notebooks.json`：笔记本索引。
- `index.md`：AI 生成的语义导航索引（由 `siyuan-index-builder` skill 创建）。

> **已知限制**：`index.md` 通过 AI 的 Write/Edit 文件工具创建，因此 AI 会将文件写到**当前 IDE 工作目录**的 `knowledge_base/` 下，而非 bridge 项目目录的 `knowledge_base/`。如果在其他项目下让 AI 重建索引，请手动将生成的 `index.md` 复制到 bridge 项目的 `knowledge_base/` 中，或只在 bridge 项目内让 AI 重建。

`source_code/` 里主要有：

- `client.py`：只读思源 API client。
- `indexer.py`：扫描和生成索引。
- `ignore.py`：隐藏和临时开放规则。
- `cli.py`：开发诊断入口。
- `mcp_server.py`：MCP stdio server。

## 隐私边界

这个项目按 private project 设计。

- 不要提交 token。
- 不要公开 `knowledge_base/` 和 `ai_workspace/`，除非你已经清理个人内容。
- AI 不应主动读取 `config.local.json`、`siyuan.ignore.local.json` 或 `siyuan.allow.local.json`，除非你明确要求。
- AI 不应修改思源笔记，也不应调用思源写 API。

如果未来要公开这个项目，需要重新设计隐私策略，并清理所有个人笔记索引和工作区材料。
