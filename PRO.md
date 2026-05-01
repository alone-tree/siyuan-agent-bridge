# SiYuan Enhance 项目工程文档

## 什么是 SiYuan Enhance

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
    └── mcp_server.py    → MCP stdio server — 面向 AI 的主要接口，暴露工具给 AI
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
plugins/siyuan-knowledge/  (面向 AI 的指令层)
    ├── skills/siyuan-knowledge/SKILL.md        → 总入口 skill："如何使用思源知识库"
    ├── skills/siyuan-index-builder/SKILL.md    → 专项 skill："如何创建结构化索引"
    └── scripts/run_mcp.py                      → MCP stdio 启动脚本
```

### 关键设计决策

**两层索引分离**：程序生成的客观索引（tree.md）和 AI 生成的语义索引（index.md）各自独立，互不依赖。
- `tree.md` 是客观事实层——脚本扫描生成，保证完整性，每次 refresh 覆盖。
- `index.md` 是语义导航层——AI 阅读后手写，含摘要和判断，增量更新。

**安全索引原则**：所有给 AI 的数据都经过隐私规则过滤。隐藏的笔记本/文档在索引层面就被移除，AI 感知不到它们的存在。

**MCP-first 架构**：项目的产品界面是 MCP + Skill，面向 AI agent 设计。CLI 命令（`python -m source_code ...`）是早期开发时的辅助工具，仅用于人工诊断和调试，正常情况下不应被使用。所有功能的实现应以 MCP 工具为第一优先级，CLI 的实现可有可无。

---

## 系统架构

### 三个概念层

| 层 | 作用 | 执行者 | 产物 |
|----|------|--------|------|
| **数据采集层** | 从思源 API 拉取笔记本列表和原始文档块 | Python 脚本 / MCP 工具 | 内存中的数据结构 |
| **过滤与索引层** | 应用隐私忽略规则，过滤后生成结构化索引 | `indexer.py` + `ignore.py` | `tree.md` + `docs.jsonl` + `notebooks.json` |
| **能力暴露层** | 通过 MCP 协议向 AI 暴露只读工具 | `mcp_server.py` (8 tools) | AI 可调用的语义能力 |

### 数据层

| 文件 | 性质 | 用途 |
|------|------|------|
| `tree.md` | 程序生成，覆盖 | 笔记本概览表 + 每笔记本完整文档树（含字数和更新时间）。两层结构，AI 默认只看第一层。 |
| `docs.jsonl` | 程序生成，覆盖 | 每行一个文档的结构化元数据（id、路径、字数、tags 等）。AI 不直接读，由 MCP 工具动态查询。 |
| `guide.md` | 人工维护，ensure | 用户对 AI 的持久偏好和工作风格指引。`refresh_index` 不覆盖已存在的 guide.md。 |
| `index.md` | AI 生成，增量更新 | 语义导航索引：快速路由表（"什么需求 → 去哪个笔记本"）、路径结构描述、AI 摘要。由 `siyuan-index-builder` skill 创建和维护。 |
| `START_HERE.md` | 项目维护 | AI agent 的入口文件，定义强制启动流程和安全规则。 |

### 指令层

| Skill | 触发条件 | 核心指令 |
|-------|----------|---------|
| `siyuan-knowledge` | 用户提到思源/知识库/笔记 | 强制调用 siyuan_start 获取启动包 → 按导航定位 → 按需深读 |
| `siyuan-index-builder` | 用户要求建索引/更新索引 | 遍历笔记本结构 → 阅读关键文档 → 为每个笔记本写结构摘要和 AI 摘要 → 生成 index.md |

---

## 完整数据流（用户使用流程）

### 步骤 1：安装部署

用户通过 CC Switch 安装 Skill 压缩包 (`dist/siyuan-knowledge-skill-latest.zip`)，并注册 MCP stdio 配置。Skill 和 MCP 注册到 AI 工具后即可使用。

### 步骤 2：会话启动

用户启动 Claude Code / Codex，AI 获得 MCP 工具列表和 Skill 指令。此时 AI 还不知道知识库内容，等待用户触发。

### 步骤 3：用户触发

用户说"帮我查一下笔记里关于光模块的内容"，触发 `siyuan-knowledge` skill。

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
| index.md 存在 | 笔记本概览表（tree.md 第一层）+ index.md 全文 + guide.md + START_HERE.md |
| index.md 不存在 | 笔记本概览表（tree.md 第一层）+ guide.md + START_HERE.md + 提示 AI 询问用户"是否先创建索引以便更快导航" |

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

**6b. 直接使用现有索引** — 从 index.md 快速路由表定位目标笔记本，从 tree.md 第一层确认该笔记本规模，然后用 `siyuan_list_documents` 看该笔记本的文档树。

### 步骤 7：搜索（siyuan_find_documents）

当 AI 需要精确检索时，调用 `siyuan_find_documents`：

1. 发起搜索（4 种模式）：keyword/query/regex/sql
2. 搜索范围（2 种）：headings（仅标题和大纲标题）/ full（所有块正文）
3. 搜索结果经过隐私规则过滤后返回
4. 返回格式：按笔记本分组，每条含文档 ID、hpath、字数、更新时间、匹配片段

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
| 3 | `siyuan_list_notebooks` | 无 | 列出可见笔记本 | ✗ 本地 |
| 4 | `siyuan_list_documents` | `notebook_id` 或 `notebook_name` | 返回某笔记本的完整文档树（含字数、更新时间、tags） | ✗ 本地 |
| 5 | `siyuan_find_documents` | `keyword` + `mode` + `scope` + `notebooks`? + `limit`? | 搜索知识库，隐私过滤后返回 | ✓ |
| 6 | `siyuan_read_document` | `document_id` + `chunk`? (default 0) + `max_chars`? + `extract_attachments`? (default false) | 返回大纲；短文档全文；长文档分 chunk；可选提取附件到 ai_workspace | ✓ |
| 7 | `siyuan_propose_guide_update` | `proposal` + `title`? + `body`? | 保存到 `ai_workspace/` | ✗ |
| 8 | `siyuan_apply_guide_update` | `content` + `mode` + `confirmed` | 追加或替换 `guide.md` | ✗ |

### 工具能力分类

```
入口层:   siyuan_start           → 始终第一个调用
导航层:   siyuan_list_notebooks  → 查看有哪些笔记本
         siyuan_list_documents   → 查看某笔记本的文档树
