# 提示词：让 AI 帮你安装 SiYuan Agent Bridge

将以下提示词复制给你的 AI Agent（Claude Code、Codex 等），AI 会自动完成安装配置。

## 提示词模板

复制下面这段文字，填入你的信息后发给 AI：

---

请帮我安装 SiYuan Agent Bridge。ZIP 文件在：

**[填写 ZIP 文件路径，例如：D:\Downloads\siyuan-agent-bridge-release-20260503.zip]**

安装信息：
- 工作空间名称：**[填写，例如：主工作空间]**
- 思源端口：**6806**（默认）
- 思源 API Token：**[填写，在思源 → 设置 → 关于 → API Token 中复制]**
- 我使用的 AI 工具：**[填写：CC Switch / Claude Code VSCode / Claude Code 桌面版 / Codex / 其他]**

请按照 INSTALL_FOR_AI.md 完成安装。注意安全：不要在对话中复述我的 token。

---

## 你需要准备什么

1. **思源笔记已启动**（前台或后台均可）
2. **知道 API Token**：思源 → 设置 → 关于 → API Token → 复制
3. **知道端口号**：默认 6806。如果有自定义，在思源 → 设置 → 关于 → 网络服务中查看
4. **知道 ZIP 文件路径**：下载到哪了
5. **知道用什么 AI 工具**：CC Switch、Claude Code、Codex 等

## 安装后会发生什么

1. AI 把工具解压到稳定目录
2. AI 创建配置文件（含 token）
3. AI 运行诊断确认思源连接正常
4. AI 注册 MCP（让你后续所有会话都能用）
5. AI 安装 Skill（可选，给 AI 使用知识库的工作流指引）
6. 你**重启 AI 客户端**，下次说"帮我查笔记"就能用了
