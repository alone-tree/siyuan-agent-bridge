# SiYuan Enhance

[English README](README.md)

SiYuan Enhance 是一个私有、本地优先的思源笔记适配器。它让外部 AI agent 能像阅读代码仓库一样，先理解你的笔记结构，再按需读取具体文档。

它不是思源插件，不是公开项目，也不是向量检索系统。你的笔记仍然保存在思源里；这个工具只负责生成结构化索引，并通过 CLI / MCP 给 AI 一个安全、可控的只读入口。

## 当前能力

- 扫描思源笔记本和完整文档树，包括子文档。
- 按 `siyuan.ignore.local.json` 隐藏笔记本、单篇文档或整棵子文档树。
- 通过 `siyuan.allow.local.json` 临时开放隐藏内容，到期后自动失效。
- 生成 `knowledge_base/` 下的安全索引、总览和笔记本地图。
- 提供 MCP 工具，让 Claude Code、Codex、OpenCode 等 agent 直接读取思源资料。
- 长文档自动分段，默认每段约 10,000 字符，可通过 `max_chars` 调整。
- 图文混排文档会保留 Markdown 图片引用，AI 可以按分段读取图片前后的文字上下文。
- 支持通过 CC Switch 导入 Skill 压缩包，并手动/JSON/deep link 注册 MCP。

## 日常怎么用

大多数时候你不需要自己使用命令行。

你主要维护这些文件：

- `knowledge_base/guide.md`：你维护的知识库阅读指南，告诉 AI 哪些主题、路径、笔记本最重要。
- `siyuan.ignore.local.json`：长期隐藏规则。
- `siyuan.allow.local.json`：临时开放规则。
- `ai_workspace/`：AI 生成的分析、任务上下文、草稿和输出。

典型流程：

1. 你在思源里正常写笔记。
2. 如果某些内容要隐藏，编辑 `siyuan.ignore.local.json`。
3. 告诉 AI：“我修改了思源 ignore，请刷新知识库索引。”
4. AI 调用 `siyuan_refresh_index` 或运行 `python -m source_code refresh`。
5. 之后 AI 只能看到未被隐藏的安全索引。

## Agent 启动流程

如果 AI 工具已经注册了 MCP，直接让它使用你的思源知识库即可。它应该调用：

```text
siyuan_start
```

这个工具只做两件事：

- 检查思源本地服务是否可用。
- 返回现有入口材料，包括 `START_HERE.md` 和 `knowledge_base/guide.md`。

它不会自动刷新索引。

如果 MCP 不可用，AI 可以在项目根目录运行：

```bash
python -m source_code start
```

## MCP 工具

当前 MCP 提供这些只读工具：

- `siyuan_start`：检查思源连接并返回启动包。
- `siyuan_refresh_index`：在用户要求、索引缺失或明显过期时刷新安全索引。
- `siyuan_list_notebooks`：列出安全索引里的可见笔记本。
- `siyuan_list_documents`：读取某个可见笔记本的文档地图。
- `siyuan_find_documents`：按关键词查找可见文档。
- `siyuan_read_document`：读取文档预览；长文档只返回第 1 段和分段提示。
- `siyuan_describe_document_chunks`：查看一篇长文档的分段地图。
- `siyuan_read_document_chunk`：读取指定分段，保留文字和图片引用的相对位置。
- `siyuan_propose_guide_update`：把建议的指南更新保存到 `ai_workspace/`，不直接修改指南。
- `siyuan_apply_guide_update`：只有在用户明确批准后，才追加或替换 `knowledge_base/guide.md`。

## 长文档和图文混排

长文档不会再一次性完整返回，避免 MCP 客户端或模型界面在中间截断。

默认分段长度是：

```text
10,000 字符
```

AI 可以通过 `max_chars` 调整，当前允许范围是 2,000 到 30,000 字符。

推荐流程：

1. `siyuan_read_document` 先读预览。
2. 如果提示文档很长，调用 `siyuan_describe_document_chunks`。
3. 根据每段标题、长度和图片数量，选择相关段落。
4. 调用 `siyuan_read_document_chunk` 读取具体分段。

图文混排文档里的图片引用会留在原位置，例如：

```md
![image](assets/image-xxx.png)
```

这样 AI 读取分段时可以同时看到图片前后的文字，不会把图片单独抽离成失去上下文的素材。

## 隐藏规则

打开：

```text
siyuan.ignore.local.json
```

隐藏整个笔记本：

```json
{
  "scope": "notebook",
  "name": "笔记本名称",
  "reason": "隐藏整个笔记本"
}
```

隐藏单篇文档：

```json
{
  "scope": "document",
  "id": "文档ID",
  "reason": "隐藏这一篇文档"
}
```

隐藏某篇文档和它下面所有子文档：

```json
{
  "scope": "subtree",
  "id": "父文档ID",
  "reason": "隐藏这篇文档和它下面的所有子文档"
}
```

改完后让 AI 刷新索引即可。旧索引里之前可见、现在被隐藏的内容会从新的 `knowledge_base/` 索引里移除。

## CC Switch 使用

Skill 可以用压缩包导入。当前最新生成的包在：

```text
dist/siyuan-knowledge-skill-latest.zip
```

MCP 可以在 CC Switch 的“新增 MCP / 自定义”界面里填入：

```json
{
  "type": "stdio",
  "command": "python",
  "args": [
    "D:\\Github\\siyuan-enhance\\plugins\\siyuan-knowledge\\scripts\\run_mcp.py"
  ],
  "env": {
    "PYTHONUTF8": "1"
  }
}
```

也可以参考：

```text
dist/siyuan-knowledge-mcp.json
dist/siyuan-knowledge-mcp-deeplink.txt
```

## 项目结构

```text
siyuan-enhance/
  AGENTS.md                  # 给 AI agent 的仓库规则
  START_HERE.md              # AI 使用本项目时的入口
  README.md                  # 英文说明
  README.zh-CN.md            # 中文说明
  config.example.json        # 配置示例
  config.local.json          # 本机 token，已被 Git 忽略
  siyuan.ignore.local.json   # 长期隐藏规则
  siyuan.allow.local.json    # 临时开放规则
  source_code/               # Python 工具代码
  plugins/siyuan-knowledge/  # Skill 和 MCP 插件材料
  knowledge_base/            # 生成的安全索引
  ai_workspace/              # AI 工作区
  tests/                     # 测试
```

`knowledge_base/` 里主要有：

- `guide.md`：你维护的知识库指南。
- `overview.md`：顶层总览。
- `tree.md`：完整文档树，默认不要让 AI 一上来全扫。
- `docs.jsonl`：文档级索引。
- `notebooks.json`：笔记本索引。
- `notebooks/`：每个笔记本自己的文档地图。

`source_code/` 里主要有：

- `client.py`：只读思源 API client。
- `indexer.py`：扫描和生成索引。
- `ignore.py`：隐藏和临时开放规则。
- `cli.py`：CLI 入口。
- `mcp_server.py`：MCP stdio server。

## 隐私边界

这个项目按 private project 设计。

- 不要提交 token。
- 不要公开 `knowledge_base/` 和 `ai_workspace/`，除非你已经清理个人内容。
- AI 不应主动读取 `config.local.json`、`siyuan.ignore.local.json` 或 `siyuan.allow.local.json`，除非你明确要求。
- AI 不应修改思源笔记，也不应调用思源写 API。

如果未来要公开这个项目，需要重新设计隐私策略，并清理所有个人笔记索引和工作区材料。