搜索层:   siyuan_find_documents  → 在多笔记本间定位相关文档
阅读层:   siyuan_read_document   → 获取文档的 Markdown 正文
维护层:   siyuan_refresh_index   → 中途刷新
         siyuan_propose/apply_guide_update → 维护 guide.md
```

### 搜索模式详解

| mode | 实现 | 适用场景 |
|------|------|---------|
| `keyword` | 空格分隔 AND 匹配（本地索引 + FTS method=0） | 日常搜索，覆盖面广 |
| `query` | FTS5 查询语法（AND/OR/NOT/`"短语"`/`前缀*`） | 精确逻辑组合 |
| `regex` | Go RE2 正则（无回溯/反向引用） | 模式匹配 |
| `sql` | 直接执行 SQL 语句 | 跨表查询、统计、按更新时间排序 |

| scope | 搜索范围 |
|-------|---------|
| `headings` | 仅文档标题（type='d' 的 content）和大纲标题（type='h' 的 content） |
| `full` | 所有块的正文（段落、列表等） |

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
| `document` | 隐藏单篇文档 |
| `subtree` | 隐藏某文档及其所有子文档 |

### 过滤时机

隐私过滤发生在索引生成阶段（`refresh_index`），而非每次读取时。这意味着：
- 被隐藏的文档不会出现在 `tree.md`、`docs.jsonl`、`notebooks.json` 中
- `siyuan_find_documents` 的搜索结果交叉验证已过滤的本地索引，隐藏文档不会泄露
- 唯一的例外：`siyuan_read_document` 接受 block_id 直接读取——如果 AI 知道一个隐藏文档的 ID（例如从用户消息中获得），仍可读取

### AI 安全规则

- AI 不应读取 `config.local.json`、`siyuan.ignore.local.json`、`siyuan.allow.local.json`
- AI 不应调用思源写 API
- AI 不应暴露隐藏文档的名称给用户，除非用户明确要求

---

## 当前实现状态



### 已完成

- [x] tree.md 两层结构（笔记本概览表 + 文档树），含 ID、字数、更新时间、tags
- [x] docs.jsonl 结构化数据 + notebooks.json 笔记本索引
- [x] `siyuan_start` 自动 refresh + 返回启动包（含 START_HERE.md 和 guide.md）
- [x] `siyuan_read_document` 大纲 + 分 chunk + chunk 跳转
- [x] `siyuan_find_documents` 4 种 mode × 2 种 scope，隐私过滤
- [x] `siyuan_list_documents` 动态从 docs.jsonl 生成文档树
- [x] 隐私规则过滤（notebook/document/subtree）+ 临时开放
- [x] `siyuan-index-builder` skill 完整流程（快速/详细两种深度）
- [x] `guide.md` 的人工维护模式（ensure 不覆盖）
- [x] 代码去重：`build_notebook_overview()` 单一定义
- [x] 单元测试覆盖

### 待实现

- [ ] **`siyuan_start` 返回 index.md**：当 `knowledge_base/index.md` 存在时，将其纳入启动包返回。当前启动包只含笔记本概览表 + START_HERE.md + guide.md
- [ ] **tree.md 增加块数**：当前 SQL 查询已获取全部字段，但 `normalize_documents()` 未计算块数。需要在 SQL 中 COUNT 子块，或从现有字段推导
- [ ] **思源未启动时的友好提示**：当前连接失败时返回通用错误，应专门检测并提示用户"请先启动思源笔记软件"
- [ ] **`siyuan-knowledge` skill 纳入 index.md 流程**：当前 skill 指令未提及 index.md，应更新为：启动后优先看 index.md 快速路由表，没有 index 时提示用户可建索引
- [ ] **`siyuan_find_documents` 实时搜索结果的隐私过滤**：当前本地索引已过滤，但实时 FTS 搜索结果交叉验证 local_docs 可能遗漏边界情况。需要确认对隐藏内容的过滤是绝对的

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
    │       - '隐藏 XX 笔记本'  → AI 调用 siyuan_hide
    │       - '隐藏 /某路径/某文档'  → AI 调用 siyuan_hide
    │       - '临时开放 日记 笔记本 30 分钟'
    │
    │       设置后我会自动刷新索引，隐藏的内容将不再可见。"
    │
    ├── 创建 .siyuan_privacy_initialized 标记（用户已看到引导）
    │
    └── 后续：
        用户随时说"把日记随笔这个笔记本隐藏掉"
          → AI 调用 siyuan_hide → 自动刷新索引 → 标记早已存在，不影响
```

