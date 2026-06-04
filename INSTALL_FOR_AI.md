# SiYuan Agent Bridge — AI 安装指南

你是用户的 AI Agent。根据本文档将 SiYuan Agent Bridge 安装到用户计算机上。

## 这是什么

SiYuan Agent Bridge 是思源笔记的 MCP 适配层。它让你安全地读取、搜索和写入用户的思源笔记。隐私过滤在索引层完成，隐私规则由用户在思源 UI 中维护，你无法修改。

## 前置条件

安装前确认：

1. **Python 3.11+** — 运行 `python --version`
2. **思源笔记已启动** — 前台或后台均可
3. **思源 API Token** — 让用户在思源中点击 设置 → 关于 → API Token → 复制
4. **Windows 系统**（当前仅支持 Windows）

## 安装步骤

### 步骤 1：确定安装目录


显式询问用户安装位置。提供的选项有：
- 安装包所在位置（默认选项）。
- `%LOCALAPPDATA%\siyuan-agent-bridge`（展开为 `C:\Users\<用户名>\AppData\Local\siyuan-agent-bridge`）
- 其他指定位置

如果用户已在其他目录完成安装，沿用已有目录。

### 步骤 2：解压

将 ZIP 解压到安装目录。结构如下：

```
<安装目录>\
├── source_code/                  # Python 适配层
├── plugins/siyuan-agent-bridge/  # MCP 插件（含 skills/、scripts/）
├── mcp_configs/                  # 多平台 MCP 配置模板
├── config.example.json           # 配置示例
├── doctor.bat                    # 诊断脚本
├── INSTALL_FOR_AI.md             # 本文件
└── README.md                     # 项目说明（给人看）
```

不要创建 `knowledge_base/`、`ai_workspace/` — 由程序运行时自动生成。

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

多工作空间可配置多个 profile。系统自动检测哪个在线。

**安全**：不要在对话中复述 token。不要把 token 写入其他文件。`config.local.json` 已被 Git 忽略。

也可以使用环境变量 `SIYUAN_TOKEN` 替代配置文件（除非用户明确要求，否则不要使用环境变量）。

### 步骤 4：运行诊断

```bash
cd /d <安装目录>
python -m source_code doctor
```

预期输出 `[ok] 主工作空间 SiYuan version: x.x.x`。

如果失败：向用户确认思源运行中、Token 正确、端口 6806 未被占用。

### 步骤 5：注册 MCP

根据用户的 AI 客户端选择配置。本质相同：command 为 `python`，args 为 `run_mcp.py` 的绝对路径，env 设置 `PYTHONUTF8=1`。

配置模板在 `mcp_configs/` 目录（cc-switch.json、claude-code-vscode.json、claude-code-desktop.json、openclaw.json）。替换其中的用户名路径即可。

### 步骤 6：验证

告诉用户：

1. 重启 AI 客户端（MCP 注册需重启生效）
2. 在新会话中说"帮我查一下笔记"
3. AI 应触发 `siyuan_start`，返回笔记本概览

当前版本可用的思源桥 MCP 工具应为：

```text
siyuan_start
siyuan_refresh_index
siyuan_list
siyuan_find
siyuan_read
siyuan_create
siyuan_edit
siyuan_doc_manage
```

如果用户是覆盖安装新版，通常只需要在 AI 客户端中新建会话即可加载最新 MCP 工具面。若工具列表仍不正确，再重启 AI 客户端。

简单读写验证：

1. 调用 `siyuan_start`
2. 用 `siyuan_list` 找到一个可见笔记本
3. 用 `siyuan_create` 创建一篇测试文档，`confirmed=true`
4. 用 `siyuan_read(include_block_ids=true)` 读取测试文档
5. 用 `siyuan_edit` 追加或修改一小段文本，`confirmed=true`
6. 可用 `siyuan_doc_manage(action=export)` 验证文档导出

## 安全规则

1. 不要在对话中复述 token
2. 不要把 token 写入日志、README 或任何会上传的文件
3. 安装完成后提醒用户：`config.local.json` 包含 API Token，不要分享或上传
4. 不要尝试读取、搜索或修改隐私规则文档
![1777899861789](image/INSTALL_FOR_AI/1777899861789.zip)
