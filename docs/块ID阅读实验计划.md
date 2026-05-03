# 块 ID 阅读实验计划

## 背景

当前 `siyuan_read_document` 的读取路径是：

```text
siyuan_read_document
  -> resolve_visible_document()
  -> SiYuanClient.export_markdown()
  -> /api/export/exportMdContent
  -> MCP server 添加文档头、大纲、chunk 信息
  -> 返回 Markdown 给 AI
```

这个方案阅读体验干净，但只返回文档 ID，不返回文档内每个块的 ID。对普通阅读、搜索、总结已经足够；但如果要研究写入工具是否能更精确，就需要实验性地把块 ID 暴露给 AI，观察它对复杂文档和简单文档分别有什么帮助。

本计划只做“读取增强实验”，不直接扩展写入能力。实验结论用于决定后续是否升级 `siyuan_edit_document`。

## 实验目标

1. 让 `siyuan_read_document` 在可选模式下返回块 ID。
2. 用同一篇复杂文档对比“纯 Markdown 读取”和“带块 ID 读取”的差异。
3. 选一篇结构简单的普通文档做同样对比。
4. 判断块 ID 是否能帮助 AI 识别：
   - 普通段落、标题、列表项、表格、空块等块边界。
   - 超级块/布局/数据库这类复杂结构是否仍然不可见。
   - 编辑工具是否可以更可靠地选择目标块。
5. 根据实验结果给出后续写入工具升级建议。

## 非目标

- 不在本轮实现多块编辑。
- 不在本轮实现块级 CRUD 工具。
- 不把块 ID 默认加到所有读取结果里。
- 不承诺保留超级块、数据库、复杂排版的原生结构。
- 不修改用户思源笔记内容。

## 关键问题

实验需要回答这些问题：

1. 块 ID 放在 Markdown 里是否会明显干扰 AI 阅读？
2. 块 ID 能否稳定对应到 AI 看到的段落、标题、列表项、表格？
3. 对复杂文档，块 ID 是否能暴露出更多有用信息，还是只会增加噪音？
4. 对简单文档，块 ID 是否足以支持更精确的单块编辑？
5. 当前 `siyuan_edit_document` 的文本锚点匹配，是否可以借助块 ID 避免列表容器块和列表项块重复匹配？
6. 如果未来支持多块编辑，块 ID 能否帮助判断“这些块是连续普通文本块”？

## 建议方案

### 工具参数

在 `siyuan_read_document` 增加一个可选参数：

```text
include_block_ids: bool = false
```

默认仍为 `false`，保持现在的纯 Markdown 阅读体验。

当 `include_block_ids=true` 时，返回带块 ID 注释的实验性 Markdown。

### 返回格式

优先使用 HTML 注释，不把 ID 混入可见正文：

```markdown
<!-- siyuan:block id=20260503102357-abc123 type=h subtype=h2 -->
## 合并

<!-- siyuan:block id=20260503102358-def456 type=p -->
思源支持将若干块合并为一个超级块，支持水平和垂直合并
```

原因：

- Markdown 渲染时注释不可见。
- AI 仍能读到注释内容。
- 不破坏原正文。
- 后续如果要引用块 ID，AI 可以直接提取。

不要使用这种可见格式：

```markdown
[block:20260503102357-abc123] 正文
```

它会污染文本锚点，也会干扰 AI 对原文的引用。

### 注释字段

第一版建议包含：

```text
id
type
subtype
```

可选包含：

```text
parent_id
sort
```

第一版不建议加入太多字段。字段越多，阅读噪音越大。`id/type/subtype` 足以完成初步判断。

## 实现路线

### 第 1 步：补充客户端能力

在 `source_code/client.py` 增加一个只读方法：

```python
def list_document_blocks(self, doc_id: str) -> list[dict[str, Any]]:
    ...
```

内部先用 SQL：

```sql
SELECT id, parent_id, root_id, type, subtype, markdown, content, sort
FROM blocks
WHERE root_id = '<doc_id>'
  AND type != 'd'
ORDER BY sort
```

注意：

- 这是只读 SQL。
- 查询前仍要通过 `ensure_notebooks_open` 打开目标笔记本。
- 不要暴露任意 SQL 给 AI。
- 先保留 `markdown` 为空的块，因为空块本身就是实验对象。

### 第 2 步：增加块 ID 渲染函数

在 `source_code/mcp_server.py` 增加一个内部函数，例如：

```python
def render_markdown_with_block_ids(markdown: str, blocks: list[dict[str, Any]]) -> str:
    ...
```

这个函数是本实验最关键的不确定点。不要一开始就追求完美对齐，可以先做保守版本：

1. 遍历 `blocks`。
2. 跳过明显不适合直接映射的容器块。
3. 对每个块的 `markdown` 做 `strip()`。
4. 如果这段文本能在导出的 `markdown` 中唯一找到，就在它前面插入注释。
5. 如果找不到或命中多次，暂时不插入注释，但统计到报告里。

