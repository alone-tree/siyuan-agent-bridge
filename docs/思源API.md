# 思源 API 能力地图

本文记录 SiYuan Agent Bridge 后续实现读写能力时可使用的思源 HTTP API。目标不是复刻完整 API 文档，而是说明这些端点在本项目中的用途、风险和 MCP 封装策略。

参考资料：

- SiYuan 官方 API 文档：https://github.com/siyuan-note/siyuan/blob/master/API.md
- Kernel API 社区文档：https://leolee9086.github.io/my-siyuan-dev-guide/kernel-api/

## 总体原则

思源 API 是底层能力集合，MCP 工具是面向 AI 的高层工作流。不要把思源端点逐个暴露给 AI。

本项目的封装原则：

1. AI 操作文档路径、块窗口和结构化编辑动作，不直接操作底层 SQL 或仓库快照。
2. MCP server 负责把引用阅读中的块序号 + 块 ID 校验为具体块操作。
3. 破坏性 API 不直接暴露给 AI。
4. 写入前必须创建思源工作空间快照。
5. 回滚第一阶段由用户手动完成，不提供 AI 自动 checkout 或 rollback 工具。

## 能力分层

| 能力层 | 代表端点 | 项目用途 | MCP 暴露策略 |
|--------|----------|----------|--------------|
| 系统 | `/api/system/version` | 连接检查、启动诊断 | 已通过 `siyuan_start` 间接使用 |
| 笔记本 | `/api/notebook/lsNotebooks`, `/api/notebook/openNotebook`, `/api/notebook/closeNotebook` | 枚举笔记本；搜索/索引前临时打开关闭笔记本 | 内部使用，不单独暴露 |
| 笔记本管理 | `/api/notebook/createNotebook`, rename/remove 类端点 | 创建、重命名、删除笔记本 | 不开放。笔记本管理是人工决策 |
| 文档树读取 | `/api/filetree/listDocsByPath`, `/api/filetree/getHPathByID`, `/api/filetree/getIDsByHPath` | 解析文档路径、结构和 ID | 内部使用或现有只读工具间接使用 |
| 文档创建 | `/api/filetree/createDocWithMd` | 创建新文档 | 暴露为 `siyuan_create` |
| 文档结构变更 | `/api/filetree/renameDocByID`, `/api/filetree/removeDocByID`, `/api/filetree/moveDocsByID`, `/api/filetree/duplicateDoc` | 重命名、删除、移动、复制文档 | 通过 `siyuan_doc_manage` 封装，写前快照 |
| 块读取 | `/api/block/getBlockKramdown`, `/api/block/getChildBlocks` | 读取块内容、构建块窗口、引用阅读定位 | 内部使用 |
| 块编辑 | `/api/block/updateBlock`, `/api/block/appendBlock`, `/api/block/insertBlock`, `/api/block/prependBlock` | 实现文档内增删改 | 只由 `siyuan_edit` 内部调用 |
| 块删除/移动 | `/api/block/deleteBlock`, `/api/block/moveBlock` | 删除或移动块 | 删除由 `siyuan_edit` 的 `delete` 动作封装；移动暂不开放 |
| 块 UI | fold/unfold 类端点 | 折叠、展开 | 不开放 |
| 属性 | `/api/attr/getBlockAttrs`, `/api/attr/setBlockAttrs` | 读取或设置块属性 | 暂不开放。后续可用于 AI 修改标记 |
| 搜索 | `/api/search/fullTextSearchBlock` | 全文搜索正文、标题和块 | 已作为 `siyuan_find` 的召回源 |
| SQL | `/api/query/sql` | 结构化读取 blocks 表、诊断、定位 | 内部使用，不开放任意 SQL |
| 导出 | `/api/export/exportMdContent` 等 | 读取文档 Markdown、导出资源 | 已用于阅读；不作为写入主路径 |
| 资源 | asset 上传、查询、OCR、清理类端点 | 图片、附件、资源管理 | 第一阶段不开放 |
| 仓库快照 | `/api/repo/createSnapshot`, `/api/repo/getRepoSnapshots` | 写入前备份；必要时帮助用户找到恢复点 | `createSnapshot` 内部强制使用；查询可后续做只读诊断 |
| 仓库恢复 | `/api/repo/checkoutRepo` | 恢复整个工作空间到某个快照 | 不暴露给 AI |
| 历史 | history rollback 类端点 | 文档/资源历史恢复 | 第一阶段不使用；只作为人工恢复参考 |
| 通知 | `/api/notification/pushMsg`, `/api/notification/pushErrMsg` | 写入完成或失败时通知用户 | 内部使用 |
| 同步/账号/设置/插件/集市 | sync、account、setting、bazaar、plugin 类端点 | 思源应用状态管理 | 不属于本项目范围 |

## 当前写入 API 组合

当前暴露三个会修改思源内容的 MCP 工具：

| MCP 工具 | 用户语义 | 内部 API 组合 |
|----------|----------|---------------|
| `siyuan_edit` | 在已有可见文档中替换、追加、删除、插入文本，或编辑普通 Markdown 表格 | 隐私检查；引用阅读定位校验；`repo/createSnapshot`；`block/updateBlock` / `appendBlock` / `insertBlock` / `deleteBlock`；`notification/pushMsg` |
| `siyuan_create` | 通过完整可读路径创建、覆盖或新增同名文档 | 隐私和路径检查；`repo/createSnapshot`；`filetree/createDocWithMd` 或 `block/deleteBlock` + `block/appendBlock`；`notification/pushMsg`；`filetree/getHPathByID` 等待路径同步 |
| `siyuan_doc_manage` | 管理文档树：改名、移动、删除、复制、导出 | 权限检查；`copy/export` 允许只读源文档；`rename/move/delete` 需可写；`move/delete` 会影响子树，写前扫描子孙权限；写操作调用 `repo/createSnapshot`；内部使用 `renameDocByID` / `moveDocsByID` / `removeDocByID` / `duplicateDoc` / `exportMdContent`；写后用 `getHPathByID` 确认路径同步 |

