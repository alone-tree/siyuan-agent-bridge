# SiYuan Agent Bridge 项目工程文档

## 什么是 SiYuan Agent Bridge

一个私有、本地优先的适配层，让外部 AI agent（Claude Code、Codex 等）能将用户的思源笔记当作结构化知识库来阅读和搜索。这不是一个公开发布的产品——它的首要用户是开发者自己，在自己的机器上跑通全流程之后，再考虑对外打包。

**核心问题**：AI 会话是无状态的，每次新会话 AI 对用户的笔记结构一无所知。如果 AI 盲目扫描所有笔记文件，隐私有风险，效率也低。

**解决方案**：提供一个结构化的"知识库壳层"——每次会话启动时，AI 先拿到一个精简的导航包（笔记本概览 + 人工指南 + 可选索引），了解"有什么"和"去哪找"，再按需深入阅读。

---

## 架构总览

```
思源笔记 (本地 HTTP API, http://127.0.0.1:6806)
    │
    ▼
source_code/  (Python 适配层)
    ├── client.py        → 只读 HTTP API 封装
    ├── indexer.py       → 扫描笔记本 → 生成 tree.md + docs.jsonl
    ├── ignore.py        → 隐私规则解析（Markdown 表格）与过滤
    ├── i18n.py          → 多语言解析、系统名称映射、默认模板
    ├── agent_notebook.py → 系统笔记本服务层（确保系统文档就绪）
    ├── config.py        → 多 URL / token 配置加载
    ├── cli.py           → 早期辅助 CLI（开发诊断用，非主要接口）
    └── mcp_server.py    → MCP stdio server — 面向 AI 的主要接口，暴露 9 个工具给 AI（含 2 个写入工具）
    │
    ▼
knowledge_base/  (生成的安全索引，每次 refresh 覆盖)
    ├── tree.md          → 两层文档树（程序生成）
    ├── docs.jsonl       → 结构化文档元数据（AI 不直接读）
    ├── notebooks.json   → 笔记本索引（程序消费）
    └── privacy_rules.json → 隐私规则缓存（从思源 Markdown 表格解析后写入）
    │
    ▼
思源系统笔记本 思源桥/  (用户指南和 AI 导航，跟随工作空间)
    ├── AI Guide             → AI 使用规则和用户偏好（确保不覆盖）
    ├── Workspace Index      → AI 语义导航索引（siyuan-index-builder skill）
    ├── About SiYuan Bridge → 给人看的工具说明（版本标识覆盖）
    └── Privacy Rules        → 人类维护的隐藏规则（AI 不可读）
    │
    ▼
plugins/siyuan-agent-bridge/  (面向 AI 的指令层)
    ├── skills/siyuan-agent-bridge/SKILL.md        → 总入口 skill："如何使用思源笔记知识库"
    ├── skills/siyuan-index-builder/SKILL.md    → 专项 skill："如何创建结构化索引"
    └── scripts/run_mcp.py                      → MCP stdio 启动脚本
```

### 关键设计决策

**两层索引分离**：程序生成的客观索引（`tree.md`）和 AI 生成的语义索引（`Workspace Index`）各自独立，互不依赖。
- `tree.md` 是客观事实层——脚本扫描生成，保证完整性，每次 refresh 覆盖。
- `Workspace Index` 是语义导航层——AI 阅读后手写，含摘要和判断，增量更新。主副本存放在思源系统笔记本中，跟随工作空间切换。

**安全索引原则**：所有给 AI 的数据都经过隐私规则过滤。隐藏的笔记本/文档在索引层面就被移除，AI 感知不到它们的存在。

**关闭笔记本原则**：思源的"关闭笔记本"仅被视为运行态（思源前台不加载），不被视为知识库排除规则。是否纳入 AI 知识库由隐私规则和索引规则决定。适配层在后台自动临时打开关闭的笔记本完成操作，结束后恢复原状态。AI 不直接操作笔记本开关。

**MCP-first 架构**：项目的产品界面是 MCP + Skill，面向 AI agent 设计。CLI 命令（`python -m source_code ...`）是早期开发时的辅助工具，仅用于人工诊断和调试，正常情况下不应被使用。所有功能的实现应以 MCP 工具为第一优先级。

---

## 系统架构

### 三个概念层

| 层 | 作用 | 执行者 | 产物 |
|----|------|--------|------|
| **数据采集层** | 从思源 API 拉取笔记本列表和原始文档块 | Python 脚本 / MCP 工具 | 内存中的数据结构 |
| **过滤与索引层** | 应用隐私忽略规则，过滤后生成结构化索引 | `indexer.py` + `ignore.py` | `tree.md` + `docs.jsonl` + `notebooks.json` |
| **能力暴露层** | 通过 MCP 协议向 AI 暴露读写工具 | `mcp_server.py` (9 tools) | AI 可调用的语义能力 |

### 数据层

| 文件 | 性质 | 用途 |
|------|------|------|
| `tree.md` | 程序生成，覆盖 | 笔记本概览表 + 每笔记本完整文档树（含字数和更新时间）。两层结构，AI 默认只看第一层。 |
| `docs.jsonl` | 程序生成，覆盖 | 每行一个文档的结构化元数据（id、路径、字数、tags 等）。AI 不直接读，由 MCP 工具动态查询。 |
| 思源 `AI Guide` | 确保存在，不覆盖 | 用户对 AI 的持久偏好和工作风格指引。存放在思源系统笔记本中，用户可在思源 UI 中编辑。 |
| 思源 `Workspace Index` | 不自动创建，AI 按需维护 | 语义导航索引：快速路由表 + 每笔记本结构摘要 + AI 摘要。由 `siyuan-index-builder` skill 创建和更新。 |
| 思源 `About SiYuan Bridge` | 确保存在，版本标识触发覆盖 | 给人看的工具说明，精简概括核心思想和用法。内容跟随项目版本更新。 |

### 指令层

指令层遵循**单一信息源**原则：每条规则只在唯一的文件中维护，通过交叉引用连接。

| 文件 | 定位 | 内容 |
|------|------|------|
| `plugins/…/SKILL.md` | 工作流入口 | Mandatory Startup 7 步流程、Tool Use Hints（非显而易见的要点）、Cross-References |
| AGENTS.md | 项目开发指南 | 项目结构、架构、开发命令（面向维护者） |
| `AI Guide`（思源） | 用户偏好 | 用户维护的持久工作风格和重点笔记本指引 |

**设计决策**：

- SKILL.md 不重复工具参数描述（MCP `tools/list` 已提供完整 schema）。
- SKILL.md 内联安全规则（7 条 `## Safety Rules`），不依赖外部文件——skill 必须可独立加载。
- AGENTS.md 面向项目维护者（开发指南、架构、命令），不面向使用者。
- SKILL.md 的 `## Tool Use Hints` 仅标注 4 个非显而易见的要点，不逐条罗列参数。

| Skill | 触发条件 | 核心指令 |
|-------|----------|---------|
| `siyuan-agent-bridge` | 用户提到思源/知识库/笔记 | 强制调用 siyuan_start 获取启动包 → 以 Workspace Index 导航 → 按需深读 |
| `siyuan-index-builder` | 用户要求建索引/更新索引 | 遍历笔记本结构 → 阅读关键文档 → 为每个笔记本写结构摘要和 AI 摘要 → 写入 `思源桥/Workspace Index` |

---

## 完整数据流（用户使用流程）

### 步骤 1：安装部署

用户通过 CC Switch 安装 Skill 压缩包 (`dist/siyuan-agent-bridge-skill-<ts>.zip`)，并注册 MCP stdio 配置。Skill 和 MCP 注册到 AI 工具后即可使用。

### 步骤 2：会话启动

用户启动 Claude Code / Codex，AI 获得 MCP 工具列表和 Skill 指令。此时 AI 还不知道知识库内容，等待用户触发。

### 步骤 3：用户触发

用户说"帮我查一下笔记里关于光模块的内容"，触发 `siyuan-agent-bridge` skill。

### 步骤 4：Skill 给出初步指令

Skill 指令要求 AI 必须首先调用 `siyuan_start`，不要直接扫描文件或调用其他工具。

### 步骤 5：siyuan_start 执行

`siyuan_start` 是门面工具，内部完成：

**5a. 连接检查** — 尝试连接思源 API
- 思源未启动 → 返回连接错误 → AI 提示用户"请先启动思源笔记软件"
- 思源已启动 → 继续

**5b. 索引刷新** — 调用 `refresh_index()`
- 通过 SQL 查询所有文档块（`type='d'`，含 `content`、`hpath`、`tag`、`updated` 等列）
- 解析思源系统笔记本中的 `隐私规则` / `Privacy Rules` Markdown 表格，应用隐私规则过滤隐藏内容
- 计算每篇文档的字数（CJK 字符数 + 英文单词数）
- 生成 `tree.md`（两层结构）和 `docs.jsonl`

**5b1. 启动包组装** — 返回内容根据 Workspace Index 是否存在分两种情况：

| 条件 | 返回内容 |
|------|---------|
| Workspace Index 存在 | 笔记本概览表（tree.md 第一层）+ Workspace Index 全文 + AI Guide |
| Workspace Index 不存在 | 笔记本概览表（tree.md 第一层）+ AI Guide + 提示 AI 可建议用户先创建导航索引 |

**tree.md 每篇文档包含的元数据**：
- 文档 ID（思源块 ID，唯一标识）
- hpath（文档在笔记本中的路径，如 `/投资研究笔记/专题研究/REITs`）
- 字数（中文字符 + 英文单词）
- 块数（文档下所有块的计数，含标题、段落、列表等）
- 更新时间（`YYYY-MM-DD` 格式）
- Tags（从思源 tag 字段解析）

### 步骤 6：AI 根据启动包做后续判断

**6a. 创建/更新索引** — 如果用户要求建索引，或 AI 判断需要导航（Workspace Index 不存在），调用 `siyuan-index-builder` skill：
- 遍历 tree.md 中每个笔记本的结构
- 用 `siyuan_read_document` 阅读每个笔记本的入口文档和重要文档
- 按模板生成 Workspace Index：快速路由表 + 每笔记本结构描述 + AI 摘要
- 通过 `siyuan_create_document` / `siyuan_edit_document` 写入 `思源桥/Workspace Index`
- 增量更新时保留人工标注（priority、更正）

**6b. 直接使用现有索引** — 从 Workspace Index 快速路由表定位目标笔记本，从 tree.md 第一层确认该笔记本规模，然后用 `siyuan_list`（带 `notebook_id`）看该笔记本的文档树。

### 步骤 7：搜索（siyuan_find_documents）

当 AI 需要精确检索时，调用 `siyuan_find_documents`：

1. 发起搜索（4 种模式）：keyword/query/regex/sql
2. 搜索范围（2 种）：headings（仅标题和大纲标题）/ full（所有块正文）
3. 搜索结果经过隐私规则过滤后返回
4. 返回格式：按笔记本分组，每条含文档 ID、hpath、字数、更新时间；同一文档下保留所有命中的块片段，避免只展示第一处命中

### 步骤 8：阅读文档（siyuan_read_document）

AI 判断需要深读某篇文档时：

| 文档长度 | 行为 |
|----------|------|
| 任意文档 | 始终返回文档大纲（标题→block 位置映射）+ 块窗口内容 |

大纲格式：解析 DisplayBlock 中的标题块，标注每个标题所在的 block 位置。AI 可以直观看到文档结构和内容的对应关系。

### 步骤 9：翻页续读

AI 阅读完当前窗口后，按需用 `block_start=N` 继续翻页读取后续内容，而不是一次性吞下整篇长文档。

---

## MCP 工具清单

| # | 工具 | 参数 | 行为 | 访问思源 API |
|---|------|------|------|:---:|
| 1 | `siyuan_start` | 无 | 刷新索引 + 确保系统笔记本 + 返回启动包（含语言偏好、Workspace Index 条件返回、隐私规则状态） | ✓ |
| 2 | `siyuan_refresh_index` | 无 | 手动刷新安全索引 | ✓ |
| 3 | `siyuan_list` | `notebook_id`? 或 `notebook_name`? | 无参数时列出所有可见笔记本；给定 notebook 时返回文档树（含字数、更新时间、tags） | ✗ 本地 |
| 4 | `siyuan_find_documents` | `keyword` + `mode` + `scope` + `notebooks`? + `limit`? | 搜索知识库，隐私过滤后返回 | ✓ |
| 5 | `siyuan_read_document` | `document_id` + `block_start`? + `block_limit`? + `token_budget`? + `include_block_ids`? | 返回大纲；按展示块窗口返回内容 | ✓ |
| 6 | `siyuan_propose_guide_update` | `proposal` + `title`? + `body`? | 保存到 `ai_workspace/` | ✗ |
| 7 | `siyuan_apply_guide_update` | `content` + `mode` + `confirmed` | 追加或替换 AI Guide（思源系统笔记本中） | ✗ |
| 8 | `siyuan_create_document` | `notebook_id` + `title` + `path`? + `markdown` + `confirmed` | 在可见笔记本中创建新文档；写前自动创建快照；快照失败拒绝写入 | ✓ |
| 9 | `siyuan_edit_document` | `document_id` + `old_text` + `new_text` + `confirmed` | 文本锚点编辑；old_text=""追加，new_text=""删除；仅支持单块编辑 | ✓ |

### 工具能力分类

```
入口层:   siyuan_start           → 始终第一个调用
导航层:   siyuan_list            → 无参数=列出笔记本；给 notebook_id=查看文档树
搜索层:   siyuan_find_documents  → 在多笔记本间定位相关文档
阅读层:   siyuan_read_document   → 获取文档的 Markdown 正文
写入层:   siyuan_create_document → 在可见笔记本中创建新文档（需 confirmed=true）
         siyuan_edit_document    → 文本锚点编辑可见文档（需 confirmed=true）
维护层:   siyuan_refresh_index   → 中途刷新，清理 ai_workspace
         siyuan_propose/apply_guide_update → 维护 AI Guide
```

### 搜索模式详解

| mode | 实现 | 适用场景 |
|------|------|---------|
| `keyword` | 思源全文搜索 API method=0，空格分隔 AND 匹配 | 日常搜索，覆盖面广 |
| `query` | 思源全文搜索 API method=1，支持 AND/OR/NOT/`"短语"`/`前缀*` | 精确逻辑组合 |
| `regex` | 思源全文搜索 API method=3，Go RE2 正则（无回溯/反向引用） | 模式匹配 |
| `sql` | 直接执行 SQL 语句 | 跨表查询、统计、按更新时间排序 |

| scope | 搜索范围 |
|-------|---------|
| `headings` | 仅文档标题和大纲标题 |
| `full` | 所有块的正文（段落、列表等） |

**搜索实现原则**：

- 搜索召回只使用思源 API，不再同时走本地索引和 API 两套召回逻辑。
- `docs.jsonl` 仍用于启动包、文档树、统计信息、隐私规则编译和搜索结果元数据补全，但不参与搜索匹配。
- 搜索结果在 MCP server 内部按隐藏规则过滤后才返回给 AI；未通过过滤的 API 原始结果不展示。
- 搜索和阅读一样遵守关闭笔记本原则：查询前临时打开关闭的笔记本，完成后恢复原状态。
- `scope=full` 使用块级结果生成正文片段；同一文档内的多个命中块都应保留，避免 AI 误判文档里只有一处相关内容。
- 返回结果默认每篇文档最多展示 5 个命中块，可用 `max_snippets_per_doc` 调整；每篇文档仍报告总命中块数和实际展示数量。

---

## 隐私模型

### 隐私规则主副本

隐私规则完全由人类在思源系统笔记本 `思源桥` / `SiYuan Bridge` 中的 `隐私规则` / `Privacy Rules` 文档维护，使用 Markdown 表格。AI 无法读取、搜索、编辑或总结该文档——它被系统硬编码隔离。

每次 `siyuan_start` 或 `siyuan_refresh_index` 时，MCP server 内部解析该文档的表格，生成 `knowledge_base/privacy_rules.json` 缓存供其他工具使用。解析失败时操作中止并返回可定位的错误信息（表格名、行号、字段名、错误类型），但不暴露具体隐藏内容。

### 规则分层

```
思源 隐私规则 文档（Markdown 表格） → 人类在思源 UI 中维护
knowledge_base/privacy_rules.json   → MCP 内部缓存（自动生成，不暴露给 AI）
```

### 作用域

| scope | 效果 |
|-------|------|
| `notebook` | 隐藏整个笔记本及其所有文档 |
| `document` | 隐藏该文档及其所有子文档 |
| `subtree` | 与 `document` 同义，保留用于显式表达”隐藏整棵子树”和兼容旧规则 |

**隐私语义决策**：

- `document` 和 `subtree` 都会同时隐藏根文档和所有子文档，避免通过路径层级泄露父文档名称。

### 表格格式

隐私规则文档包含两张表格：

- `## 隐藏笔记本` / `## Hide Notebooks`：支持按 Notebook ID（精确匹配）或 Notebook Name（同名全部隐藏）隐藏笔记本。
- `## 隐藏文档` / `## Hide Documents`：必须填写 Document ID 精确匹配。Title 仅供人类确认，不参与匹配。

`Hide` 列填 `yes` 才启用；`no` 表示暂不启用。支持表头别名兼容（`Hide`/`Enabled`、`笔记本ID`/`Notebook ID` 等）。

### 过滤时机

隐私过滤发生在索引生成阶段（`refresh_index`），以及每次搜索/阅读时：
- 被隐藏的文档不会出现在 `tree.md`、`docs.jsonl`、`notebooks.json` 中
- 被隐藏文档的子文档也不会出现在 `tree.md`、`docs.jsonl` 和 `siyuan_list` 中
- `siyuan_find_documents` 使用思源 API 实时搜索，返回前在 MCP server 内部应用隐私规则
- `siyuan_read_document` 读取前必须在可见文档集合中解析；隐藏文档和隐私规则文档即使已知 ID 也不会被读取
- 如需临时开放隐藏内容，用户应在思源中手动将表格中的 `Hide` 改为 `no`，交流完毕后再改回 `yes`
- 隐私规则文档修改后，告诉 AI”刷新一下”或下次 `siyuan_start`/`siyuan_refresh_index` 时自动生效

### 系统笔记本保护

系统笔记本 `思源桥` / `SiYuan Bridge` 及其文档不能被隐藏。`siyuan_create_document` 拒绝创建隐私规则文档路径。

