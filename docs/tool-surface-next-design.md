# 工具面下一版设计决策

日期：2026-06-03

## 背景

`siyuan_edit` 已经成为新的结构化编辑入口，旧的 exact text anchor 和 Guide 专用写入工具逐渐不再承担核心工作流。下一步需要减少工具数量、统一命名，并把文档级文件操作和权限模型补齐。

## 删除不再需要的工具

计划移除：

- `siyuan_edit_document`
- `siyuan_propose_guide_update`
- `siyuan_apply_guide_update`

理由：

- `siyuan_edit` 已覆盖普通文档编辑的主要场景，并且基于引用阅读的 block index + block id 校验，比 `old_text -> new_text` 更稳定。
- Guide 更新可以回归普通文档编辑流程：通过系统笔记本文档路径读取，再用 `siyuan_edit` 修改。
- 删除专用 Guide propose/apply 工具可以减少 AI 的工具选择负担，避免“同样是写文档，不知道用哪个工具”的分叉。

兼容策略：

- 若担心已有客户端或旧 Skill 仍调用这些工具，可以先在一个小版本中标记 deprecated，并更新 Skill/README；下一版本再删除。
- 若当前目标是尽快精简工具面，也可以直接删除，同时更新所有工具说明、测试和文档。

## 统一工具名称

命名方向：去掉不必要的 `document` 后缀，让工具名称更短、更像面向用户的动作。

计划调整：

- `siyuan_read_document` -> `siyuan_read`
- `siyuan_create_document` -> `siyuan_create`
- `siyuan_find_documents` -> `siyuan_find`
- `siyuan_refresh_index` 可考虑保留，因为它操作的是安全索引，不是普通文档。
- `siyuan_list`、`siyuan_start`、`siyuan_edit` 保持不变。

设计原则：

- 工具名表达用户意图，不暴露底层对象名。
- 对普通 AI 使用者而言，“read / find / edit / create / list” 已足够明确。
- 参数和工具描述中继续明确目标是 SiYuan 文档，避免歧义。

兼容策略：

- 如果 MCP 客户端不支持 alias，可在过渡期同时暴露新旧名称，旧名称描述中标记 deprecated。
- 如果要最大化精简工具数量，则直接改名并同步更新 Skill、README、测试和安装说明。

## 新增文档文件操作工具

需要提供文档级文件操作能力：

- 修改文档名称
- 移动文档位置
- 删除某篇文档

建议新增一个聚合工具，而不是拆成多个工具：

```text
siyuan_file
```

示例 actions：

- `rename`
- `move`
- `delete`

理由：

- 这些操作都属于文档树/文件管理，不是内容编辑。
- 聚合在一个工具中能减少工具数量，同时保持操作语义清晰。
- 删除、移动、重命名都属于较高风险操作，应统一走权限检查和确认机制。

安全要求：

- 必须 `confirmed=true`。
- 执行前创建 SiYuan 工作空间快照。
- 隐藏文档不可操作。
- 只读文档不可操作。
- `read_write` 权限文档才允许 rename / move / delete。
- 删除文档需要在返回信息中明确提示可通过 SiYuan 快照手动恢复。

是否把 create 也放入 `siyuan_file`：

- 暂不建议。`siyuan_create` 是内容写入入口的一部分，和 `siyuan_edit` 关系更近。
- `rename / move / delete` 是文档树管理入口，适合聚合。

## 细化权限控制

当前隐私规则只有隐藏/展示两档。下一版需要变成三档：

- `hidden`：AI 不可搜索、不可读取、不可编辑、不可移动、不可删除。
- `read_only`：AI 可搜索、可读取，不可修改。写入、删除、移动位置、重命名都算修改。
- `read_write`：AI 可搜索、可读取、可修改。具体写入仍需用户明确要求和 `confirmed=true`。

核心逻辑保持不变：

- 权限由用户在 SiYuan 系统笔记本中的 Privacy Rules 文档维护。
- MCP server 内部解析权限规则。
- AI 不可读取、搜索或编辑 Privacy Rules 文档。
- 所有索引导出、搜索结果、读取和写入前都先经过权限过滤。

推荐规则模型：

```text
permission = hidden | read_only | read_write
```

兼容旧规则：

- 旧的 `Hide=yes` 映射为 `hidden`。
- 旧的 `Hide=no` 映射为 `read_write`。
- 新增 `Permission` 列后，优先读取 `Permission`；没有该列时走旧 `Hide` 兼容逻辑。

权限检查矩阵：

| 操作 | hidden | read_only | read_write |
|------|--------|-----------|------------|
| list/search/index | no | yes | yes |
| read | no | yes | yes |
| create under notebook/path | no | no | yes |
| edit content | no | no | yes |
| rename | no | no | yes |
| move | no | no | yes |
| delete | no | no | yes |

补充规则：

- 若父路径或笔记本为 `hidden`，子文档全部隐藏。
- 若父路径或笔记本为 `read_only`，子文档默认只读，除非更具体的规则显式提升为 `read_write`。是否允许“子规则提升权限”需要单独确认；保守方案是不允许从父级只读提升。
- 若文档被多个规则命中，默认采用更严格权限：`hidden > read_only > read_write`。

## 实施顺序建议

1. 先实现权限模型扩展，但保持旧 Privacy Rules 兼容。
2. 再新增 `siyuan_file`，让 rename / move / delete 统一走新权限检查。
3. 再改工具命名和删除旧工具，避免同时改变权限、工具名和行为导致排查困难。
4. 最后更新 Skill、README、安装说明和测试。