AI 不需要知道这些底层端点。它只提供：

```text
document
action
start_index
start_id
end_index/end_id（可选）
markdown 或 table_edit
confirmed
```

或：

```text
title
path
markdown
if_exists（可选：reject / overwrite / create_new）
confirmed
```

## 块树读取与块 ID 诊断视图

思源提供 `/api/block/getChildBlocks`，可按父块 ID 读取直接子块。官方说明中也明确：标题下方的块会被视为标题块的子块。这说明思源文档不是一张仅靠全局 `sort` 就能线性还原的表，而是由 `parent_id + sort` 共同决定阅读顺序的块树。

本项目的 `include_block_ids=true` 诊断视图采用 `/api/block/getChildBlocks` 作为主路径：

```text
POST /api/block/getChildBlocks
{ "id": "<parent_block_id>" }
```

这样做的原因是：实测部分导入长文档中，所有根级段落的 `sort` 都是同一个值（例如全为 `10`），仅靠 SQL 的 `parent_id + sort` 仍无法还原同级阅读顺序；而 `getChildBlocks` 返回值已经按思源内部顺序排列。

SQL 一次性读取仍保留为诊断/备用能力：

```sql
SELECT id, parent_id, root_id, type, subtype, markdown, content, sort
FROM blocks
WHERE root_id = '<doc_id>' AND type != 'd'
ORDER BY parent_id, sort
```

但它不能作为长文档块 ID 诊断视图的主顺序来源。

诊断视图仍然不是思源原生结构的完整还原：

- 文档块 `d` 不作为正文渲染；文档 ID 已在工具头部返回。
- 列表容器块 `l` 不渲染，但会继续遍历其列表项。
- 列表项 `i` 和表格 `t` 的 Markdown 通常已包含子内容，渲染后不再递归子孙，避免重复。
- 超级块 `s` 只显示块 ID 注释，不渲染其完整 Markdown，然后继续遍历子块，避免超级块内容和子块内容重复。
- 空块不渲染。
- 超级块、数据库、属性视图仍不能靠 Markdown 诊断视图完整表达。

## 写前快照与手动回滚

每次编辑或创建文档之前，MCP server 必须先调用：

```text
/api/repo/createSnapshot
```

该 API 当前只解析 `memo` 参数；它创建的是整个工作空间/数据仓库快照，不支持通过 `path` 限定单篇文档或局部路径，也不支持 `tags` 参数。

快照 memo 应至少包含：

```text
siyuan-agent-bridge
operation type
target notebook/document
timestamp
```

如果快照创建失败，写入应失败，不继续修改思源内容。

实测注意：新工作空间如果尚未初始化“数据仓库密钥”，`/api/repo/createSnapshot` 会返回失败。用户需要先在思源 UI 的 `设置 - 关于 - 数据仓库密钥` 中初始化密钥，再由本工具创建快照。本工具不保存、不生成数据仓库密钥。

实测返回行为：`/api/repo/createSnapshot` 成功时可能返回 `data: null`，不提供 snapshot id。初始化后如果工作空间没有新的数据变更，调用成功也可能不会在 `/api/repo/getRepoSnapshots` 中新增一条带 memo 的快照。后续实现写入工具时，需要在真实写入前后再验证“写前快照”是否能稳定形成可恢复点。

第一阶段不实现 `siyuan_rollback`。原因：

- 回滚不是日常操作，只在 AI 编辑造成严重问题时使用。
- 自动回滚需要处理块、资源、文档树、引用关系，复杂度高。
- `checkoutRepo` 会恢复整个工作空间，风险过高，不应由 AI 调用。
- 用户手动从思源快照恢复更符合这种事故级操作的风险边界。

工具执行成功后应返回快照信息，方便用户在需要时定位恢复点。

## 不直接暴露的高风险 API

以下 API 不应作为 MCP 工具直接开放：

| API 类型 | 原因 |
|----------|------|
| `checkoutRepo` | 恢复整个工作空间，可能覆盖用户后续修改 |
| `removeNotebook` | 删除范围大，笔记本管理是人工决策 |
| `moveBlock` | 块移动会改变正文结构，暂不开放 |
| `deleteBlock` 独立工具 | 删除由 `siyuan_edit` 的 `delete` 动作封装，仍受引用阅读定位和快照约束 |
| 任意 SQL 工具 | 容易泄露隐私边界外的数据，也可能诱导 AI 绕过高层工具 |
| 设置、同步、账号、插件、集市类 API | 和笔记编辑目标无关，风险大于收益 |

## 后续可能扩展

后续可以在不增加底层暴露面的前提下增加能力：

| 能力 | 可能方案 |
|------|----------|
| 块 ID 引用 | `siyuan_read(include_block_ids=true)` 返回块序号和块 ID 定位头 |
| 资源写入 | 在 `siyuan_create` 或专门的资产工具中封装上传和 Markdown 插入 |
| 只读快照查询 | 增加诊断工具列出由本项目创建的最近快照 |
| 自动回滚 | 等写入稳定后再评估块级操作日志，不直接使用 repo checkout |
| AI 修改标记 | 用 `setBlockAttrs` 标记由 AI 创建或修改的块 |
