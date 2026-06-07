# MCP 配置模板

本目录包含各 AI 客户端/平台的 MCP 注册配置模板。配置中的路径使用占位符 `<INSTALL_DIR>`，AI Agent 或用户在安装时替换为实际安装目录的绝对路径。

安装目录由用户在安装时选择，无固定默认值。

## 支持的客户端

| 文件 | 客户端 | 说明 |
|------|--------|------|
| `cc-switch.json` | CC Switch | Claude Code 插件管理工具 |
| `claude-code-vscode.json` | Claude Code VSCode 插件 | 项目级 `.mcp.json` |
| `claude-code-desktop.json` | Claude Code 桌面版 | 全局 MCP 配置 |

| `openclaw.json` | OpenClaw | 通过 MCP 配置文件注册 |

## 通用配置格式

所有客户端使用相同的 MCP stdio 配置，只需替换路径：

```json
{
  "mcpServers": {
    "siyuan-bridge": {
      "command": "python",
      "args": [
        "<INSTALL_DIR>\\plugins\\siyuan-bridge\\scripts\\run_mcp.py"
      ],
      "env": {
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

- `PYTHONUTF8` 环境变量确保 Python 输出使用 UTF-8 编码，防止中文路径或内容出现编码问题。

## 注意事项

- MCP 配置中的 `args` 必须使用**绝对路径**，不支持相对路径或环境变量展开（`%LOCALAPPDATA%` 在 JSON 中不会自动展开）。
- 安装后务必**重启 AI 客户端**，MCP 注册才能生效。
- 如果 Python 在 PATH 中不可用，将 `"command": "python"` 替换为 Python 可执行文件的绝对路径（如 `C:\\Python311\\python.exe`）。
