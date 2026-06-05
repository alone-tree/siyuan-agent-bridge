# 思源 MCP 插件方案

状态：讨论稿

## 目标

把现有 Siyuan Bridge 从“用户下载一个外部 Python 项目，再让 AI 帮忙配置 MCP”，推进为“用户在思源里安装插件，再复制一段 MCP 配置即可使用”。

插件不是思源内置聊天工具，也不是另一个通用思源 API 面板。它的产品目标是降低本地 MCP 的安装和配置成本，让 Claude Code、Codex、Hermes 等外部 AI Agent 可以稳定连接用户的思源工作空间。

## 产品形态

产品由两部分组成：

1. 思源插件

   插件安装在当前思源工作空间的插件目录中，跟随工作空间走。它提供设置页、保存当前工作空间的连接信息，并生成当前工作空间可用的 MCP 配置片段。

2. 插件内置 Python Bridge

   插件包内包含完整的 Python MCP 程序。AI Agent 启动 MCP 时，实际运行的是插件目录里的 Python 脚本。MCP server 本身可以独立启动；思源未启动时，它返回“思源未启动”，而不是注册失败或进程卡死。

   当前 Python Bridge 只依赖 Python 标准库，没有 `requirements.txt` 或额外第三方包。这是插件分发的重要前提：第一版插件只需要确认用户本机有可用 Python，不需要在插件安装时执行 pip 安装。

一句话形态：

> 思源插件负责落盘、配置和生成 MCP JSON；Python Bridge 负责真正的 MCP 工具能力。

## 用户前提

第一版默认用户已经具备：

- 已安装思源桌面端。
- 已安装 Claude Code、Codex、Hermes 或其他支持 MCP 的 AI Agent。
- 本机已有可用 Python。
- 用户愿意手动复制 MCP 配置到对应 AI Agent。

第一版不负责安装 Python，不负责安装 AI Agent，不自动修改 AI Agent 的配置文件。

因为 Python Bridge 没有第三方依赖，第一版不需要管理虚拟环境或依赖安装。用户填写的 Python 命令只要能运行标准库 Python 程序即可。

## 使用流程

### 1. 安装插件

用户在思源中安装 Siyuan Bridge 插件。

安装后，当前工作空间的插件目录中会出现完整插件文件，包括 Python Bridge。

因为插件跟随工作空间，所以不同思源工作空间会有不同的插件安装路径，也会有各自独立的 Token 和配置文件。

第一版产品应避免让用户在 AI Agent 中注册多份同名 MCP。多个相同工具入口会让 AI 困惑，也会增加用户排障成本。推荐形态是：用户选择一个插件安装目录作为主要 MCP 入口，在这一份配置中维护多个工作空间资料。

### 2. 打开设置页

用户进入插件设置页，看到当前工作空间的连接配置：

- 思源 API 地址
- Token
- Python 命令
- 当前 MCP 插件安装路径
- MCP 启动脚本路径
- 默认工作空间名称
- 其他工作空间列表

Token 只保存在本机当前工作空间的插件配置中，不出现在 MCP JSON 中。

当前安装插件的工作空间是默认工作空间。插件应尽量自动获取当前工作空间的 Token 和基础信息，并把它作为第一条工作空间配置。用户不需要先理解多工作空间模型，也不需要手动新增当前工作空间。

如果用户还有其他思源工作空间，可以在设置页手动添加工作空间名称和 Token。

### 3. 保存本地配置

用户填写或确认 API 地址、默认工作空间 Token、Python 命令和工作空间名称后，插件把这些信息写入插件目录中的本地配置文件。

这份配置默认服务当前工作空间。用户有多个思源工作空间时，可以在同一份 MCP 配置中添加其他工作空间的名称和 Token，而不是在 AI Agent 中注册多份 Siyuan Bridge MCP。

多工作空间配置采用列表形态：

