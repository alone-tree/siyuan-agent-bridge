# PD — 思源桥产品设计文档

> 2026-06-03 追加设计记录：[`table-edit-next-design.md`](./table-edit-next-design.md) 记录 table_edit 坐标网格与列操作；[`tool-surface-next-design.md`](./tool-surface-next-design.md) 记录工具精简、命名统一、文档文件操作和三档权限模型。

面向开发者和深度用户，阐述设计理念、架构决策和实现权衡。

---

## 定位

思源桥是一个私有、本地优先的思源笔记 MCP 适配层。它的产品形态是 MCP 工具和 Skill，面向的终端用户是 AI agent（而非人类直接使用命令行）。

**一句话：让顶尖 AI agent 拥有结构化的个人知识库，而不是在笔记软件里塞一个二流 AI 工具。**

## 与同类项目的差异

GitHub 上有多个将思源 API 封装为 MCP 工具的开源项目。它们和思源桥有交集，但产品目标不同。

### vs 其他思源 MCP 项目

其他项目通常将思源 API 直接暴露为 MCP 工具，追求"思源能做什么，MCP 就能做什么"。思源桥则刻意简化，将数十个 API 收束为 5 个工具，并尽可能将MCP工具设计得接近AI编程时使用的工具（因为当前大多数AI模型都会针对编程进行强化训练，但不太可能针对思源笔记的API进行强化）。每个工具内部整合多个 API 调用，目的是减少 AI 的选择负担和出错概率——AI 面对 30 个陌生工具时，出错几率远高于 5 个熟悉的工具。

### vs 向量化知识库

大多数知识库项目将文档向量化，然后 RAG 检索返回相关段落。这很快，但 AI 拿到的是去上下文的片段。主流 AI 编程工具（Claude Code、Codex、Cursor）很少使用向量化，更多依赖文件树、关键词检索和分段阅读。

思源桥选择**不向量化**。它提供的是目录（list）、检索（find，基于思源 FTS5 全文搜索）、分段阅读（read）。这是人查资料的逻辑，也是确保 AI 完整理解上下文的关键。代价是慢，但换来的是准确。

### vs 笔记内置 AI

Notion AI、思源集市的部分AI插件等将 AI 嵌入笔记软件。优势是贴近内容，劣势是永远追不上专用 agent 工具。思源桥选择反过来——以 AI agent 为中心，笔记作为数据层接入。AI 工具更新后可以立刻用上最新能力，无需等待笔记软件支持。此外，由于现在市面上几乎所有AI agent都支持MCP和skill，因此用户可以自由选择喜欢的平台。

### 已知参考项目

| 项目 | 定位 | 许可 |
|------|------|------|
| `GALIAIS/siyuan-mcp-server` | 通用 SiYuan MCP Server（TypeScript），覆盖文档、块、模板、SQL 等 | MIT |
| `leolulu/siyuan-mcp-server` | Python 版完整工具集，含写操作流程规范 | MIT |
| `porkll/siyuan-mcp` | npm 通用 MCP，含 Cursor/Claude 配置示例 | 需确认 |
| `onigeya/siyuan-mcp-server` | 早期 TypeScript MCP，简洁 API 封装 | ISC |
| `MyrkoF/siyuan-query-mcp` | 面向数据库/属性视图的 MCP | 开源 |
| `frostime/syplugin-anMCPServer` | 思源插件形态的 MCP，支持读写 | 开源 |

思源桥的底层技术工作（API client、MCP 协议封装）与上述项目有较多重叠。真正独特的部分是：隐私过滤安全索引、启动包、AI 语义导航、机制/策略分离的 Skill 设计。

## 工具层设计

### 5 工具模型

AI 编程工具的核心工具只有 5 个：列出文件、搜索、读文件、编辑、写文件。思源桥一一对应：

| 工具 | 整合的思源 API | 设计意图 |
|------|----------------|---------|
| `siyuan_list` | listNotebooks + lsDocs | 笔记本概览或单笔记本文档树 |
| `siyuan_find` | fullTextSearchBlock + 隐私过滤 | FTS5 全文搜索，4 种模式 |
| `siyuan_read` | getBlockTree + exportMdContent + getBlockInfo | 大纲 + 窗口分段 + 附件提取 |
| `siyuan_edit` | getBlockInfo + updateBlock/insertBlock/deleteBlock + createSnapshot | 引用阅读定位后的结构化编辑，含表格行列单元格操作 |
| `siyuan_create` | createDocWithMd + createSnapshot | Markdown 新建，支持标签/模板 |

