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
    ├── ignore.py        → 隐私忽略 / 临时开放规则管理
    ├── config.py        → 多 URL / token 配置加载
    ├── cli.py           → 早期辅助 CLI（开发诊断用，非主要接口）
    └── mcp_server.py    → MCP stdio server — 面向 AI 的主要接口，暴露 11 个工具给 AI（含 2 个写入工具）
    │
    ▼
knowledge_base/  (生成的安全索引，每次 refresh 覆盖)
    ├── tree.md          → 两层文档树（程序生成）
    ├── docs.jsonl       → 结构化文档元数据（AI 不直接读）
    ├── notebooks.json   → 笔记本索引（程序消费）
    ├── guide.md         → 用户维护的阅读指南（ensure，不覆盖）
    └── index.md         → AI 生成的导航索引（siyuan-index-builder skill）
    │
    ▼
plugins/siyuan-agent-bridge/  (面向 AI 的指令层)
    ├── skills/siyuan-agent-bridge/SKILL.md        → 总入口 skill："如何使用思源笔记知识库"
    ├── skills/siyuan-index-builder/SKILL.md    → 专项 skill："如何创建结构化索引"
    └── scripts/run_mcp.py                      → MCP stdio 启动脚本
```

### 关键设计决策

**两层索引分离**：程序生成的客观索引（tree.md）和 AI 生成的语义索引（index.md）各自独立，互不依赖。
- `tree.md` 是客观事实层——脚本扫描生成，保证完整性，每次 refresh 覆盖。
- `index.md` 是语义导航层——AI 阅读后手写，含摘要和判断，增量更新。

**安全索引原则**：所有给 AI 的数据都经过隐私规则过滤。隐藏的笔记本/文档在索引层面就被移除，AI 感知不到它们的存在。

**关闭笔记本原则**：思源的"关闭笔记本"仅被视为运行态（思源前台不加载），不被视为知识库排除规则。是否纳入 AI 知识库由隐私规则和索引规则决定。适配层在后台自动临时打开关闭的笔记本完成操作，结束后恢复原状态。AI 不直接操作笔记本开关。

**MCP-first 架构**：项目的产品界面是 MCP + Skill，面向 AI agent 设计。CLI 命令（`python -m source_code ...`）是早期开发时的辅助工具，仅用于人工诊断和调试，正常情况下不应被使用。所有功能的实现应以 MCP 工具为第一优先级，CLI 的实现可有可无。

---

## 系统架构

### 三个概念层

| 层 | 作用 | 执行者 | 产物 |
|----|------|--------|------|
| **数据采集层** | 从思源 API 拉取笔记本列表和原始文档块 | Python 脚本 / MCP 工具 | 内存中的数据结构 |
| **过滤与索引层** | 应用隐私忽略规则，过滤后生成结构化索引 | `indexer.py` + `ignore.py` | `tree.md` + `docs.jsonl` + `notebooks.json` |
| **能力暴露层** | 通过 MCP 协议向 AI 暴露读写工具 | `mcp_server.py` (11 tools) | AI 可调用的语义能力 |

### 数据层

| 文件 | 性质 | 用途 |
|------|------|------|
| `tree.md` | 程序生成，覆盖 | 笔记本概览表 + 每笔记本完整文档树（含字数和更新时间）。两层结构，AI 默认只看第一层。 |
| `docs.jsonl` | 程序生成，覆盖 | 每行一个文档的结构化元数据（id、路径、字数、tags 等）。AI 不直接读，由 MCP 工具动态查询。 |
| `guide.md` | 人工维护，ensure | 用户对 AI 的持久偏好和工作风格指引。`refresh_index` 不覆盖已存在的 guide.md。 |
| `index.md` | AI 生成，增量更新 | 语义导航索引：快速路由表（"什么需求 → 去哪个笔记本"）、路径结构描述、AI 摘要。由 `siyuan-index-builder` skill 创建和维护。 |

### 指令层

指令层遵循**单一信息源**原则：每条规则只在唯一的文件中维护，通过交叉引用连接。

| 文件 | 定位 | 内容 |
|------|------|------|
| `plugins/…/SKILL.md` | 工作流入口 | Mandatory Startup 7 步流程、Tool Use Hints（非显而易见的要点）、Cross-References |
| AGENTS.md | 项目开发指南 | 项目结构、架构、开发命令（面向维护者） |
| `guide.md` | 用户偏好 | 用户维护的持久工作风格和重点笔记本指引 |

**设计决策**：

- SKILL.md 不重复工具参数描述（MCP `tools/list` 已提供完整 schema）。
- SKILL.md 内联安全规则（7 条 `## Safety Rules`），不依赖外部文件——skill 必须可独立加载。
- AGENTS.md 面向项目维护者（开发指南、架构、命令），不面向使用者。
- SKILL.md 的 `## Tool Use Hints` 仅标注 4 个非显而易见的要点，不逐条罗列参数。

