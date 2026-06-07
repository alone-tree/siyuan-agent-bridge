# 常见问题与故障排除

## MCP 工具全部不可用（连接超时）

**症状：** 所有思源桥 MCP 工具返回"timed out"或"思源未启动"，但思源笔记确实在运行。

**已知缺陷：** 如果你在打开 Claude Code（或 MCP 进程启动）之后切换了 VPN 状态，MCP 子进程可能进入异常状态，导致本地 `127.0.0.1` 连接超时。

**解决方法：** **重启 Claude Code**（完全关闭后重新打开）。这会重新创建 MCP server 进程，恢复正常。

> 此问题是 Claude Code 的 MCP 进程管理行为，与思源桥代码无关。思源桥的 SiYuan 客户端直连 `127.0.0.1:6806`，不使用代理。

---

## 遥测/反馈功能在中国大陆无法使用

**原因：** 遥测 Worker 托管在 `siyuan-bridge-telemetry.864271839.workers.dev`。`.workers.dev` 域名在中国大陆被 DNS 污染且 IP 阻断。

**解决方法：**

1. **使用 VPN/代理：** 开启 Clash、V2Ray 等代理工具（系统代理或 TUN 模式）。Python 端会自动探测系统代理。

2. **自定义域名：** 如果你有自己的域名并绑定了 Worker，可以在 `telemetry.json` 中手动配置：
   ```json
   {
     "telemetry": "upload",
     "telemetry_endpoint": "https://your-custom-domain.com"
   }
   ```

---

## 遥测数据不准确（"ok" 字段的含义）

**说明：** 遥测事件中的 `ok` 字段表示工具调用**是否抛出异常**，而非用户目标是否达成。

例如：`siyuan_bridge_feedback` 在网络不可达时返回 `ok: 1`，因为工具正常返回了错误提示文案，没有崩溃。但反馈实际上未送达。

这是一个已知的遥测精度问题，后续版本会细化错误分类。

---

## `telemetry.json` 文件损坏

**症状：** 遥测复选框状态异常，或文件内容包含 `{"code":404,...}` 等 API 错误残留。

**原因：** 早期版本的 bug 导致 SiYuan API 错误 JSON 被错误写入配置文件。

**解决方法：**
1. 删除 `bridge/telemetry.json`
2. 在思源笔记插件首页重新勾选"加入用户体验改进计划"

---

## 思源笔记未启动

**症状：** MCP 工具返回"思源未启动或 API 不可达"。

**检查清单：**
1. 思源笔记桌面应用是否在运行？
2. 思源笔记打开的是否是正确的工作空间？
3. API Token 是否已配置？检查 `bridge/config.local.json` 中的 `token` 字段

---

## 遥测搜集了哪些数据？

每次 MCP 工具调用记录：工具名、子操作、成功/失败、耗时、错误类型、匿名设备 ID、操作系统、思源/思源桥版本。

**不搜集：** 笔记内容、文档 ID、块 ID、API Token、笔记本名称。

详见 [反馈与遥测后端参考](./feedback-telemetry-backend.md)。

---

## 如何查看本地遥测数据？

遥测事件本地存储在 `bridge/stats/events/YYYY-MM-DD.jsonl`，每行一个 JSON 对象。

匿名 ID 存储在 `bridge/stats/telemetry_id`。

---

## 如何查询远端遥测数据？

需要 Cloudflare 账号权限和 wrangler CLI。详见 [反馈与遥测后端参考](./feedback-telemetry-backend.md#开发者运维)。

---

## 相关文档

- [反馈与遥测后端参考](./feedback-telemetry-backend.md) — Worker API、D1 表结构、运维命令
- [遥测功能设计](./telemetry-design.md) — 完整的遥测系统设计文档
- [开发指南](./DEVELOPMENT_GUIDE.md) — 开发环境搭建与调试
