# 阅读工具 Block Window 改造计划

## 目标

把 `siyuan_read_document` 从“按字符 chunk 阅读”为主，升级为“按思源展示块窗口阅读”为主。

核心目标：

1. 长文档按完整 block 连续分页，不从字符中间截断。
2. 大纲显示标题所在的 block 位置，方便 AI 选择后续阅读窗口。
3. 标题较少且文档很长时，补充原文窗口预览，避免 AI 无法判断该读哪一段。
4. `include_block_ids=true` 对外称为“引用阅读”，用于跨文档块引用、精确定位和后续编辑辅助。
5. 保留旧 `chunk/max_chars` 作为兼容路径或降级方案，但默认使用 block window。

## 不做的事情

1. 不实现复杂结构的精确编辑能力。
2. 不把完整块树 JSON 暴露给 AI 作为默认阅读结果。
3. 不引入外部 tokenizer 依赖。第一阶段使用轻量 token 估算器。
4. 不删除旧 `chunk/max_chars` 参数，避免破坏已有调用。

## 目标接口

`siyuan_read_document` 建议参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `document_id` | string | 必填 | 文档 ID，保持现有逻辑 |
| `chunk` | int? | `0` 或空 | 旧兼容参数。显式传入时走旧字符 chunk 路径 |
| `max_chars` | int? | 旧默认值 | 仅旧字符 chunk 路径使用 |
| `block_start` | int | `1` | 新 block window 起点，1-based |
| `block_limit` | int | `200` | 最多返回多少个展示块 |
| `token_budget` | int | `50000` 或 `80000` | 估算 token 上限，作为安全阀 |
| `include_block_ids` | bool | `false` | `true` 时进入引用阅读，插入块 ID 注释 |

兼容规则：

1. 如果用户显式传入 `chunk > 0`，继续走旧字符 chunk 逻辑。
2. 否则默认走 block window。
3. `include_block_ids=true` 不改变分页模型，只改变正文渲染方式：在对应展示块前插入 HTML 注释。

## 内部数据模型

新增内部展示块模型，建议命名为 `DisplayBlock`：

```python
@dataclass
class DisplayBlock:
    index: int
    id: str
    type: str
    subtype: str
    markdown: str
    estimated_tokens: int
    is_heading: bool
    heading_level: int | None
    heading_text: str
```

注意：

1. `index` 是展示块序号，不是思源 `sort`。
2. 展示块只包含 AI 实际会看到的文本块。
3. 列表项、表格等如果自身 Markdown 已包含子内容，不再递归渲染子孙，避免重复。
4. 超级块、列表容器等结构容器通常不作为普通展示文本，但需要继续递归其子块。

## 块遍历策略

使用 `/api/block/getChildBlocks`，不要依赖 SQL `ORDER BY sort` 作为阅读顺序。

原因：

1. 真实长文档中同一父块下多个子块可能拥有相同 `sort`。
2. `getChildBlocks` 返回的是思源前端实际子块顺序，更适合阅读。

建议保留现有 `client.list_document_blocks()` 作为诊断或备用能力，但正常阅读使用 `client.get_child_blocks()`。

## Token 估算器

新增轻量函数 `estimate_token_count(text: str) -> int`。

第一阶段不要引入外部依赖，建议启发式：

1. CJK 字符：约 `1.0 token / 字`
2. 拉丁单词：约 `1.3 token / word`
3. 数字串：约 `0.8 token / item`
4. 标点和其他符号：约 `0.4 token / char`

用途：

1. 计算每个 `DisplayBlock.estimated_tokens`。
2. 生成当前窗口时，超过 `token_budget` 则停在块边界。
3. 返回头部显示当前窗口估算 token 数。

约束：

1. 至少返回一个块，即使单块超过 `token_budget`。
2. 估算只是安全阀，不需要追求模型级 tokenizer 精度。

## 阅读返回格式

新默认返回结构仍然是 Markdown 文本，不改成 JSON。

建议头部包含：

```text
文档: /路径/标题
ID: 2026...
展示块: 1-200 / 278
估算 tokens: 43800 / 50000
下一窗口: block_start=201, block_limit=200
阅读模式: 普通阅读
```

引用阅读时：

```text
阅读模式: 引用阅读（已插入块 ID 注释）
```

正文块 ID 注释示例：

```markdown
<!-- siyuan:block id=20260503093754-xc5t981 type=p -->
这里是原文段落。
```

## 大纲策略

大纲从 `DisplayBlock` 中的标题块生成，而不是再从最终 Markdown 字符位置反推。

大纲示例：

```text
大纲：
- block 3: # 第一章
- block 42: ## 关键结论
- block 118: ## 详细分析
```

如果标题数量足够，直接展示大纲即可。

## 窗口预览策略

只有同时满足以下条件时，才返回窗口预览：

1. 标题数量少于 5 个。
2. 总展示块数超过 100。

预览规则：

1. 每隔 50 个展示块取一个样本：`1, 51, 101, 151...`
2. 每个样本取该块开头一小句，或前 `40-80` 个字符。
3. 不调用 AI 总结，不生成解释性摘要，只返回原文片段。
4. 返回前明确说明原因。

示例：

```text
本文档标题较少，因此抽取每 50 个块的开头片段帮助选择阅读窗口：
- block 1: 2026 年 4 月 29 日下午 1:30...
- block 51: 我们在本季度继续看到云业务...
- block 101: 资本开支主要集中在数据中心...
```