| Skill | 触发条件 | 核心指令 |
|-------|----------|---------|
| `siyuan-agent-bridge` | 用户提到思源/知识库/笔记 | 强制调用 siyuan_start 获取启动包 → 以 index.md 导航 → 按需深读 |
| `siyuan-index-builder` | 用户要求建索引/更新索引 | 遍历笔记本结构 → 阅读关键文档 → 为每个笔记本写结构摘要和 AI 摘要 → 生成 index.md |

---

## 完整数据流（用户使用流程）

### 步骤 1：安装部署

用户通过 CC Switch 安装 Skill 压缩包 (`dist/siyuan-agent-bridge-skill-latest.zip`)，并注册 MCP stdio 配置。Skill 和 MCP 注册到 AI 工具后即可使用。

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
- 应用 `siyuan.ignore.local.json` 隐私规则，过滤隐藏内容
- 计算每篇文档的字数（CJK 字符数 + 英文单词数）
- 生成 `tree.md`（两层结构）和 `docs.jsonl`

**5b1. 启动包组装** — 返回内容根据 index.md 是否存在分两种情况：

| 条件 | 返回内容 |
|------|---------|
| index.md 存在 | 笔记本概览表（tree.md 第一层）+ index.md 全文 + guide.md |
| index.md 不存在 | 笔记本概览表（tree.md 第一层）+ guide.md + 提示 AI 可建议用户先创建导航索引 |

**tree.md 每篇文档包含的元数据**：
- 文档 ID（思源块 ID，唯一标识）
- hpath（文档在笔记本中的路径，如 `/投资研究笔记/专题研究/REITs`）
- 字数（中文字符 + 英文单词）
- 块数（文档下所有块的计数，含标题、段落、列表等）
- 更新时间（`YYYY-MM-DD` 格式）
- Tags（从思源 tag 字段解析）

### 步骤 6：AI 根据启动包做后续判断

**6a. 创建/更新索引** — 如果用户要求建索引，或 AI 判断需要导航（index.md 不存在），调用 `siyuan-index-builder` skill：
- 遍历 tree.md 中每个笔记本的结构
- 用 `siyuan_read_document` 阅读每个笔记本的入口文档和重要文档
- 按模板生成 index.md：快速路由表 + 每笔记本结构描述 + AI 摘要
- 增量更新时保留人工标注（priority、更正）

**6b. 直接使用现有索引** — 从 index.md 快速路由表定位目标笔记本，从 tree.md 第一层确认该笔记本规模，然后用 `siyuan_list`（带 `notebook_id`）看该笔记本的文档树。

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
| 短文档（≤max_chars） | 返回文档大纲 + 全文 |
| 长文档（>max_chars） | 返回文档大纲 + chunk 编号映射 + chunk 1 内容 |

大纲格式：解析 Markdown 标题（`#`/`##`/`###`），标注每个标题落在哪个 chunk。AI 可以直观看到文档结构和内容的对应关系。

### 步骤 9：分段续读

AI 阅读完 chunk 1 后，按需用 `chunk=2`, `chunk=3` 等参数继续读取后续内容，而不是一次性吞下整篇长文档。

---

## MCP 工具清单

| # | 工具 | 参数 | 行为 | 访问思源 API |
|---|------|------|------|:---:|
| 1 | `siyuan_start` | 无 | 刷新索引 + 返回启动包（含 index.md 条件返回） | ✓ |
| 2 | `siyuan_refresh_index` | 无 | 手动刷新安全索引 | ✓ |
| 3 | `siyuan_list` | `notebook_id`? 或 `notebook_name`? | 无参数时列出所有可见笔记本；给定 notebook 时返回文档树（含字数、更新时间、tags） | ✗ 本地 |
| 4 | `siyuan_find_documents` | `keyword` + `mode` + `scope` + `notebooks`? + `limit`? | 搜索知识库，隐私过滤后返回 | ✓ |
| 5 | `siyuan_read_document` | `document_id` + `chunk`? (default 0) + `max_chars`? | 返回大纲；短文档全文；长文档分 chunk | ✓ |
| 6 | `siyuan_propose_guide_update` | `proposal` + `title`? + `body`? | 保存到 `ai_workspace/` | ✗ |
| 7 | `siyuan_apply_guide_update` | `content` + `mode` + `confirmed` | 追加或替换 `guide.md` | ✗ |
| 8 | `siyuan_privacy` | `action` ("hide"\|"unhide") + `scope` + `locator` + `confirmed` + `reason`? | 隐藏或取消隐藏笔记本/文档/子树，自动刷新索引 | ✓ |
| 9 | `siyuan_temporary_allow` | `action` ("open"\|"close") + `scope`? + `locator`? + `minutes`? + `reason`? | open=临时开放隐藏内容（有时效）；close=清除所有临时开放 | ✗ |
| 10 | `siyuan_create_document` | `notebook_id` + `title` + `path`? + `markdown` + `confirmed` | 在可见笔记本中创建新文档；写前自动创建快照；快照失败拒绝写入 | ✓ |
| 11 | `siyuan_edit_document` | `document_id` + `old_text` + `new_text` + `confirmed` | 文本锚点编辑；old_text=""追加，new_text=""删除；仅支持单块编辑 | ✓ |