另外 2 个辅助工具：`siyuan_start`（启动入口）、`siyuan_refresh_index`（手动刷新索引）。

### 机制与策略分离

三层内容的职责划分是思源桥的核心设计约束：

| 层 | 谁维护 | 存放位置 | 内容性质 |
|----|--------|---------|---------|
| **脚本固定内容** | 开发者 | `source_code/` | 机制实现（MCP 工具、索引生成） |
| **Skill 通用指令** | 开发者 | `plugins/` SKILL.md | 机制用法（"先调 siyuan_start"） |
| **用户个性化** | 用户 + AI | 思源系统笔记本 | 策略偏好（"优先看投资笔记本的汇总文档"） |

核心原则：机制层只描述"怎么操作"，不预判具体笔记结构或工作流。策略层由用户控制。
- ✗ Bad：SKILL.md 写"优先搜索投资相关笔记本" — 个别用户的策略
- ✓ Good：SKILL.md 写"优先读取 AI 使用指南中用户指定的重点笔记本" — 通用机制

## 阅读与检索

### 为什么不用向量化

向量检索引擎把文档切成片段，检索时返回最相关的几个片段。问题在于：AI 拿到片段后，不知道这段文字在整个文档中的位置、前后文是什么、作者为什么在这里写这段话。

思源桥的选择：
- **大纲优先**：每次 read 先返回完整大纲（标题 → 块位置映射），AI 始终知道文档结构。
- **分段阅读**：按块窗口返回连续内容，保持上下文连贯。
- **全文搜索**：用思源内置的 FTS5，保证精确匹配，不丢上下文。

如果未来 AI 上下文窗口继续增大（如 10M token），向量化的优势会更小。

### 搜索：API-only 召回 + 隐私过滤

早期搜索曾同时走本地索引和思源 API 两条路径，实践中暴露出搜索语义不一致、合并去重逻辑复杂的问题。最终统一为 API-only：

1. 统一调用思源 FTS5 全文搜索 API 召回结果。
2. 搜索前自动临时打开关闭的笔记本，搜索完成后恢复原状，持续时间大概1-3秒。
3. 搜索结果在 MCP server 内部经隐私规则过滤后返回给 AI。命中隐私规则的结果直接丢弃。
4. 用 `docs.jsonl` 补全文档的字数、更新时间等元数据——它不参与搜索匹配，只做元数据补全。
5. 同一文档内的多个命中块全部保留为 snippets（默认展示前 5 个），避免 AI 误判文档里只有一处相关内容。

**4 种搜索模式：**

| mode | 实现 | 适用场景 |
|------|------|---------|
| `keyword` | FTS5 空格分隔 AND 匹配 | 日常搜索 |
| `query` | FTS5 高级语法，AND/OR/NOT/`"短语"`/`前缀*` | 精确逻辑组合 |
| `regex` | Go RE2 正则（无回溯/反向引用） | 模式匹配 |
| `sql` | 直接执行 SQL，需 admin 权限 | 跨表查询、统计 |

**2 种范围**：`headings`（仅标题）和 `full`（所有块正文）。

### 长文档：Chunk → Block Window 迁移

早期版本按字符数分 chunk（默认 10,000 字符），在段落边界切分。真实文档测试后暴露了字符分块的固有问题：

| 维度 | Chunk（字符分块） | Block Window（块窗口） |
|------|:---:|:---:|
| 语义边界 | 段落级，可能切断语义 | 自然语义边界（标题即块、段落即块） |
| 大小控制 | 字符数可控，但 token 估算不稳定 | 用 `block_limit` + `token_budget` 双约束 |
| 精确定位 | 无块 ID，只能靠引用文字 | 每个块有唯一 ID，引用精确 |
| 读写衔接 | 无法精确定位写入目标 | 写入可指定块 ID |

**当前实现**：按展示块窗口返回。默认 `block_start=1`、`block_limit=200`、`token_budget=50000`。每次返回至少一个完整块，不会从块中间截断。大纲、引用阅读和后续编辑共享同一套位置模型。