**用户使用场景**：

```
用户: "帮我查一下光模块行业的数据"
  → AI 触发 siyuan_start
  → 首次启动，返回笔记本列表 + 末尾隐私引导
  
用户: "哦对，把日记随笔这个笔记本隐藏掉"
  → AI 调用 siyuan_hide("notebook", "日记随笔")
  → 自动 refresh
  → 继续正常回答光模块的问题
```

**关键洞察**：用户第一次用了 `siyuan_hide` 之后，就建立了心智模型——以后想隐藏新的内容，对 AI 说同样的话就行。这比一次性 wizard 更可持续。

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
| `siyuan_hide(scope, locator, reason)` | 隐藏笔记本/文档/子树 |
| `siyuan_unhide(scope, locator)` | 取消隐藏 |
| `siyuan_allow(scope, locator, minutes, reason)` | 临时开放隐藏内容 |
| `siyuan_allow_close()` | 立即关闭所有临时开放 |

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

**当前状态**：Markdown 中保留 `![](assets/image.png)` 的图片引用，但 AI 无法看到图片内容（除非 AI 是多模态模型且能访问本地文件路径）。

**方案**：在 `siyuan_read_document` 中增加可选参数 `extract_attachments`。当 AI 认为文档中的附件（图片、PDF、表格等）值得查看时，可指定此参数。

```
siyuan_read_document(
    document_id: str,
    chunk: int = 0,
    max_chars: int = 10000,
    extract_attachments: bool = false   ← 新增
)
```

**行为**：

| `extract_attachments` | 行为 |
|:---:|------|
| `false`（默认） | 仅返回 Markdown 文本，图片保留原始引用 `![](assets/image.png)` |
| `true` | 提取文档关联的附件，复制到 `ai_workspace/attachments/<doc-id>/` 下，返回 Markdown 中将图片引用替换为指向 `ai_workspace/` 的相对路径 |

这样 AI 可以直接读取 `ai_workspace/attachments/` 下的文件（包括通过 Read 工具查看图片）。附件只在 AI 明确需要时才提取，避免无谓的磁盘占用。

**ai_workspace 清理机制**：

在 `siyuan_refresh_index` 中增加清理功能：每次 refresh 时自动清空 `ai_workspace/` 中除 `README.md` 以外的所有内容。这确保每次新会话开始时 workspace 是干净的，不会越堆越多。