### 工具能力分类

```
入口层:   siyuan_start           → 始终第一个调用
导航层:   siyuan_list            → 无参数=列出笔记本；给 notebook_id=查看文档树
搜索层:   siyuan_find_documents  → 在多笔记本间定位相关文档
阅读层:   siyuan_read_document   → 获取文档的 Markdown 正文
写入层:   siyuan_create_document → 在可见笔记本中创建新文档（需 confirmed=true）
         siyuan_edit_document    → 文本锚点编辑可见文档（需 confirmed=true）
维护层:   siyuan_refresh_index   → 中途刷新，清理 ai_workspace
         siyuan_propose/apply_guide_update → 维护 guide.md
隐私层:   siyuan_privacy         → 隐藏/取消隐藏（action="hide"|"unhide"，需 confirmed=true）
         siyuan_temporary_allow → 临时开放/关闭（action="open"|"close"）
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

### 规则分层

```
siyuan.ignore.local.json     → 长期隐藏规则（Git 跟踪，但内容属私人）
siyuan.allow.local.json      → 临时开放规则（有时效性，到期自动失效）
```

### 作用域

| scope | 效果 |
|-------|------|
| `notebook` | 隐藏整个笔记本及其所有文档 |
| `document` | 隐藏该文档及其所有子文档 |
| `subtree` | 与 `document` 同义，保留用于显式表达“隐藏整棵子树”和兼容旧规则 |

**隐私语义决策**：

- 思源文档同时是内容页和树节点。若只隐藏父文档本身但保留子文档，文档树和搜索结果仍会暴露父路径名称。
- 因此 `document` 不再表示“只隐藏单篇文档”，而是表示“隐藏这个文档节点及其所有后代文档”。
- 如果用户明确只想让某一段内容不可见，应在思源内调整文档结构，或把需要隐藏的内容放入单独文档后隐藏该文档树。

### 过滤时机

隐私过滤发生在索引生成阶段（`refresh_index`），而非每次读取时。这意味着：
- 被隐藏的文档不会出现在 `tree.md`、`docs.jsonl`、`notebooks.json` 中
- 被隐藏文档的子文档也不会出现在 `tree.md`、`docs.jsonl` 和 `siyuan_list` 中，避免通过路径层级泄露父文档名称
- `siyuan_find_documents` 使用思源 API 实时搜索，但返回前会在 MCP server 内部应用同一套隐藏规则
- `siyuan_read_document` 读取前必须先在可见文档集合中解析 `document_id` / hpath / title；隐藏文档即使已知 ID，也不会通过 MCP 读取
- 如果需要临时读取隐藏内容，必须通过 `siyuan_temporary_allow` 显式临时开放；临时开放同样受 `confirmed=true` 保护

### AI 安全规则

- AI 不应读取 `config.local.json`、`siyuan.ignore.local.json`、`siyuan.allow.local.json`
- AI 不应调用思源写 API
- AI 不应暴露隐藏文档的名称给用户，除非用户明确要求

---

## 当前实现状态



### 已完成

- [x] tree.md 两层结构（笔记本概览表 + 文档树），含 ID、字数、更新时间、tags
- [x] docs.jsonl 结构化数据 + notebooks.json 笔记本索引
- [x] `siyuan_start` 自动 refresh + 返回启动包（含 guide.md）
- [x] `siyuan_start` 纳入 index.md：当 `knowledge_base/index.md` 存在时，将其纳入启动包返回；不存在时提示 AI 可建议用户创建索引
- [x] `siyuan-agent-bridge` SKILL.md 更新：Mandatory Startup 明确 AI 优先使用 index.md 快速路由表，Tool Use 添加 index.md 说明
- [x] 思源未启动时的友好提示：连接失败时返回"思源笔记似乎没有启动。请打开思源笔记软件后重试。"而非技术错误堆栈
- [x] `siyuan_read_document` 大纲 + 分 chunk + chunk 跳转
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
- [x] **Skill 打包**：`dist/siyuan-agent-bridge-skill-latest.zip` 含隐私工具和 index.md 指令
- [x] **关闭笔记本自动开关**：`ensure_notebooks_open` 上下文管理器，在索引刷新、文档读取、FTS/SQL 搜索时自动临时打开关闭的笔记本，用完恢复原状态。AI 不感知也不操作笔记本开关
- [x] **统计指标重构**：删除从未使用的 `index_word_count` 和 `markdown_chars`，新增 `block_count`（文档子块数）和 `char_count`（原始字符数，与分块的 `len()` 对齐）。索引刷新从 424 次 `export_markdown()` HTTP 调用优化为 2 条 SQL 查询（GROUP BY + 全块内容），耗时从 ~30s 降到 ~2s。所有展示（tree.md、siyuan_list、搜索结果、read_document 文档头）同步显示块数和字符数
- [x] **附件提取**：`siyuan_read_document` 自动提取文档中所有资源文件（图片、PDF、xlsx 等）到 `ai_workspace/attachments/<doc-id>/assets/`，保留原始文件名和目录结构。Markdown 原文不动，AI 按文件名自行对应。文档头显示附件数量，无附件不提。`siyuan_refresh_index` 自动清理
- [x] **写入功能第一阶段**：`siyuan_create_document` + `siyuan_edit_document` 两个 MCP 工具。文本锚点模式——AI 传入 `old_text`（从 Markdown 读到的原文片段），服务端在块级搜索匹配后执行块操作。只支持单块编辑；跨块文本返回错误。写前自动创建思源工作空间快照；快照失败拒绝写入。写入后 pushMsg 通知思源前台。隐藏内容不可写。所有写入工具必须 `confirmed=true`
- [x] **WinError 10054 连接重置修复**：思源 Go HTTP 服务器默认启用 keep-alive，空闲超时后关闭连接；Python urllib 尝试复用死连接时触发 WSAECONNRESET（10054）。修复：所有 HTTP 请求添加 `Connection: close` 头，每次请求后关闭连接；连接错误自动重试 3 次（间隔 0.3s/0.6s）。错误消息同时改进为显示具体原因而非笼统的"似乎没有启动"

### 待实现

- [ ] **`siyuan_temporary_allow` 对已刷新隐藏文档的生效**：当前 hide 触发 refresh 后文档从 docs.jsonl 移除，temporary_allow 无法找回。需重新设计索引策略或让 temporary_allow 走实时 API

---

## 设计讨论与待决策问题

以下是在设计过程中识别出的开放问题，记录了各种方案的权衡分析。随着项目推进，这些讨论的结论应逐步移入对应的设计章节。

### 问题 1：长文档分段 — Chunk vs Block

**背景**：当前长文档按字数分 chunk（默认 10,000 字符），在段落边界切分。思源内部用 block（块）组织内容，每个块有唯一 ID、类型（标题/段落/列表）、内容。

| 维度 | Chunk（字数分块） | Block（思源块） |
|------|:---:|:---:|
| 实现复杂度 | 低，纯 Markdown 切分 | 中高，需查询块树 API |
| 语义边界 | 段落级，可能切断语义 | 自然语义边界（标题即块、段落即块） |
| 大小可控 | ✓ 每段 ~10,000 字符 | ✗ 块不固定（一句话～上千字） |
| 精确定位 | ✗ 无块 ID，只能靠引用文字 | ✓ 每个块有唯一 ID |
| 读写衔接 | ✗ 无法精确定位写入目标 | ✓ 写入必须指定块 ID |
| MCP 响应适配 | ✓ 大小均匀 | ✗ 可能需要合并小块 |

**中间方案（推荐短期采用）**：保持 Chunk 分块逻辑不变，但在导出的 Markdown 中嵌入 HTML 注释形式的块 ID，不影响 AI 阅读但保留精确定位能力：

```markdown
## REITs 市场分析 <!-- block:20260428160040-1m6rd04 -->

