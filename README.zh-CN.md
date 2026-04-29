# SiYuan Enhance

[English README](README.md)

SiYuan Enhance 是一个私有、本地优先的思源笔记适配器。它让外部 AI agent 能像阅读代码仓库一样，读取你的思源笔记结构，并在需要时深入阅读具体文档。

它不是思源插件，不是公开项目，也不是向量检索系统。笔记仍然保存在思源里；这个工具只负责生成结构化索引，并给 AI 一个安全、可控的只读入口。

## 你平时怎么用

大多数时候你不需要自己使用命令行。

你只需要维护几个本地文件：

- `knowledge_base/guide.md`：告诉 AI 哪些笔记本、路径、主题最重要。
- `siyuan.ignore.local.json`：告诉工具哪些笔记本或文档要长期隐藏，可随仓库同步。
- `siyuan.allow.local.json`：临时开放规则，可随仓库同步。
- `ai_workspace/`：AI 生成的分析、任务上下文、草稿和输出。

日常流程通常是：

1. 你在思源里正常写笔记。
2. 你如果想隐藏某些内容，就打开 `siyuan.ignore.local.json`，复制模板并填写笔记本名称或文档 ID。
3. 你告诉 AI：“我改了思源 ignore，请刷新知识库索引。”
4. AI 运行刷新命令，重新生成安全索引。
5. 之后 AI 只会看到未被隐藏的笔记结构。

## 主要原理

思源笔记把数据保存在本地，同时提供本地 HTTP API，通常地址是：

```text
http://127.0.0.1:6806
```

这个项目使用思源的只读 API 来做三件事：

- 扫描所有笔记本和文档结构。
- 根据 `siyuan.ignore.local.json` 排除隐藏内容。
- 生成 AI 可读的索引文件，例如 `knowledge_base/tree.md` 和 `knowledge_base/docs.jsonl`。

AI 不会一次性读取你的所有笔记。它会先看结构化目录，再按需读取具体文档。

## 隐藏规则怎么写

打开：

```text
siyuan.ignore.local.json
```

这个文件已经带有中文模板。程序只读取里面的 `ignore` 数组，其他说明字段不会影响运行。

隐藏整个笔记本，推荐按名称：

```json
{
  "scope": "notebook",
  "name": "笔记本名称",
  "reason": "隐藏整个笔记本"
}
```

隐藏单篇文档，按文档 ID：

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

完整文件大概长这样：

```json
{
  "ignore": [
    {
      "scope": "notebook",
      "name": "日记随笔",
      "reason": "隐藏私人日记"
    },
    {
      "scope": "subtree",
      "id": "20260429120000-abcdefg",
      "reason": "隐藏这篇文档和子文档"
    }
  ]
}
```

改完后，不需要你自己运行命令。告诉 AI：

```text
我改了思源 ignore，请刷新知识库索引。
```

AI 会负责重新扫描并清理旧索引。之前已经暴露在 `knowledge_base/` 里的文档，如果现在被隐藏，会从新索引里移除。

## 临时开放怎么处理

临时开放主要给 AI 使用。

如果你需要临时让 AI 看某个隐藏内容，可以直接告诉 AI：

```text
临时开放这篇文档 30 分钟：文档ID 是 xxx
```

或者：

```text
临时开放这个笔记本 1 小时：笔记本名称是 xxx
```

AI 会写入或读取 `siyuan.allow.local.json`。这个文件带过期时间，到期后自动失效。

重要的是：临时开放不会重写长期索引 `knowledge_base/`，所以临时打开的内容不会长期留在 AI 可见目录里。

## 项目目录结构

```text
siyuan-enhance/
  AGENTS.md                 # 给 AI agent 看的使用规则
  README.md                 # 英文说明
  README.zh-CN.md           # 中文说明
  config.example.json       # 配置示例
  config.local.json         # 本机 token，已被 Git 忽略
  siyuan.ignore.local.json  # 长期隐藏规则，可随仓库同步
  siyuan.allow.local.json   # 临时开放规则，可随仓库同步
  source_code/                # Python 工具代码
  knowledge_base/           # 生成的知识库索引
  ai_workspace/             # AI 工作区
  tests/                    # 测试
```

`knowledge_base/` 里主要有：

- `guide.md`：你维护的知识库指南。
- `tree.md`：AI 可读的笔记目录树。
- `docs.jsonl`：文档级索引。
- `notebooks.json`：笔记本索引。

`source_code/` 里主要有：

- `client.py`：只读思源 API client。
- `indexer.py`：扫描和生成索引。
- `ignore.py`：隐藏和临时开放规则。
- `cli.py`：AI/开发者使用的命令行入口。

## 给 AI 的工作方式

AI 在这个仓库里工作时，应该：

1. 先读 `AGENTS.md`。
2. 再读 `knowledge_base/guide.md`。
3. 再读 `knowledge_base/tree.md`。
4. 需要深入时，按文档 ID 读取具体文档。
5. 生成的分析和草稿放进 `ai_workspace/`。
6. 如果你说已经改了 ignore，AI 应该刷新索引。

AI 不应该主动读取 `config.local.json`、`siyuan.ignore.local.json` 或 `siyuan.allow.local.json`，除非你明确要求。

## 隐私边界

这个项目按 private project 设计。

- `config.local.json` 不进入 Git。
- `siyuan.ignore.local.json` 可以进入 Git，方便多设备同步隐藏策略。
- `siyuan.allow.local.json` 可以进入 Git，方便多设备同步临时开放策略。
- `knowledge_base/` 和 `ai_workspace/` 默认可以进入 Git，因为当前仓库是私人使用。

如果未来要公开这个项目，需要重新检查隐私策略，移除个人笔记内容和 AI 工作区材料。
