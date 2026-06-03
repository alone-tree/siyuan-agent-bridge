# table_edit 下一版设计决策

日期：2026-06-03

## 背景

真实引用阅读测试显示，当前 `siyuan_read_document(include_block_ids=true)` 会把普通 Markdown 表格按原始 Markdown 展示，包括 `| --- | --- |` 分隔行。这符合 Markdown 文件阅读习惯，但不利于 AI 直接判断可编辑行号，容易把分隔行误认为数据行。

普通 Markdown 表格不是数据库/属性视图，不需要把表头、字段、列名设计成另一套多维表语义。对 AI 最稳定的模型是二维网格：先用引用阅读定位表格块，再用 `row` + `column_index` 定位单元格。

## 引用阅读表格视图

普通阅读继续保留原始 Markdown，避免影响日常总结、复制和改写体验。

引用阅读中的普通 Markdown 表格块改为编辑坐标网格，而不是原始 Markdown 表格。

示例：

```text
[41] id=20260602204109-89wob5o type=table rows=4 columns=4

| row_index | col 1 | col 2 | col 3 | col 4 |
| row 0 | 指标 | 重构前 | 重构后 | 变化 |
| row 1 | 注册完成率 | 64.3% | 79.1% | +14.8pp |
| row 2 | 首单转化率 | 31.2% | 34.9% | +3.7pp |
```

这个坐标网格不是合法 Markdown 表格，不需要 `| --- | --- |` 分隔行。它是给 AI 的编辑坐标视图，目的是减少分隔行造成的行号歧义。

## 坐标规则

- `row=0` 表示表头行。
- `row>=1` 表示数据行。
- `column_index>=1` 表示列号。
- Markdown 分隔行由工具解析和渲染，不参与计数。
- 新工作流优先使用 `column_index`。
- 旧的 `column` 参数可保留兼容，但不作为推荐入口。

## table_edit 操作

`table_edit.operation` 精简为五个：

- `set_cell`
- `insert_row`
- `delete_row`
- `insert_column`
- `delete_column`

## set_cell 同时支持单个和多个单元格

不新增 `set_cells`。`set_cell` 输入 `cell` 时修改一个单元格；输入 `cells` 数组时一次修改多个单元格。这样保持 action 数量精简，同时允许一次快照、一次表格重写完成相关单元格更新。

单个单元格：

```json
{
  "operation": "set_cell",
  "cell": {
    "row": 1,
    "column_index": 3,
    "value": "80.0%",
    "expected_old_value": "79.1%"
  }
}
```

多个单元格：

```json
{
  "operation": "set_cell",
  "cells": [
    {"row": 1, "column_index": 3, "value": "80.0%", "expected_old_value": "79.1%"},
    {"row": 1, "column_index": 4, "value": "+15.7pp", "expected_old_value": "+14.8pp"}
  ]
}
```

## 行列插入

插入行：

```json
{
  "operation": "insert_row",
  "row": 2,
  "position": "before",
  "values": ["平均注册耗时", "127s", "43s", "-66%"]
}
```

插入列：

```json
{
  "operation": "insert_column",
  "column_index": 2,
  "position": "after",
  "values": ["备注", "已验证", "待复查"]
}
```

列插入的 `values[0]` 对应 `row 0` 表头，其后依次对应数据行。少于现有行数时补空；多于现有行数时拒绝。

## 暂不支持批量插入多行或多列

第一版暂不支持一次插入多行或多列。

批量单元格修改风险低且需求高；批量插入多行/多列会引入位置移动、二维 `values` 形状校验和 AI 参数组织复杂度。第一版先保持单行/单列插入。

## 2026-06-03 实现状态

已实现：

- 引用阅读中的普通 Markdown 表格块渲染为坐标网格，且不包含 Markdown 分隔行。
- 普通阅读仍保留原始 Markdown 表格。
- `set_cell` 支持 `cell` 单个单元格、`cells` 多个单元格，并兼容旧版顶层 `row/column/value/expected_old_value`。
- `row=0` 可编辑表头，`row>=1` 编辑数据行。
- 新增 `insert_row`、`insert_column`、`delete_column`。
- 保留旧 `insert_row_before` / `insert_row_after` 作为兼容 alias。
- `delete_column` 拒绝删除最后一列。
- 插入列的 `values[0]` 对应表头，其后对应数据行；少于现有行数补空，多于现有行数拒绝。

验证：

```bash
pytest tests/ -q
# 156 passed
```