中国REITs市场目前有80只基金... <!-- block:20260428160041-abc123 -->
```

**建议**：短期保持 Chunk + 块 ID 注释。等写入功能开发时再评估是否迁移到纯 Block 方案。Block 的核心价值（精确定位）对纯读取场景增益有限。

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

→ 已升级为问题 11 的完整方案：在首次初始化时创建"思源Agent"专用笔记本，将 guide 文档的主副本放在思源中。`knowledge_base/guide.md` 降级为本地缓存。详见问题 11。

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

**隐私性考量**：首次启动时 AI 会看到所有笔记本名称和文档标题——这一步在设置隐藏之前不可避免。敏感信息在首次启动时短暂暴露，标记创建后下次启动即应用隐私规则。如果用户确实第一次就有明确要隐藏的内容，可以在当次对话中设置后立即生效。

**需要新增的 MCP 工具**（CLI 层已实现，只需暴露到 MCP）：

| MCP 工具 | 对应用途 |
|----------|---------|
| `siyuan_privacy(action, scope, locator, reason?)` | 隐藏/取消隐藏笔记本/文档/子树 |
| `siyuan_temporary_allow(action, scope?, locator?, minutes?, reason?)` | 临时开放/关闭隐藏内容 |

---

### 问题 6：Index、Guide、Memory 的存储和同步

| 文件 | 格式 | 位置 | Git 同步 | 理由 |
|------|------|------|:---:|------|
| `tree.md` | Markdown | `knowledge_base/` | 否 | 本地生成，每台设备独立 |
| `docs.jsonl` | JSONL | `knowledge_base/` | 否 | 同上 |
| `notebooks.json` | JSON | `knowledge_base/` | 否 | 同上 |
| `guide.md`（本地缓存） | Markdown | `knowledge_base/` | 否 | 从思源拉取的缓存副本，`siyuan_start` 自动同步 |
| 思源 "思源Agent/guide" 文档 | 思源文档 | 思源内部 | 思源同步 | **主副本**，用户在思源 UI 中编辑（见问题 11） |
| `index.md` | Markdown | `knowledge_base/` | 可选 | AI 生成，同步可复用 |
| `siyuan.ignore.local.json` | JSON | 项目根 | **是** | 隐私规则应所有设备生效 |
| `siyuan.allow.local.json` | JSON | 项目根 | 否 | 临时规则，有时效性 |
| `.siyuan_privacy_initialized` | 空标记 | 项目根 | **是** | 标记已完成初始化 |

**多设备场景**：用户通过 git 同步项目 repo。每台设备运行自己的思源、生成自己的 tree.md。guide.md 和 ignore 规则通过 git 共享。

**存储位置的选择**：放在项目根目录和 `knowledge_base/` 中，而非思源插件目录。理由：
- 思源插件目录由思源内部管理，外部工具不应污染
- 项目目录可通过 git 做版本控制和同步
- 解耦——思源插件系统变化不影响本工具

---

### 问题 7：阅读返回格式 — 纯 Markdown vs 块增强 vs JSON

| 方案 | AI 阅读体验 | 引用精度 | 实现复杂度 |
|------|:---:|:---:|:---:|
| A. 纯 Markdown | 最干净 | 段落级（靠引用文字） | 最低 |
| B. Markdown + HTML 注释块 ID | 干净（注释不可见） | 块级精确 | 低（后处理注入） |
| C. 块列表 JSON（含完整元数据） | 噪音大，需解析 | 最高 | 高 |

**推荐方案 B**：在导出的 Markdown 中嵌入 HTML 注释形式的块 ID。AI 阅读体验不变（注释被渲染器忽略），但需要精确定位时可引用块 ID。思源 API 的 `exportMdContent` 不返回块信息，需要额外查询块树进行后处理注入。

**额外信息是否干扰 AI？** — 以注释形式嵌入的信息不会干扰 AI 理解正文。但不要在可见文本中混入元数据（如 `[id:xxx updated:xxx]`），这会打断阅读流。

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

### 问题 10：PRO.md 本身的定位

PRO.md 是**设计文档 + 决策记录**，不是 README。它面向三类读者：

1. **开发者（用户）** — 追踪项目进度，了解设计意图
2. **本项目的 AI** — 在新会话中快速了解项目上下文

每次讨论中产生的设计决策、方案权衡、踩过的坑，都应沉淀到 PRO.md 中。它应该保持更新，反映项目当前的真实状态和思考过程。

---

### 问题 11：思源 Agent 笔记本 — Guide 文档的归属

**问题**：guide.md 当前放在 `knowledge_base/` 目录中，用户需要用文本编辑器打开才能修改。之前在问题 3 中讨论过"在思源里放镜像文档"的方案，但那个方案存在鸡生蛋蛋生鸡的问题——AI 不知道去哪找这个文档。

**新方案**：在首次初始化时，程序直接在用户的思源中创建一个专用笔记本和 guide 文档，让 guide 的主副本天然就在思源里。

**具体做法**：

```
首次初始化 (siyuan_start 检测到 .siyuan_privacy_initialized 不存在)
    │
    ├── 步骤 1：隐私设置引导（见问题 5）
    │
    ├── 步骤 2：创建"思源Agent"笔记本
    │   ├── 在思源中创建笔记本，名称如 "思源Agent" 或 "AI Agent"
    │   └── 相比普通笔记本，这个名称明确告诉用户"这是给 AI 用的"
    │
    ├── 步骤 3：在笔记本中创建 guide 文档
    │   ├── 文档标题：如 "AI指南 - 如何阅读我的笔记"
    │   ├── 初始内容：由程序自动生成的引导模板（用户可自由编辑）
    │   └── 文档 ID 记录到本地配置文件，供后续启动查找
    │
    └── 步骤 4：创建 .siyuan_privacy_initialized 标记