默认值设计从宽——现代 AI 模型上下文窗口普遍较长，不应默认切得过碎；但也预留 `block_limit` 和 `token_budget` 参数让 AI 按需控制。

### 块引用与引用阅读

思源支持跨文档块引用语法 `((block_id "锚文本"))`。`siyuan_read` 提供 `include_block_ids` 参数（默认 `false`），开启后对外称“引用阅读”模式。

**引用阅读的实现**：通过 `/api/block/getChildBlocks` 按思源返回的真实子块顺序递归遍历块树，在每个可展示块前返回定位头：

```markdown
[1] id=20260410083015-abc123 type=heading
## 中际旭创分析

[2] id=20260410083016-def456 type=paragraph
2025年营收增长45%，其中800G光模块占比超过60%。
```

AI 需要跨文档引用时，可从定位头中提取目标块 ID，构造 `((20260410083016-def456 "800G光模块占比达60%"))`。需要编辑时，AI 使用同一组 `index + id` 定位目标块，避免仅靠文本匹配带来的歧义。

**遍历规则**：
- 跳过文档块、列表容器块和空块。
- 列表项这类自身 Markdown 已包含子内容的块，渲染后不再递归子孙，避免重复。
- 超级块只显示块 ID 定位头并继续遍历子块。
- 普通 Markdown 表格在引用阅读中渲染为带行列号的网格视图，隐藏 Markdown 分隔行。

**默认不启用**：普通阅读保持纯 Markdown 体验。引用阅读只在跨文档块引用、精确定位或编辑辅助时按需开启。

## 写入与编辑

### 写入安全：快照兜底

AI 编程工具的回滚方案是恢复到对话前的状态。思源桥无法精确追踪每次对话的边界，因此采用更保守的策略：

**每次写入前自动创建思源数据快照。快照写入成功，编辑才能生效。快照失败，拒绝写入。**

用户通过思源原生的快照功能手动回滚。思源默认每天保留 2 个快照，保存 180 天，无需担心快照膨胀。

当前写入工具设计：

- `siyuan_create` 创建新文档。
- `siyuan_edit` 编辑已有可见文档。编辑前先用 `siyuan_read(include_block_ids=true)` 取得目标块的 `start_index` 和 `start_id`。
- `single_block_replace` 用于一块替换为一块，保留目标块 ID 和块属性。
- `multi_block_replace` 用于跨块替换或一块变多块，先插入新内容再删除旧块；旧块 ID 不保留。
- `insert_before` / `insert_after` 不修改锚点块。
- `append` 追加到文档末尾。
- `delete` 删除指定块或块范围。
- `table_edit` 编辑普通 Markdown 表格，支持 `set_cell`、`insert_row`、`delete_row`、`insert_column`、`delete_column`。
- 所有写入需 `confirmed=true`，并在写入前创建思源工作空间快照。

设计演进说明：早期写入模型使用 `old_text -> new_text` 文本锚点。真实使用发现，AI 看到的是近似 Markdown，而思源底层是块树；空格、表格格式、导出差异或用户并发修改都会让精确文本锚点变脆。当前模型改为引用阅读坐标定位：AI 先读到块序号和块 ID，再用结构化动作表达修改意图。PD 保留这段演进说明，详细过程记录在 `docs/devlog.md`。

### 表格编辑

普通 Markdown 表格不是数据库/属性视图。引用阅读时，普通表格块会显示为 AI 友好的网格：

```markdown
[12] id=... type=table
| row_index | col 1 | col 2 | col 3 |
| row 0 | 指标 | 重构前 | 重构后 |
| row 1 | 注册完成率 | 64.3% | 79.1% |
```

表格坐标规则：

- `row=0` 是表头。
- `row>=1` 是数据行。
- `column_index` 从 1 开始。
- Markdown 分隔行 `| --- | --- |` 不暴露给 AI。
- 修改表头或首列也使用普通单元格操作，不额外设计字段/主键语义。

### 块样式属性（IAL）静默保留

思源块的块样式（背景色、信息/警告卡片等）存储在 `blocks.ial` 字段中。`siyuan_edit` 调用 `update_block` 时如不传 IAL，思源内核会重置样式。

解决方案：编辑前用 SQL 静默读取当前块的 IAL，编辑完成后通过 `setBlockAttrs` 恢复。IAL 完全不暴露给 AI——AI 只看到和操作 Markdown 文本，样式由系统原样保留。

