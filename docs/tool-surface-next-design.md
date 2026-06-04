# 工具面下一轮设计决策

日期：2026-06-03

状态：工具删除、命名统一、文档级管理工具和权限模型第一版均已实现。

## 背景

`siyuan_edit` 已成为新的结构化编辑入口，旧的 exact text anchor 工具和 Guide 专用写入工具不再承担核心工作流。下一步目标是减少工具数量、统一命名，并继续补齐文档级文件操作和权限模型。

## 已完成：删除不必要工具

已从 MCP 工具面移除：

- `siyuan_edit_document`
- `siyuan_propose_guide_update`
- `siyuan_apply_guide_update`

理由：

- `siyuan_edit` 覆盖普通文档编辑的主要场景，并且基于引用阅读的 block index + block id 校验，比 `old_text -> new_text` 更稳定。
- Guide 更新回归普通文档编辑流程：通过系统笔记本文档路径读取，再用 `siyuan_edit` 修改。
- 删除专用 Guide propose/apply 工具可以减少 AI 的工具选择负担，避免“同样是写文档，却不知道该用哪个工具”的分叉。

实现策略：

- 当前开发版直接删除旧工具入口，不暴露 deprecated alias。
- 同步更新 Skill、README、测试和当前产品说明。

## 已完成：统一工具命名

已改名：

- `siyuan_find_documents` -> `siyuan_find`
- `siyuan_read_document` -> `siyuan_read`
- `siyuan_create_document` -> `siyuan_create`

保持不变：

- `siyuan_start`
- `siyuan_refresh_index`
- `siyuan_list`
- `siyuan_edit`

设计原则：

- 工具名贴近 AI 和用户意图，不暴露底层资源分类。
- 对通用 AI 使用者而言，`read / find / edit / create / list` 已经足够明确。
- 参数和工具说明中继续明确目标是 SiYuan 文档，避免语义漂移。

## 已完成：新增文档级管理工具

需要提供文档级文件操作：

- 修改文档名称
- 移动文档位置
- 删除某篇文档
- 复制文档
- 导出文档

已实现为一个综合工具：

```text
siyuan_doc_manage
```

actions：

- `rename`
- `move`
- `delete`
- `copy`
- `export`

理由：

- 这些操作属于文档树/文件管理，不是正文内容编辑。
- 综合成一个工具能减少工具数量，同时保留操作语义清晰。
- 删除、移动、重命名都属于较高风险操作，应统一走权限检查和确认机制。
- `copy` 和 `export` 属于读取派生操作，源文档只需可读；其中 `copy` 会创建新文档，仍需 `confirmed=true` 和写前快照。

安全要求：

- 必须 `confirmed=true`。
- 执行前创建 SiYuan 工作空间快照。
- 隐藏文档不可操作。
- `read_write` 权限的文档才允许 rename / move / delete。
- `read_only` 文档允许 copy / export，不允许 rename / move / delete。
- 删除文档需要在返回信息中明确提示可通过 SiYuan 快照手动恢复。

是否把 create 也并入 `siyuan_doc_manage`：

- 暂不建议。`siyuan_create` 是内容写入入口的一部分，和 `siyuan_edit` 关系更近。
- `rename / move / delete / copy / export` 是文档存在后的管理操作，适合聚合。

## 已完成：细化权限控制第一版

当前隐私规则只有隐藏/展示两档，下一步扩展为：

- `hidden`：AI 不可见，不可读取，不可编辑，不可移动，不可删除。
- `read_only`：AI 可见、可读取，但不可修改。写入、删除、移动位置、重命名都算修改。
- `read_write`：AI 可见、可读取、可修改。任何写操作仍需要用户明确要求和 `confirmed=true`。

核心逻辑保持不变：

- 权限由用户在 SiYuan 系统笔记本中的 Privacy Rules 文档维护。
- MCP server 内部解析权限规则。
- AI 不可读取、搜索或编辑 Privacy Rules 文档。
- 索引、搜索、读取、写入前都经过权限过滤。

推荐字段模型：

```text
permission = hidden | read_only | read_write
```

兼容旧规则：

- 旧的 `Hide=yes` 映射为 `hidden`。
- 旧的 `Hide=no` 映射为 `read_write`。
- 如果存在 `Permission` 列，优先读取 `Permission`；没有该列时走旧 `Hide` 兼容逻辑。

权限矩阵：

| 操作 | hidden | read_only | read_write |
|------|--------|-----------|------------|
| list/search/index | no | yes | yes |
| read | no | yes | yes |
| create under notebook/path | no | no | yes |
| edit content | no | no | yes |
| rename | no | no | yes |
| move | no | no | yes |
| delete | no | no | yes |
| copy | no | yes | yes |
| export | no | yes | yes |

开放问题：

- 如果路径父级笔记本为 `hidden`，其中文档全部隐藏。
- 如果路径父级笔记本为 `read_only`，其中文档默认只读，除非更具体的规则显式声明为 `read_write`。是否允许子规则突破父级只读需要再确认；保守方案是不允许突破父级只读。
- 如果文档命中多条规则，默认采用更严格权限：`hidden > read_only > read_write`。

## 实施顺序

1. 已完成工具删除和命名统一。
2. 已实现权限模型扩展第一版，兼容旧 Privacy Rules 格式。
3. 已新增 `siyuan_doc_manage`，把 rename / move / delete / copy / export 统一接入权限检查。
4. 最后更新 Skill、README、安装说明和测试。