```

**为什么这样设计**：

1. **用户编辑便利** — 用户直接在思源 UI 里编辑 guide，不需要找文件路径、不需要文本编辑器。思源是用户最熟悉的环境。

2. **解决发现性问题** — guide 文档在一个**名称固定的笔记本**里（"思源Agent"），AI 通过 `siyuan_start` 拿到的笔记本概览表就能看到它。Skill 指令里只需写："始终优先读取'思源Agent'笔记本中的指南文档"——不需要知道文档 ID。

3. **自然的人类行为** — 用户看到笔记本列表里有"思源Agent"，会好奇点进去看。看到里面的 guide 文档，自然会编辑。比编辑 `knowledge_base/guide.md` 这种藏在项目目录里的文件要直观得多。

4. **与 note 融为一体** — guide 不再是一个"外部配置文件"，而是知识库的一部分。用户可以像管理任何笔记一样管理它：加标签、关联其他文档、用思源的搜索找到它。

5. **减少外部文件依赖** — guidance 不需要经过 git 同步。只要思源在，guide 就在。多设备场景下，用户通过思源本身的同步机制就能在所有设备上看到同一个 guide。

**与现有文件的关系**：

| 文件 | 新角色 |
|------|------|
| 思源 "思源Agent/guide" 文档 | **主副本** — 用户在思源里编辑，AI 启动时通过 MCP 读取 |
| `knowledge_base/guide.md` | **降级为缓存** — 运行 `siyuan_start` 时从思源拉取并保存到本地。如果思源未启动或 guide 文档被删除，fallback 到缓存 |
| SKILL.md | 在 Mandatory Startup 中写明："启动后务必读取'思源Agent'笔记本下的指南文档" |

**Skill 指令中的描述**（示例）：

```markdown
## Mandatory Startup