### 复杂块类型兼容

思源支持多种以代码块（`type=c`）存储的复杂渲染块：ABC 五线谱、ECharts 图表、Mermaid 图表、Flowchart 流程图、PlantUML、Graphviz 等。这些块通过 IAL 中的语言标识区分渲染引擎。

实测确认：所有这些类型本质都是代码块，编辑流程的 IAL 静默保留机制天然兼容所有复杂块类型。AI 可以编辑其 DSL 源码，但不对语义做校验（如不检查 JSON 是否合法 ECharts 配置）——语义错误由思源渲染引擎在 UI 中暴露。

### 数据库/属性视图（Database/AV）处理

思源数据库在导出 Markdown 中显示为空 `<div>` 占位符，AI 看不到任何数据行。思源桥做了专项处理：

- **阅读**：检测到 `type=av` 块后，调用 `/api/av/getAttributeView` 获取完整数据，按列转置为 Markdown 表格。注入只读标记 `<!-- siyuan:database ... readonly=true -->`。
- **编辑拦截**：数据库块不可编辑。若 AI 尝试编辑，返回明确错误提示改用追加模式在文档末尾创建新表格。
- **搜索**：思源原生搜索能穿透数据库找到内容，正常返回命中文档。

不作完整的数据库管理器——不暴露字段类型、视图配置、筛选排序等语义。AI 的价值是理解和建议，不是替代思源数据库 UI。

## 隐私设计

### 隐私：硬编码隔离

隐私规则由用户在思源 UI 中维护（Markdown 表格），MCP 服务器内部解析后过滤所有索引导出和搜索结果。

关键设计决策：**移除 AI 管理隐私规则的权限。** 早期版本考虑过让 AI 通过MCP工具接受文档 ID 来管理隐私设置，但最终砍掉——因为这仍然依赖 AI"自觉"，不可靠。改为隐私规则文档本身在代码中硬编码为不可读，AI 甚至不知道它的存在。

过滤发生的时机：
- 索引生成时（`indexer.py`）— tree.md 和 docs.jsonl 不会包含隐藏文档
- 搜索返回时（`mcp_server.py`）— 搜索结果在返回 AI 前被过滤
- 阅读时（`mcp_server.py`）— 隐藏文档即使已知 ID 也无法读取
- 列表时（`mcp_server.py`）— 隐藏文档不在文档树中

## 工作空间基础设施

### 系统笔记本设计

思源桥启动时在思源中自动创建 `思源桥` / `SiYuan Bridge` 笔记本，包含 4 篇文档：

| 文档 | 谁维护 | 生命周期 |
|------|--------|---------|
| AI 使用指南 / AI Guide | 用户在思源 UI 编辑，AI可辅助维护 | 不存在时创建默认模板，存在时不覆盖 |
| 隐私规则 / Privacy Rules | 用户在思源 UI 编辑 | 不存在时创建默认模板，存在时不覆盖 |
| 关于思源桥 / About SiYuan Bridge | 模板自动生成 | 版本标识变更时覆盖 |
| 工作空间索引 / Workspace Index | AI 生成（通过 skill） | 不自动创建，不覆盖 |

设计意图：让用户能在思源中像编辑普通文档一样参与 AI 行为的设定。不需要打开代码文件，不需要懂Python或json。

**语言与命名策略**：同一个工作空间只维护一套系统文档。查找时兼容中文名（`思源桥`、`思源代理桥`）和英文名（`SiYuan Bridge`、`SiYuan Agent Bridge`），以及已知的混合名（`关于Siyuan Agent Bridge`）。内部使用稳定 key（`ai_guide`、`workspace_index`、`about`、`privacy_rules`），不依赖显示名称。系统文档缺失时按当前语言创建（中文环境创建中文名，非中文环境创建英文名）；已存在的沿用已有名称，不自动重命名。

**About 文档覆盖机制**：内置模板含版本标识（当前为 `<!-- template_version: 3 -->`）。refresh 时对比现有文档是否包含相同版本标识——匹配则跳过，不匹配则用新模板覆盖。用户自行编辑后版本标识被破坏，不会被意外覆盖。