```text
默认工作空间
  - 名称：当前安装插件的工作空间
  - Token：插件自动获取或用户确认

其他工作空间
  - 用户点击“添加工作空间”
  - 手动输入名称和 Token
```

### 4. 生成 MCP 配置

用户选择 AI Agent 类型：

- Claude Code
- Codex
- Hermes
- 通用 MCP

插件根据当前工作空间的真实插件路径和用户填写的 Python 命令，生成可以复制的 MCP JSON。

MCP JSON 只包含启动命令和脚本路径，不包含 Token。AI Agent 通过这段配置启动插件目录里的 Python MCP server。

### 5. 配置 AI Agent

用户把 MCP JSON 复制到对应 AI Agent 的配置中，并重启或刷新 AI Agent。

之后 AI Agent 就能看到 Siyuan Bridge 的 MCP 工具。中文产品名统一叫“思源桥”，英文产品名统一叫“Siyuan Bridge”。

### 6. 开始使用

用户在 AI Agent 中发起请求，例如查找笔记、读取文档、创建文档或编辑内容。

AI Agent 调用 MCP server。MCP server 读取插件目录中的本地配置，再连接思源 API。

如果思源已启动且 Token 正确，工具正常工作。

如果思源未启动，MCP server 正常返回可理解的错误：需要用户打开思源。

如果思源已启动但 Token 不匹配，MCP server 不应只返回“连接失败”。它应提示用户可能打开了另一个思源工作空间，或当前工作空间尚未加入思源桥配置。

## 数据流

### 安装时

```text
思源插件安装
  -> 插件文件落到当前工作空间 data/plugins
  -> Python Bridge 随插件一起落盘
```

### 配置时

```text
用户在插件设置页确认默认工作空间 / Python 命令
  -> 可选：手动添加其他工作空间名称和 Token
  -> 插件写入当前工作空间插件目录下的本地配置
  -> 插件生成 MCP JSON
  -> 用户复制到 AI Agent
```

### 使用时

```text
AI Agent
  -> 根据 MCP JSON 启动插件目录里的 Python MCP server
  -> Python MCP server 读取插件目录里的本地配置
  -> 匹配当前可用的思源工作空间配置
  -> 调用对应思源工作空间的 API
  -> 返回搜索、阅读、写入或错误结果给 AI Agent
```

### 思源未启动时

```text
AI Agent
  -> 启动 Python MCP server 成功
  -> 调用 MCP 工具
  -> MCP server 探测思源 API 不可达
  -> 返回“思源未启动，请打开思源”
```

关键点：MCP 注册和 MCP 进程启动不依赖思源是否正在运行。

### Token 不匹配时

```text
AI Agent
  -> 调用 MCP 工具
  -> MCP server 发现思源 API 可达但 Token 不可用
  -> 返回“可能打开了未配置的工作空间，请切换工作空间或在插件中添加该工作空间配置”
```

关键点：Token 错误需要被解释为工作空间问题，而不是泛化成普通连接失败。

## 工作空间边界

插件配置以思源工作空间为单位隔离：

- 每个工作空间有自己的插件安装目录。
- 每个工作空间有自己的 Token。
- 一个 MCP 入口可以维护多个工作空间资料。
- AI Agent 默认只注册一个 Siyuan Bridge MCP，避免出现多份同名工具。

用户有多个思源工作空间时，推荐做法不是注册多个 MCP server，而是在同一个思源桥配置中添加多个工作空间资料，例如：

- 工作
- 个人
- 项目资料库

当当前思源工作空间和已保存资料不匹配时，MCP 应给出明确提示，让用户切换工作空间或回到插件设置页补充配置。

## 第一版范围

第一版只追求最小闭环：

- 插件包内携带完整 Python Bridge。
- 插件设置页保存 API 地址、Token、Python 命令和工作空间名称。
- 插件设置页默认创建当前安装工作空间资料。
- 插件设置页支持手动添加其他工作空间名称和 Token。
- 插件设置页生成可复制 MCP JSON。
- Python MCP server 可以从插件目录启动。
- 思源未启动时 MCP server 仍可注册和响应。

