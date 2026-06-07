# SiYuan Bridge — Agent Navigation

Python 项目，MCP + Skill 架构。产品界面是 MCP 工具和 Skill，CLI 仅供开发诊断。


## 文档定位

AGENTS.md文件是入口导航，不替代架构文档和开发指南。它告诉 AI：项目有哪些部分、先读什么、不同任务该接到哪些文档和代码位置。开发、测试和发布的详细规则放在 `docs/DEVELOPMENT_GUIDE.md`；完整真实架构和工具契约放在 `docs/ARCHITECTURE.md`。

代码修改后必须要在相应文档记录，但禁止将所有相关信息不加选择写入AGENTS.md文档。本文档务必保持精简。专门、详细的内容需要转移到对应文档，并提供精确到标题的指引。

## 必读流程

不要猜测代码可能的样子和实现方式，不管是本项目还是思源笔记的接口、思源插件注册规则都不要自己猜。如果有任何不清楚不确定的地方，直接阅读代码以及相应说明文档。必要时先搜索网络资料。

开始改代码前必须完整阅读：

1. `AGENTS.md`：入口导航、硬性安全规则、任务路由。
2. `docs/ARCHITECTURE.md`：当前真实架构、数据流、MCP 工具契约、已知债务。是理解最核心的说明文件。
3. `docs/DEVELOPMENT_GUIDE.md`：开发流程、同步清单、验证规则、外部 Agent 验证。

不允许只读开头，不允许只 grep 局部，不允许跳过中间或后半段。没有完整阅读这三份文档，不准开始修改代码。

读完三份必读文档后，按任务类型追加阅读下面的对应入口。

## CodeGraph 使用要求

如果当前 Agent 环境提供 CodeGraph MCP 工具，分析代码结构、查找符号、追踪调用链、评估改动影响时必须优先使用 CodeGraph。调用subagent也需要明确告知优先使用codegraph。

如果当前 Agent 环境没有暴露 `codegraph_*` 工具，先确认是否已安装并注册 CodeGraph MCP。使用codegraph能够极大提高探索代码库速度、节省token消耗。强烈推荐。


## 任务路由

| 任务类型 | 先读文档 | 再看代码/材料 |
|---|---|---|
| MCP 工具名称、schema、参数、返回格式、权限边界 | `docs/ARCHITECTURE.md` 的 “MCP 工具总览” 和各工具章节；`docs/DEVELOPMENT_GUIDE.md` 的 “修改工具面时必须同步” | `source_code/mcp_server.py` 的实现和 `tool_specs()`；`plugins/siyuan-bridge/skills/siyuan-bridge/SKILL.md`；`README.md`；相关测试 |
| `siyuan_create`、`siyuan_edit`、`siyuan_doc_manage` 写入行为 | `docs/ARCHITECTURE.md` 的 “写入模型”、对应工具章节；`docs/DEVELOPMENT_GUIDE.md` 的 “修改写入模型时必须验证” 和 “修改文档管理时必须验证” | `source_code/mcp_server.py`；`source_code/client.py`；`tests/test_mcp_server.py`；`tests/test_client.py` |
| 隐私、权限、系统笔记本、Privacy Rules | `docs/ARCHITECTURE.md` 的 “系统笔记本””隐私与权限模型”；`docs/DEVELOPMENT_GUIDE.md` 的 “修改隐私模型时必须验证” | `source_code/ignore.py`；`source_code/agent_notebook.py`；`source_code/indexer.py`；相关测试 |
| 索引、列表、搜索、读取、附件、块窗口 | `docs/ARCHITECTURE.md` 的 “索引模型””搜索模型””阅读模型”；`docs/DEVELOPMENT_GUIDE.md` 的 “修改读取模型时必须验证” | `source_code/indexer.py`；`source_code/mcp_server.py`；`source_code/client.py`；相关测试 |
| 思源底层 API 封装 | `docs/思源API.md`；`docs/ARCHITECTURE.md` 的 “底层 API 封装策略” | `source_code/client.py`；`tests/test_client.py` |
| Workspace Index 工作流 | `docs/ARCHITECTURE.md` 的 “siyuan-index-builder Skill”；`plugins/siyuan-bridge/skills/siyuan-index-builder/SKILL.md` | `plugins/siyuan-bridge/skills/siyuan-bridge/SKILL.md`；相关 MCP 工具实现 |
| 安装、打包、发布材料 | `docs/DEVELOPMENT_GUIDE.md` 的发布/验证部分 | `mcp_configs/`；`README.md`；`siyuan-plugin/README*.md` |
| 历史问题、排障、阶段性结论 | `docs/devlog.md`，优先读最新记录；不要把旧计划当当前事实 | 必要时同步回 `ARCHITECTURE.md` 或 `DEVELOPMENT_GUIDE.md` |
| 遥测、统计、用户体验改善 | `docs/ARCHITECTURE.md` 的”遥测数据流”；`docs/feedback-telemetry-backend.md` | `source_code/telemetry.py`；`source_code/mcp_server.py`；`worker/` |
| 插件前端 UI、消息通知、用户反馈 | `docs/FRONTEND.md` | `siyuan-plugin/index.js`；`siyuan-plugin/src/index.js`；`siyuan-plugin/index.css`；`siyuan-plugin/plugin.json` |
| 未决定的想法、待评估 idea | `docs/IDEAS.md` | 定案后再迁移到 `ARCHITECTURE.md` 或 `DEVELOPMENT_GUIDE.md` |