如果标题不少于 5 个，或总展示块数不超过 100，不显示窗口预览。

## 实现步骤

### 1. 重构阅读块构建

修改 `source_code/mcp_server.py`：

1. 增加 `DisplayBlock` 数据结构。
2. 增加 `build_display_blocks(client, root_id, include_block_ids=False)` 或类似函数。
3. 统一普通阅读和引用阅读的块遍历逻辑。
4. 保留已有复杂结构处理规则：列表项和表格避免重复，超级块递归子块。

### 2. 增加 token 估算

修改 `source_code/mcp_server.py` 或拆到独立模块：

1. 增加 `estimate_token_count(text)`。
2. 在构建 `DisplayBlock` 时计算 token。
3. 在窗口选择时用 `token_budget` 截断。

建议优先放在 `mcp_server.py`，如果后续复用再拆模块。

### 3. 增加 block window 参数

修改 `siyuan_read_document` 工具 schema 和函数签名：

1. 增加 `block_start`。
2. 增加 `block_limit`。
3. 增加 `token_budget`。
4. 保留 `chunk/max_chars/include_block_ids`。

参数校验保持简洁：

1. `block_start < 1` 时按 `1`。
2. `block_limit` 建议 clamp 到 `1-1000`。
3. `token_budget` 建议 clamp 到 `1000-200000`。

### 4. 返回大纲和窗口预览

修改阅读结果组装逻辑：

1. 大纲显示标题对应的展示块编号。
2. 标题少于 5 个且总展示块超过 100 时，增加窗口预览。
3. 当前窗口之外的大纲仍然保留完整文档大纲，方便跳转。

### 5. 保留旧 chunk 路径

旧路径建议暂时不删除：

1. 如果 `chunk > 0`，使用旧 `split_markdown_chunks`。
2. 如果用户没有传 `chunk`，使用新 block window。
3. README 和 Skill 应引导新用法，不鼓励继续使用 chunk。

### 6. 更新文档和 Skill

需要更新：

1. `PRO.md`：记录实现结果和最终参数默认值。
2. `README.md` / `README.en.md`：同步 `siyuan_read_document` 新参数。
3. `plugins/siyuan-agent-bridge/skills/siyuan-agent-bridge/SKILL.md`：提示 AI 默认用 block window；需要引用时开启引用阅读。
4. 如有工具说明集中定义，也同步更新。

## 测试计划

### 单元测试

修改 `tests/test_mcp_server.py`：

1. `estimate_token_count` 对中文、英文、混合文本有基本覆盖。
2. `build_display_blocks` 使用 `getChildBlocks` 返回顺序，不依赖 SQL `sort`。
3. 默认阅读返回 `展示块: 1-... / total`。
4. `block_start` 能从指定展示块开始。
5. `block_limit` 能限制展示块数量。
6. `token_budget` 在块边界截断，并至少返回一个块。
7. 标题少于 5 且总块数超过 100 时返回窗口预览。
8. 标题不少于 5 时不返回窗口预览。
9. 总块数不超过 100 时不返回窗口预览。
10. `include_block_ids=true` 返回引用阅读说明和块 ID 注释。
11. `chunk > 0` 仍走旧兼容路径。

修改 `tests/test_client.py`：

1. 保留 `get_child_blocks` 相关测试。
2. 如果新增客户端方法，再补测试。

### 真实 MCP 测试

实现后重启 MCP，至少测试这些文档类型：

1. 短文档：确认不会出现多余窗口预览。
2. 标题丰富的长文档：确认大纲足够，且不出现窗口预览。
3. 标题很少的长文档：确认出现每 50 块原文预览。
4. 复杂结构文档：确认超级块、列表、表格没有明显重复或乱序。
5. 引用阅读：确认块 ID 注释与正文相邻，能用于 `((block_id))` 引用。

## 验收标准

1. `pytest tests/ -v` 全部通过。
2. 默认 `siyuan_read_document` 不再按字符 chunk 截断长文档。
3. 长文档返回可继续阅读的 `block_start` 参数。
4. 大纲中的标题显示 block 位置。
5. 低标题密度长文档返回窗口预览。
6. `include_block_ids=true` 被描述为引用阅读。
7. 旧 `chunk/max_chars` 调用不被破坏。
8. 文档和 Skill 同步更新。

## 给执行 AI 的提示词

你要在 `D:\Github\siyuan-agent-bridge` 中实现阅读工具的 Block Window 改造。请先阅读 `PRO.md` 中“问题 1：长文档分段 — Chunk vs Block Window”和本计划文件，再修改代码。目标是让 `siyuan_read_document` 默认按展示块窗口返回内容，新增 `block_start`、`block_limit`、`token_budget` 参数；保留旧 `chunk/max_chars` 兼容路径；`include_block_ids=true` 对外称为“引用阅读”。阅读大纲需要显示标题所在的 block 位置。只有当标题少于 5 个且总展示块数超过 100 时，才每隔 50 个块抽取原文开头片段作为窗口预览，不能用总结。使用 `/api/block/getChildBlocks` 的真实顺序构建展示块，不要依赖 SQL `sort` 作为阅读顺序。实现后更新 `PRO.md`、README、Skill 文档，并补充单元测试，最后运行 `pytest tests/ -v`。