**系统笔记本保护**：`思源桥` 笔记本不能被隐私规则隐藏。若用户尝试隐藏，MCP 拒绝并提示这是系统笔记本。

### 工作空间索引

AI 编程项目通常有 README.md 作为项目概览入口，AI 探索代码库前会先读它。思源桥借鉴了这个思路。

索引的生成策略：
- 不简单打印文档树结构（信息噪音大）
- 不做无差别的全文摘要（太长，AI 记不住）
- AI 扫描所有笔记本后，判断定位和重点，形成结构化导航表 + 关键文档摘要
- 一个全工作空间索引，只有一个文档（可扩展到单个笔记本的深度索引）

### 关闭笔记本：透明处理

思源允许关闭笔记本（不显示在 UI 中）。关闭只代表用户当前不想看，不代表内容没价值。思源桥在索引、搜索和写入时，会临时打开关闭的笔记本，完成后恢复原状。

如果用户不希望 AI 访问某些笔记本，应该使用隐私规则，而非关闭笔记本。

### 多工作空间

思源一次只能暴露一个工作空间（固定端口 6806，监听第一个启动的工作空间，其余空间随机获得端口）。思源桥通过 token 自动检测当前在线的工作空间。

因为系统笔记本、隐私规则、索引等都存储在思源中，它们天然跟随工作空间切换。这比在配置文件中管理这些信息更优雅——配置文件和笔记内容不会脱节。

实践中发现的问题：如果用户先启动工作空间A，再启动工作空间B，再关闭工作空间A，此时6806端口仍然挂在空间A上。需要将空间B也关闭，再重启空间B，才能监听空间B的通讯。

## 完整数据流

以下是一次典型的 AI 会话中思源桥的工作流程：

**步骤 1：用户触发** — 用户说"帮我查一下笔记里关于 XX 的内容"，触发 `siyuan-agent-bridge` skill。

**步骤 2：启动** — Skill 要求 AI 调用 `siyuan_start`。调用后工具内部完成：连接检查 → 确保系统笔记本就绪 → 刷新安全索引（tree.md + docs.jsonl）→ 组装启动包返回。

**步骤 3：启动包内容** — 返回笔记本概览表（所有笔记本的文档数、字数、最近更新）+ Workspace Index（如存在）+ AI 使用指南 + 隐私规则命中数 + 语言偏好。Workspace Index 不存在时，提示 AI 可建议用户创建导航索引。

**步骤 4：导航** — AI 从 Workspace Index 快速路由表定位目标笔记本，用 `siyuan_list`（带 `notebook_id`）查看该笔记本的文档树（含字数和更新时间）。

**步骤 5：搜索** — 需要跨笔记本精确检索时，调用 `siyuan_find`。API-only 召回 → 隐私过滤 → 元数据补全 → 返回按文档分组的命中结果。

**步骤 6：阅读** — AI 判断需要深读某篇文档时，调用 `siyuan_read`。先返回大纲（标题→块位置），再按块窗口返回正文。长文档用 `block_start=N` 翻页继续。附件自动提取到 `ai_workspace/`。

**步骤 7：写入**（可选）— 用户明确要求写入时，AI 调用 `siyuan_create` 或 `siyuan_edit`。写前创建数据快照，快照成功写入才生效。写入后 pushMsg 通知思源前台。

## 本地文件角色

思源中的系统文档是"主副本"。本地生成的索引文件是"缓存"：

| 文件 | 性质 | 刷新时机 |
|------|------|---------|
| `knowledge_base/tree.md` | 程序生成 | 每次 `siyuan_start` / `siyuan_refresh_index` |
| `knowledge_base/docs.jsonl` | 程序生成 | 同上 |
| `knowledge_base/notebooks.json` | 程序生成 | 同上 |
| `knowledge_base/privacy_rules.json` | 缓存 | 同上 |
| `ai_workspace/` | AI 工作区 | `siyuan_start` 时清理 |

## 已知限制

- **超级块嵌套布局**——思源支持块合并为超级块，超级块再嵌套，形成复杂排版。思源桥展平为 Markdown，不保留布局结构。
- **数据库（Database）**——简化为普通表格，不提供数据库操作接口。AI 只能新建普通表格块。
- **只支持 Windows**——因为开发者没有 Mac/Linux 环境。欢迎 PR。
- **不支持移动端**——依赖本地 Python 和 MCP。
- **单人使用**——未做多用户协作考虑。一个工作空间同一时间只有一个用户。