## 第一版不做

- 不内置 Python。
- 不创建虚拟环境。
- 不执行 pip install。
- 不安装或管理 Claude Code、Codex、Hermes。
- 不自动修改 AI Agent 配置文件。
- 不把 MCP server 改写为 TypeScript。
- 不做思源内聊天 UI。
- 不在 AI Agent 中鼓励注册多份同名 MCP。

## 产品验收

第一版达到以下效果即可认为成立：

1. 用户从思源安装插件后，不需要再单独下载 Python Bridge 项目。
2. 插件设置页默认显示当前安装工作空间，并能保存它的 Token。
3. 用户可以手动添加其他工作空间名称和 Token。
4. 用户在插件设置页填入 Python 命令后，可以复制出可用 MCP JSON。
5. AI Agent 使用这段 JSON 后，可以启动插件目录里的 MCP server。
6. 思源启动时，AI Agent 可以正常调用 MCP 工具。
7. 思源未启动时，AI Agent 仍能启动 MCP server，并得到明确的“思源未启动”提示。
8. 打开未配置工作空间时，AI Agent 得到明确的工作空间或 Token 不匹配提示。

## 实现计划

### 1. 保持现有 Python Bridge 为唯一能力实现

现有 `source_code/` 继续作为 MCP 工具、思源 API、索引、隐私过滤和写入保护的唯一实现。

思源插件不重新实现 MCP 工具，不复制一套业务逻辑，不把 MCP server 改写成 TypeScript。插件只是把 Python Bridge 放到思源插件目录里，并提供配置入口。

第一版目标是最小侵入：

- 不改 MCP 工具名称、schema 和语义。
- 不改现有 `profiles` 配置模型。
- 不引入 Python 第三方依赖。
- 不引入 pip、venv 或安装期依赖解析。

### 2. 新增思源插件工程目录

新增一个独立的思源插件目录，用来承载插件 UI 和插件内置 Bridge：

```text
siyuan-plugin/
  plugin.json
  src/
  dist/
  bridge/
```

其中：

- `plugin.json` 描述思源插件本身。
- `src/` 是插件设置页源码。
- `dist/` 是思源实际加载的前端构建产物。
- `bridge/` 是由复制脚本生成的 Python Bridge 运行目录。

`bridge/` 不手工维护。它由脚本从当前仓库复制必要文件生成，避免 Python 代码出现两份主副本。

### 3. 复制脚本只复制必要 Python 运行文件

新增一个开发期复制脚本，例如：

```text
scripts/sync_siyuan_plugin_bridge.py
```

第一版不生成 zip，不做发布打包，只把必要文件复制到：

```text
siyuan-plugin/bridge/
```

需要复制的最小集合：

```text
source_code/
plugins/siyuan-agent-bridge/scripts/run_mcp.py
plugins/siyuan-agent-bridge/skills/
config.example.json
README.md
INSTALL_FOR_AI.md
LICENSE
```

不复制：

- `config.local.json`
- `knowledge_base/`
- `ai_workspace/`
- `.git/`
- `.mcp.json`
- `dist/`
- `.test_tmp/`
- `tests/`

复制后的目标结构必须保留当前 `run_mcp.py` 能识别的相对层级：

```text
siyuan-plugin/bridge/
  source_code/
  plugins/siyuan-agent-bridge/scripts/run_mcp.py
```

这样现有 `run_mcp.py` 从自身路径向上推导运行根目录时，可以自然落到 `bridge/`。

### 4. 复用现有 `config.local.json`

插件设置页写入：

```text
siyuan-plugin/bridge/config.local.json
```

格式继续使用现有配置模型：