### AI 安全规则

- AI 不应读取 `config.local.json`
- AI 不应尝试读取、搜索、总结或编辑隐私规则文档
- AI 不应暴露被隐藏的笔记本或文档名称，除非用户明确要求

---

## 当前实现状态



### 已完成

- [x] tree.md 两层结构（笔记本概览表 + 文档树），含 ID、字数、更新时间、tags
- [x] docs.jsonl 结构化数据 + notebooks.json 笔记本索引
- [x] `siyuan_start` 自动 refresh + 返回启动包（含语言偏好、AI Guide、Workspace Index、隐私规则状态）
- [x] 系统笔记本 `思源桥` / `SiYuan Bridge` 自动创建和维护，含四份系统文档
- [x] 隐私规则迁移到思源 Markdown 表格——人类在思源 UI 中维护，MCP 内部解析，AI 不可读取
- [x] `siyuan_privacy` 和 `siyuan_temporary_allow` MCP 工具已移除——隐私规则完全由人类控制
- [x] 多语言策略：中文默认，英文兼容，语言偏好进入启动包
- [x] `siyuan-agent-bridge` SKILL.md 更新：Mandatory Startup 明确 AI 优先使用 Workspace Index 快速路由表
- [x] 思源未启动时的友好提示：连接失败时返回"思源笔记似乎没有启动。请打开思源笔记软件后重试。"而非技术错误堆栈
- [x] `siyuan_read_document` 大纲 + 块窗口分页翻读
- [x] `siyuan_find_documents` 4 种 mode × 2 种 scope，隐私过滤
- [x] `siyuan_list` 动态从 docs.jsonl 生成文档树
- [x] 隐私规则过滤（notebook/document/subtree）+ 临时开放
- [x] `siyuan-index-builder` skill 完整流程（快速/详细两种深度）
- [x] `guide.md` 的人工维护模式（ensure 不覆盖）
- [x] 代码去重：`build_notebook_overview()` 单一定义
- [x] 单元测试覆盖
- [x] **MCP 隐私工具**：2 个工具（合并为 `siyuan_privacy` + `siyuan_temporary_allow`），confirmed=true 保护
- [x] **`siyuan_refresh_index` 清理 ai_workspace**：每次 refresh 清空临时文件，保留 README.md
- [x] **Bug 修复**：`find_documents()` haystack 补全 alias/memo 字段；FTS paths 参数格式修正
- [x] **隐私安全加固**：`_enrich_search_blocks()` 对不在安全索引中的文档一律跳过（`continue`），防止 FTS 实时搜索结果绕过隐私过滤。正确性由 `ensure_notebooks_open` 保证——refresh 时已打开所有笔记本，可见文档全量入索引
- [x] **搜索改为 API-only 召回**：`siyuan_find_documents` 不再合并本地索引搜索结果和 API 搜索结果，而是统一使用思源搜索 API 召回，再在 MCP server 内部按隐私规则过滤并补全文档元数据
- [x] **Skill 打包**：`dist/siyuan-agent-bridge-skill-<ts>.zip` 含隐私工具和 index.md 指令
- [x] **关闭笔记本自动开关**：`ensure_notebooks_open` 上下文管理器，在索引刷新、文档读取、FTS/SQL 搜索时自动临时打开关闭的笔记本，用完恢复原状态。AI 不感知也不操作笔记本开关
- [x] **统计指标重构**：删除从未使用的 `index_word_count` 和 `markdown_chars`，新增 `block_count`（文档子块数）和 `char_count`（原始字符数，与分块的 `len()` 对齐）。索引刷新从 424 次 `export_markdown()` HTTP 调用优化为 2 条 SQL 查询（GROUP BY + 全块内容），耗时从 ~30s 降到 ~2s。所有展示（tree.md、siyuan_list、搜索结果、read_document 文档头）同步显示块数和字符数
- [x] **附件提取**：`siyuan_read_document` 自动提取文档中所有资源文件（图片、PDF、xlsx 等）到 `ai_workspace/attachments/<doc-id>/assets/`，保留原始文件名和目录结构。Markdown 原文不动，AI 按文件名自行对应。文档头显示附件数量，无附件不提。`siyuan_refresh_index` 自动清理
- [x] **写入功能第一阶段**：`siyuan_create_document` + `siyuan_edit_document` 两个 MCP 工具。文本锚点模式——AI 传入 `old_text`（从 Markdown 读到的原文片段），服务端在块级搜索匹配后执行块操作。只支持单块编辑；跨块文本返回错误。写前自动创建思源工作空间快照；快照失败拒绝写入。写入后 pushMsg 通知思源前台。隐藏内容不可写。所有写入工具必须 `confirmed=true`
- [x] **WinError 10054 连接重置修复**：思源 Go HTTP 服务器默认启用 keep-alive，空闲超时后关闭连接；Python urllib 尝试复用死连接时触发 WSAECONNRESET（10054）。修复：所有 HTTP 请求添加 `Connection: close` 头，每次请求后关闭连接；连接错误自动重试 3 次（间隔 0.3s/0.6s）。错误消息同时改进为显示具体原因而非笼统的"似乎没有启动"
- [x] **块 ID 嵌入可选模式**：`siyuan_read_document` 新增 `include_block_ids` 参数（默认 `false`）。当 `include_block_ids=true` 时，通过 `/api/block/getChildBlocks` 按思源返回的真实子块顺序遍历块树，重建一份引用阅读 Markdown 视图，插入 `<!-- siyuan:block id=... type=... -->` HTML 注释。跳过文档块、列表容器块和空块；列表项、表格这类自身 Markdown 已包含子内容的块会阻止继续渲染其子孙，避免重复；超级块只显示块 ID 注释并继续遍历子块。新增 `client.get_child_blocks()`；保留 `client.list_document_blocks()` 作为 SQL 诊断能力。单元测试 70 个全部通过。
- [x] **块窗口阅读模式（Block Window）**：`siyuan_read_document` 默认按展示块窗口返回，不再按字符 chunk 截断。新增 `DisplayBlock` 数据模型，通过 `/api/block/getChildBlocks` 按思源真实子块顺序构建展示块列表。新增 `block_start`（默认 1）、`block_limit`（默认 200，1-1000）、`token_budget`（默认 50000）参数。大纲显示标题所在的 block 位置。标题少于 5 个且总展示块超过 100 时，每隔 50 个块提供原文开头片段作为窗口预览。`include_block_ids=true` 对外称为"引用阅读"。旧 `chunk/max_chars` 路径保留为兼容降级方案。参见 PD.md 问题 1。

### 待实现

- [ ] **`siyuan_temporary_allow` 等价功能**：当前隐私规则由人类在思源中手动修改表格的 `Hide` 列来临时开放/关闭。未来可考虑更便捷的临时开放机制（如时效性自动恢复），但核心原则不变——AI 不能自主修改隐私规则。

---

## 设计讨论与待决策问题

以下是在设计过程中识别出的开放问题，记录了各种方案的权衡分析。随着项目推进，这些讨论的结论应逐步移入对应的设计章节。

### 问题 1：长文档分段 — Chunk vs Block Window

**背景**：早期长文档按字符数分 chunk（默认 10,000 字符），在段落边界切分。思源内部用 block（块）组织内容，每个块有唯一 ID、类型（标题/段落/列表）、内容。真实长文档测试后，按字符切分的问题更明显：中英文字符数与 token 数差异大，chunk 可能切断完整段落，也无法稳定对应后续引用或编辑位置。

| 维度 | Chunk（字数分块） | Block（思源块） |
|------|:---:|:---:|
| 实现复杂度 | 低，纯 Markdown 切分 | 中，需查询块树 API |
| 语义边界 | 段落级，可能切断语义 | 自然语义边界（标题即块、段落即块） |
| 大小可控 | 字符数可控，但 token 估算不稳定 | 用 block_limit + token_budget 双约束 |
| 精确定位 | ✗ 无块 ID，只能靠引用文字 | ✓ 每个块有唯一 ID |
| 读写衔接 | ✗ 无法精确定位写入目标 | ✓ 写入必须指定块 ID |
| MCP 响应适配 | 输出大小均匀 | 按窗口连续读取，保留完整块 |

**当前结论**：`siyuan_read_document` 已从字符 chunk 迁移到 block window（✅ 2026-05-03 已实现）。默认阅读按块窗口返回，`block_start=1`、`block_limit=200`、`token_budget=50000`，不会从字符中间截断。大纲、引用阅读和后续编辑共享同一套位置模型。

**默认限制不应太小**：现代 AI 模型上下文窗口普遍较长，默认窗口应足够慷慨，避免长文档被切得过碎。但也不应默认塞满最大上下文，因为不同运行环境的上下文长度、工具输出成本和对话历史占用不同。推荐用较大的默认值（如 `block_limit=200`，`token_budget=50000-80000`），同时允许 AI 明确提高预算或继续读取后续窗口。

**引用阅读命名**：带块 ID 的模式不应称为“诊断阅读”。它的主要用途是跨文档块引用、精确定位和后续编辑辅助，因此对外应称为“引用阅读”。内部参数可以继续保留 `include_block_ids=true` 以兼容现有接口；面向 Skill 和文档时表达为“需要精确引用时开启引用阅读”。

**大纲与窗口预览**：阅读返回应优先提供标题大纲，并在大纲中标注标题所在的 block 位置，帮助 AI 选择后续窗口。只有同时满足两个条件时才补充窗口预览：(1) 标题少于 5 个；(2) 总展示块数超过 100。窗口预览不是摘要，只是每隔 50 个块抽取该块开头的一小句或前若干字符，并明确说明“本文档标题较少，因此抽取每 50 个块的开头片段帮助选择阅读窗口”。如果文章不长，或标题结构已经足够详细，则不额外生成预览。

**旧 chunk 已移除**（2026-05-03）：旧 `chunk/max_chars` 路径已完全删除。核心原则：普通阅读要干净，引用阅读要精确，长文档按完整块连续翻页，token 预算只做安全阀。

---

### 问题 2：Index 和 Guide 的更新触发时机

**Index（index.md）何时更新？**

| 触发条件 | 是否自动 |
|---------|:---:|
| 用户明确说"更新索引"/"重建索引" | — |
| index.md 不存在 | AI 主动询问是否创建 |
| 新增大量文档或全新笔记本 | AI 提醒用户索引可能过时 |
| tree.md 统计数与 index.md 描述差距过大 | AI 提醒用户索引可能过时 |

**不应每次 refresh 都重建 index.md**——它需要 AI 阅读文档才能写摘要，有 API 和时间成本。索引的价值在于"加速导航"，如果建索引本身成本高于收益就没意义。

**Guide（guide.md）何时更新？**

| 触发条件 | 方式 |
|---------|------|
| 用户明确告知新偏好 | AI 用 `siyuan_apply_guide_update` |
| 用户直接编辑文件 | 任何文本编辑器随时修改 |
| AI 主动提议 | `siyuan_propose_guide_update` → 用户批准 → `siyuan_apply_guide_update` |

---

### 问题 3：Guide vs AI Memory 的边界

| | guide.md | AI Memory（Claude 内置） |
|---|----------|------------------------|
| **范围** | 本知识库专属：哪些笔记本重要、阅读顺序、工作风格 | 跨项目通用：用户身份、职业、偏好 |
| **维护者** | 用户 + AI 辅助 | 用户 + Claude 自动 |
| **生命周期** | 跟随项目 repo | 跟随 Claude 账户 |
| **内容举例** | "投资研究时优先看光模块笔记本，写作时看自己写的文章" | "用户是经济学硕士，做投资分析，偏好数据驱动" |

**它们各自独立，不重叠。** Guide 是"在这个知识库里怎么做"，Memory 是"用户是什么样的人"。

**是否需要在思源笔记里放一个 guide 镜像文档？**

→ 已升级为问题 11 的系统笔记本方案：在 `思源桥` 笔记本中维护 `AI Guide`、`Workspace Index` 和 `About SiYuan Bridge`，让工作规则和导航索引随思源工作空间切换；本地 `guide.md/index.md` 降级为兼容缓存。详见问题 11。

---

### 问题 4：三层内容的职责划分

| 层 | 谁维护 | 存放位置 | 内容性质 | 举例 |
|----|--------|---------|---------|------|
| **a. 脚本固定内容** | 开发者 | `source_code/` | 机制实现 | MCP 工具实现、索引生成逻辑 |
| **b. Skill 通用指令** | 开发者 | `plugins/` SKILL.md | 机制用法 | "先调 siyuan_start"、"不要扫文件" |
| **c. 用户个性化** | 用户 + AI | `guide.md` + 思源文档 | 策略偏好 | "我的投资笔记本最优先" |

**核心原则**：(a) 和 (b) 不应预判用户的具体笔记结构、主题、工作流。它们只描述**机制**（"怎么操作"），不描述**策略**（"操作什么"）。

- ✗ Bad：SKILL.md 写"优先搜索光模块笔记本" — 这是个别用户的策略
- ✓ Good：SKILL.md 写"优先读取 guide.md 中用户指定的重点笔记本" — 这是通用机制，适用于所有用户

---

### 问题 5：首次运行的隐私设置引导

**问题**：让用户手动编辑 `siyuan.ignore.local.json` 门槛太高。需要一个引导流程让 AI 帮助用户完成首次隐私设置。

#### 方案 A：一次性收集全部待隐藏内容

**流程**：首次启动时，AI 提示用户一次性列出所有需要隐藏的笔记本和文档，用户确认"这些就是全部"后，AI 批量写入并标记初始化完成。

**优点**：
- 理论上一轮对话就完成了隐私设置
- 用户被迫做一次全面的隐私审视

**缺点**：
- "哪些内容要对 AI 隐藏"是一个随着使用才会逐步明晰的判断，不是一次性能列完的清单
- 用户可能随口问个问题触发了初始化，此时他的注意力在问题上，不在隐私设置上
- 强行要求"一次性说全"把隐私设置变成了门槛任务，用户倾向于草草跳过
- 最要命：初始化时返回了完整的未过滤笔记本列表——如果用户直接说"跳过"，AI 仍然看过了所有列表，但标记文件已创建，下次不会再引导

#### 方案 B：渐进式引导（推荐）

**核心理念**：**标记文件的意义不是"隐私设置完毕"，而是"用户已经知道有这个功能，也知道怎么用了"。** 不管用户是否实际设置了隐藏规则，只要进入过一次启动流程就创建标记。

**流程**：

```
第一次启动 (siyuan_start)
    │
    ├── 检测 .siyuan_privacy_initialized 标记文件
    │   ├── 存在 → 正常启动流程，不显示隐私引导
    │   └── 不存在 → 在启动包末尾附加隐私引导提示
    │
    ├── 启动包正常返回（包含完整笔记本概览）
    │   │
    │   └── 末尾附加：
    │       "## 隐私设置
    │
    │       你可以随时要求隐藏特定笔记本或文档，今后在所有新会话中永久生效。
    │       例如：
    │       - '隐藏 XX 笔记本'  → AI 调用 siyuan_privacy
    │       - '隐藏 /某路径/某文档'  → AI 调用 siyuan_privacy
    │       - '临时开放 日记 笔记本 30 分钟'
    │
    │       设置后我会自动刷新索引，隐藏的内容将不再可见。"
    │
    ├── 创建 .siyuan_privacy_initialized 标记（用户已看到引导）
    │
    └── 后续：
        用户随时说"把日记随笔这个笔记本隐藏掉"
          → AI 调用 siyuan_privacy(action="hide", ...) → 自动刷新索引 → 标记早已存在，不影响
```

**用户使用场景**：

```
用户: "帮我查一下光模块行业的数据"
  → AI 触发 siyuan_start
  → 首次启动，返回笔记本列表 + 末尾隐私引导
  
用户: "哦对，把日记随笔这个笔记本隐藏掉"
  → AI 调用 siyuan_privacy(action="hide", scope="notebook", locator="日记随笔")
  → 自动 refresh
  → 继续正常回答光模块的问题
```

**关键洞察**：用户第一次用了 `siyuan_privacy` 之后，就建立了心智模型——以后想隐藏新的内容，对 AI 说同样的话就行。这比一次性 wizard 更可持续。

**优点**：
- 不打断用户的当前任务流程——隐私引导只是启动包末尾的一句话，不会阻塞
- 用户可以渐进式地发现需要隐藏的内容，随时追加
- 即使跳过不做任何设置，功能也正常运行
- 引导只出现一次，不会重复骚扰

**缺点**：
- 首次启动时返回了完整的未过滤笔记本列表（这是所有方案的固有问题——用户必须看到列表才能决定隐藏什么）

#### 最终选择

**方案 B**。隐私不是一次性的决策，而是一个持续迭代的过程。工具应该支持这个现实，而不是假设用户能在第一分钟就想清楚所有边界。

**隐私性考量**：首次启动时 AI 会看到所有笔记本名称和文档标题——这一步在设置隐藏之前不可避免。敏感信息在首次启动时短暂暴露，隐私规则生效后下次启动即应用。如果用户确实第一次就有明确要隐藏的内容，可以在思源中编辑 `隐私规则` 文档的表格，告诉 AI"刷新一下"后立即生效。

**当前状态**（2026-05-03）：隐私规则已迁移到思源系统笔记本中的 Markdown 表格。`siyuan_privacy` 和 `siyuan_temporary_allow` MCP 工具已移除——隐私规则完全由人类在思源 UI 中控制，AI 不能修改。用户临时开放隐藏内容时，在表格中将对应行的 `Hide` 改为 `no`，交流完毕后再改回 `yes`。

---

### 问题 6：Index、Guide、Memory 的存储和同步

| 文件 | 格式 | 位置 | Git 同步 | 理由 |
|------|------|------|:---:|------|
| `tree.md` | Markdown | `knowledge_base/` | 否 | 本地生成，每台设备独立 |
| `docs.jsonl` | JSONL | `knowledge_base/` | 否 | 同上 |
| `notebooks.json` | JSON | `knowledge_base/` | 否 | 同上 |
| `privacy_rules.json` | JSON | `knowledge_base/` | 否 | 从思源 Markdown 表格解析的缓存，每次 refresh 覆盖 |
| 思源 `思源桥/AI Guide` | 思源文档 | 思源内部 | 思源同步 | 工作空间级主副本，用户在思源 UI 中编辑 |
| 思源 `思源桥/Workspace Index` | 思源文档 | 思源内部 | 思源同步 | 工作空间级语义导航索引，AI 用现有写入工具维护 |
| 思源 `思源桥/About SiYuan Bridge` | 思源文档 | 思源内部 | 思源同步 | 给人的工具说明和开发者消息，系统可随模板版本更新 |
| 思源 `思源桥/Privacy Rules` | 思源文档 | 思源内部 | 思源同步 | 人类维护的隐藏规则配置，MCP 内部解析，AI 不可读取 |
| `.siyuan_privacy_initialized` | 空标记 | 项目根 | **是** | 标记已完成初始化 |

