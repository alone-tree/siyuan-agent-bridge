# 插件前端

本文件只记录思源插件前端细节。前端与 Python Bridge、Worker 后端的架构关系写在 `ARCHITECTURE.md`。

## 当前入口

- 思源实际加载：`siyuan-plugin/index.js`。
- 源码参考：`siyuan-plugin/src/index.js`。
- 样式：`siyuan-plugin/index.css`。
- 插件清单：`siyuan-plugin/plugin.json`。

根 `index.js` 必须保持 CommonJS：`require("siyuan")`、`module.exports`。不要改成 `import` / `export default`，否则思源桌面端会报 `Cannot use import statement outside a module`，插件加载失败，设置齿轮消失。

## UI 结构

插件设置入口打开 Home Dialog，包含：

- 通知：GET Worker `/api/notifications`。
- MCP 配置：展示 Python 命令、Bridge 路径、MCP JSON 和 profiles。
- 反馈：POST Worker `/api/feedback`。
- 用户体验改进：读写 `bridge/telemetry.json` 中的 `telemetry`。

## 配置文件

- `bridge/config.local.json`：profiles、Token、语言。Token 不写入 MCP JSON。
- `bridge/telemetry.json`：匿名 ID、遥测开关、端点、代理。

首次启用插件时，前端从思源 `/api/system/getConf` 读取当前工作空间 Token 和路径，并在缺失配置时自动创建 `config.local.json`。

## 验证

不要直接改测试工作空间里的插件代码。先改仓库 `siyuan-plugin/`，再导入：

```bat
python scripts\import_siyuan_plugin.py --workspace %SIYUAN_TEST_WORKSPACE%
```

模拟首次安装：

```bat
python scripts\import_siyuan_plugin.py --workspace %SIYUAN_TEST_WORKSPACE% --fresh
```

最低检查：

- 插件能启用，设置齿轮存在。
- 首次启用能生成 `bridge/config.local.json`。
- MCP JSON 不包含 Token。
- Home Dialog 的通知、反馈、遥测开关不会阻塞 MCP 配置。
