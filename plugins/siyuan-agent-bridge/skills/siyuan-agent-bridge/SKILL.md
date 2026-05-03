---
name: siyuan-agent-bridge
description: Use when the user wants to read, search, or write their private SiYuan notes (思源笔记). Triggers on mentions of 思源, 知识库, or when the agent needs personal context from the user's notes.
---

# SiYuan Agent Bridge

通过 MCP 工具访问用户的思源笔记。不要扫描本地文件系统寻找笔记内容。

## Mandatory Startup

1. 调用 `siyuan_start` —— 刷新安全索引，确保系统笔记本 `思源代理桥` 及其文档就绪，返回启动包（笔记本概览表、Workspace Index（如存在）、AI Guide）。
2. 阅读返回的启动包。
3. **以 Workspace Index 为导航主入口。** 快速导航表将用户意图映射到笔记本，笔记本详情是 AI 扫描后浓缩的结构摘要和判断——信任它来定位相关笔记本。
4. 若启动包不包含 Workspace Index，提示用户："我可以先快速扫一遍你的笔记本结构，创建一个导航索引（Wiki Index），之后每次新会话都能更快定位。"
5. 用 `siyuan_list`（带 `notebook_id`）查看单个笔记本的文档树，含字数和更新时间。
6. 用 `siyuan_read_document` 按需深读。始终按展示块窗口返回，不截断字符。始终返回大纲（标题→block 位置映射）。长文档用 `block_start=N` 翻页继续阅读，用 `block_limit` 和 `token_budget` 控制窗口大小。需要精确跨文档块引用或编辑定位时，开启 `include_block_ids=true`（引用阅读模式）。
7. 遵循启动包中 `AI Guide` 的持久偏好。系统笔记本 `思源代理桥` 中还有一篇 `/About SiYuan Agent Bridge`（给人看的说明），普通任务无需读取。

若 MCP 工具不可用，告知用户 SiYuan Agent Bridge MCP 未注册或不可达。不要回退到扫描文件。

## Tool Use Hints

完整参数说明由 MCP `tools/list` 提供。以下仅标注非显而易见的要点：

**读取工具：**
- `siyuan_start` —— 始终最先调用。
- `siyuan_find_documents` —— 搜索知识库，通过思源 API 实时搜索后经隐私规则过滤返回结果。
- `siyuan_read_document` —— 只读取可见文档；隐藏文档即使已知 ID 也不会被读取，除非先显式临时开放。附件（图片、PDF 等）自动提取到 `ai_workspace/attachments/<doc-id>/`，保留原始引用。`block_limit=200`、`token_budget=50000` 按展示块窗口返回，不截断字符。用 `block_start=N` 翻页继续阅读。大纲显示标题所在 block 位置。`include_block_ids=true` 进入引用阅读，自动在块前插入 `<!-- siyuan:block id=... type=... -->` HTML 注释，用于跨文档块引用和精确定位编辑。
- `siyuan_privacy` / `siyuan_temporary_allow`（open）—— 必须 `confirmed=true`，仅在用户明确批准后设置。`document` 表示该文档及其所有子文档。

**写入工具：**
- `siyuan_create_document` —— 在可见笔记本中创建新文档。`path` 支持嵌套路径（如 `/父文档/子文档`），可在已有文档下创建子文档。正文不需要重复写与文档标题相同的一级标题（`# title`），除非你想让正文大纲标题与文档树标题不同。写入前自动创建思源工作空间快照；快照失败拒绝写入。创建成功后自动刷新索引。必须 `confirmed=true`。
- `siyuan_edit_document` —— 用 `old_text` → `new_text` 文本锚点在可见文档中编辑。`old_text=""` 将 `new_text` 追加到文档末尾；`new_text=""` 删除匹配文本。不支持跨块文本（遇到时返回错误，需拆成多次单块编辑）。写入前自动创建快照。必须 `confirmed=true`。

## Safety Rules

- 不要直接调用底层思源写 API（updateBlock、appendBlock、deleteBlock 等）。
- 只有在用户明确要求写入时，才使用 `siyuan_create_document` 或 `siyuan_edit_document`。
- 写入前告知用户将要修改的内容。
- 写入工具必须 `confirmed=true`，仅在用户明确批准后设置。
- 不要尝试自动回滚。如果用户要回滚，提示用户在思源快照中手动恢复。
- 不要读取 `config.local.json`、`siyuan.ignore.local.json`、`siyuan.allow.local.json`，除非用户明确要求。
- 不要暴露被隐藏的笔记本或文档名称，除非用户明确要求。
- 不要全量扫描 `knowledge_base/tree.md` —— 使用 `siyuan_start` 返回的概览表。
- 长文档不要一次性塞进回复 —— 使用 `siyuan_read_document` 的 `block_start` 参数分段翻页读取。
- 派生分析和草稿放在 `ai_workspace/`。

## Cross-References

- **导航索引创建**：触发 `siyuan-index-builder` skill。
- **项目开发**：见仓库 `AGENTS.md`（面向维护者）。