如果用户希望保留某次 AI 的分析结果，应在会话结束前手动移到其他位置。

**数据库（思源数据库块）**的读取可通过 `siyuan_find_documents` 的 sql 模式实现，暂不需要专门的数据库读取工具。

---

### 问题 9：未来写入功能设计预留

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
   - Use `siyuan_list_documents` with notebook_name="思源Agent" to find it.
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

### 开发路线图

排序标准：**"现在我每次打开 AI，这件事能让我少走多少弯路"**。不按"软件工程的完整性"排，不按"如果以后有别的用户怎么办"排。

#### 第一优先级：每次会话都直接受益

一条原则：**index.md 已经存在了（365 篇文档、完整导航、AI 摘要），但 AI 现在完全不知道它存在。** 这是目前最大的浪费。

| # | 事项 | 改动量 | 效果 |
|---|------|:---:|------|
| **A** | **`siyuan_start` 纳入 index.md** | 小 | 每次新会话，AI 直接拿到完整导航。从"盲人摸象"变成"有地图" |
| **B** | **`siyuan-knowledge` SKILL.md 更新** | 中 | AI 知道启动后优先看 index.md 快速路由表，知道怎么用已有的导航和搜索。不改这个，A 改了 AI 也不会用 |
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
| **H** | **`siyuan_read_document` 附件提取** | 中 | 图文混排文档可以把图片拉到本地给 AI 看 |
| **I** | **tree.md 增加块数** | 小 | 元数据更完整 |
| **J** | **实时搜索隐私过滤审查** | 小 | 安全审计 |

#### 第四优先级：对外发布时才需要

| # | 事项 |
|---|------|
| K | README 更新 |
| L | dist 发布包重新打包 |
| M | 首次初始化隐私引导（自己已经设置过了，不需要） |

#### 远期：写入功能

等前面全部稳定后再考虑。

---

#### 当前建议

**先做 A + B**。两个改动加起来，效果是：每次打开新会话，AI 直接拿到你花了时间建好的 index.md 导航，知道去哪找什么。这是目前最大的体验断层——东西已经建好了，AI 就是不知道怎么去读它。

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

#### B. `siyuan-knowledge` SKILL.md 更新

**改动**：`plugins/siyuan-knowledge/skills/siyuan-knowledge/SKILL.md`

**要点**：
- Mandatory Startup 新增步骤：启动后优先检查 index.md 是否存在，存在则用快速路由表定位
- Tool Use 中说明 index.md 的定位（AI 生成的语义导航）和 fallback 策略（过期时用 tree + find）
- 新增隐私工具的用法说明
- startup 流程改为：`siyuan_start` → 读 index.md（如有）→ 读 guide → 后续操作

#### C. MCP 隐私工具

**改动**：`mcp_server.py`，直接调用 `ignore.py` 和 `indexer.py` 的底层函数

| 工具 | 实现 |
|------|------|
| `siyuan_hide(scope, locator, reason)` | 调用 `add_persistent_ignore()` → 自动 `refresh_index()` |
| `siyuan_unhide(scope, locator)` | 调用 `remove_persistent_ignore()` → 自动 `refresh_index()` |
| `siyuan_allow(scope, locator, minutes, reason)` | 调用 `make_temporary_allow()` + `write_temporary_allow()` |
| `siyuan_allow_close()` | 调用 `close_temporary_allow()` |

注意：这是 AI 通过 MCP 使用的工具，安全要求高——hide 和 unhide 需要 AI 在调用前向用户确认范围，避免误操作。

#### D. `siyuan_start` 连接失败友好提示

**改动**：`mcp_server.py` 的 `siyuan_start()` 方法

区分两种错误：
- 连接被拒绝 → "思源笔记似乎没有启动。请打开思源笔记软件后重试。"
- 其他错误（token、网络等）→ 保留现有错误信息

#### E. `siyuan_refresh_index` 清理 ai_workspace

**改动**：`indexer.py` 的 `refresh_index()` 或 `mcp_server.py` 的 `siyuan_refresh_index()`

每次 refresh 时清空 `ai_workspace/` 下除 `README.md` 外的所有文件和目录。

#### F. 思源 API 写操作 + "思源Agent"笔记本

**改动**：`client.py`（新增 API）+ `mcp_server.py`（首次初始化逻辑）

