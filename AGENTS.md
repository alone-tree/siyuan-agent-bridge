# SiYuan Agent Bridge — Developer Guide

Python 项目，MCP + Skill 架构。产品界面是 MCP 工具和 Skill，CLI 仅供开发诊断。

## Project Structure

```
source_code/         Python 适配层
  client.py          → SiYuan HTTP API 封装（读写）
  indexer.py         → 扫描笔记本 → 生成 tree.md + docs.jsonl
  mcp_server.py      → MCP stdio server（11 个工具）
  ignore.py          → 隐私规则管理
  config.py          → 配置加载
  cli.py             → 开发诊断 CLI
plugins/             Skill 打包材料（供 CC Switch 导入）
  siyuan-agent-bridge/
    skills/          → siyuan-agent-bridge SKILL.md（使用者工作流）
    scripts/         → run_mcp.py（MCP stdio 启动脚本）
knowledge_base/      生成的索引（Git 忽略，仅本地存在）
  tree.md            → 程序生成，每次 refresh 覆盖
  docs.jsonl         → 结构化文档元数据
  guide.md           → 用户维护的阅读指南（ensure，不覆盖）
  index.md           → AI 生成的语义导航索引
ai_workspace/        AI 工作区（Git 忽略）
dist/                构建产物（Skill zip + MCP 配置）
pack_skill.py        一键打包 Skill 压缩包到 dist/
tests/               测试
docs/                说明文档（PRO.md、计划、API 文档等）
```

## Documentation

修改设计决策、发现新问题、完成重要讨论后，必须更新 `docs/PRO.md`。不要遗漏。这是项目知识持续积累的核心机制。

## Architecture

- **MCP-first**：所有用户功能通过 MCP 工具暴露，CLI 只作为开发者诊断临时使用。
- **默认只读，确认后可写**：AI 不应直接调用底层思源写 API。只有在用户明确要求写入时，才使用 `siyuan_create_document` 或 `siyuan_edit_document`。写入前自动创建思源工作空间快照。
- **隐私预过滤**：`docs.jsonl` 生成时已过滤隐藏内容；搜索时以此做门控。
- **关闭笔记本透明打开**：索引、搜索和写入前自动临时打开关闭的笔记本，完成后恢复。

## Common Commands

```bash
# 诊断
python -m source_code doctor
python -m source_code notebooks

# 索引
python -m source_code refresh
python -m source_code start    # 等价于 siyuan_start

# 搜索/阅读
python -m source_code find <keyword>
python -m source_code tree
python -m source_code read <doc-id>

# 隐私
python -m source_code ignore status

# 测试
pytest tests/ -v
```

## Dev Notes

- MCP server 通过 stdin/stdout JSON-RPC 通信，由 `plugins/…/scripts/run_mcp.py` 启动。
- `config.local.json` 包含思源 API token，已被 Git 忽略。
- Skill zip 打包：运行 `python pack_skill.py` 生成 `dist/siyuan-agent-bridge-skill-<时间戳>.zip`。
- 索引刷新时 `guide.md` 不会被覆盖（ensure），`tree.md` 和 `docs.jsonl` 会被覆盖。