## 代码结构

```
source_code/
├── client.py           # 思源 HTTP API 封装（读写、快照、附件）
├── indexer.py          # 索引生成（tree.md + docs.jsonl）
├── ignore.py           # 隐私规则解析（Markdown 表格）与过滤
├── i18n.py             # 多语言解析、系统名称映射、默认模板
├── agent_notebook.py   # 系统笔记本服务层（确保四文档就绪）
├── config.py           # 配置加载（profiles + 环境变量 + 自动检测）
├── mcp_server.py       # MCP stdio server（9 个工具）
└── cli.py              # 开发诊断 CLI

plugins/siyuan-agent-bridge/
├── .mcp.json           # MCP 注册配置
├── .codex-plugin/      # Codex 插件清单
├── scripts/run_mcp.py  # MCP stdio 启动脚本
└── skills/             # Skill 定义（siyuan-agent-bridge + siyuan-index-builder）
```

---

## 2026-06-02：siyuan_edit 工具设计讨论

### 背景

Hermes + DeepSeek 的真实使用暴露出一个问题：早期 `old_text -> new_text` 文本锚点编辑对 AI 不够友好。AI 看到的是近似 Markdown 文本，但思源底层是块结构；一旦 UI、导出 Markdown、空格、表格格式或块内容发生轻微变化，文本锚点就容易匹配失败。

核心判断：不要强行把思源块当作标准 Markdown 文件的行来处理。工具应该顺应思源块设计，同时让 AI 的操作方式尽量接近常见的文档编辑。

### 第一性原理

AI 想编辑文档时，最自然需要的是：

- 先读到可理解的文档内容。
- 在需要修改时，能看到可引用的位置标识。
- 用路径找到文档，用块序号和块 ID 锁定目标。
- 对大段内容做范围替换，对局部内容做插入、删除或表格编辑。
- 不依赖精确原文匹配，但要有足够校验，避免改错地方。

### 文档定位

优先使用文档路径，而不是文档 ID。路径对 AI 更友好，也更接近人类理解文档的方式。

路径必须包含笔记本名称，从笔记本名称开始，例如：

```text
/存储芯片行业研究报告/芯片/澜起科技（688008）深度研究报告
```

只有当同一路径存在重名或路径无法唯一定位时，才要求补充文档 ID。

### read 模式

`siyuan_read` 默认使用普通阅读，不显示块 ID、序号和类型。只有当 AI 需要编辑、引用、定位或调试块结构时，才启用引用阅读。

引用阅读需要展示每个可编辑 display block 的：

- 全局块序号。
- 块 ID。
- 语义块类型。

示例：

```markdown
[16] id=20260602163315-710wwtv type=heading
### 列表

[17] id=20260602163321-194aatq type=list
1. 第一项
2. 二
   1. 二的缩进1
   2. 二的缩进2
3. 三
```

不展示冗余底层信息，例如 `raw_type=h level=3` 或 `raw_type=l list=ordered`。标题层级、列表有序无序已经可以从 Markdown 自身看出。

### 块类型

引用阅读中的类型使用英文语义名称，不使用思源底层简称，也不混用中英文。

推荐类型：

- `heading`
- `paragraph`
- `list`
- `table`
- `code`
- `attachment`
- `database`
- `superblock`
- `blockquote`
- `math`
- `html`
- `iframe`
- `video`
- `audio`
- `widget`
- `thematic_break`

附件统一显示为 `type=attachment`，不再细分 image、pdf、doc 等类型。具体文件类型可从链接后缀判断。

数据库块保留块 ID，不默认暴露 `database_id / av-id`，避免 AI 把两个 ID 混淆。必要时可以在专门的数据库工具里暴露属性视图 ID。

### 超级块

超级块作为一个 display block，占一个全局序号。其内部子块继续显示自己的序号和 ID。超级块结束标记不单独占序号。

示例：

```text
[22] id=... type=superblock
{{{ superblock start

[23] id=... type=paragraph
内容 1

[24] id=... type=paragraph
内容 2

}}} superblock end [22]
```

`delete` 允许删除超级块，并连同内部子块一起删除。`replace` 暂时不支持直接替换复杂超级块；如果需要重构超级块内部内容，应拆分为更小范围处理。