1. Call `siyuan_start` first.
2. Read the returned startup packet.
3. **Read the guide document** in the `思源Agent` notebook.
   - Use `siyuan_list` with notebook_name="思源Agent" to find it.
   - Then use `siyuan_read_document` to read its full content.
   - This document contains the user's durable preferences for how you should use their notes.
4. Follow the guide's instructions for all subsequent work.
```

**需要新增的 API 调用**：

- `createNotebook(name)` — 创建笔记本（思源 `/api/notebook/createNotebook`）
- `createDocWithMd(notebook, title, markdown)` — 用 Markdown 创建文档（思源 `/api/block/insertBlock`）

这些仅在首次初始化时调用一次。

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
| 块级读取 | `galiais`、`onigeya` | 参考 block tree 查询和块 ID 处理 | 本项目仍以 Markdown 阅读体验为主，块 ID 作为 HTML 注释增强 |
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

**问题**：当用户在非 bridge 项目目录下工作时，`siyuan-index-builder` skill 告诉 AI 用标准文件工具（Write/Edit）将 `index.md` 写入 `knowledge_base/index.md`。但 AI 的工作目录是用户当前的项目目录，不是 bridge 安装目录，所以 index.md 会被写入错误的位置。

**后果**：
- index.md 无法通过 git 跨设备同步（bridge 项目的 git 仓库收不到这个文件）
- 换到其他项目目录后，AI 无法获取之前生成的导航索引
- MCP 工具（`siyuan_start` 等）不受影响——它们通过 `self.root`（bridge 项目根目录）读写，路径始终正确

**根因**：MCP server 通过 `run_mcp.py` 的 `os.chdir(REPO_ROOT)` 始终以 bridge 根目录为工作目录，但 AI agent 的文件系统操作（Write/Edit）使用的是 IDE/终端的当前工作目录，这两者不一致。

**方案对比**：

| | 方案 A：提示词引导 | 方案 B：新增 MCP 工具 |
|---|---|---|
| 做法 | skill 里告诉 AI 写绝对路径 | 加 `siyuan_write_index` 工具，类似 `siyuan_apply_guide_update` |
| 路径确定性 | ✗ AI 需推断 bridge 安装位置 | ✓ MCP server 始终知道 `self.root` |
| 传输稳定性 | — | 300 行以内 markdown，MCP stdio 完全能承载 |
| 原子写入 | ✗ 依赖 AI 工具 | ✓ MCP 内部 tmp + rename |
| 一致性 | 与 guide.md 维护模式不同 | 与 `siyuan_apply_guide_update` 模式统一 |

**当前处理**：暂不实现方案 B。在当前工作目录（bridge 项目本身）内让 AI 重建 index，避免路径问题。后续需要跨项目使用时，再添加 `siyuan_write_index` MCP 工具。

**结论**：方案 B 是正确解法，但当前优先级不高——用户主要在 bridge 项目本身内使用。纳入后续待实现。

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
| **第二阶段** | 块 ID 嵌入（`siyuan_read_document` 返回注释） | 仅在跨文档块引用时需要 | 待实现 |

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

#### 多工作空间连接配置问题

思源允许用户切换不同工作空间；不同工作空间可能使用不同 HTTP API 端口和 token。当前项目的连接配置仍偏向“单个默认工作空间”：从环境变量或 `config.local.json` 读取一组 URL/token，然后尝试连接。

写入功能会放大这个问题：如果 AI 连接到错误工作空间，轻则读不到当前内容，重则把编辑写到旧工作空间。因此底层连接配置后续需要升级：

| 问题 | 后续方向 |
|------|----------|
| 多工作空间端口不同 | 支持按工作空间维护多个 endpoint profile |
| 多工作空间 token 不同 | token 需要随 profile 绑定，不应假设全局唯一 |
| MCP 重启后仍指向旧工作空间 | `siyuan_start` 应显示当前连接的端口、版本、笔记本概览，帮助用户确认 |
| 写入前误连旧工作空间 | 写入工具应在返回中包含当前 endpoint 和目标文档信息，必要时要求用户确认 |

第一阶段先不实现 profile 管理。本轮测试可用临时环境变量指定端口和 token，不写入仓库文档或配置文件。

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
| **G** | **阅读返回中嵌入块 ID** | 中 | 能精确定位到思源块，为后续引用和写入做准备 |
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

| # | 事项 | 改动量 | 效果 |
|---|------|:---:|------|
| **G** | **块 ID 嵌入**（`siyuan_read_document` 返回 `<!-- block:xxx -->` 注释） | 中 | 支持跨文档块引用 `((id "text"))` |
| **H** | **`siyuan_write_index` MCP 工具** | 小 | 解决 index.md 跨目录写入问题（见问题 14） |
| **I** | **`siyuan_temporary_allow` 对已刷新隐藏文档的生效** | 中 | 修复已知缺陷：temporary_allow 需走实时 API 找回已过滤文档 |

已完成的 F 原方案（思源Agent笔记本）降级为远期可选——当前 guide.md 在项目目录中已可用。

---

#### 当前状态

**A + B + C + D + E 已完成** (2026-05-02)。A（index.md 纳入启动包）、B（SKILL.md 更新）、C（MCP 隐私工具 2 个——合并为 `siyuan_privacy` + `siyuan_temporary_allow`）、D（连接失败友好提示）、E（ai_workspace 清理）全部到位。

**三-I（统计指标重构）已完成** (2026-05-02)。新增 `block_count` + `char_count`，删除死代码，索引刷新从 ~30s 降到 ~2s。

**三-J（实时搜索隐私过滤审查）已完成** (2026-05-02)。`_enrich_search_blocks()` 对不在安全索引的文档一律 `continue`。

**三-H（附件提取）已完成** (2026-05-02)。`siyuan_read_document` 自动提取所有 `assets/` 引用文件。

**提示词优化已完成** (2026-05-02)。删除 START_HERE.md，AGENTS.md 改为开发者指南，SKILL.md 内联安全规则，单一信息源原则落地。

**F（写入功能第一阶段）已完成** (2026-05-03)。`siyuan_create_document` + `siyuan_edit_document` 两个 MCP 工具可用。文本锚点模式——AI 传入 `old_text`（从 Markdown 读到的原文片段），服务端在块级搜索唯一匹配后执行 `updateBlock`/`appendBlock`。`old_text=""` 追加到文档末尾；`new_text=""` 删除匹配文本。写前自动创建思源工作空间快照；快照失败拒绝写入。写入后 `pushMsg` 通知思源前台。隐藏内容不可写。所有写入工具必须 `confirmed=true`。单元测试 13 个全部通过。经真实思源工作空间验证：创建子文档、替换、追加、删除 4 种操作全部正常。

**WinError 10054 连接重置问题已修复** (2026-05-03)。根因：思源内核使用 Go `net/http` 服务器，默认 HTTP keep-alive；空闲超时后服务器关闭连接，Python urllib 尝试复用时触发 `WSAECONNRESET (10054)`。修复：(1) `client.py` 所有 HTTP 请求添加 `Connection: close` 头，每次请求后关闭连接；(2) 连接错误自动重试 3 次（间隔 0.3s/0.6s）；(3) 错误消息改进，显示具体连接失败原因而非笼统的"似乎没有启动"。详见下方"HTTP Keep-Alive 连接问题"小节。

下一步：G（块 ID 嵌入）、H（`siyuan_write_index`）、I（`siyuan_temporary_allow` 修复）。

原 F（思源Agent笔记本）降级为远期可选——当前 guide.md 在项目目录中已可用。

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

在 `siyuan_read_document` 返回的 Markdown 中嵌入 `<!-- block:xxx -->` HTML 注释。AI 阅读体验不受影响，需要跨文档块引用 `((id "text"))` 时可提取目标块 ID。写入功能不依赖此项——文本锚点已足够。

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
├── PRO.md                          # 本文件 — 项目工程文档
├── README.md                       # 中文快速指南（主版本）
├── README.md                       # 中文快速指南（主版本）
├── README.en.md                    # 英文快速指南
├── AGENTS.md                       # 项目开发指南（面向维护者）
├── config.example.json             # 配置示例
├── config.local.json               # 本机 token（Git 忽略）
├── siyuan.ignore.local.json        # 长期隐藏规则
├── siyuan.allow.local.json         # 临时开放规则
│
├── source_code/                    # Python 工具代码
│   ├── client.py                   #   思源 API client（读写）
│   ├── config.py                   #   配置加载
│   ├── ignore.py                   #   隐私规则管理
│   ├── indexer.py                  #   索引生成（tree.md + docs.jsonl）
│   ├── cli.py                      #   CLI 入口
│   └── mcp_server.py               #   MCP stdio server（11 tools）
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
│   ├── guide.md                    #   用户维护的阅读指南
│   └── index.md                    #   AI 生成的导航索引
│
├── ai_workspace/                   # AI 工作区（分析、草稿）
├── tests/                          # 测试
└── dist/                           # 发布产物
    ├── siyuan-agent-bridge-skill-latest.zip
    ├── siyuan-agent-bridge-mcp.json
    └── siyuan-agent-bridge-mcp-deeplink.txt
```