**多设备/多工作空间场景**：每台设备运行自己的思源、生成自己的 `tree.md/docs.jsonl`。Guide 和 Index 应优先跟随思源工作空间；隐私规则通过思源系统笔记本中的 Markdown 表格维护，随思源同步。

**本地生成文件的位置选择**：`tree.md/docs.jsonl/notebooks.json` 仍放在项目根目录的 `knowledge_base/` 中，而非思源插件目录。理由：
- 思源插件目录由思源内部管理，外部工具不应污染
- 项目目录可通过 git 做版本控制和同步
- 解耦——思源插件系统变化不影响本工具

---

### 问题 7：阅读返回格式 — 纯 Markdown vs 块增强 vs JSON

| 方案 | AI 阅读体验 | 引用精度 | 实现复杂度 | 当前定位 |
|------|:---:|:---:|:---:|------|
| A. 纯 Markdown | 最干净 | 段落级（靠引用文字） | 最低 | 默认方案 |
| B. Markdown + HTML 注释块 ID | 较干净 | 块级精确 | 中（需后处理对齐） | 只作为跨文档块引用的可选增强 |
| C. 块列表 JSON（含完整元数据） | 噪音大，需解析 | 最高 | 高 | 不作为通用阅读返回 |

**当前结论**：默认保持纯 Markdown 阅读体验。AI 使用笔记时，最常见需求是搜索、理解、总结、改写和局部文本修改，纯 Markdown 的性价比最高。块 ID 增强应作为“引用阅读”模式，只在跨文档块引用、精确定位、后续编辑辅助或用户明确要求块 ID 时启用。

**为什么不默认追求块级精确**：

- 思源的文档结构比普通 Markdown 复杂，存在超级块、横向/纵向布局、数据库、属性视图、嵌套列表、空块等结构。导出 Markdown 本身已经是一个有损视图。
- 后处理注入块 ID 需要把导出的 Markdown 和原始块树重新对齐。普通段落可行，复杂列表、表格、超级块、数据库区域容易出现重复、错位或不可逆。
- AI 的主要价值不是像人一样精确操控思源 UI，而是基于文本完成阅读、搜索、草稿、总结和低风险局部编辑。为少数结构化场景引入全量块树噪音，会降低日常使用体验。

**额外信息是否干扰 AI？** — 即使未来使用 HTML 注释嵌入块 ID，也只应在特定模式下返回，不应默认污染阅读结果。不要在可见文本中混入元数据（如 `[id:xxx updated:xxx]`），这会打断阅读流。

---

### 问题 8：附件和图片处理

**已实现** (2026-05-02)。最终设计偏离初始方案——不做可选参数，默认自动提取；不修改 Markdown 引用路径。

**实现决策**：

- **默认自动提取**：`siyuan_read_document` 每次读取时自动提取文档中所有 `assets/` 引用的资源文件。不做开关参数——因为提取到 workspace 的文件会在 `siyuan_refresh_index` 时自动清理，没有堆积问题。
- **Markdown 不改动**：图片/附件引用 `![](assets/xxx.png)` 或 `[file](assets/xxx.xlsx)` 完全保持原样。AI 读到文件名后，在 `ai_workspace/attachments/<doc-id>/assets/` 下按同名文件查找。
- **覆盖所有附件类型**：正则 `\]\(assets/([^)]+)\)` 同时匹配图片引用（`![...](assets/...)`）和普通链接（`[...](assets/...)`），确保 PDF、xlsx、docx 等非图片附件一并提取。
- **通过 HTTP API 下载**：`client.get_asset()` 对思源 HTTP 服务器发 GET 请求获取资源文件，支持中文文件名（URL 编码）。
- **文档头提示**：有附件时显示 `附件: N 个已提取到 ai_workspace/attachments/<doc-id>/`，无附件时不显示。

**ai_workspace 清理机制**：

`siyuan_refresh_index` 清空 `ai_workspace/` 中除 `README.md` 外的所有内容（包括 attachments 目录）。每次新会话开始时 workspace 是干净的。

---

### 问题 9：未来写入功能设计预留

