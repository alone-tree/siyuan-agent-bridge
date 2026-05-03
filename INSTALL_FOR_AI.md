# SiYuan Agent Bridge — AI Agent 安装说明

你是用户的 AI Agent。你的任务是根据本文档将 SiYuan Agent Bridge 安装到用户的计算机上，让用户后续可以通过你使用思源笔记作为知识库。

## 这是什么

SiYuan Agent Bridge 是一个私有、本地优先的思源笔记适配层。它通过 MCP 工具和 Skill 工作流让 AI agent 安全地读取、搜索和写入用户的思源笔记。

核心设计：隐私过滤在索引层完成，隐藏内容从根本上对 AI 不可见。隐私规则由用户在思源 UI 中维护，AI 无法修改。

## 前置条件

在开始安装前，确认以下条件满足：

1. **Python 3.11+** — 运行 `python --version` 确认
2. **思源笔记已启动** — 思源需要在前台或后台运行，默认端口 6806
3. **思源 API Token** — 从思源获取（见下方）
4. **Windows 系统** — 当前内测版仅支持 Windows

### 获取思源 API Token

引导用户按以下步骤获取：
1. 打开思源笔记
2. 点击右上角 **设置** → **关于**
3. 找到 **API Token**，点击 **复制**
4. 把 Token 粘贴给你（**不要在对话中复述 token**）

如果用户不知道端口号，默认就是 `6806`。思源笔记固定使用此端口。

## 安装步骤

### 步骤 1：确定安装目录

默认安装目录：
```
%LOCALAPPDATA%\siyuan-agent-bridge
```

通常展开为 `C:\Users\<用户名>\AppData\Local\siyuan-agent-bridge`。

使用 `%LOCALAPPDATA%` 的好处：
- CC Switch 等中转平台可以从该目录自动发现插件
- 目录稳定，不会因解压到 Downloads 后文件移动而失效

如果用户已有的 AI 配置指向其他目录，沿用已有目录。

### 步骤 2：解压文件

将 ZIP 包解压到安装目录。解压后目录结构应如下：

```
%LOCALAPPDATA%\siyuan-agent-bridge\
├── source_code/                  # Python 适配层
│   ├── client.py
│   ├── config.py
│   ├── indexer.py
│   ├── ignore.py
│   ├── i18n.py
│   ├── agent_notebook.py
│   ├── cli.py
│   └── mcp_server.py
├── plugins/
│   └── siyuan-agent-bridge/
│       ├── .mcp.json             # MCP 注册配置（CC Switch 兼容）
│       ├── .codex-plugin/
│       │   └── plugin.json       # Codex 插件清单
│       ├── skills/
│       │   ├── siyuan-agent-bridge/
│       │   │   ├── SKILL.md
│       │   │   └── plugin.json
│       │   └── siyuan-index-builder/
│       │       ├── SKILL.md
│       │       └── plugin.json
│       └── scripts/
│           └── run_mcp.py        # MCP stdio 启动脚本
├── mcp_configs/                  # 多平台 MCP 配置模板（参考用）
├── config.example.json           # 配置示例
├── install.bat                   # 人工安装脚本
├── doctor.bat                    # 诊断脚本
├── INSTALL_FOR_AI.md             # 本文件
├── PROMPT_FOR_AI_INSTALL.md      # 用户可复制给 AI 的提示词
└── README.md                     # 项目说明（给人看）
```

**不要创建以下目录**——它们由程序运行时自动生成：`knowledge_base/`、`ai_workspace/`。

### 步骤 3：创建配置文件

在安装目录下创建 `config.local.json`：

```json
{
  "profiles": [
    {
      "name": "主工作空间",
      "token": "<用户提供的token>"
    }
  ],
  "language": "zh-CN"
}
```

**安全要求**：
- 不要在对话中复述 token。
- 不要把 token 写入日志、README 或任何会被上传/提交的位置。
- `config.local.json` 只保存在本地安装目录，不打包进 ZIP。

如果用户有多个思源工作空间（不同端口或 token），可配置多个 profile：

```json
{
  "profiles": [
    {
      "name": "主工作空间",
      "token": "<token1>"
    },
    {
      "name": "测试工作空间",
      "token": "<token2>"
    }
  ],
  "language": "zh-CN"
}
```

运行时系统会自动检测哪个工作空间在线。

也可以使用环境变量（不写入文件）：
- `SIYUAN_TOKEN` — API Token
- `SIYUAN_AGENT_LANGUAGE` — 语言偏好（`zh-CN` / `en`）

### 步骤 4：运行诊断