这样做的好处是：不会因为复杂结构对齐失败而污染整个文档。

### 第 3 步：定义可注入块类型

第一版建议优先注入：

| type | subtype | 说明 |
|------|---------|------|
| `h` | `h1`/`h2`/`h3`... | 标题 |
| `p` | 空或普通 subtype | 普通段落 |
| `t` | 空 | 表格，谨慎注入 |
| `i` | `u`/`o` | 列表项，谨慎注入 |

第一版建议跳过：

| type | 原因 |
|------|------|
| `l` 列表容器 | 容器 Markdown 往往包含整个列表，会和子项重复 |
| `d` 文档块 | 已经有 Document ID |
| markdown 为空且 content 为空的块 | 暂时无法稳定插入，先统计 |

列表项是否注入需要通过实验判断。可以先做两种输出：

1. 只注入标题 + 普通段落。
2. 注入标题 + 普通段落 + 列表项。

对比哪种更适合 AI 阅读和编辑。

### 第 4 步：扩展 MCP schema

在 `siyuan_read_document` 的 tools schema 中增加：

```json
{
  "include_block_ids": {
    "type": "boolean",
    "default": false,
    "description": "Experimental. Include HTML comments with SiYuan block IDs before matched Markdown blocks. Use only when precise block reference or edit diagnostics are needed."
  }
}
```

工具 description 也需要加一句：

```text
By default returns clean Markdown. Set include_block_ids=true only for precise block reference or edit diagnostics.
```

### 第 5 步：保持 chunk 逻辑

带块 ID 模式仍然要走现有 chunk 逻辑：

```text
export markdown
-> optional inject block comments
-> extract attachments
-> split chunks
-> build outline
```

注意顺序：

- 先注入块 ID，再 split chunk。
- 大纲仍然从带注释的 Markdown 中提取标题，但正则应不受注释影响。
- 字数统计可以继续按完整返回文本统计，也可以只统计原始 Markdown。建议第一版保持现状，不额外优化。

## 实验样本

### 样本 A：复杂文档

文档：

```text
一个新的笔记本 / 一个结构复杂的文档
Document ID: 20260503102357-gio646r
```

它包含：

- 超级块
- 水平合并
- 垂直合并
- 嵌套超级块
- 表格
- 图片
- 嵌套无序列表
- 嵌套有序列表
- 空块
- 数据库/属性视图

对它分别调用：

```text
siyuan_read_document(document_id="20260503102357-gio646r", max_chars=12000)
siyuan_read_document(document_id="20260503102357-gio646r", max_chars=12000, include_block_ids=true)
```

观察：

- 哪些段落前成功出现块 ID？
- 超级块本身有没有被显示出来？
- 水平/垂直布局是否仍然只是被压平？
- 表格前是否能标注块 ID？
- 列表项 ID 是否有用，还是产生噪音？
- 数据库是否仍然只是普通 Markdown 表格？
- 空块是否能被识别？

### 样本 B：简单文档

选择一篇结构简单、只包含标题和普通段落的文档。建议从当前测试工作空间中选一篇之前创建的测试文档，或者新建一个只读样本后再读取。

选择标准：

- 3 到 8 个段落。
- 最好有二级标题。
- 不包含表格、图片、数据库、超级块。
- 不包含复杂列表。

对它分别调用：

```text
siyuan_read_document(document_id="<simple_doc_id>", max_chars=12000)
siyuan_read_document(document_id="<simple_doc_id>", max_chars=12000, include_block_ids=true)
```

观察：

- 块 ID 是否几乎能一一对应到 AI 看到的段落？
- 输出是否仍然易读？
- AI 能否根据块 ID 明确指出“要改哪一段”？
- 对单块编辑是否比文本锚点更可靠？

## 评估表

实施后写一份实验报告，至少包含这张表：

| 维度 | 复杂文档 | 简单文档 | 结论 |
|------|----------|----------|------|
| 阅读干扰 | | | |
| 块 ID 覆盖率 | | | |
| 标题识别 | | | |
| 普通段落识别 | | | |
| 列表识别 | | | |
| 表格识别 | | | |
| 空块识别 | | | |
| 数据库识别 | | | |
| 超级块/布局识别 | | | |
| 对编辑工具的帮助 | | | |

还需要记录：

```text
导出 Markdown 总块数
SQL 查询块数
成功注入块 ID 数
跳过块数
跳过原因分类
```

## 对编辑工具的可能启发

根据实验结果，可能出现三种结论。

### 结论 A：块 ID 对简单文档非常有效

如果简单文档中标题和段落都能稳定注入块 ID，可以考虑后续给 `siyuan_edit_document` 增加可选参数：

```text
block_id: str | None = None
```