> **注意**：此问题为早期设计思考。写入功能已重新设计为 Claude Code Edit/Write 模式（文本锚点 + 2 个精简工具），详见 [问题 15](#问题-15写入功能设计--claude-code-editwrite-模式映射)。以下内容保留作为历史记录。

写入功能需要三个前提：

1. **精确定位** → 读取时返回块 ID（见问题 1 和问题 7）
2. **权限控制** → 所有写操作需要 `confirmed=true` 参数
3. **API 基础** → 思源提供 `/api/block/appendBlock`、`/api/block/updateBlock` 等

**暂不实现，但设计上预留接口**：

| 工具（预留） | 用途 |
|------|------|
| `siyuan_append_block(parent_id, content, type)` | 在文档末尾追加块 |
| `siyuan_insert_block(previous_id, content, type)` | 在指定块后插入 |
| `siyuan_update_block(block_id, content)` | 更新块内容 |
| `siyuan_create_document(notebook_id, title, content)` | 创建新文档 |

所有这些工具都需要 `confirmed=true`。AI 可以先提议（`siyuan_propose_write`），用户批准后再执行。**这个功能在当前阶段不做，等核心读取工具稳定后再推进。**

---

### 问题 10：PD.md 本身的定位

PD.md 是**设计文档 + 决策记录**，不是 README。它面向三类读者：

1. **开发者（用户）** — 追踪项目进度，了解设计意图
2. **本项目的 AI** — 在新会话中快速了解项目上下文

每次讨论中产生的设计决策、方案权衡、踩过的坑，都应沉淀到 PD.md 中。它应该保持更新，反映项目当前的真实状态和思考过程。

---

### 问题 11：系统笔记本 — Guide / Index 的归属

**问题**：`guide.md` 和 `index.md` 当前放在项目目录的 `knowledge_base/` 中。这个方案在单一工作空间和 bridge 项目目录内可用，但多工作空间会错配：每个思源工作空间的笔记内容不同，Guide 和语义 Index 也应该跟随该工作空间，而不是跟随本地代码仓库。

**当前结论**：在思源中维护一套系统笔记本和系统文档。项目面向中文用户，默认按中文创建；同时预留英文名称，便于未来多语言适配。`siyuan_start` 和 `siyuan_refresh_index` 内部确保系统笔记本存在，并维护四份固定文档：

| 文档 | 确保策略 | 说明 |
|------|---------|------|
| `AI 使用指南` / `AI Guide` | 不存在则创建；存在则不覆盖 | AI 的持久使用规则和偏好，用户可在思源 UI 中直接编辑 |
| `工作空间索引` / `Workspace Index` | 不自动创建 | 语义导航索引，不存在时提示 AI 引导用户创建 |
| `关于思源桥` / `About SiYuan Bridge` | 不存在则创建；模板版本更新时覆盖 | 给人看的工具说明和开发者消息，精简概括核心思想和用法 |
| `隐私规则` / `Privacy Rules` | 不存在则创建默认表格；存在则解析 | 人类维护的隐藏规则配置，MCP 内部解析，AI 永远不可读取 |

文档命名刻意区分职责：AI 使用指南给 AI，工作空间索引给 AI 做导航，关于文档给人，隐私规则给 MCP server 做隐私过滤。避免使用 `Guide for Humans`，因为它和 `Guide` 太像，容易让 AI 或用户混淆。

**语言与命名策略**：

- 同一个工作空间只维护一套系统笔记本和系统文档，不同时创建中英文两套。
- 查找系统笔记本时，同时兼容中文名 `思源桥` 和英文名 `SiYuan Bridge`。只要找到任意一个，就使用现有笔记本，不因为当前系统语言不同而新建或重命名。
- 查找系统文档时，同样兼容中英文名称。例如 `AI 使用指南` 和 `AI Guide` 都视为同一种内部文档 `ai_guide`。
- 只有当目标笔记本或目标文档不存在时，才根据当前语言创建。中文环境创建中文名称；非中文环境创建英文名称。
- 第一阶段不自动重命名已有系统笔记本或系统文档。用户切换系统语言后，仍然沿用已存在的名称。
- 内部逻辑应使用稳定 key，而不是直接依赖显示名称：`ai_guide`、`workspace_index`、`about`、`privacy_rules`。
- 语言偏好也应进入 `siyuan_start` 启动包，明确告诉 AI 检测到的用户/工作空间语言，以及用户可见回复应优先使用的语言，除非用户明确要求。这样即使 Skill、系统文档和用户消息语言不一致，AI 也有一个稳定的优先级参考。

启动包中的语言偏好示例：

```markdown
## 语言偏好

检测到的用户/工作空间语言：zh-CN
优先回复语言：中文
除非用户明确要求使用其他语言，否则默认用中文回复。
```

英文环境示例：

```markdown
## Language Preference

Detected user/workspace language: en
Preferred reply language: English
Use English by default when talking to the user, unless the user explicitly asks for another language.
```

语言偏好来源优先级：

1. 用户显式配置，例如 `language = "zh-CN"` 或 `language = "en"`。
2. 系统 locale。
3. 已存在系统笔记本/系统文档的语言。
4. 检测失败时默认 `zh-CN`。

用户当前消息如果明确要求另一种语言，则当前用户消息优先。

**About 文档覆盖机制**：内置模板内含版本标识字符串（如 `<!-- template_version: 1 -->`）。refresh 时对比思源中现有文档是否包含完全相同的版本标识；若匹配则说明用户未修改且模板未更新，跳过；若不匹配则用新模板覆盖。这样开发者更新模板后，用户自动获得新版说明；用户自行编辑后版本标识会被破坏，不会被意外覆盖。

AI 使用指南、关于文档和隐私规则在每次 refresh/siyuan_start 时检查，缺失则按当前语言自动创建。AI 使用指南一旦存在就不覆盖；关于文档是开发者向用户传递工具说明和新消息的渠道，可以按内置模板版本更新；隐私规则由人类维护，存在后不覆盖，只解析。工作空间索引永远不自动创建，只提示。

**简化原则**：不要把系统笔记本做成强隔离的特殊知识库。它可以进入普通 `refresh_index`、`siyuan_list`、`siyuan_find_documents`，这样代码更简单，也方便 AI 必要时通过普通工具找到它。系统行为主要靠 Skill 指令约束，而不是额外 MCP 工具和复杂过滤层。

**启动流程**：

```
siyuan_start
    │
    ├── 查找系统笔记本：思源桥 / SiYuan Bridge（兼容旧名 思源代理桥 / SiYuan Agent Bridge）
    ├── 不存在则按当前语言调用 /api/notebook/createNotebook 创建
    ├── 检查 AI 使用指南 / AI Guide，不存在则按当前语言创建默认 Guide
    ├── 检查 关于思源桥 / About SiYuan Bridge
    │   ├── 不存在 → 用内置模板创建
    │   └── 存在 → 对比版本标识字符串，不匹配则用新模板覆盖
    ├── 检查 隐私规则 / Privacy Rules，不存在则创建默认表格；存在则解析并校验
    ├── 读取 AI 使用指南 / AI Guide
    ├── 读取 工作空间索引 / Workspace Index；不存在则返回”尚未创建导航索引”的提示
    ├── 在启动包中提及 关于文档 / About 文档的路径和用途，但不塞入全文
    └── 刷新并返回普通知识库概览
```

**Index 写入方式**：不新增 `siyuan_write_index` MCP 工具。AI 使用现有写入工具即可：

- 第一次创建工作空间索引：调用 `siyuan_create_document`，目标笔记本为系统笔记本，中文环境路径固定为 `/工作空间索引`，英文环境路径固定为 `/Workspace Index`。
- 后续更新工作空间索引：调用 `siyuan_edit_document` 替换正文。
- 所有写入继续走现有快照保护和 `confirmed=true` 机制。

**About 文档内容原则**：

- 内容以中文为主，同一段内先中文、后英文作为辅助。This project is primarily for Chinese-speaking users; English is auxiliary.
- 内容必须精简，只解释工具核心思想、系统笔记本里三份文档的用途、用户日常应该怎么用。
- 明确提示该文档由系统维护，可能在 refresh 时更新，不要在其中记录个人内容。
- 详细内容不复制 README，只提示阅读项目 README、项目网站或联系开发者。项目公开网站尚未稳定时，可以先保留占位链接，后续再替换。

默认内容草案（中文为主，英文为辅，同一段先中后英；含版本标识）：

```markdown
<!-- template_version: 1 -->

# 关于思源桥 / About SiYuan Bridge

本文档由思源桥自动维护，可能在刷新时更新。请不要在这里记录个人内容。This document is maintained by SiYuan Bridge and may be updated during refresh. Do not store personal notes here.

思源桥是连接思源笔记和 AI agent 的本地桥接工具。它让 AI 在隐私规则保护下阅读、搜索和维护你的思源知识库。SiYuan Bridge is a local bridge between SiYuan notes and AI agents, letting AI read, search, and maintain your knowledge base under privacy rules.

## 系统笔记本里的三份文档 / Three Documents in This Notebook

- **AI Guide**：给 AI 看的长期规则，你可以在这里写下偏好、重点笔记本、写作风格和限制。AI Guide stores long-term instructions for AI — your preferences, important notebooks, writing style, and constraints.
- **Workspace Index**：AI 生成的语义导航索引，帮助新会话快速了解这个工作空间里有什么。Workspace Index is an AI-generated semantic navigation map for new sessions.
- **About SiYuan Bridge**：就是本文档，给人看的工具说明。About SiYuan Bridge is this document — a human-readable introduction to the tool.

## 日常怎么用 / How to Use

你平时正常在思源里写笔记。需要时告诉 AI"帮我查一下笔记里关于 XX 的内容"。如果某些笔记不想被 AI 看到，使用隐藏规则，不要删除或隐藏这个系统笔记本。You write notes in SiYuan as usual. When needed, ask AI to search your notes. To hide content from AI, use hide rules — do not delete or hide this system notebook.

更多信息请阅读项目 README、项目网站，或联系开发者。For more details, read the project README, visit the project website, or contact the developer.
```

**启动包策略**：`siyuan_start` 应返回 AI 使用指南和工作空间索引（如果存在），因为它们直接影响 AI 如何使用知识库。关于文档不默认塞入启动包全文，只在启动包中给出一行说明：这是给人看的工具说明和更新消息，普通任务无需读取。这样避免每次会话重复工具介绍，同时让 AI 知道它存在。

**Privacy Rules 设计**：

隐藏规则应由人类在思源 UI 中维护，而不是由 AI 通过 MCP 工具修改。`Privacy Rules` 是系统配置，不是知识库文档：MCP server 可以内部读取和解析，AI 不能通过 `siyuan_start`、`siyuan_list`、`siyuan_find_documents`、`siyuan_read_document` 看到它，也不能编辑它。

第一阶段使用 Markdown 表格，不使用 JSON。原因是 JSON 对非程序员门槛较高；表格更像“填表”，也更符合思源的编辑体验。

默认模板：

```markdown
# Privacy Rules

隐私规则完全由人类在本文档控制，AI 无法阅读、编辑或删除该文档。
This document is fully controlled by humans. AI cannot read, edit, or delete it.

请只编辑下面两张表格。可以新增或删除表格行，但不要新增表格，也不要编辑表头，否则会报错。`Hide` 填 `yes` 才会对 AI 隐藏；填 `no` 表示暂不启用。你可以把某一行临时改为 `no` 来短暂开放给 AI，交流完毕后再改回 `yes`。文档修改会在每次工具刷新时生效。
Only edit the two tables below. You may add or remove rows, but do not add tables or edit table headers. A row hides content from AI only when `Hide` is `yes`; `no` means disabled.

隐藏文档必须填写 Document ID。Title 只给你自己确认，系统不会按标题匹配。
Document hiding requires Document ID. Title is only for your confirmation and is not used for matching.

隐藏笔记本时优先填写 Notebook ID。获取方法：在笔记本列表中点击笔记本右侧三个点，选择“设置”，然后点击“复制 ID”。如果暂时不知道 ID，也可以只填写 Notebook Name；若多个笔记本重名，同名笔记本都会被隐藏。
For notebooks, Notebook ID is preferred. To get it, click the three-dot menu next to the notebook, open Settings, and click Copy ID. If you do not know the ID yet, use Notebook Name. If multiple notebooks share the same name, all matching notebooks will be hidden.

## Hide Notebooks

| Hide | Notebook ID | Notebook Name | Reason |
|---------|-------------|---------------|--------|
| no | 20260503123456-abcdefg | 示例笔记本 | 示例，不会生效 |
| yes | 20260503123456-abcdefg | 示例：私人资料 | 示例，会隐藏 |
| yes |  | 示例：个人日记 | 按名称隐藏 |

## Hide Documents

| Hide | Document ID | Title | Reason |
|---------|-------------|-------|--------|
| no | 20260503123456-abcdefg | 示例文档 | 示例，不会生效 |
| yes | 20260503123456-abcdefg | 示例：未公开项目 | 示例，会隐藏 |
```

解析规则：

- 只解析固定标题 `## Hide Notebooks` 和 `## Hide Documents` 下的第一张表。
- 只启用 `Hide=yes` 的行；`no` 行作为示例或暂不启用。
- 笔记本规则优先使用 `Notebook ID` 精确匹配；如果没有 ID，则按 `Notebook Name` 精确匹配。
- 如果多个笔记本名称相同，且规则只写了名称，则隐藏所有同名笔记本。
- 文档规则必须填写 `Document ID`；`Title` 只给人确认，不参与匹配。
- 隐藏文档等于隐藏该文档及其所有子文档。
- `Reason` 选填，只给人审计，不参与匹配。

表格标题和表头应尽量按模板填写，但解析器应做温和兼容，避免因为空格、括号或旧模板字段造成不必要的失败：

- `Hide` 可兼容 `Enabled`、`对AI隐藏？`、`对 AI 隐藏？`、`Hide from AI?`。
- `Notebook ID` 可兼容 `笔记本ID`、`笔记本 ID`、`笔记本ID（建议填）`、`笔记本 ID（建议填）`、`笔记本 ID（优先）`、`Notebook ID (preferred)`。
- `Notebook Name` 可兼容 `笔记本名称`。
- `Document ID` 可兼容 `文档ID`、`文档 ID`、`文档ID（必填）`、`文档 ID（必填）`、`文档ID（必填，不填会报错）`、`Document ID (required)`。
- `Title` 可兼容 `标题`、`标题（仅供确认）`、`Title (for confirmation only)`。
- `Reason` 可兼容 `备注`、`备注（可选）`、`Note (optional)`。

兼容原则是“尽量不给用户造成麻烦”，但不能把自然语言段落当作规则解析，也不能支持模糊匹配、正则或路径隐藏。

校验策略：

- 表格缺失、关键表头无法识别、`Hide` 不是 `yes/no`、启用行缺少必要字段，都视为解析失败。
- 启用的 `Document ID` 不存在时视为解析失败。
- 启用的 `Notebook ID` 不存在时视为解析失败。
- 只写 `Notebook Name` 且没有匹配笔记本时视为解析失败。
- 解析失败时不应退化为“没有隐藏规则”。应中止 start/refresh/search/read/write，并提示用户打开系统笔记本中的 `Privacy Rules` / `隐私规则` 修复格式。
- 错误信息应该能帮助定位问题，但不能泄漏具体隐藏内容。允许返回表格名、行号、字段名和错误类型；不返回该字段里的具体值。

错误示例：

```text
隐私规则格式错误：
- Hide Documents 第 3 行：Document ID 为空。
- Hide Notebooks 第 2 行：Hide 只能填写 yes/no。
- Hide Documents 第 4 行：Document ID 不存在或不可访问。
```

不要返回具体隐藏的笔记本名称、文档标题或 ID。

隐私检查状态不需要落盘成持久文件。第一阶段每次 start / refresh / search / read / write 操作前解析 `Privacy Rules`：解析成功则本次操作继续，解析失败则本次操作中止。后续如果需要性能优化，可以只做进程内短期缓存。

用户如何获取 ID：

- 文档 ID：可让 AI 在仍未隐藏时通过搜索/列表告诉用户，也可由用户在思源 UI 中复制引用或查看文档属性获得。若标题本身敏感，用户不应让 AI 搜索该标题，应直接从思源 UI 获取 ID。
- 笔记本 ID：在思源笔记本列表中点击笔记本右侧三个点，选择“设置”，再点击“复制 ID”。第一阶段仍允许用户只填写笔记本名称；笔记本通常不重名，若重名则全部隐藏，符合保守隐私原则。

**与旧本地隐私规则的关系**：

当前仍处于开发阶段，没有外部用户需要兼容。系统笔记本上线后，不再做 `siyuan.ignore.local.json` / `siyuan.allow.local.json` fallback，也不合并旧规则。隐私规则主副本就是思源系统笔记本中的 `Privacy Rules` / `隐私规则`。旧隐私 MCP 工具可以暂时保留开发兼容，但 Skill 和 README 不再引导 AI 使用它们；后续稳定后可以删除。

**Skill 规则**：

- 创建或更新语义索引时，把结果写入系统笔记本的工作空间索引文档。中文环境默认路径是 `思源桥/工作空间索引`，英文环境默认路径是 `SiYuan Bridge/Workspace Index`；如果已有另一语言名称，则使用已有文档。
- 整理、总结、重建用户知识库索引时，不要把 `思源桥` 笔记本当作用户原始知识材料。
- 系统笔记本中的 AI 使用指南是使用规则，工作空间索引是导航索引，关于文档是给人的说明和开发者消息，隐私规则是隐私配置；四者都不是用户原始资料。
- AI 不应读取、搜索、总结或编辑隐私规则文档。
- 如果普通搜索命中系统笔记本，AI 应先判断当前任务是否真的需要系统资料；多数用户知识问答不应引用它。

**隐藏规则保护**：系统笔记本不能被隐藏。如果用户尝试隐藏 `思源桥` / `SiYuan Bridge` 笔记本，或隐藏其下的任一系统文档、子文档，MCP 应拒绝并提示：这是系统笔记本，隐藏后启动包和隐私规则会失效；如果确实有私密内容，应先把内容移动到其他笔记本再隐藏。

**与本地文件的关系**：

系统笔记本上线后，`knowledge_base/guide.md` 和 `knowledge_base/index.md` 不再使用。`siyuan_start` 直接读取思源中的 `AI Guide` 和 `Workspace Index`。当前处于开发阶段，本地尚未维护这些文件，无需迁移。

| 存储位置 | 角色 |
|---------|------|
| 思源系统笔记本 / AI 使用指南 或 AI Guide | 主副本，用户可在思源 UI 中直接编辑 |
| 思源系统笔记本 / 工作空间索引 或 Workspace Index | 主副本，AI 用现有写入工具创建/更新 |
| 思源系统笔记本 / 关于思源桥 或 About SiYuan Bridge | 系统维护，模板版本更新时覆盖 |
| 思源系统笔记本 / 隐私规则 或 Privacy Rules | 人类维护，MCP 内部解析，AI 不可读取 |

**需要新增的 API 封装**：

- `create_notebook(name)` — 调用思源 `/api/notebook/createNotebook`
- 复用已有 `create_doc_with_md()`、`siyuan_create_document`、`siyuan_edit_document`

这个方案的关键价值：AI Guide/Workspace Index/Privacy Rules 随思源工作空间切换，不再依赖本地文件路径；MCP 工具数量可以减少，隐私规则由人类在思源里直接维护；系统笔记本保持可见但通过 Skill 避免污染语义索引；About 文档通过版本标识机制，作为开发者向用户传递工具说明和更新消息的轻量渠道。

---

### 问题 12：外部开源项目参考边界与查重报告

**背景**：目前已有多个公开的 SiYuan MCP 项目，主要方向是把思源 API 封装成通用 MCP 工具。它们和本项目有交集，但产品目标不同。本项目不应发展成“另一个完整 SiYuan MCP Server”，而应保持“私有、本地优先、隐私过滤、面向 AI agent 的知识库桥接层”这一定位。

#### 已知可参考项目

| 项目 | 主要定位 | 许可证/状态 | 可参考内容 |
|------|----------|-------------|------------|
| `galiais/siyuan-mcp-server` | 通用 SiYuan MCP Server，覆盖 notebooks、documents、blocks、templates、exports、assets、SQL、system tools | MIT | TypeScript MCP 工具组织方式、端口发现、文档/块/资产/SQL API 调用方式、写入工具的参数设计 |
| `leolulu/siyuan-mcp-server` | Python 版 SiYuan MCP Server，偏完整工具集，包含写操作流程规范 | MIT | Python MCP 组织方式、写操作通知链路、块操作参数优先级、用户可读错误/通知文案 |
| `porkll/siyuan-mcp` | npm 发布的通用 SiYuan MCP，支持搜索、文档操作、日记、快照、标签等 | 需在使用前确认仓库 LICENSE | npm/stdio 打包方式、Cursor/Claude 配置示例、常用文档操作工具设计 |
| `onigeya/siyuan-mcp-server` | 早期 SiYuan MCP Server，面向文档、块、SQL、模板等 API 操作 | ISC | 简洁的 TypeScript API 封装、工具命名方式、基础连接配置 |
| `MyrkoF/siyuan-query-mcp` | 面向思源数据库/Attribute Views 的 MCP Server | 开源，使用前确认 LICENSE | 数据库视图读取、结构化查询、表格类知识的 MCP 返回格式 |
| `Syplugin-an MCPServer` | 思源插件形态的 MCP Server，支持搜索、读取、写入/追加 | 需在使用前确认仓库 LICENSE | 插件内运行方式、从思源插件环境访问 API、写入/追加操作的交互边界 |

**许可证原则**：
- MIT / ISC 项目可以复制、修改、分发和商用，但必须保留原作者版权声明和许可证文本。
- 没有明确 LICENSE 的公开仓库不能直接复制代码。公开可见不等于开源授权。
- 如果复制超过少量片段，应在 `THIRD_PARTY_NOTICES.md` 或相关文件头中注明来源、许可证和改动范围。
- 优先“参考 API 调用方式后自行实现”，少做大段搬运，避免把外部项目的架构和维护负担带入本项目。

#### 可借鉴但不应照搬的部分

| 模块 | 可参考项目 | 借鉴方式 | 本项目边界 |
|------|------------|----------|------------|
| SiYuan API client | `galiais`、`leolulu`、`onigeya` | 参考 endpoint、payload、错误处理、端口发现 | 保持本项目 client 简洁，只封装当前需要的 API |
| 写入能力 | `leolulu`、`galiais`、`porkll`、`Syplugin-an` | 参考 `appendBlock`、`insertBlock`、`updateBlock`、`createDocWithMd` 的参数和确认流程 | 只做窄写入；所有写操作必须 `confirmed=true`，并优先提供 propose/preview |
| 块级读取 | `galiais`、`onigeya` | 参考 block tree 查询和块 ID 处理 | 本项目仍以 Markdown 阅读体验为主，块 ID 只作为跨文档引用或诊断模式的可选增强 |
| SQL/数据库读取 | `MyrkoF`、`galiais` | 参考 Attribute Views、SQL 返回结构和表格格式 | 仅在知识检索需要时提供，避免变成完整数据库管理器 |
| 资产/附件处理 | `galiais`、`Syplugin-an` | 参考 assets 路径、上传/读取、OCR 或导出接口 | 默认不提取附件；只有 `extract_attachments=true` 时复制到 `ai_workspace/` |
| MCP 工具 schema | 所有通用 MCP 项目 | 参考参数命名、tool description、客户端配置 | 工具数量保持克制，优先支持 AI 知识库工作流 |
| 发布打包 | `porkll`、`galiais`、`leolulu` | 参考 npm/PyPI/stdio 配置和 README 示例 | 当前仍以本地自用为主，对外发布放在第四优先级 |

#### 不建议借鉴或复制的部分

- 完整 CRUD 工具集：删除、移动、重命名、快照、模板、资产上传、系统工具等不属于当前核心路径。
- 通用“AI 管理思源”的产品叙事：本项目不是让 AI 全权操作思源，而是让 AI 安全读取和导航私人知识库。
- 复杂插件化架构：当前项目体量小，过早引入外部项目的大型抽象会降低可维护性。
- 默认写入能力：写入是远期能力，必须建立在块 ID、确认机制、preview/propose 流程稳定之后。

#### 查重报告

| 能力区域 | 与现有项目重复度 | 说明 |
|----------|------------------|------|
| HTTP 连接、token、端口配置 | 高 | 所有 SiYuan MCP 项目都需要做，属于基础设施重复 |
| 文档搜索、读取、导出 Markdown | 中高 | 通用 MCP 项目通常已有类似工具，但本项目返回格式更偏 agent 阅读 |
| MCP stdio server 和 tool schema | 中高 | 协议层重复不可避免，差异主要在工具设计和工作流约束 |
| 文档/块写入 API | 当前低，未来会升高 | 未来若加入写入，会和通用项目重复；应保持窄接口和确认机制 |
| 安全索引 `tree.md` / `docs.jsonl` | 低 | 现有项目多为实时 API 封装，本项目生成可过滤、可导航的本地索引 |
| 隐私忽略/临时开放规则 | 很低 | 这是本项目核心差异，隐藏内容在索引层移除，而不是只靠 AI 自觉 |
| `siyuan_start` 启动包 | 很低 | 面向无状态 AI 会话的启动导航包，是本项目特有体验 |
| `index.md` 语义导航 | 很低 | AI 生成、用户可修正、用于快速路由的导航索引不是通用 MCP 的重点 |
| Skill 强制工作流 | 很低 | 通过 skill 约束 AI 先启动、再导航、再深读，是产品层差异 |
| `guide.md` 用户偏好层 | 低 | 类似 memory/配置，但本项目把它限定为知识库使用策略 |

**结论**：本项目约有 30%–45% 的底层技术工作与现有 SiYuan MCP 项目重叠，主要是 API client、MCP 协议封装、搜索/读取/写入 endpoint。按产品目标计算，核心重复度约 20%–30%。真正独特的部分是：隐私过滤后的安全索引、启动包、AI 语义导航、guide、Skill 工作流和按需深读机制。

**后续策略**：
1. 保留本项目主体架构，不迁移到外部通用 MCP 项目的架构。
2. 后续开发写入能力时，先调研 `leolulu`、`galiais`、`porkll`、`Syplugin-an` 的 API 调用和确认流程。
3. 只复制许可证允许且明显稳定的小段实现；优先重写。
4. 写入工具只服务本项目场景：引用块、追加分析、更新 guide、创建 AI 工作草稿；不追求完整思源管理。
5. 若引入外部代码，新增 `THIRD_PARTY_NOTICES.md` 记录来源。

参考链接：
- `galiais/siyuan-mcp-server`: https://github.com/GALIAIS/siyuan-mcp-server
- `leolulu/siyuan-mcp-server`: https://github.com/leolulu/siyuan-mcp-server
- `porkll/siyuan-mcp`: https://github.com/porkll/siyuan-mcp
- `onigeya/siyuan-mcp-server`: https://github.com/onigeya/siyuan-mcp-server
- `MyrkoF/siyuan-query-mcp`: https://github.com/MyrkoF/siyuan-mcp
- `Syplugin-an MCPServer`: https://github.com/frostime/syplugin-anMCPServer

---

### 问题 14：index.md 跨目录写入问题

**问题**：当用户在非 bridge 项目目录下工作时，`siyuan-index-builder` skill 告诉 AI 用标准文件工具（Write/Edit）将 `index.md` 写入 `knowledge_base/index.md`。但 AI 的工作目录是用户当前的项目目录，不是 bridge 安装目录，所以 index.md 会被写入错误的位置。即使路径正确，本地 `index.md` 也无法天然跟随思源工作空间切换。

**后果**：
- `index.md` 可能被写入错误项目目录。
- 切换思源工作空间后，启动包可能读到旧工作空间的导航索引。
- 用 git 同步本地索引不是理想方案；语义索引更应该跟随思源工作空间同步。

**根因**：MCP server 通过 `run_mcp.py` 的 `os.chdir(REPO_ROOT)` 始终以 bridge 根目录为工作目录，但 AI agent 的文件系统操作（Write/Edit）使用的是 IDE/终端的当前工作目录，这两者不一致。

**当前结论**：不新增 `siyuan_write_index`。改为把语义索引主副本放在思源系统笔记本 `思源桥/Workspace Index` 中，并要求 AI 使用现有 `siyuan_create_document` / `siyuan_edit_document` 维护它。

**理由**：

1. 现有写入工具已经有快照、确认、隐私检查和思源前台通知，不需要再做一套写入链路。
2. MCP 工具数量保持克制，避免为每个固定文档新增专用工具。
3. Index 放在思源里后，天然随工作空间切换，也能走思源自己的同步。
4. Skill 只需说明固定写入位置：`思源桥/Workspace Index`。

**实现要求**：

- `siyuan_start` 读取系统笔记本中的工作空间索引（`工作空间索引` / `Workspace Index`），不存在则提示尚未创建。
- `siyuan-index-builder` 生成索引时，创建或更新系统笔记本中的工作空间索引。
- 整理知识库时不要把 `思源桥` 笔记本本身作为用户资料来源，避免旧 Index 污染新 Index。

---

### 问题 13：搜索召回 — 本地索引 + API vs API-only

**背景**：早期 `siyuan_find_documents` 同时走两条路径：本地 `docs.jsonl` 搜标题/路径/tag，思源 `fullTextSearchBlock` 搜正文块，然后合并结果。这带来了两套搜索语义：标题搜索像本地字符串匹配，正文搜索像思源全文检索。实践中还暴露出字段名、类型名、paths 参数和 snippet 来源不一致的问题。

#### 方案 A：本地索引 + 思源 API 混合召回

**优点**：
- 思源 API 不可用时，标题/path/tag 仍可从本地索引返回。
- 隐私边界直观：本地索引已经过滤过隐藏内容。

**缺点**：
- 搜索行为不一致：同一个 query 在本地和思源 API 中语义不同。
- 合并、去重、排序、snippet 来源都需要额外逻辑。
- 本地索引只包含文档元数据，不含正文；用户容易误以为 `scope=full` 和 `scope=headings` 都能被本地兜底。

#### 方案 B：API-only 召回 + MCP 内部隐私过滤（已采用）

**流程**：

1. `siyuan_find_documents` 统一调用思源搜索 API 召回结果。
2. 搜索前用 `ensure_notebooks_open` 临时打开关闭的笔记本；如果用户没有限定 notebook，则打开所有关闭笔记本。
3. API 返回的 block 在 MCP server 内部转换为文档级结果。
4. 同一篇文档内的多个命中 block 聚合到同一个文档结果下，全部保留为 snippets。
5. 对每个候中文档应用 `siyuan.ignore.local.json` 和 `siyuan.allow.local.json` 规则；未通过过滤的结果直接丢弃，不返回给 AI。
6. 用 `docs.jsonl` 和 `notebooks.json` 补全文档字数、块数、更新时间、笔记本名称等元数据；它们不参与搜索匹配。
7. 渲染返回时用 `max_snippets_per_doc` 控制同一文档展示的命中块数量，默认 5 个；同时展示“共命中 N 个块，展示前 M 个”。

**优点**：
- 搜索行为统一，标题、正文、query、regex 都由思源自己的搜索语义决定。
- 代码更简单，不需要维护本地搜索和 API 搜索的双路合并。
- 结果更实时，新写入思源的内容不必等 refresh 后才能被搜索到。
- 仍保留隐私边界：过滤发生在 MCP server 内部，隐藏内容不会进入最终工具响应。

**风险与约束**：
- 隐私过滤必须兼容 API 返回结构：`rootID`/`root_id`、`NodeDocument`/`d`、`box`、`path`、`hPath` 都要处理。
- 按笔记本名称隐藏时，过滤层需要读取思源当前笔记本列表获取名称；但这些名称只用于内部判断，不作为隐藏结果返回。
- 例如隐藏规则是 `{"scope": "notebook", "name": "私人日记"}` 时，API 搜索结果通常只带 `box=notebook_id`，不带笔记本名称；因此 MCP server 必须在内部把 `notebook_id` 映射回当前笔记本名称，才能判断这个结果是否属于被隐藏笔记本。
- 文档树隐藏不能只依赖已过滤的 `docs.jsonl`，因为隐藏根文档可能已从本地索引移除；需要用 API 返回的 `path` 判断文档是否位于隐藏根文档下。
- SQL 模式仍是诊断/高级查询入口，不作为普通搜索默认路径。

**结论**：搜索层采用 API-only 召回。本地索引继续承担启动导航、文档树、统计信息和隐私规则辅助编译职责，但不再作为搜索召回来源。

---

### 问题 15：写入功能设计 — Claude Code Edit/Write 模式映射

**核心洞察**：AI agent（Claude Code、Codex 等）修改代码文件只用两个工具——Edit（精确替换）和 Write（全量重写）。AI 不需要知道行号、AST 节点 ID、字符偏移量。它只传「我看到的原文」和「我要改成什么」。把同一个范式映射到思源的块级写入，可以大幅降低 AI 的操作门槛。

#### 思源 API 能力地图与取舍

思源 API 能力很宽，覆盖笔记本、文档树、块读写、搜索、SQL、资源、历史、仓库快照、同步、系统设置等。完整能力地图单独记录在 [`思源API.md`](./思源API.md)，本节只保留面向 MCP 工具设计的取舍结论。

| 能力层 | 代表 API | 本项目取舍 |
|--------|----------|------------|
| 笔记本 | `notebook/lsNotebooks`, `openNotebook`, `closeNotebook`, `createNotebook`, `removeNotebook` | 继续内部使用打开/关闭关闭的笔记本；不暴露笔记本创建、删除、重命名 |
| 文档树 | `filetree/createDocWithMd`, `renameDocByID`, `removeDocByID`, `moveDocsByID` | 只暴露创建文档；不暴露移动、删除、重命名 |
| 块编辑 | `block/updateBlock`, `appendBlock`, `insertBlock`, `deleteBlock`, `moveBlock` | 只作为服务端内部实现；AI 不直接操作 block API |
| 搜索/读取 | `search/fullTextSearchBlock`, `query/sql`, `export/exportMdContent`, `getBlockKramdown` | 继续支撑搜索、阅读和写入定位 |
| 仓库快照 | `repo/createSnapshot`, `getRepoSnapshots`, `checkoutRepo` | 写入前自动创建工作空间快照；不把 checkout 暴露给 AI |
| 历史回滚 | `history/rollbackDocHistory` 等 | 仅作为人工恢复参考，不作为第一阶段 MCP 工具 |
| 通知 | `notification/pushMsg`, `pushErrMsg` | 写入完成后必须通知用户 |

图例：暴露给 AI 的工具只保留高层语义；底层 API 由 MCP server 内部组合调用。

#### 设计原则

1. **AI 操作文本，不操作块**：AI 不应知道 block ID 的存在（跨文档引用除外）。它看到的和操作的都是 Markdown 文本。
2. **工具越少越好**：Claude Code 只用 Edit + Write 两个工具修改任意代码。写入功能也应该是同量级。
3. **服务器做翻译**：文本→块 ID 映射、old_text 搜索、块操作全部在服务端完成。AI 只传文本。
4. **失败安全**：文本不匹配就拒绝。不给 AI 任何破坏性能力。
5. **写前快照**：每次编辑或创建文档前，先调用思源仓库快照 API 备份整个工作空间。第一阶段不提供 AI 自动回滚工具；如果出现严重问题，用户自行用思源快照恢复工作空间。思源自带有快照清理功能，默认保留180天，每天2个。暂时不需要专门的快照清理功能。

#### 工具一：`siyuan_edit_document`

AI 在文档内进行局部修改的主要工具。对应 Claude Code 的 Edit。

```
参数:
  document_id: str
  old_text:    str         ← 从 Markdown 中摘取的原文片段
  new_text:    str         ← 要替换成的内容
  confirmed:   bool

语义（由 old_text 和 new_text 的组合决定）:
  old_text=""‥ new_text="内容"          → 追加到文档末尾
  old_text="原文"‥ new_text="新文"       → 替换匹配块
  old_text="原文"‥ new_text=""          → 删除匹配块
  old_text="原文"‥ new_text="原文\n新增"   → 后方插入（AI 自然地把锚点文本
                                           包进 new_text，等价于在原块后
                                           插入新块）
```

**服务端流程：**

```
1. 通过 SQL 查询文档下所有块的 Markdown 内容
2. 在块级粒度搜索 old_text
3. 唯一性判断：
   ├── 0 命中  → 返回 "找不到这段文字。文档可能已被修改，请重新读取。"
   ├── >1 命中 → 返回每个命中的上下文（前 80 字符），
   │             让 AI 提供更长的 old_text 以消除歧义
   └── 1 命中  → 继续
4. old_text 与块的匹配形式：
   ├── old_text == 块全文         → updateBlock(block_id, new_text)
   ├── old_text ⊂ 块内容（子串）  → updateBlock(block_id, 替换后的块全文)
   └── old_text 跨多块            → 识别涉及的块列表，逐个处理
5. pushMsg("在 [文档名] 中修改了 N 个块")
6. 返回 {"block_ids": [...], "preview": "..."}
```

#### 工具二：`siyuan_create_document`

对应 Claude Code 的 Write——创建新文档。思源里无法像文件那样"清空后整篇重写"，因为删除文档会丢失子文档、引用等元数据。因此 Write 模式只用于创建，不用于覆盖。

创建文档后，需要立刻执行refresh刷新工作。将新建的文档加载到文档树里面，不然会查看不到。

```
参数:
  notebook_id: str
  title:       str
  path:        str          ← 可选
  markdown:    str
  confirmed:   bool

行为:
  → /api/filetree/createDocWithMd
  → pushMsg("在 [笔记本名] 创建了文档 [title]")
  → 返回新文档的 ID 和 hpath
```

#### 不实现的功能及理由

| API | 理由 |
|-----|------|
| `removeDoc` / `deleteBlock`（独立工具） | 删除通过 `edit_document(new_text="")` 隐式完成。Claude Code 也没有独立的删除工具 |
| `renameDoc` | 改标题属于"重构"，用户在思源里操作更安全 |
| `moveDoc` / `moveBlock` | 改变结构风险高，用户在思源界面拖拽更方便 |
| `createNotebook` / `removeNotebook` | 笔记本管理是人工决策，不应该让 AI 自动创建/删除 |
| `foldBlock` / `unfoldBlock` | UI 层面操作，与知识管理无关 |
| `setBlockAttrs` | 使用频率极低，有需求再加 |
| `prependBlock` / `insertBlock`（独立暴露） | AI 通过 `edit_document` 的文本锚点操作间接完成，不需要知道块位置参数 |
| 整篇覆盖（Write 覆盖现有文档） | 思源文档有子文档树、标签、引用等附加属性，清空重建会丢失这些。只做创建不做覆盖 |

#### 跨文档块引用需要块 ID 嵌入

`siyuan_edit_document` 的文本锚点方案解决了**同一文档内**的增删改。但跨文档块引用场景——在文档 A 中引用文档 B 的某个块 `((block_id "锚文本"))`——AI 必须知道目标块的 ID。

这与 Edit 工具不矛盾：AI 不需要知道所有块的 ID，只需要知道它**想引用的那个**。解决方案是在 `siyuan_read_document` 返回的 Markdown 中嵌入 HTML 注释形式的块 ID：

```markdown
## 中际旭创分析 <!-- block:20260410083015-abc123 -->

2025年营收增长45%，其中800G光模块占比超过60%。
<!-- block:20260410083016-def456 -->
```

AI 读到干净的 Markdown，注释不影响理解。需要引用时，AI 从注释中提取目标块 ID，构造 `((20260410083016-def456 "800G光模块占比"))`。

#### 两阶段实现路径

两个能力**解耦**，可分阶段推进：

| 阶段 | 内容 | 前置依赖 | 状态 |
|------|------|---------|:--:|
| **第一阶段** | `siyuan_edit_document` + `siyuan_create_document` | 无。文本锚点不需要块 ID 嵌入 | ✅ 已完成 |
| **第二阶段（可选）** | 块 ID 嵌入（`siyuan_read_document` 返回注释） | 仅在跨文档块引用或诊断复杂结构时需要 | 待实现 |

**文本锚点的优势**：AI 用刚读完的 Markdown 原文作为锚点直接写入——和它改代码的心智模型完全一致。不需要先实现块 ID 嵌入也能开始写入功能。

**文本锚点的风险与缓解**：
- 唯一性不够：通过要求 AI 提供更长上下文解决（与 Edit 工具的机制一致）
- 并发修改（AI 读后用户改了）：单人笔记使用场景下几乎不发生；发生时 old_text 匹配失败，AI 重新读取即可
- 大块替换：一个块可能有几千字，AI 想只改其中一句。匹配逻辑支持子串替换（old_text 是块内容的子集）

#### 写前快照与手动回滚

写入功能第一阶段必须支持回滚，但回滚不作为 AI 的常用操作，也不暴露 `siyuan_rollback` 工具。

**采用方案：每次写入前创建思源工作空间快照。**

```
AI 调用 siyuan_edit_document / siyuan_create_document
  → MCP server 调用 /api/repo/createSnapshot
  → memo 标记 siyuan-agent-bridge + 操作类型 + 文档信息
  → 执行具体写入
  → pushMsg 通知用户
  → 返回写入结果和快照信息
```

这样做的原因：

| 考虑 | 决策 |
|------|------|
| 回滚不是常用动作 | 正常情况下 AI 应该通过文本锚点和确认机制完成正确编辑 |
| 真正需要回滚时通常是严重事故 | 让用户在思源的快照/备份机制里手动恢复，更符合风险级别 |
| 不希望 AI 自动扩大破坏范围 | 不暴露 `checkoutRepo`，避免 AI 把整个工作空间恢复到旧状态 |
| 实现复杂度 | 第一阶段不维护块级操作日志，不做自动逆向写入 |

`repo/createSnapshot` 是写入前的硬性步骤。如果快照创建失败，写入工具应拒绝继续，除非未来显式增加“跳过快照”的人工确认参数。

`repo/checkoutRepo`、`history/rollbackDocHistory` 等恢复 API 不暴露给 AI。工具返回的快照信息只用于让用户在必要时找到对应备份。

**实测前置条件**：新工作空间如果尚未初始化“数据仓库密钥”，`/api/repo/createSnapshot` 会失败并提示“请先在 [设置 - 关于 - 数据仓库密钥] 中初始化数据仓库密钥”。因此写入功能需要在第一次写入前检测并给出明确错误：请用户先到思源 UI 初始化数据仓库密钥，然后重试。这个密钥不应由本工具保存或生成。

**实测返回行为**：`/api/repo/createSnapshot` 成功时可能返回 `data: null`，不返回 snapshot id。初始化仓库密钥后，如果工作空间没有新的数据变更，调用 `createSnapshot` 可能返回成功但不会在 `getRepoSnapshots` 中新增一条带 memo 的快照。写入工具需要把“创建快照请求成功”和“快照列表中能查到新条目”区分开；真正写入前通常会存在待提交状态，仍需在实现时用真实编辑流程再验证一次。

#### 快照增长与自动清理

写入功能每次编辑前创建工作空间快照，长期使用后会产生大量 `siyuan-agent-bridge` 快照。进一步调研后，这个问题大概率可以交给思源内置仓库清理机制处理，本项目不需要自己实现普通快照删除。

**思源内置机制**：

- 设置项“数据快照保留天数”对应 `Conf.Repo.IndexRetentionDays`，默认 180。
- 设置项“数据快照每天保留个数”对应 `Conf.Repo.RetentionIndexesDaily`，默认 2。
- 源码注释明确为“自动清理数据仓库 / Automatic purge for local data repo”。
- `job.StartCron()` 每 24 小时调用 `model.AutoPurgeRepoJob()`。
- `AutoPurgeRepoJob()` 进入任务队列后执行 `autoPurgeRepo()`；该函数有 6 小时防重复执行限制。
- `autoPurgeRepo()` 要求仓库密钥已初始化，然后读取 repo indexes，根据保留天数和每日保留数量计算 `retentionIndexIDs`，最后调用 `repo.Purge(retentionIndexIDs...)`。

对“180 天 + 每天 2 个”的理解：未被额外保留的本地数据仓库索引会按这两个参数被稀疏保留。超过保留天数的索引不会进入保留集合；同一天内超过每日数量的索引只保留一部分。`repo.Purge(retentionIndexIDs...)` 负责删除不在保留集合中的仓库索引和未引用对象。

这意味着：只要本项目创建的是**普通未标记快照**，它们应该会被思源内置机制纳入清理范围。用户可以通过思源 UI 中的这两个设置控制快照增长。

**本项目策略**：

| 事项 | 决策 |
|------|------|
| 自动快照是否打 tag | 不打。tag 视为用户保护信号，自动快照保持普通未标记状态 |
| 是否实现自定义删除普通快照 | 暂不实现。没有看到按普通快照 ID 删除的公开路由 |
| 是否在 refresh 后自动调用 `purgeRepo` | 暂不调用。思源已有 24 小时自动任务，手动 `purgeRepo` 是整体清理，没必要替代内置调度 |
| 是否保留候选识别工具 | 可以作为诊断能力，但不是第一阶段必要功能 |
| 是否让 AI 处理清理 | 不让。清理属于底层维护，不是 AI 对话任务 |

**关于标签快照**：思源有 `/api/repo/tagSnapshot` 和 `/api/repo/removeRepoTagSnapshot`。源码显示 `tagSnapshot(id, name)` 会对指定快照添加 tag，`removeRepoTagSnapshot(tag)` 调用 `repo.RemoveTag(tag)`，删除的是标签快照/标签保留关系，不是按普通快照 ID 删除快照本体。因此不应给所有 bridge 快照自动打 tag；tag 应保留给用户手动保护重要恢复点。

**仍需实测的问题**：源码能确认自动清理会根据 `IndexRetentionDays` 和 `RetentionIndexesDaily` 调用 `repo.Purge(retentionIndexIDs...)`，但没有在本项目中实测 purge 后普通快照列表的具体变化。若后续需要验证，可在测试工作空间中：

1. 把“数据快照保留天数”临时调小，例如 1 天；把“每天保留个数”调成 1。
2. 制造多条普通未标记快照和至少一条带 tag 的快照。
3. 记录 `/api/repo/getRepoSnapshots` 和 `/api/repo/getRepoTagSnapshots`。
4. 调用 `/api/repo/purgeRepo` 或等待 24 小时自动任务。
5. 再次查询快照列表，确认普通未标记快照被清理、tag 快照仍保留。
6. 测试完成后恢复用户原本的保留设置。

当前结论：**本项目不需要再自建快照清理机制**。写入工具只需确保自动创建的快照 memo 有本工具前缀、且不自动打 tag；快照数量控制交给思源内置数据仓库清理设置。

#### 写入工具实测后的修正决策

真实 MCP 写入测试后，发现几个需要明确取舍的问题：

| 问题 | 决策 |
|------|------|
| 多工作空间导致旧 `index.md` 混入启动包 | 暂不处理。当前假设用户主要使用单一工作空间；多工作空间 profile 后续再做 |
| `new_text=""` 删除整块会留下空块/占位符 | 暂不处理。当前编辑能力只承诺单块文本替换；未来支持多块编辑时，再统一引入内部 `deleteBlock` 语义 |
| 创建文档时 Markdown 首行 H1 与文档标题重复 | 文档标题归文档树，正文一级标题归正文大纲；应该在MCP工具中提示AI，默认不用一级大纲作为标题，除非用户明确要求 |
| `createSnapshot` 的 `tags` 参数 | 本轮移除。思源 `/api/repo/createSnapshot` 只解析 `memo`；自动快照也不应该打 tag |
| `siyuan_edit_document` 后不刷新本地索引 | 保持现状。编辑后刷新有性能成本；搜索是 API-only，读取走实时导出，局部编辑后不要求立即刷新本地统计 |

因此本轮修正只做两个实现改动：去掉快照 `tags` 参数；创建文档时规避重复 H1。其他问题记录为后续能力边界。

#### 复杂结构文档的阅读与编辑边界

2026-05-03 用一个包含超级块、水平/垂直合并、嵌套超级块、表格、图片、嵌套列表、空块和数据库的测试文档验证了当前 MCP 阅读行为。

**当前 MCP 看到的内容**：

- `siyuan_read_document` 调用思源 `/api/export/exportMdContent`，返回的是思源导出的 Markdown，不是原生块树。
- MCP server 只在外层追加文档路径、ID、字数、块数、更新时间、附件提取提示和基于 Markdown 标题生成的大纲。
- 超级块和布局信息不会以特殊结构返回。水平合并、垂直合并、叠加合并会被思源导出逻辑展开为普通 Markdown 段落，顺序大致是阅读顺序。
- 表格会导出为 Markdown 表格；图片会导出为 Markdown 图片引用；列表会导出为 Markdown 列表。
- 空块可能表现为空行或零宽占位符。
- **数据库/属性视图（已升级，2026-05-04）**：不再依赖导出 Markdown 中空的 `<div>` 占位符。`build_display_blocks` 检测到 `type=av` 块后，调用 `/api/av/getAttributeView` 获取字段定义和行数据，按 `keyIDs` 顺序转置列向数据为 Markdown 表格。AI 看到实际数据（列名 + 所有行），并通过 HTML 注释标注只读。详见下方 [数据库/属性视图处理](#数据库属性视图处理)。

**原始块层的复杂性**：

- 同一篇文档在 `blocks` 表中同时包含段落块、标题块、表格块、列表容器块和列表项块。
- 列表尤其容易造成重复视图：列表容器块包含整个列表的 Markdown，列表项块和叶子段落块又分别包含局部内容。若编辑逻辑天真遍历所有非文档块，可能对同一段逻辑内容产生多处匹配。
- 超级块/布局在导出 Markdown 中被压平后，AI 无法可靠判断原始视觉结构，也无法保证修改后仍保持原布局。

**产品判断**：

本项目不应把目标设为“让 AI 精确操控思源的所有块结构”。这个目标实现复杂、收益有限，并且容易给用户造成“AI 能安全编辑任意复杂文档”的错误预期。更合理的定位是：

1. 阅读和搜索尽量完整，允许有损表达复杂结构。
2. 编辑工具只承诺简单、低风险、文本锚点式修改。
3. 复杂结构区域以保守处理为主：能确认是单个普通文本块才编辑；不能确认时拒绝，并提示用户在思源 UI 中处理。
4. AI 需要大幅改写复杂文档时，优先新建草稿文档、追加建议、生成可人工复制的改写稿，而不是原地重排复杂结构。

**编辑工具优化方向**：

| 方向 | 价值 | 可实现性 | 决策 |
|------|------|----------|------|
| 单块段落/标题替换 | 高。覆盖最常见的错字、补充、改写、句段替换 | 高 | 保持核心能力 |
| 文档末尾追加 | 高。适合总结、评论、行动项、AI 草稿 | 高 | 保持核心能力 |
| 锚点后插入新块 | 高。适合在已有标题/段落后补充内容，借鉴 Claude Code Edit 模式 | 高 | 已实现（2026-05-04） |
| 创建新文档 | 高。适合长内容、复杂改写和低风险写入 | 高 | 保持核心能力 |
| 单个普通列表项替换 | 中。常见但块结构比段落复杂 | 中 | 可支持，但必须唯一匹配 |
| 多块连续文本替换 | 中。用户会有需求，但边界复杂 | 中低 | 后续谨慎实现，只处理连续普通文本块 |
| 单块删除 | 中。误删代价高，但功能自然 | 中 | 已支持 `new_text=""` 真删除单块（deleteBlock API）；跨块删除不支持 |
| 超级块/布局编辑 | 低到中。使用频率低，失败代价高 | 低 | 不追求精确支持 |
| 数据库/属性视图编辑 | 低。不是普通写作编辑 | N/A | 不编辑——拦截并提示用追加模式新建表格 |
| 文档整体覆盖 | 表面价值高，实际风险大 | 低 | 不做；用创建新文档替代 |

**建议的实现约束**：

- `siyuan_edit_document` 默认只编辑唯一匹配的单个块。
- 候选块应优先限制为普通文本块和标题块；列表、表格、数据库、超级块相关区域需要更严格判断。
- 如果 `old_text` 同时命中列表容器块和列表项/段落块，应返回歧义，让 AI 提供更精确的锚点或改为新建草稿。
- 如果目标块 Markdown 中包含复杂结构信号（表格、多级列表、大量零宽空块、疑似数据库导出），工具应倾向拒绝复杂替换。
- 多块编辑如果后续实现，应只支持“连续普通文本块”这一窄场景，并在返回中明确修改了几个块；不要尝试重建超级块、数据库或复杂排版。
- 对 AI 的 skill 提示词应强调：读到复杂结构文档时，可以总结和提出修改建议；真正编辑时优先做小的文本替换或创建新文档，不要承诺保留复杂排版。

**最终取舍**：功能完备性让位于可实现性和安全性。日常价值最高的是“可靠地读、搜、创建、追加、改一小段”，不是完整复刻思源编辑器。

后续将通过 [`块ID阅读实验计划.md`](./块ID阅读实验计划.md) 验证可选块 ID 返回模式：先观察复杂文档和普通文档在带块 ID 输出中的差异，再决定是否给编辑工具增加 `block_id` 辅助参数。这个实验不改变默认纯 Markdown 阅读策略，也不直接承诺复杂结构编辑能力。

#### 数据库/属性视图处理

**实现日期**：2026-05-04

**问题**：思源数据库（属性视图）在导出 Markdown 中显示为空 `<div>` 占位符，AI 看不到任何数据行。但思源原生搜索能穿透数据库找到内容——三端不一致（搜索能看到，阅读看不到，编辑碰不到）。

**实现决策**：

1. **阅读**：`build_display_blocks` 检测到 `type=av` 块后，不再使用块自身的空 Markdown（即 `<div>` 占位符），而是从块 Markdown 中提取 `data-av-id`，调用 `/api/av/getAttributeView` 获取属性视图的完整数据，按 `keyIDs` 顺序转置列向数据（`keyValues[].key.name` 为列头，`keyValues[].values[]` 为列值）为 Markdown 表格。在表格上方注入 HTML 注释和引用提示：

   ```markdown
   <!-- siyuan:database av-id=xxx type=table readonly=true -->
   > 此表格为数据库（属性视图），只读。如需编辑数据，请在文档末尾追加新表格。

   |主键|单选|
   | --- | --- |
   |1|A|
   |...|...|
   ```

   注释仅供 AI 解析（标注只读属性），引用提示供人阅读。在引用阅读模式（`include_block_ids=true`）下，额外注入 `<!-- siyuan:block id=xxx type=av -->` 保留块级定位。

2. **编辑拦截**：`_match_old_text` 的 SQL 查询排除 `type=av`（`type NOT IN ('d', 'av')`）。若 `old_text` 仅命中数据库块，返回 `"database_block"` 状态并抛出明确错误：

   > 匹配到的 old_text 位于数据库/属性视图块中，不支持直接编辑。如需修改数据，请用 old_text=""（追加模式）在文档末尾创建新表格。

3. **替代工作流**：AI 被告知可以用 `old_text=""` 在文档末尾追加建议表格，但不直接修改数据库。用户看到 AI 的建议后在思源 UI 中手动操作。

4. **搜索**：保持现状。思源原生搜索能穿透数据库找到内容，搜索结果中数据库所在文档会被列出来。

**技术细节**：

- `client.py` 新增 `get_attribute_view(av_id)` 方法，封装 `/api/av/getAttributeView`。注意 `_post` 已剥离 `data` 信封，直接返回 `result.get("av", {})`。
- 列值渲染根据字段类型处理：`block` 类型取 `value.block.content`，`select` 类型 merge `value.mSelect[].content`，其他类型 fallback 到 `value.block.content` 或 `value.content`。
- `DATABASE_BLOCK_TYPES = frozenset({"av"})` 独立于 `SKIP_BLOCK_TYPES`，语义清晰：av 块不跳过（需要渲染），但数据来源是 API 而非块自身的 Markdown。
- av 块不遍历子节点（数据库内部行结构对 AI 无意义且可能导致重复视图）。

**为何不做结构化数据库视图**：不暴露字段类型、选项列表、视图配置、筛选/排序规则等数据库语义。AI 的价值是理解和建议，不是替代思源数据库 UI。完整数据库管理器（如 `siyuan-query-mcp`）是独立项目。

#### 块样式属性（IAL）静默保留

**实现日期**：2026-05-04

**问题**：思源块的行级样式（信息/成功/警告/错误等背景色）存储在 `blocks.ial` 字段中（如 `style="color: var(--b3-card-info-color);background-color: var(--b3-card-info-background);"`）。`siyuan_edit_document` 调用 `update_block` 时只传了 `dataType: "markdown"` 和 `data`，未传 `ial`，思源内核会重置 IAL，导致编辑后样式丢失。

**实现决策**：

- `client.update_block()` 增加可选 `ial` 参数，有值时传入 `{"ial": "..." }` 字段。
- 编辑流程在调用 `update_block` 前，用 SQL `SELECT ial FROM blocks WHERE id = '{block_id}'` 静默读取当前块的 IAL。
- IAL **完全不暴露给 AI**——不在 `siyuan_read_document` 输出、搜索片段或编辑预览中出现。AI 无需知道样式细节。
- AI 无法通过 MCP 工具修改样式属性，只能修改文本内容。样式由思源原样保留。

#### 块 ID 精确定位编辑

**实现日期**：2026-05-04

**问题**：当 `old_text` 很短（如单个词"信息"）时，可能同时匹配多个块，导致编辑失败。纯文本锚点无法区分同内容的块。

**实现决策**：

- `siyuan_edit_document` 增加可选 `block_id` 参数。
- 提供 `block_id` 时，跳过文本搜索，直接用 ID 定位块，但**必须同时验证**：
  1. 块 ID 存在且内容非空 → 否则报"块 ID 不存在或内容为空"
  2. 块属于当前文档（`root_id` 匹配）→ 否则报"块不属于该文档"
  3. 块不是数据库块（`type=av`）→ 否则报数据库不可编辑
  4. `old_text` 是块内容的子串 → 否则报"ID 和文本不匹配"
- 四项全部通过才执行编辑。这避免了 ID 写错导致改错块的风险。
- AI 用 `siyuan_read_document(include_block_ids=true)` 获取块 ID 后，可精确编辑。

**使用场景**：歧义消解（短词多匹配）。`block_id` 的唯一用途是消除歧义——其他情况不需要它。当 `old_text` 已能唯一定位时传 `block_id` 是冗余但无害的（跳过 SQL 搜索直接验证）。

#### 锚点匹配插入新块（Claude Code Edit 模式）

**实现日期**：2026-05-04

**问题**：`siyuan_edit_document` 可以替换已有块、在末尾追加新块，但无法在文档中间插入新块。当用户已在文档中搭建了标题骨架，AI 自然应该在对应标题下补充内容，而不是把内容写到末尾或新建文档让用户手动合并。

**设计理念**：借鉴 Claude Code Edit 工具的单一锚点模式——`old_string` 既是定位也是内容锚点，`new_string` 包含锚点+新内容。AI 不需要区分"替换/插入"模式，工具根据参数自动判断。

**实现决策**：

- 当 `new_text.startswith(old_text)` 且 `block_md.strip() == old_text.strip()`（锚点块内容与 `old_text` 完全一致）且 `len(new_text) > len(old_text)` 时，工具判定为插入模式。
- 提取 `new_text` 中 `old_text` 之后的内容部分，调用 `client.insert_block_after(block_id, suffix)` 在锚点块后插入新块。
- 三个条件缺一不可，防止子串误判：
  - `startswith` → 确认 AI 的意图是保留锚点
  - `== 精确匹配` → 只在锚点是整个块内容时才插入，行内子串不触发
  - `len >` → 排除无操作（`new_text == old_text`）
**语义矩阵**：

| old_text | new_text | 行为 |
|---|---|---|
| `## ABC 五线谱` | `## ABC 五线谱\n\nchart` | 锚点匹配 → 在标题后插入代码块 |
| `错别子` | `错别字` | `new_text` 不以 `old_text` 开头 → 替换 |
| `苹果`（行内词） | `苹果很甜` | 块内容不等于 `"苹果"` → 替换（子串替换） |
| `""` | `新内容` | 末尾追加（不受影响） |

**和 Claude Code Edit 的对应关系**：

```
Claude Code Edit:  old_string="## ABC"  new_string="## ABC\n\nchart"  → 文件后插入
我们:              old_text="## ABC"    new_text="## ABC\n\nchart"    → 锚点块后插入
```

AI 无需学新参数或新模式。它像编辑文件一样描述"从什么改成什么"，工具自动判断是替换还是插入。

**和 `block_id` 的关系**：插入模式不依赖 `block_id`。当锚点文本有歧义时，AI 可以加 `block_id` 消除歧义（和替换模式一致）。`block_id` 的语义始终是"歧义消解"，不随编辑模式变化。

**不用 `old_text=""` + `block_id` 实现插入的原因**：
- `old_text=""` 的语义是"找不到目标，加到末尾"，不应让它在有 `block_id` 时产生新语义
- 不符合 Claude Code Edit 工作原理（不存在 `old_string=""` 的插入变体）
- 锚点匹配插入已覆盖所有插入场景

#### 单块删除（`new_text=""`）

**实现日期**：2026-05-04

**行为**：当 `old_text` 匹配到块且 `new_text=""` 时，工具将块内容清空，块从视图中消失。

**测试验证**（2026-05-04，`/高级块类型创建测试`）：

| 块类型 | 结果 | 备注 |
|---|---|---|
| 段落 (`p`) | ✅ | 唯一匹配即可删除 |
| 标题 (`h`) | ✅ | 大纲中消失 |
| 代码块 (`c`) | ✅ | 含围栏的完整匹配 |
| 引用块 (`b`) | ✅ | 同段落 |
| 列表项 (`i`) | ⚠️ | 需 block_id 消歧义（容器块+列表项双重表示） |
| 中间位置块 | ✅ | 前后块无缝衔接，无布局问题 |

**技术细节**：当替换后的 `new_block_md` 为空或仅含空白时，调用 `client.delete_block(block_id)`（封装 `/api/block/deleteBlock`）真正删除块，不留空壳。IAL 保留逻辑在删除路径前短路，避免无谓的 SQL 查询。

**跨块删除**：不支持。`_match_old_text` 搜索单个块的 markdown，`old_text` 跨多个块时没有单个块能匹配，报"未找到匹配"。要删除多个块，AI 需要逐个调用。

**语义矩阵总结**：

| old_text | new_text | 行为 |
|---|---|---|
| 非空 | 非空，`new_text.startswith(old_text)` + 精确匹配 | 插入 |
| 非空 | 非空，其他 | 替换（或子串替换） |
| `""` | 非空 | 末尾追加 |
| 非空 | `""` | 删除（清空块内容） |
| `""` | `""` | 报错 |

#### 复杂渲染块类型编辑支持

**实现日期**：2026-05-04

**问题**：思源支持多种复杂渲染块类型（ABC 五线谱、ECharts 图表、Flowchart 流程图、Graphviz 关系图、Mermaid 图表、Mindmap 思维导图、PlantUML 等），它们本质上都是 `type=c`（代码块），通过 IAL 中的语言标识区分渲染引擎。早期测试仅修改了块旁介绍文字，未验证这些块的内容能否被 MCP 工具正确编辑。

**测试验证**（2026-05-04，`/格式测试/其他类型`）：

| 块类型 | 块 ID | 测试内容 | 结果 |
|---|---|---|---|
| ABC 五线谱 | `20260504130705-2xuukj5` | 《小星星》完整乐谱（16 小节，ABC 记谱法） | ✅ |
| ECharts | `20260504130637-z767o1q` | 柱状图 JSON 配置（标题、坐标轴、系列数据） | ✅ |
| Flowchart | `20260504130841-s304vf4` | 身份验证流程图（4 节点 + 条件分支） | ✅ |
| Graphviz | `20260504130912-v0xm5no` | 系统架构 DOT 图（4 节点带样式和边标签） | ✅ |
| Mermaid | `20260504130930-rq1c8ek` | 编辑-存储-同步时序图（3 参与者，7 步交互） | ✅ |
| Mindmap | `20260504130953-o0oo50e` | 思源生态系统三级思维导图 | ✅ |
| PlantUML | `20260504131115-ib6vjwg` | 用户-笔记本-文档类图（带属性和关联） | ✅ |

**结论**：

- 所有这些类型本质都是代码块（`type=c`），`update_block` API 对其文本内容的处理与普通代码块完全一致。
- 由于编辑流程已实现 IAL 静默保留（编辑前读取 IAL → edit 后 `setBlockAttrs` 恢复），代码块的语言标识（如 `data-type="abc"` 等）不会因编辑而丢失，渲染引擎正常工作。
- 不需要为每种渲染类型做特殊处理。现有架构（文本锚点搜索 + block_id 双重验证 + IAL 两步保留）天然支持所有以 `type=c` 存储的复杂块类型。
- MCP 工具对复杂块的功能边界：可以编辑文本源码，但不对源码语义做校验（如不检查 JSON 是否是合法 ECharts 配置、ABC 是否合法记谱）。语义错误由思源渲染引擎在 UI 中暴露。

**AI 使用建议**：当用户要求"画一个 XX 图"时，AI 应直接用 `siyuan_edit_document` 编辑对应代码块的内容（或用 `old_text=""` 追加新代码块），填入合法的 DSL 源码。不需要用 `siyuan_create_document` 新建文档。

#### 多工作空间连接配置问题

思源允许用户切换不同工作空间；不同工作空间可能使用不同 HTTP API 端口和 token。连接配置应支持多个工作空间 profile，但运行时只允许连接一个当前在线工作空间。

推荐 `config.local.json` 结构：

```json
{
  "profiles": [
    {
      "name": "主工作空间",
      "url": "http://127.0.0.1:6806",
      "token": "..."
    },
    {
      "name": "测试工作空间",
      "url": "http://127.0.0.1:11965",
      "token": "..."
    }
  ],
  "language": "zh-CN"
}
```

不设置 `active_profile`。运行时自动检测哪个 profile 在线：

1. 遍历 `profiles`，逐个测试 URL 和 token。
2. 没有 profile 在线：报错，提示用户打开一个已配置的思源工作空间。
3. 只有一个 profile 在线：自动使用该 profile。
4. 多个 profile 在线：报错，列出在线 profile 的名称和 URL，提示用户关闭到只剩一个后重试。

不支持多个工作空间同时在线后由 AI 混合使用。原因是系统笔记本、AI 使用指南、工作空间索引、隐私规则都属于工作空间级上下文；如果同时连接多个工作空间，容易出现“读取 A、用 B 的隐私规则过滤、把索引写到 C”的高风险混淆。

安装/init 流程应支持：

1. 输入工作空间名称（可选）。
2. 输入端口，默认 `6806`。
3. 输入 token。
4. 测试连接。
5. 成功后写入 `config.local.json`。
6. 可选继续添加其他工作空间。

环境变量可作为高级用户临时覆盖，但不是普通安装路径：

```text
SIYUAN_API_URL
SIYUAN_API_TOKEN
SIYUAN_AGENT_LANGUAGE
```

安全要求：

- `config.local.json` 必须 Git 忽略。
- ZIP 包不能包含 `config.local.json`。
- doctor 和错误信息不能打印 token。
- 给 AI Agent 的安装说明必须明确：不要复述、记录或上传 token。

`siyuan_start` / `doctor` 应显示当前自动选中的 profile 名称和 URL，帮助用户确认连接的是哪个工作空间。

#### ZIP 内测安装包与 AI Agent 辅助安装

第一阶段对外内测不做传统 exe 安装器，也暂不做思源插件和项目网站。发布物以一个 ZIP 包为主，目标是让用户把 ZIP 交给自己的 AI Agent，由 AI Agent 完成解压、配置、MCP 注册、Skill 注册和诊断。

目标用户流程：

```text
1. 用户下载 ZIP。
2. 用户打开思源，确认要连接的工作空间。
3. 用户把 ZIP 路径、工作空间名称、端口、token 告诉自己的 AI Agent。
4. AI Agent 解压 ZIP 到稳定目录。
5. AI Agent 运行安装/初始化脚本，写入 config.local.json。
6. AI Agent 注册 MCP 配置。
7. AI Agent 安装或引用 Skill。
8. AI Agent 运行 doctor 验证。
9. 用户重启 AI 客户端后开始使用。
```

用户唯一需要主动提供的信息：

```text
- ZIP 文件路径
- 工作空间名称（可选，但推荐）
- 工作空间端口，默认 6806
- 工作空间 token
```

ZIP 包需要对 AI Agent 自解释，至少包含：

```text
INSTALL_FOR_AI.md              # 给 AI Agent 的安装说明
doctor.bat                     # 诊断脚本
plugins/.../scripts/run_mcp.py # 稳定 MCP 启动脚本
plugins/.../skills/...         # Skill 目录
mcp_configs/                   # 常见 MCP 客户端配置模板
```

安装目录应稳定，不建议让 MCP 指向 Downloads 中的临时解压目录。Windows 可优先解压到：

```text
%LOCALAPPDATA%\siyuan-agent-bridge
```

`INSTALL_FOR_AI.md` 必须明确安全要求：

- 不要在对话中复述 token。
- 不要把 token 写入日志、README 或任何会被上传/提交的位置。
- `config.local.json` 只保存在本地安装目录，且不打包进 ZIP。
- 安装完成后运行 doctor，确认思源连接、系统笔记本、隐私规则、MCP 启动脚本和 Skill 都正常。

MCP 注册策略：

- 内测阶段不要求安装器自动识别所有 AI 客户端。
- ZIP 中提供常见客户端配置模板，AI Agent 根据用户使用的客户端替换绝对路径。
- MCP 配置应指向 ZIP 解压后的 `plugins/siyuan-agent-bridge/scripts/run_mcp.py`。

Skill 注册策略：

- ZIP 内保留完整 Skill 目录。
- 如果用户的 AI 客户端支持 Skill，AI Agent 将 Skill 复制到对应目录。
- 如果客户端不支持 Skill，AI Agent 至少注册 MCP，并把 README / Skill 内容作为使用说明参考。

这个发布路径的核心不是让用户手工理解 MCP，而是让用户的 AI Agent 能够”读懂包、解压、配置、验证”。因此 ZIP 包根目录的说明文件和诊断脚本比传统产品界面更重要。

**安装目录灵活性**：ZIP 可以解压到任意文件夹，不强制 `%LOCALAPPDATA%`。`run_mcp.py` 通过 `Path(__file__).resolve().parents[1]` 自动解析安装根目录，不依赖固定路径。

**版本更新行为**（实测验证）：

| 组件 | 覆盖解压后 | 说明 |
|------|:---:|------|
| MCP | 自动更新 | MCP 配置存的是 `run_mcp.py` 的路径，覆盖文件后路径不变，重启 Claude Code 即生效 |
| Skill | 需手动同步 | CC Switch 通过 ZIP 导入时把 Skill 复制到自身存储（`~/.cc-switch/skills/`），而非直接引用源文件。覆盖安装目录不影响 CC Switch 内的 Skill 副本 |
| `config.local.json` | 不受影响 | 不在 ZIP 包内，覆盖解压不会丢失 |
| `knowledge_base/` | 不受影响 | 运行时生成，不在 ZIP 包内 |

**Skill 更新步骤**：在 CC Switch 中先删除旧 Skill，再导入新 ZIP。直接导入新 ZIP 而不删旧的可能导致残留文件。CC Switch 的 symlink/file-copy 同步模式影响的是它到 CLI 工具目录的连接方式（`~/.cc-switch/skills/` → `~/.claude/skills/`），不影响与安装目录源文件的关系。

#### 安全机制

所有写入工具遵循统一的安全模式：

```
AI 调用写入工具
  ├── confirmed=true 必须
  ├── 参数校验（格式、长度）
  ├── 调用思源 API
  ├── pushMsg 通知 → 用户在思源 UI 看到变更
  └── 返回操作结果
```

- 不做 silent write：每次写入都在思源前台弹通知
- 不做 delete 独立工具：删除只能通过 edit_document(new_text="")
- confirmed=true 与现有隐私工具保持一致

---

### 开发路线图

排序标准：**"现在我每次打开 AI，这件事能让我少走多少弯路"**。不按"软件工程的完整性"排，不按"如果以后有别的用户怎么办"排。

#### 第一优先级：每次会话都直接受益

一条原则：**index.md 已经存在了（365 篇文档、完整导航、AI 摘要），但 AI 现在完全不知道它存在。** 这是目前最大的浪费。

| # | 事项 | 改动量 | 效果 |
|---|------|:---:|------|
| **A** | **`siyuan_start` 纳入 index.md** | 小 | 每次新会话，AI 直接拿到完整导航。从"盲人摸象"变成"有地图" |
| **B** | **`siyuan-agent-bridge` SKILL.md 更新** | 中 | AI 知道启动后优先看 index.md 快速路由表，知道怎么用已有的导航和搜索。不改这个，A 改了 AI 也不会用 |
| **C** | **MCP 隐私工具**（hide/unhide/allow/close） | 中 | 现在想隐藏内容要编辑 JSON 文件。做完之后在对话里说"隐藏 XX"就行 |
| **D** | **`siyuan_start` 连接失败友好提示** | 极小 | 思源没启动时不再是一坨错误堆栈，而是"请先启动思源笔记" |

A 和 B 是同一件事的两面：代码返回 index + AI 知道去读它。做完之后，**每次新会话的启动体验从"从头探索"变成"有现成导航"**。

#### 第二优先级：日常使用顺手

| # | 事项 | 改动量 | 效果 |
|---|------|:---:|------|
| **E** | **`siyuan_refresh_index` 清理 ai_workspace** | 小 | 每次 refresh 清空上次的临时文件，保持整洁 |
| **F** | **思源 API 写操作 + "思源Agent"笔记本** | 大 | 在思源里创建 guide 文档，用户可以在思源 UI 中编辑。当前 guide.md 在项目目录里已经能用，迁移到思源是体验优化而非紧急需求 |

#### 第三优先级：锦上添花

| # | 事项 | 改动量 | 效果 |
|---|------|:---:|------|
| **G** | **阅读返回中嵌入块 ID** | 中 | 降级为可选增强，只服务跨文档块引用或复杂结构诊断 |
| ~~H~~ | ~~`siyuan_read_document` 附件提取~~ | — | ✅ 已完成：自动提取所有资源文件到 workspace，保留原始引用不变 |
| ~~I~~ | ~~tree.md 增加块数~~ | — | ✅ 已完成：扩展为统计指标全面重构，新增 block_count + char_count，SQL 优化 |
| ~~J~~ | ~~实时搜索隐私过滤审查~~ | — | ✅ 已完成：`_enrich_search_blocks()` 严格 `continue`，正确性由 ensure_notebooks_open 保证 |

#### 第四优先级：对外发布时才需要

| # | 事项 |
|---|------|
| K | README 更新 |
| L | dist 发布包重新打包 |
| M | 首次初始化隐私引导（自己已经设置过了，不需要） |

#### 待实现（更新于 2026-05-03）

| # | 事项 | 改动量 | 效果 | 状态 |
|---|------|:---:|------|:--:|
| **I** | **临时开放更便捷机制** | 小 | 当前通过手动改表格 `Hide` 列为 `no` 实现临时开放；未来可考虑时效性自动恢复 | 待设计 |

---

#### 当前状态

**A + B + C + D + E 已完成** (2026-05-02)。A（index.md 纳入启动包）、B（SKILL.md 更新）、C（MCP 隐私工具 2 个——合并为 `siyuan_privacy` + `siyuan_temporary_allow`）、D（连接失败友好提示）、E（ai_workspace 清理）全部到位。

**三-I（统计指标重构）已完成** (2026-05-02)。新增 `block_count` + `char_count`，删除死代码，索引刷新从 ~30s 降到 ~2s。

**三-J（实时搜索隐私过滤审查）已完成** (2026-05-02)。`_enrich_search_blocks()` 对不在安全索引的文档一律 `continue`。

**三-H（附件提取）已完成** (2026-05-02)。`siyuan_read_document` 自动提取所有 `assets/` 引用文件。

**提示词优化已完成** (2026-05-02)。删除 START_HERE.md，AGENTS.md 改为开发者指南，SKILL.md 内联安全规则，单一信息源原则落地。

**系统笔记本 + 隐私规则迁移已完成** (2026-05-03)。`i18n.py`（多语言解析与模板）、`agent_notebook.py`（系统笔记本服务层）新增；`ignore.py` 重写（删除本地 JSON I/O，新增 Markdown 表格解析）；`mcp_server.py` 更新（移除 `siyuan_privacy` 和 `siyuan_temporary_allow`，新增 Privacy Rules 硬编码保护，工具从 11 个精简为 9 个）；`cli.py` 清理隐私命令；SKILL.md 更新。119 个测试全部通过。

剩余待实现：临时开放的更便捷机制（当前通过手动改表格 `Hide` 列实现）。

**WinError 10054 连接重置问题已修复** (2026-05-03)。根因：思源内核使用 Go `net/http` 服务器，默认 HTTP keep-alive；空闲超时后服务器关闭连接，Python urllib 尝试复用时触发 `WSAECONNRESET (10054)`。修复：(1) `client.py` 所有 HTTP 请求添加 `Connection: close` 头，每次请求后关闭连接；(2) 连接错误自动重试 3 次（间隔 0.3s/0.6s）；(3) 错误消息改进，显示具体连接失败原因而非笼统的"似乎没有启动"。详见下方"HTTP Keep-Alive 连接问题"小节。

**G（块 ID 嵌入可选模式）已完成** (2026-05-03)。`siyuan_read_document` 新增 `include_block_ids` 参数（默认 `false`），启用后通过 HTML 注释 `<!-- siyuan:block id=... type=... -->` 注入块 ID。这个模式对外应称为“引用阅读”，主要服务跨文档块引用、精确定位和后续编辑辅助。实现已从“全局 `ORDER BY sort` 扁平拼接”改为调用 `/api/block/getChildBlocks`，使用思源返回的真实子块顺序递归遍历。列表容器自身不渲染但会遍历列表项；列表项和表格的 Markdown 已包含子内容，因此渲染后不再递归子孙，避免重复；超级块只显示注释并继续遍历子块，避免超级块 Markdown 和子块重复。详情见 [`块ID阅读实验计划.md`](./块ID阅读实验计划.md)。

真实 MCP 读取对比实验已完成 (2026-05-03)：`siyuan_read_document` 的普通阅读、分页、附件提取和引用阅读均可用；实验发现普通阅读模式下超级块会同时输出超级块 Markdown 和子块内容，导致复杂文档重复显示。已修复为普通阅读跳过超级块容器、只递归显示子块；引用阅读保留超级块块 ID 注释并递归显示子块。

注意：Codex 当前已加载的 MCP 工具缓存只暴露 8 个工具，缺少 `siyuan_start`；仓库内 `plugins/siyuan-agent-bridge/scripts/run_mcp.py` 通过本地 JSON-RPC `tools/list` 验证实际暴露 9 个工具。若客户端看不到 `siyuan_start`，需要重新加载/重启 MCP 注册。

剩余待实现：临时开放的更便捷机制；是否给 `siyuan_edit_document` 增加 `block_id` 可选参数仍待设计。

原 F（思源Agent笔记本）已调整为更轻量的系统笔记本方案：不新增 MCP 写索引工具，不把系统笔记本强行排除出普通索引；通过 Skill 约束 AI 不把它当作用户原始知识材料。

---

### 后续完善详细清单

以下是各任务的详细实现说明，按优先级排列。完成 A+B 后逐步推进。

#### A. `siyuan_start` 纳入 index.md

**改动**：`mcp_server.py` 的 `siyuan_start()` 方法

**逻辑**：
```
if knowledge_base/index.md 存在:
    启动包中插入 index.md 全文（在 guide.md 之前）
else:
    启动包末尾附加提示："当前没有导航索引，是否需要我先快速扫一遍
    你的笔记本结构，创建一个索引？这样以后每次都能更快定位到相关内容。"
```

index.md 放在 notebook overview 之后、guide 之前，形成自然的阅读顺序：概览 → 导航索引 → 个人偏好。

#### B. `siyuan-agent-bridge` SKILL.md 更新

**改动**：`plugins/siyuan-agent-bridge/skills/siyuan-agent-bridge/SKILL.md`

**要点**：
- Mandatory Startup 新增步骤：启动后优先检查 index.md 是否存在，存在则用快速路由表定位
- Tool Use 中说明 index.md 的定位（AI 生成的语义导航）和 fallback 策略（过期时用 tree + find）
- 新增隐私工具的用法说明
- startup 流程改为：`siyuan_start` → 读 index.md（如有）→ 读 guide → 后续操作

#### C. MCP 隐私工具

**改动**：`mcp_server.py`，直接调用 `ignore.py` 和 `indexer.py` 的底层函数

| 工具 | 实现 |
|------|------|
| `siyuan_privacy(action="hide", scope, locator, reason?)` | 调用 `add_persistent_ignore()` → 自动 `refresh_index()` |
| `siyuan_privacy(action="unhide", scope, locator)` | 调用 `remove_persistent_ignore()` → 自动 `refresh_index()` |
| `siyuan_temporary_allow(action="open", scope, locator, minutes?, reason?)` | 调用 `make_temporary_allow()` + `write_temporary_allow()` |
| `siyuan_temporary_allow(action="close")` | 调用 `close_temporary_allow()` |

注意：这是 AI 通过 MCP 使用的工具，安全要求高——hide 和 unhide 需要 AI 在调用前向用户确认范围，避免误操作。

#### D. `siyuan_start` 连接失败友好提示

**改动**：`mcp_server.py` 的 `siyuan_start()` 方法

区分两种错误：
- 连接被拒绝 → "思源笔记似乎没有启动。请打开思源笔记软件后重试。"
- 其他错误（token、网络等）→ 保留现有错误信息

#### E. `siyuan_refresh_index` 清理 ai_workspace

**改动**：`indexer.py` 的 `refresh_index()` 或 `mcp_server.py` 的 `siyuan_refresh_index()`

每次 refresh 时清空 `ai_workspace/` 下除 `README.md` 外的所有文件和目录。

#### F. 写入功能第一阶段：`siyuan_edit_document` + `siyuan_create_document`

**改动**：`client.py`（新增 write API 方法）+ `mcp_server.py`（新增 2 个 MCP 工具）

**设计**：文本锚点模式——AI 传入 `old_text`（从 Markdown 中读到的原文片段），服务端搜索匹配块后执行块操作。AI 不接触块 ID，心智模型与改代码一致。详见 [问题 15](#问题-15写入功能设计--claude-code-editwrite-模式映射)。

**步骤**：
1. `client.py` 新增 `create_snapshot()`、`append_block()`、`update_block()`、`insert_block()`、`create_doc_with_md()` 方法
2. `mcp_server.py` 新增 `siyuan_edit_document(document_id, old_text, new_text, confirmed)` —— 写前快照 + 文本锚点搜索 + 块操作
3. `mcp_server.py` 新增 `siyuan_create_document(notebook_id, title, path?, markdown, confirmed)` —— 创建新文档
4. 写入后 pushMsg 通知思源前台

**不实现**：独立 delete_block、renameDoc、removeDoc、moveBlock 工具。

#### G. 块 ID 嵌入

**改动**：`mcp_server.py` + `client.py`

在 `siyuan_read_document` 的引用阅读模式中嵌入 `<!-- block:xxx -->` HTML 注释。默认阅读不启用，避免把复杂块元数据带入普通阅读场景。需要跨文档块引用 `((id "text"))`、精确定位，或为后续编辑确认目标块时，AI 可以提取目标块 ID。写入功能第一阶段不依赖此项——文本锚点已足够。

详见 [问题 7](#问题-7阅读返回格式--纯-markdown-vs-块增强-vs-json) 和 [问题 15](#问题-15写入功能设计--claude-code-editwrite-模式映射)。

#### H. `siyuan_read_document` 附件提取 ✅ 已完成

**已实现** (2026-05-02)。自动提取所有 `assets/` 引用文件到 `ai_workspace/attachments/<doc-id>/assets/`，保留原始文件名。详见 [问题 8 已实现](#问题-8附件和图片处理)。

#### I. tree.md 增加块数

**改动**：`indexer.py`

在 `normalize_documents()` 中计算每篇文档的子块数量。可以通过 SQL 的 `COUNT` 子查询，或从思源的块树 API 获取。

#### J. 实时搜索隐私过滤审查

**改动**：`mcp_server.py` 的 `siyuan_find_documents()`

审查 `_enrich_search_blocks()` 和 `merge_search_results()` 的逻辑，确保 FTS 实时搜索结果中属于隐藏文档的块不会被意外返回。

#### K-M. 对外发布

| # | 事项 | 说明 |
|---|------|------|
| K | README 更新 | 反映新的 MCP 工具列表、启动流程、隐私模型 |
| L | dist 发布包更新 | 重新打包 skill zip + MCP 配置 |
| M | 首次初始化隐私引导 | 方案 B 的完整实现，`.siyuan_privacy_initialized` 标记 + 启动包隐私引导 |

**写入功能设计已升级**：原"远期：写入功能"（依赖块 ID、暴露块级 CRUD 工具）替换为问题 15 的 Claude Code Edit/Write 模式——文本锚点定位 + 2 个精简工具。详见 [问题 15](#问题-15写入功能设计--claude-code-editwrite-模式映射)。

---

### HTTP Keep-Alive 连接问题 (WinError 10054)

**现象**：部分 MCP 工具调用间歇性失败，错误消息为 `[WinError 10054] 远程主机强迫关闭了一个现有的连接。`，随后所有 URL 尝试均失败，AI 端显示"思源连接失败"。重试后通常恢复正常。

**根因**：思源内核使用 Go 的 Gin 框架（底层为 `net/http`），Go HTTP 服务器默认启用 HTTP keep-alive——TCP 连接在处理完请求后保持打开以复用。但服务器端有 `IdleTimeout`，空闲超时后主动关闭连接（发送 TCP RST）。Python 的 `urllib.request.urlopen` 在 HTTP/1.1 下默认也使用 keep-alive，会尝试复用之前打开的连接。当 Python 尝试在已被 Go 服务器关闭的连接上发送新请求时，Windows 返回 `WSAECONNRESET (10054)`。

**修复（2026-05-03）**：

1. **`Connection: close` 头** — `client.py` 的 `_post()` 和 `get_asset()` 方法在所有 HTTP 请求中添加 `Connection: close` 头。这告知服务器每次请求后关闭连接，客户端也每次建立新连接，彻底避免复用死连接。
2. **自动重试** — `_post()` 对 `SiYuanConnectionError` 自动重试最多 3 次（间隔 0.3s / 0.6s），应对 TCP 层面的瞬时故障。只重试连接错误（`URLError`、`TimeoutError`、`OSError`），不重试 HTTP 错误或 API 错误。
3. **错误消息改进** — `mcp_server.py` 中 `SiYuanConnectionError` 的错误消息从固定的"思源笔记似乎没有启动，请提示用户手动打开思源笔记后重试。"改为显示具体失败原因（如 `Request timed out` 或 `[WinError 10054]...`），同时保留人工提示。

**技术参考**：
- 思源内核 HTTP 服务：`kernel/server/serve.go`，使用 `gin-gonic/gin` → Go `net/http.Server`
- Go `net/http` 默认 `IdleTimeout` 行为：服务器在空闲超时后关闭 keep-alive 连接
- Python `urllib` HTTP/1.1 默认 keep-alive：连接池可能复用已被服务器关闭的连接
- Stack Overflow 确认：*"Your code tries to reuse the connection just as the server is closing it because it has been idle for too long. You should basically just retry the operation over a new connection."*

---

## 目录结构

```
siyuan-agent-bridge/
├── README.md                       # 中文快速指南（主版本）
├── README.en.md                    # 英文快速指南
├── AGENTS.md                       # 项目开发指南（面向维护者）
├── config.example.json             # 配置示例
├── config.local.json               # 本机 token（Git 忽略）
│
├── docs/                           # 说明文档
│   ├── PD.md                      #   项目产品设计文档（本文件）
│   ├── siyuan-api-doc.md           #   思源 API 官方文档
│   ├── 思源API.md                   #   思源 API 能力地图
│   ├── 块ID阅读实验计划.md           #   块 ID 实验计划
│   └── 阅读工具BlockWindow改造计划.md #   Block Window 改造计划
│
├── source_code/                    # Python 工具代码
│   ├── client.py                   #   思源 API client（读写）
│   ├── config.py                   #   配置加载
│   ├── ignore.py                   #   隐私规则解析（Markdown 表格）与过滤
│   ├── i18n.py                     #   多语言解析、系统名称映射、默认模板
│   ├── agent_notebook.py           #   系统笔记本服务层
│   ├── indexer.py                  #   索引生成（tree.md + docs.jsonl）
│   ├── cli.py                      #   CLI 入口
│   └── mcp_server.py               #   MCP stdio server（9 tools）
│
├── plugins/siyuan-agent-bridge/       # Skill + MCP 插件
│   ├── .mcp.json                   #   MCP server 注册配置
│   ├── .codex-plugin/
│   │   └── plugin.json             #   插件清单（CC Switch 入口）
│   ├── skills/
│   │   ├── siyuan-agent-bridge/       #   总入口 skill
│   │   │   ├── SKILL.md
│   │   │   └── plugin.json
│   │   └── siyuan-index-builder/   #   建索引 skill
│   │       ├── SKILL.md
│   │       └── plugin.json
│   └── scripts/
│       └── run_mcp.py              #   MCP 启动脚本
│
├── knowledge_base/                 # 生成的安全索引
│   ├── tree.md                     #   两层文档树（程序生成）
│   ├── docs.jsonl                  #   文档元数据（结构化）
│   ├── notebooks.json              #   笔记本索引
│   └── privacy_rules.json          #   隐私规则缓存（从思源 Markdown 表格解析）
│
├── ai_workspace/                   # AI 工作区（分析、草稿）
├── tests/                          # 测试
└── dist/                           # 发布产物
    ├── siyuan-agent-bridge-skill-<ts>.zip
    ├── siyuan-agent-bridge-mcp.json
    └── siyuan-agent-bridge-mcp-deeplink.txt
```

---

## 设计原则

1. **自己优先**：这个工具首先是给开发者自己用的。先在自己电脑上跑通全流程、产生实际价值，之后再考虑打包发布给他人使用。设计决策以"自己能用"为标准，不为想象中的通用场景过度设计。

2. **MCP-first**：产品的唯一界面是 MCP + Skill，面向 AI agent 设计。CLI 命令是早期开发阶段的辅助工具，正常情况下不应被用户或 AI 使用。所有新功能的实现以 MCP 工具为第一优先级，CLI 不变也没关系。

2. **本地优先**：不依赖云服务，所有索引存储在本地。思源 HTTP API 仅在同一台机器的 `127.0.0.1` 上访问。

3. **安全默认**：隐私过滤在索引层完成，而非信任 AI 遵守规则。隐藏的文档从根本上不会出现在索引中。

4. **职责分离**：程序管客观事实（tree.md：有哪些文档），AI 管语义导航（Workspace Index：去哪找什么），人管偏好（AI Guide：我希望 AI 怎么做）。

5. **按需加载**：AI 不一次性读取所有内容。启动时只看概览表和导航索引，找到目标后才深读具体文档。长文档分段读取，避免 MCP 响应截断。

6. **最终可靠**：AI 写的 Workspace Index 可能过时，但程序生成的 tree.md 始终准确。如果 Workspace Index 没找到答案，AI 应该 fallback 到 tree.md + `siyuan_list`。

7. **人控覆盖**：用户在思源中编辑 `隐私规则` / `Privacy Rules` 文档的 Markdown 表格控制隐藏范围，编辑 `AI Guide` 控制 AI 行为。AI 只读、只提议，不能修改隐私规则文档。

---

## 多平台打包策略草案（2026-05-06）

### 背景

当前项目的产品形态不是单纯的 MCP server，而是“核心 MCP 能力 + AI 行为工作流 + 安装诊断材料”的组合。MCP 提供读、搜、写、刷新、隐私预过滤等机制能力；Skill / Agent Guide 负责告诉 AI 如何启动、如何检索、如何尊重隐私、如何按需构建 Workspace Index；安装指南负责让 AI 帮用户完成本地安装、Token 配置、MCP 注册和诊断。

因此，发布策略不应把 MCP 和 Skill 当作两个互不相关的产物。更合适的方向是：核心能力只维护一套，面向不同 AI 平台生成不同适配包。

### 决策

采用 **Source once, package many** 的打包思路：

1. 维护一套核心 MCP 代码：`source_code/` 作为唯一能力实现。
2. 维护一份 canonical agent guide：后续考虑将源文件命名为 `agent-guide.md`、`agent-workflow.md` 或 `siyuan-agent-guide.md`，打包时再生成平台需要的 `SKILL.md`、rules、context file 等格式。
3. 针对不同平台设计打包脚本，运行后生成对应平台压缩包。
4. 初期优先支持：
   - Claude Code 插件包
   - Codex 插件包
   - 通用 MCP + Skill 分离包
5. 安装指南面向 AI 重写为安装 playbook，目标是让 AI 能一次安装正确。

### 目录设想

后续可以考虑将打包相关内容整理为：

```text
packaging/
  core/
    agent-guide.md
    install-for-ai.md
  platforms/
    claude-code/
    codex/
    generic-mcp-skill/
  scripts/
    pack_claude.py
    pack_codex.py
    pack_generic.py
    pack_all.py
```

实际迁移时不必一次性完成，可以先在现有 `plugins/`、`mcp_configs/`、`pack_skill.py`、`pack_release.py` 基础上演进。

### 产物设想

初期发布产物：

```text
dist/
  siyuan-agent-bridge-claude-code-plugin-<version>.zip
  siyuan-agent-bridge-codex-plugin-<version>.zip
  siyuan-agent-bridge-generic-mcp-skill-<version>.zip
```

其中：

- Claude Code / Codex 插件包是推荐入口，尽量包含 MCP server、Skill、启动脚本、安装说明和诊断材料。
- 通用 MCP + Skill 分离包用于兼容只支持 MCP 或不支持插件系统的平台。
- 后续可扩展 Qwen Code、CodeBuddy、Gemini CLI、Lingma、Trae、Comate 等平台适配，但核心 MCP 和 Agent Guide 不应重复维护。

### 安装指南重写要点

`INSTALL_FOR_AI.md` 应从普通说明文档改为面向 AI Agent 的安装 playbook：

1. 判断当前 AI 平台和可用能力：插件、MCP、Skill / rules / context。
2. 询问用户安装目录。
3. 解压到目标目录并确认目录结构。
4. 创建 `config.local.json`，写入 SiYuan Token，但不要在对话中复述或泄露 Token。
5. 运行 `python -m source_code doctor` 验证连接。
6. 根据平台写入对应 MCP 配置。
7. 提醒用户重启 AI 客户端。
8. 在新会话中通过 `siyuan_start` 验证可用性。

### 原则

统一的是产品包和安装体验，不是各平台的插件标准。不同平台的 manifest、目录结构、rules / skill 名称可以不同，但它们都应从同一套核心 MCP 和同一份 Agent Guide 派生。

---

## LLM Wiki 概念调研与借鉴分析（2026-05-08）

### LLM Wiki 是什么

LLM Wiki 由 Andrej Karpathy 于 2026 年 4 月提出，核心理念：**让 LLM 成为主动的知识库管理员（active librarian），而不只是被动的搜索工具。** 它的关键命题是——"wiki 是持久化的 artifact，聊天是临时的"。

与 RAG 的根本区别：

| | RAG | LLM Wiki |
|---|---|---|
| 检索方式 | 每次查询重新检索 raw 碎片 | 读取已编译的结构化 wiki |
| 知识积累 | 无积累，无状态 | 持续编译，越用越丰富 |
| 检索单位 | 去上下文的 chunk | 结构化 wiki 页面 |
| 交叉引用 | 查询时现算 | 预构建好 |
| 矛盾检测 | 偶然发现 | 摄入时主动标记 |

三层架构：

```
Layer 3 → Schema (CLAUDE.md)    — 规则：告诉 LLM 如何组织、命名、链接
Layer 2 → Wiki (Markdown)       — LLM 持续维护：概念页、实体页、来源摘要、交叉引用
Layer 1 → Raw Sources (只读)    — 不可变的原始资料
```

三个核心操作：

1. **Ingest**：放原始资料 → LLM 读取、总结、更新 wiki、建立交叉引用
2. **Query**：提问 → LLM 读取已编译 wiki 回答（不重搜原始文档）
3. **Lint**：健康检查 → 发现矛盾、孤立页面、知识空白

核心项目参考：`nashsu/llm_wiki`（桌面应用）、`SamurAIGPT/llm-wiki-agent`（Claude Code/Codex/Gemini 通用 agent）、`SwarmVault`（知识编译器）。

### 与思源桥的对比

**一致的地方**（不需要改）：

- 都反对向量化碎片，坚持结构化阅读保持上下文
- 都采用三层分离（Raw/Wiki/Schema vs 机制/策略/个性化）
- 都本地优先，Markdown 作为通用格式
- 都强调 wiki 是持久化产物而非会话附属
- Workspace Index 已有"AI 维护导航层"的雏形

**思源桥 vs LLM Wiki 的本质差异**：

- LLM Wiki 解决"从零散的 raw sources 构建结构化知识库"——输入是 PDF、网页剪辑等原始资料
- 思源桥解决"连接已有结构化笔记和顶级 AI agent"——思源本身就是 wiki，不需要重建
- 思源的用户已经在主动写笔记、建结构；LLM Wiki 的"编译"步骤在思源桥中是多余的

### 可以借鉴的方向

1. **Workspace Index 持续编译**：从"一次生成、手动刷新"演进为 AI 在每次有价值会话后自动增量更新——更新交叉引用、标记新文档、标注知识空白
2. **Lint/审计操作**：增加知识健康检查能力——发现矛盾、孤立文档、过时信息；可作为 Skill 级别操作
3. **查询回答归档**：核心洞察——好的分析不应消失在聊天记录里。Skill 可引导 AI 将重要的跨文档分析写回知识库
4. **Schema 更明确**：SKILL.md 可增加"知识组织规范"章节，定义页面格式、命名约定、链接规范

### 为何不做为底层功能

LLM Wiki 的三个操作 (Ingest/Query/Lint) 本质上都是高层工作流，完全可由现有 5 个基础工具组合实现：

| LLM Wiki 操作 | 需要的现有工具 |
|---|---|
| Ingest | `find` → `read` → `create`/`edit` |
| Query | `find` → `read` → 推理合成 |
| Lint | `find` + `read` 全库扫描 → 分析 |

不需要新增任何 MCP 工具。LLM Wiki 本质是一套**策略指令**——告诉 AI "用这些工具怎么操作、按什么规范组织"。这正是 Skill 层该做的事。

这恰好体现了 PD 中**机制与策略分离**原则的典型应用场景：

```
机制层 (source_code/)    → 5 个工具，不变
策略层 (plugins/skills/) → 未来可新增 llm-wiki 配套 Skill
个性化层 (思源笔记本)     → 用户指定哪些笔记本作为 "重点维护区"
```

如果反过来把 wiki 操作沉到机制层（新增专用工具），反而会违反设计约束：把特定工作流焊死在代码里、增加工具数量加大 AI 选择负担、与现有工具边界重叠。

### 结论

LLM Wiki 的核心理念与思源桥底层哲学高度一致，适合作为**配套 Skill** 提供，而非纳入底层 MCP 工具。后期可提供类似 `siyuan-wiki-builder` / `siyuan-knowledge-lint` 的 Skill，让 AI 对已有的结构化思源笔记做更深层的维护和关联。


---

## 参考 Sisyphus 后的产品方向补充（2026-05-08）

### 参考对象

参考项目：`yangtaihong59/siyuan-plugins-mcp-sisyphus`

该项目选择“思源原生插件 + MCP Server + CLI”的形态：安装在思源内，通过插件设置管理连接方式和权限，并向外部 AI agent 暴露 MCP 工具。它更偏“让 AI 全面操作思源”的工具路线，覆盖 notebook、document、block、AV、search、file、tag、system、flashcard、mascot、fs 等聚合能力。

### 可借鉴点

1. **做成思源插件的安装体验**

   当前项目是外部 Python 程序，虽然符合“AI agent 为中心”的架构，但普通用户安装成本较高：需要下载 release、配置 token、注册 MCP、确认 Python 环境。Sisyphus 的思源插件形态有明显优势：用户可以从思源集市安装，配置入口在思源内部，Token、工作空间、笔记本权限等信息天然靠近数据源。

   后续可以考虑增加“思源插件壳”：

   - 插件负责提供设置 UI、Token / profile 管理、权限管理、MCP 配置生成、诊断按钮。
   - 核心 MCP 工具和 Agent Guide 仍保持独立，可继续面向 Claude Code、Codex、OpenClaw、Qwen Code 等 AI 平台打包。
   - 不必立刻放弃外部 Python 形态；可以先把思源插件作为安装与配置前端，再评估是否逐步迁移 MCP server 到插件内部。

2. **help 命令与渐进式披露**

   Sisyphus 通过 help action / resources 让复杂工具说明按需展开，避免一次性把所有细节塞进 tool description 或 Skill。这个思路适合本项目。

   后续可以考虑增加：

   - `siyuan_help(topic="startup")`
   - `siyuan_help(topic="privacy")`
   - `siyuan_help(topic="read_document")`
   - `siyuan_help(topic="write_safety")`
   - `siyuan_help(topic="workspace_index")`

   Skill / Agent Guide 中只保留关键工作流和安全原则，细节通过 help 工具按需加载。这样既降低上下文占用，也能让不同平台的 Skill 文件更短、更稳定。

3. **读写删除权限分离管理**

   当前项目主要通过 Privacy Rules 做隐藏过滤，并在写入前创建快照；写入工具本身较克制，不暴露删除、移动、重命名等高风险能力。Sisyphus 的笔记本级 `rwd` / `rw` / `r` / `none` 权限模型值得参考。

   后续可以考虑在 Privacy Rules 或系统笔记本中引入更清晰的权限层：

   - `hidden` / `none`：AI 完全不可见。
   - `read`：可搜索、可读取，不可写入。
   - `write`：可在用户确认后编辑或新建。
   - `delete`：默认不开放；即使未来支持，也应单独授权并强确认。

   这能把“隐私隐藏”和“操作权限”拆开，避免把所有安全需求都塞进 hide 规则里。

### 保持自己的独特性

不能把项目做成“另一个全功能思源 API 遥控器”。本项目的差异化应继续明确为：

1. **做产品，而不只是做工具**

   目标不是暴露更多 API，而是让 AI agent 稳定、安全、低心智负担地使用用户的个人知识库。工具数量应保持克制，接口设计继续贴近 AI 编程工具熟悉的 list / find / read / edit / create 心智模型。

2. **主打知识库管理，而非思源全功能操作**

   项目核心是把思源变成 AI 可理解、可导航、可长期维护的结构化知识库。Workspace Index、AI Guide、Privacy Rules、启动包、分段阅读、引用阅读等机制应继续作为产品中心。

3. **借鉴 LLM Wiki / Agent Wiki 思路**

   后续可以围绕不同知识库工作流设计专门 skills，例如：

   - workspace index builder：构建全局导航。
   - research synthesizer：围绕主题聚合多篇笔记。
   - reading map builder：从读书笔记生成知识地图。
   - project memory maintainer：维护项目长期背景、决策和待办。
   - citation / block reference helper：生成精确块引用。

   这些 skill 不只是“怎么调用 API”，而是内部工作流，是产品价值的一部分。

4. **MCP + Skill + 内部工作流的整体组合**

   MCP 是能力层，Skill / Agent Guide 是行为层，系统笔记本中的 AI Guide / Workspace Index / Privacy Rules 是用户可控的策略层。三者共同构成产品，不应被拆成互不相关的安装项。

5. **AI 友好与人类友好双重设计**

   AI 友好：少工具、强约束、渐进式披露、启动包、按需读取、写前快照、明确错误信息。

   人类友好：安装简单、权限可理解、配置可视化、可在思源中管理偏好和隐私、能通过快照回滚、能看到 AI 维护的 Workspace Index。

### 阶段性判断

短期仍以现有 Python MCP + Skill 打包策略推进，优先解决多平台安装包和 AI 安装指南。中期探索“思源插件壳”作为配置和安装入口。长期如果插件形态足够稳定，再评估是否把 MCP server 本身迁移到思源插件内部或提供双运行时。