### 列表

列表先采用最简单、最鲁棒的方案：把整个列表容器视为一个 display block，暂时不展开列表内部的 list item 块 ID。

原因：

- 列表内部存在嵌套块关系，完全展开会显著增加阅读噪音。
- 大多数列表编辑可以通过替换整个列表块完成。
- 若未来需要局部编辑列表项，可再设计块内文本替换或列表专用 action。

### siyuan_edit 设计

新工具命名为 `siyuan_edit`，而不是 `siyuan_edit_block`。它面向文档编辑语义，而不是暴露底层块 API。

推荐 actions：

- `replace`
- `insert_after`
- `insert_before`
- `append`
- `delete`
- `table_edit`

`replace_range` 和 `replace_section` 不单独作为 action。替换章节只是 range replace 的一个特例：用 `start_index/start_id` 和 `end_index/end_id` 定位范围即可。`end` 为闭区间。

### 参数结构

统一使用一个工具 + action 分发。不同 action 使用不同必需参数，但外层结构保持一致。

示例：

```json
{
  "document": "/存储芯片行业研究报告/芯片/澜起科技（688008）深度研究报告",
  "action": "replace",
  "start_index": 87,
  "start_id": "20260602150643-bgjckyt",
  "end_index": 96,
  "end_id": "20260602150643-xxxxxxx",
  "markdown": "...",
  "confirmed": true
}
```

按 action 的必需参数：

- `replace`：`document`、`start_index`、`start_id`、`markdown`、`confirmed`；范围替换时还需要 `end_index`、`end_id`。
- `insert_after` / `insert_before`：`document`、`start_index`、`start_id`、`markdown`、`confirmed`。
- `append`：`document`、`markdown`、`confirmed`。
- `delete`：`document`、`start_index`、`start_id`、`confirmed`；范围删除时还需要 `end_index`、`end_id`。
- `table_edit`：`document`、`start_index`、`start_id`、`table_edit`、`confirmed`。

安全校验：

1. `document` 必须唯一定位文档。
2. `start_id` 必须存在。
3. `start_index` 必须与引用阅读中的全局块序号一致。
4. 范围操作需要同时校验 `end_id` 和 `end_index`。
5. `replace` / `delete` 的范围必须连续。
6. `replace` 遇到复杂块类型时拒绝，并提示拆分处理。
7. `delete` 可以删除附件、图片、数据库占位块、超级块等特殊块。

### table_edit

表格编辑单独作为 action，命名为 `table_edit`，而不是 `table`。`table` 作为 action 名过于模糊，不利于 AI 理解。

目标：避免每次修改表格都重写整张 Markdown 表。

支持操作：

- `set_cell`：修改单元格。
- `insert_row_before`：在指定行前插入一行。
- `insert_row_after`：在指定行后插入一行。
- `delete_row`：删除指定行。

示例：

```json
{
  "document": "/存储芯片行业研究报告/芯片/澜起科技（688008）深度研究报告",
  "action": "table_edit",
  "start_index": 88,
  "start_id": "table-block-id",
  "table_edit": {
    "operation": "set_cell",
    "row": 3,
    "column": "当前值",
    "value": "232.30",
    "expected_old_value": "~260~280"
  },
  "confirmed": true
}
```

`row` 使用 1-based 数据行编号，不包含表头。列优先使用列名；列名不唯一或不清晰时使用 `column_index`。

### 错误信息

错误信息要清晰告诉 AI：

- 哪个校验失败。
- 当前文档是否可能已被修改。
- 需要重新调用哪种 read。
- 如果是复杂块拒绝替换，应该如何拆分处理。

例如：

```text
目标块校验失败：start_index=87 对应的当前块 ID 是 xxx，但请求中的 start_id 是 yyy。
文档可能在上次读取后发生变化。请重新调用 siyuan_read(include_block_ids=true)，并启用引用阅读后再编辑。
```

### 第一版实现状态

`siyuan_edit` 当前已实现 `single_block_replace`、`multi_block_replace`、`insert_after`、`insert_before`、`append`、`delete`、`table_edit`。其中 `table_edit` 只支持普通 Markdown 表格；数据库/属性视图仍保持只读。

旧的 exact text anchor 编辑入口已经移除，当前统一使用 `siyuan_edit`。