语义：

- 有 `block_id` 时，优先精确编辑该块。
- 没有 `block_id` 时，继续使用 `old_text` 文本锚点。
- `block_id` 必须属于 `document_id` 对应文档。
- 即使有 `block_id`，仍要求 `old_text` 能在该块内匹配，避免 AI 拿旧 ID 误改。

这会形成更安全的双重确认：

```text
目标块 ID 正确 + old_text 仍匹配当前块内容 -> 允许编辑
```

### 结论 B：复杂文档中块 ID 有部分帮助，但不能还原结构

如果超级块、数据库、复杂列表仍然无法可靠表示，保持当前产品边界：

- 复杂文档可以读。
- 复杂结构可以总结。
- 普通段落可以小改。
- 不承诺保留复杂排版。
- 大改时新建草稿文档。

这时块 ID 的价值主要是“帮编辑工具避开复杂块”，不是“支持复杂块编辑”。

### 结论 C：块 ID 噪音大于收益

如果注入后阅读明显混乱，或者块 ID 与 Markdown 段落对应关系不稳定，则不要继续推进默认阅读增强。最多保留一个诊断工具，例如：

```text
siyuan_inspect_document_blocks(document_id)
```

它返回结构化块列表，专门用于调试，不进入普通阅读流。

## 后续可能的工具设计

本轮实验后再决定是否做以下能力。

### 方案 1：继续只用 `siyuan_read_document`

只增加 `include_block_ids` 参数。

优点：

- 工具数量不增加。
- AI 心智简单。

缺点：

- 普通阅读工具承担了诊断职责。

### 方案 2：新增只读诊断工具

新增：

```text
siyuan_inspect_document_blocks(document_id, max_blocks?)
```

返回结构化块列表：

```markdown
# Block Inspection: /path

| # | id | type | subtype | parent | markdown preview |
|---|----|------|---------|--------|------------------|
```

优点：

- 普通阅读保持干净。
- 诊断复杂结构更清楚。

缺点：

- 工具数量增加。
- AI 需要知道什么时候调用。

建议：先实现方案 1 做实验。只有当 `include_block_ids` 显得不适合混在阅读工具里，再考虑方案 2。

## 测试要求

### 单元测试

新增或更新 `tests/test_mcp_server.py`：

1. `include_block_ids` 默认为 false，旧输出不变。
2. `include_block_ids=true` 时会插入 HTML 注释。
3. 同一段 Markdown 多次出现时不注入，避免错位。
4. 列表容器块默认跳过。
5. 空块不会导致异常。
6. chunk 模式下块 ID 注释不会破坏 chunk 输出。

新增或更新 `tests/test_client.py`：

1. `list_document_blocks()` SQL 返回结构正确。
2. 空返回时返回空 list。
3. 非 list 响应抛出清晰错误。

### 真实 MCP 测试

必须在测试工作空间中完成：

1. `siyuan_start`
2. 读取复杂文档纯 Markdown。
3. 读取复杂文档带块 ID。
4. 读取简单文档纯 Markdown。
5. 读取简单文档带块 ID。
6. 写实验报告，记录上面的评估表。

本轮不调用写入工具。

## 风险与处理

| 风险 | 处理 |
|------|------|
| 导出 Markdown 与 blocks 表无法稳定对齐 | 只对唯一匹配的块注入；其余跳过并统计 |
| 列表容器和列表项重复 | 第一版跳过 `type='l'`；列表项是否注入由实验判断 |
| 数据库导出信息不足 | 记录为能力边界，不尝试通过 Markdown 还原数据库 |
| 超级块结构不可见 | 记录为能力边界，不承诺复杂布局编辑 |
| 块 ID 干扰 AI 阅读 | 默认关闭，只在实验/诊断时启用 |
| AI 误用 block_id 写入 | 后续如支持 block_id 编辑，也必须同时校验 document_id 和 old_text |

## 实施顺序

1. 增加 `SiYuanClient.list_document_blocks()`。
2. 增加 `render_markdown_with_block_ids()`，只做唯一匹配注入。
3. 给 `siyuan_read_document` 增加 `include_block_ids` 参数。
4. 更新 MCP tool schema 和 description。
5. 补单元测试。
6. 运行 `pytest tests/ -v`。
7. 重启 MCP。
8. 对复杂文档和简单文档做真实读取对比。
9. 写实验报告。
10. 根据报告决定是否升级 `siyuan_edit_document`。

## 成功标准

实验成功不等于块 ID 必须上线。成功标准是：

1. 能明确看到块 ID 对简单文档是否有帮助。
2. 能明确看到复杂文档的哪些结构仍然无法通过块 ID 解决。
3. 能决定后续写入工具是否需要 `block_id` 可选参数。
4. 不破坏默认 `siyuan_read_document` 的阅读体验。
5. 不引入任何写入风险。