---

## 设计原则

1. **自己优先**：这个工具首先是给开发者自己用的。先在自己电脑上跑通全流程、产生实际价值，之后再考虑打包发布给他人使用。设计决策以"自己能用"为标准，不为想象中的通用场景过度设计。

2. **MCP-first**：产品的唯一界面是 MCP + Skill，面向 AI agent 设计。CLI 命令是早期开发阶段的辅助工具，正常情况下不应被用户或 AI 使用。所有新功能的实现以 MCP 工具为第一优先级，CLI 不变也没关系。

2. **本地优先**：不依赖云服务，所有索引存储在本地。思源 HTTP API 仅在同一台机器的 `127.0.0.1` 上访问。

3. **安全默认**：隐私过滤在索引层完成，而非信任 AI 遵守规则。隐藏的文档从根本上不会出现在索引中。

4. **职责分离**：程序管客观事实（tree.md：有哪些文档），AI 管语义导航（index.md：去哪找什么），人管偏好（guide.md：我希望 AI 怎么做）。

5. **按需加载**：AI 不一次性读取所有内容。启动时只看概览表和导航索引，找到目标后才深读具体文档。长文档分段读取，避免 MCP 响应截断。

6. **最终可靠**：AI 写的 index.md 可能过时，但程序生成的 tree.md 始终准确。如果 index.md 没找到答案，AI 应该 fallback 到 tree.md + `siyuan_list`。

7. **人控覆盖**：用户直接编辑 `siyuan.ignore.local.json` 控制隐藏范围，编辑 `guide.md` 控制 AI 行为。AI 只读、只提议，不直接修改这些文件。