```bash
cd /d %LOCALAPPDATA%\siyuan-agent-bridge
python -m source_code doctor
```

预期输出：
```
[ok] 主工作空间 (http://127.0.0.1:6806) SiYuan version: x.x.x
```

如果输出 `No configured SiYuan workspace responded.`：
- 确认思源笔记正在运行
- 确认 Token 正确（设置 → 关于 → API Token）
- 确认端口为 6806

### 步骤 5：注册 MCP

根据用户使用的 AI 客户端，选择对应的注册方式。

#### CC Switch（推荐）

CC Switch 是 Claude Code 插件管理工具。如果用户使用 CC Switch：

**方式 A：自动发现**（如果 CC Switch 支持插件目录扫描）
将 `%LOCALAPPDATA%\siyuan-agent-bridge\plugins\siyuan-agent-bridge\` 添加到 CC Switch 的插件目录列表。

**方式 B：手动导入**
1. 打开 CC Switch 界面
2. 进入"新增 MCP" → "自定义"
3. 填入以下配置（替换用户名）：

```json
{
  "type": "stdio",
  "command": "python",
  "args": [
    "C:\\Users\\<用户名>\\AppData\\Local\\siyuan-agent-bridge\\plugins\\siyuan-agent-bridge\\scripts\\run_mcp.py"
  ],
  "env": {
    "PYTHONUTF8": "1"
  }
}
```

#### Claude Code（VS Code 插件）

在项目根目录或 VS Code 用户设置中创建/编辑 `.mcp.json`：

```json
{
  "mcpServers": {
    "siyuan-agent-bridge": {
      "command": "python",
      "args": [
        "C:\\Users\\<用户名>\\AppData\\Local\\siyuan-agent-bridge\\plugins\\siyuan-agent-bridge\\scripts\\run_mcp.py"
      ],
      "env": {
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

#### Claude Code（桌面版）

编辑 Claude Code 桌面版的 MCP 配置文件（通常在 `%APPDATA%\Claude\mcp_servers.json` 或类似路径）：

```json
{
  "mcpServers": {
    "siyuan-agent-bridge": {
      "command": "python",
      "args": [
        "C:\\Users\\<用户名>\\AppData\\Local\\siyuan-agent-bridge\\plugins\\siyuan-agent-bridge\\scripts\\run_mcp.py"
      ],
      "env": {
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

#### Codex

Codex 通过 `.codex-plugin/plugin.json` 发现 MCP。解压后 `plugins/siyuan-agent-bridge/.codex-plugin/plugin.json` 已包含完整注册信息。在 Codex 中添加此插件目录即可。

#### 其他客户端

参考 `mcp_configs/` 目录中的配置模板。所有客户端所需的命令相同：
- **command**: `python`
- **args**: `[安装目录的 run_mcp.py 绝对路径]`
- **env**: `{"PYTHONUTF8": "1"}`

### 步骤 6：安装 Skill（可选但推荐）

Skill 提供 AI 使用知识库的工作流指引。Skill 压缩包可在 `dist/` 目录找到（`siyuan-agent-bridge-skill-*.zip`）。

**对于 CC Switch 用户**：
在 CC Switch 中导入 Skill zip 包。

**对于 Claude Code 用户**：
将 Skill 目录复制到 Claude Code 的 skills 目录，或通过 CC Switch 导入。

**Skill 列表**：
- `siyuan-agent-bridge` — 总入口 Skill：如何使用思源知识库
- `siyuan-index-builder` — 专项 Skill：创建语义导航索引

### 步骤 7：验证安装

安装完成后，告诉用户：

1. 重启 AI 客户端（确保 MCP 新注册生效）
2. 在新会话中对 AI 说："帮我查一下笔记"
3. AI 应自动触发 `siyuan_start`，返回笔记本概览

如果 AI 说"我无法访问思源"或类似提示：
- 确认 MCP 注册正确
- 运行 `python -m source_code doctor` 确认思源连接正常
- 参考 `mcp_configs/` 目录中的配置模板检查配置
- 确认思源笔记正在运行

## 安全规则

作为 AI Agent，在安装过程中你必须遵守：

1. **不要在对话中复述 token**。Token 是敏感信息，只在写入 `config.local.json` 时使用。
2. **不要将 token 写入其他文件**。Token 只存在于 `config.local.json` 中。
3. **不要上传 token**。`config.local.json` 已被 Git 忽略，不要提交到版本控制。
4. **安装完成后提醒用户**：`config.local.json` 包含思源 API Token，请不要分享或上传。
5. **不要以任何形式记录用户的隐私规则**。隐私规则文档由 MCP 硬编码保护，你不应尝试绕过。