```json
{
  "profiles": [
    {
      "name": "当前工作空间",
      "token": "..."
    }
  ],
  "language": "zh-CN"
}
```

当前安装插件的工作空间作为默认 profile。其他工作空间由用户手动添加到同一个 `profiles` 列表。

不新增 `workspaces` 字段，不新增第二套 token 配置格式。

### 5. 插件设置页第一版功能

设置页只做必要闭环：

- 显示当前插件目录。
- 显示 `bridge/` 目录。
- 显示 MCP 启动脚本路径。
- 输入 Python 命令。
- 显示默认工作空间 profile。
- 保存默认工作空间 Token。
- 手动添加、修改、删除其他 profile。
- 生成可复制 MCP JSON。

MCP JSON 中只包含：

- server 名称。
- Python command。
- `run_mcp.py` 绝对路径。
- `PYTHONUTF8=1` 环境变量。

MCP JSON 不包含 Token。

### 6. Python 侧最小补强

Python 核心只做必要兼容，不做结构性重构：

1. 确认 `run_mcp.py` 在 `siyuan-plugin/bridge/` 结构下能正确把 `bridge/` 作为运行根目录。
2. 确认 MCP server 从 `bridge/config.local.json` 读取 `profiles`。
3. 优化 `detect_active_profile()` 的错误信息：
   - 没有配置 profile：提示回到插件设置页添加 Token。
   - 端口不可达：提示打开思源。
   - 思源可达但所有 token 被拒绝：提示可能打开了未配置工作空间，或当前工作空间 Token 未加入 profiles。

这一步不改变工具 schema。

### 7. 开发验证顺序

第一阶段验证按这个顺序做：

1. 运行 Python 单元测试。

   ```bat
   python -m pytest tests -q
   ```

2. 运行 Bridge 复制脚本。

   ```bat
   python scripts/sync_siyuan_plugin_bridge.py
   ```

3. 检查 `siyuan-plugin/bridge/` 结构。

   必须存在：

   ```text
   siyuan-plugin/bridge/source_code/mcp_server.py
   siyuan-plugin/bridge/source_code/config.py
   siyuan-plugin/bridge/plugins/siyuan-agent-bridge/scripts/run_mcp.py
   ```

4. 在 `siyuan-plugin/bridge/` 下创建测试用 `config.local.json`。

5. 用插件路径启动 MCP JSON-RPC，验证 `initialize` 和 `tools/list`。

6. 思源启动时，调用 `siyuan_start`。

7. 思源未启动时，确认 MCP server 仍能启动，工具返回可理解的未启动提示。

8. Token 不匹配时，确认错误提示指向工作空间配置问题。

涉及 MCP 跨 Agent 行为时，仍按开发指南使用 Claude Code bypass 模式做外部验证。

测试工作空间中的插件目录只代表用户安装后的结果，不是源码目录。调试时不要直接修改 `D:\Siyuan2test\data\plugins\siyuan-bridge` 或其他测试工作空间下的插件代码。正确流程：

```text
修改仓库中的 siyuan-plugin/
  -> 运行或确认 Bridge 同步
  -> 删除/覆盖测试工作空间插件目录
  -> 必要时保留 bridge/config.local.json
  -> 在思源 UI 中按用户路径重新测试
```

这样才能保证测试结果等同于用户重新安装或重新下载插件后的自然结果。

### 8. 第一阶段交付物

第一阶段完成后应得到：

- 一个可加载的思源插件骨架。
- 一个可运行的插件设置页。
- 一个只复制必要 Python 文件的 Bridge 同步脚本。
- 插件目录内可独立启动的 Python MCP server。
- 插件设置页生成的 MCP JSON。
- 针对插件运行目录的最小测试或验证记录。

不交付：

- zip 发布包。
- 插件集市发布材料。
- 自动安装 Python。
- 自动写入 Claude Code、Codex、Hermes 配置文件。
- TypeScript 版 MCP server。
