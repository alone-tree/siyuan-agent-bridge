---
name: siyuan-agent-bridge
description: Use when the user wants to read, search, or write their private SiYuan notes (思源笔记). Triggers on mentions of 思源, 知识库, or when the agent needs personal context from the user's notes.
---

# 思源桥

通过 MCP 工具访问用户的思源笔记。不要扫描本地文件系统寻找笔记内容。

## 启动流程

1. 调用 `siyuan_start` —— 刷新安全索引，确保系统笔记本及其文档就绪，返回启动包（语言偏好、笔记本概览表、工作空间索引（如存在）、AI 使用指南、隐私规则状态）。
2. 阅读返回的启动包。
3. **遵循启动包中的语言偏好。** 除非用户明确要求，否则使用启动包声明的语言回复用户。
4. **以工作空间索引为导航主入口。** 快速导航表将用户意图映射到笔记本，笔记本详情是 AI 扫描后浓缩的结构摘要和判断——信任它来定位相关笔记本。
5. 若启动包不包含工作空间索引，提示用户："我可以先快速扫一遍你的笔记本结构，创建一个导航索引，之后每次新会话都能更快定位。"
6. 用 `siyuan_list`（带 `notebook_id`）查看单个笔记本的文档树，含有效权限、字数和更新时间。
7. 用 `siyuan_read` 按需深读。始终按展示块窗口返回，不截断字符。始终返回大纲（标题→block 位置映射）。长文档用 `block_start=N` 翻页继续阅读，用 `block_limit` 和 `token_budget` 控制窗口大小。需要精确跨文档块引用或编辑定位时，开启 `include_block_ids=true`（引用阅读模式）。
8. 遵循启动包中 AI 使用指南的持久偏好。系统笔记本 `思源桥` 中还有一篇 `/关于思源桥`（给人看的说明），普通任务无需读取。

若 MCP 工具不可用，告知用户思源桥 MCP 未注册或不可达。不要回退到扫描文件。

## 隐私规则

- 隐私规则完全由用户在思源中维护，通过系统笔记本中的 `隐私规则` / `Privacy Rules` 文档的 Markdown 表格控制。
- `siyuan_privacy` 和 `siyuan_temporary_allow` 工具已被移除。AI 无法修改隐私规则。
- AI 不能读取、搜索、总结或编辑隐私规则文档。该文档被系统硬编码隔离。
- 如需临时开放隐藏或只读内容，用户在思源中手动将权限改为 读写 即可；交流完毕后再改回原权限。
- 隐私规则文档修改后，告诉 AI"刷新一下"或在下次 `siyuan_start` / `siyuan_refresh_index` 时自动生效。
- 如果隐私规则解析失败，AI 会收到可定位的错误信息（表格名、行号、字段名和错误类型），但不会包含具体隐藏的笔记本名称、文档 ID 或标题。

## Tool Use Hints

- `siyuan_start` —— 始终最先调用。返回语言偏好、笔记本概览、Workspace Index、AI Guide、隐私规则状态。
- `siyuan_find` —— 搜索知识库，通过思源 API 实时搜索后经隐私规则过滤返回结果。
- `siyuan_read` —— 只读取可见文档；隐藏文档和隐私规则文档即使已知 ID 也不会被读取。
- `siyuan_list` —— 返回可见笔记本/文档的有效权限。`read_write` 可写，`read_only` 只能读取、复制或导出；隐私规则文档和隐藏内容不会出现在列表中。
- `siyuan_create`、`siyuan_edit` —— 写入工具。始终 `confirmed=true`。写入前自动创建思源工作空间快照。默认不写入，除非用户明确要求。
- `siyuan_create` 优先传完整可读路径 `path=/Notebook/Folder/Doc`；只有笔记本名称重名或使用内部路径时才补充 `notebook_id`。目标已存在时默认 `if_exists=reject`，可显式用 `overwrite` 清空块后重写并保留文档 ID，或用 `create_new` 新增同名文档。
- `siyuan_create` 成功后会等待思源路径同步并自动刷新安全索引；正常情况下可直接使用返回路径继续读取或管理。
- 编辑已有文档前，先用 `siyuan_read(include_block_ids=true)` 进行引用阅读，并把返回的块序号和块 ID 作为 `siyuan_edit` 定位参数。
- `siyuan_doc_manage` —— 管理文档树。`rename/move/delete/copy` 需要用户明确要求和 `confirmed=true`；`rename/move/delete` 还需要可写权限。`delete` 会删除整棵子树，子孙文档也必须全部可写；`move` 保留子树权限，但如果源文档来自只读/隐藏祖先路径则拒绝移动。`copy` 必须传完整 `target_path`，只复制源文档本身，不复制子文档。`export` 只导出可读文档到 `ai_workspace/exports/`。
- `siyuan_doc_manage` 的 rename/move/copy/delete 成功后会等待路径同步并自动刷新安全索引；如果返回提示路径同步超时，临时改用 `document_id` 或显式调用 `siyuan_refresh_index`。
- 编辑普通 Markdown 表格时，使用引用阅读返回的网格坐标：`row=0` 是表头，`row>=1` 是数据行，`column_index` 从 1 开始。表格不是数据库，不要把表头、字段或多维表语义混在一起。
- `siyuan_refresh_index` —— 会话中途刷新安全索引，不清理 `ai_workspace/`。只有 `siyuan_start` 会在新会话启动时清理 workspace。
- 系统笔记本 `思源桥` / `SiYuan Bridge` 及其文档会被自动创建和维护。

## Safety Rules

- 不要修改思源笔记中的隐私规则文档。
- 不要尝试读取、搜索或总结隐私规则文档。
- 不要读取 `config.local.json`、`siyuan.ignore.local.json`、`siyuan.allow.local.json`，除非用户明确要求。
- 不要暴露被隐藏的笔记本或文档名称，除非用户明确要求。
- 不要全量扫描 `knowledge_base/tree.md` —— 使用 `siyuan_start` 返回的概览表。
- 长文档不要一次性塞进回复 —— 使用 `siyuan_read` 的 `block_start` 参数分段翻页读取。
- 派生分析和草稿放在 `ai_workspace/`。
- 系统笔记本中的文档不作为用户原始资料。不要把 AI Guide、Workspace Index、About 中的内容当作用户的知识库内容。

## Cross-References

- **导航索引创建**：触发 `siyuan-index-builder` skill。
- **项目开发**：见仓库 `AGENTS.md`（面向维护者）。