**步骤**：
1. `client.py` 新增 `create_notebook(name)` 和 `create_doc_with_md(notebook_id, title, markdown)` 两个方法
2. 首次初始化时（检测标记文件不存在），在思源中创建"思源Agent"笔记本
3. 在笔记本中创建 guide 文档（模板内容由程序生成）
4. 将文档 ID 记录到本地配置文件
5. 后续 `siyuan_start` 通过 notebook 名称找到 guide 文档的 ID，自动读取

详见 [问题 11](#问题-11思源-agent-笔记本--guide-文档的归属)。

#### G. 阅读返回中嵌入块 ID

**改动**：`mcp_server.py` + `client.py`

在导出 Markdown 后，查询文档的块树（`/api/block/getBlockTree`），在每个块内容前嵌入 `<!-- block:xxx -->` HTML 注释。AI 阅读体验不受影响，但获得精确定位能力。

详见 [问题 7](#问题-7阅读返回格式--纯-markdown-vs-块增强-vs-json)。

#### H. `siyuan_read_document` 附件提取

**改动**：`mcp_server.py`

新增 `extract_attachments` 参数（默认 false）。设为 true 时，提取文档关联的附件到 `ai_workspace/attachments/<doc-id>/`，并将 Markdown 中的引用路径更新为指向 workspace。

详见 [问题 8](#问题-8附件和图片处理)。

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

#### 远期：写入功能

依赖 4.1（块 ID）。预留工具接口：`siyuan_append_block` / `siyuan_insert_block` / `siyuan_update_block` / `siyuan_create_document`，全部需要 `confirmed=true`。

---

## 目录结构

```
siyuan-enhance/
├── PRO.md                          # 本文件 — 项目工程文档
├── README.md                       # 英文快速指南
├── README.zh-CN.md                 # 中文快速指南
├── AGENTS.md                       # AI agent 仓库规则（兼容性保留）
├── START_HERE.md                   # AI 入口文件
├── config.example.json             # 配置示例
├── config.local.json               # 本机 token（Git 忽略）
├── siyuan.ignore.local.json        # 长期隐藏规则
├── siyuan.allow.local.json         # 临时开放规则
│
├── source_code/                    # Python 工具代码
│   ├── client.py                   #   只读思源 API client
│   ├── config.py                   #   配置加载
│   ├── ignore.py                   #   隐私规则管理
│   ├── indexer.py                  #   索引生成（tree.md + docs.jsonl）
│   ├── cli.py                      #   CLI 入口
│   └── mcp_server.py               #   MCP stdio server（8 tools）
│
├── plugins/siyuan-knowledge/       # Skill + MCP 插件
│   ├── plugin.json                 #   插件清单
│   ├── skills/
│   │   ├── siyuan-knowledge/       #   总入口 skill
│   │   │   └── SKILL.md
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
    ├── siyuan-knowledge-skill-latest.zip
    ├── siyuan-knowledge-mcp.json
    └── siyuan-knowledge-mcp-deeplink.txt
```

---

## 设计原则

1. **自己优先**：这个工具首先是给开发者自己用的。先在自己电脑上跑通全流程、产生实际价值，之后再考虑打包发布给他人使用。设计决策以"自己能用"为标准，不为想象中的通用场景过度设计。

2. **MCP-first**：产品的唯一界面是 MCP + Skill，面向 AI agent 设计。CLI 命令是早期开发阶段的辅助工具，正常情况下不应被用户或 AI 使用。所有新功能的实现以 MCP 工具为第一优先级，CLI 不变也没关系。

2. **本地优先**：不依赖云服务，所有索引存储在本地。思源 HTTP API 仅在同一台机器的 `127.0.0.1` 上访问。

3. **安全默认**：隐私过滤在索引层完成，而非信任 AI 遵守规则。隐藏的文档从根本上不会出现在索引中。

4. **职责分离**：程序管客观事实（tree.md：有哪些文档），AI 管语义导航（index.md：去哪找什么），人管偏好（guide.md：我希望 AI 怎么做）。

5. **按需加载**：AI 不一次性读取所有内容。启动时只看概览表和导航索引，找到目标后才深读具体文档。长文档分段读取，避免 MCP 响应截断。

6. **最终可靠**：AI 写的 index.md 可能过时，但程序生成的 tree.md 始终准确。如果 index.md 没找到答案，AI 应该 fallback 到 tree.md + siyuan_list_documents。

7. **人控覆盖**：用户直接编辑 `siyuan.ignore.local.json` 控制隐藏范围，编辑 `guide.md` 控制 AI 行为。AI 只读、只提议，不直接修改这些文件。