涉及设计决策、工具契约、开发流程或排障结论时，不要只更新代码。必须同步更新对应文档。

## 项目地图

```text
source_code/         Python 适配层
  client.py          思源 HTTP API 封装
  indexer.py         扫描笔记本，生成 tree.md / docs.jsonl / notebooks.json
  mcp_server.py      MCP stdio server，9 个工具的 schema 和实现
  ignore.py          Privacy Rules Markdown 表格解析与过滤
  i18n.py            多语言名称、系统文档名、默认模板
  agent_notebook.py  系统笔记本服务层
  config.py          配置加载和 profile 探测
  cli.py             开发诊断 CLI

plugins/
  siyuan-bridge/
    skills/          给外部 AI 的 Skill 指令副本。
    scripts/         run_mcp.py，MCP stdio 启动脚本

knowledge_base/      运行时缓存，Git 忽略，每次 refresh 可能覆盖
  tree.md            程序生成的客观文档树
  docs.jsonl         结构化文档元数据
  notebooks.json     可见笔记本索引
  privacy_rules.json Privacy Rules 解析缓存

思源笔记工作空间       用户启动的工作空间（用MCP看到的内容）
  思源桥/SiYuan Bridge   思源桥MCP系统笔记本，跟随思源工作空间切换
    AI Guide            用户偏好和 AI 使用规则，确保存在但不覆盖
    Workspace Index     AI 维护的语义导航索引，不自动创建
    About SiYuan Bridge 给人看的说明，模板版本变化时覆盖
    Privacy Rules       人类维护的隐私规则，AI 不可读
  其他笔记本
    其他文档
      其他子文档

ai_workspace/        AI 临时工作区，Git 忽略
dist/                构建产物
tests/               单元测试
docs/                架构、开发指南、前端、API、idea、devlog
  architecture-map.html 人类可读产品架构图，整体架构大改时同步更新
```

## 开发核心约束

- MCP-first：用户功能通过 MCP 工具暴露，CLI没有专门优化，只作早期开发诊断使用。
- 确认后可写：写入工具必须要求用户明确写入意图和 `confirmed=true`，写入前创建思源快照。
- 恢复要求：项目不提供 AI 自动回滚/checkout。写入后如需恢复，只能提示用户通过思源快照手动恢复；不要让 AI 调用高风险恢复接口。
- 不自动启动思源：连接失败只提示用户手动打开思源，不鼓励AI查找程序路径。在开发时，务必保留错误返回信息中的相关说明，不要省略“让用户启动”等关键表述。
- Privacy Rules 硬隔离：任何操作都需要在执行前经隐私规则过滤。源码写死隐藏Privacy Rules文档，AI 不可读取、搜索或编辑 Privacy Rules 文档。
- 系统笔记本由机器维护：AI Guide 确保存在不覆盖；Workspace Index 不自动创建；About 按模板版本维护。
- 关闭笔记本透明打开/关闭：索引、搜索和写入前可临时打开关闭的笔记本，完成后必须恢复。
- 工作区可能有用户改动：不要回滚、删除或重置非本任务改动。

## 协作规则

除非用户明确要求修复、实现、改代码、跑测试、提交或执行其他具体操作，否则只查看相关文档和代码，做只读分析说明，不要擅自行动。

回复必须精简、明确、直接。不要绕圈子，不要输出无关铺垫。尽可能节省输出token，只提供影响决策的必要信息。

## Windows 命令

Windows 上读取中文、输出中文、处理复杂引号或避免 PowerShell 编码问题时，优先使用 CMD UTF-8 包装：

```bat
cmd /d /s /c "chcp 65001 >nul && <command>"
```

示例：

```bat
cmd /d /s /c "chcp 65001 >nul && type AGENTS.md"
cmd /d /s /c "chcp 65001 >nul && rg -n ""关键词"" AGENTS.md"
cmd /d /s /c "chcp 65001 >nul && python -m pytest tests -q"
```

不要使用默认 `Get-Content AGENTS.md` 读取中文，不要把终端乱码误判为文件损坏。

## 常用入口

```bash
# 导入到本地思源测试
python scripts/import_siyuan_plugin.py --workspace <思源工作空间路径>
python scripts/import_siyuan_plugin.py --workspace <路径> --fresh  # 首次安装/清空重装

# 打包集市发布 zip
python scripts/build_package.py

# 诊断
python -m source_code doctor
python -m source_code notebooks

# 索引
python -m source_code refresh
python -m source_code start

# 搜索/阅读
python -m source_code find <keyword>
python -m source_code tree
python -m source_code read <doc-id>

# 测试
python -m pytest tests -q
```

## 外部验证

涉及 MCP 工具面、安装配置或跨 Agent 行为时，常规测试后必须做外部 Agent 验证。使用 AI 实际调用项目 MCP，没有经过实测检验的修改不允许称为“测试通过”。详细流程、宽授权 / bypass 模式、失败降级和各类改动的最低验证要求见 `docs/DEVELOPMENT_GUIDE.md` 的 “外部 Agent 验证”。

## 构建与发布

导入测试、打包和版本发布流程见 `docs/DEVELOPMENT_GUIDE.md` 的 "构建与发布" 章节。
