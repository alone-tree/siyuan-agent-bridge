# 插件前端页面设计（未实现）

## 关联文档

后端基础设施（Worker + D1）见 `docs/telemetry-design.md`。
MCP 工具 `siyuan_feedback` 见下方描述，实现该工具时参考 `docs/ARCHITECTURE.md` 的 MCP 工具契约。

---

## 动机

思源桥插件目前只有一个全配置页面，点击顶部工具栏齿轮图标直接打开。没有首页入口，也没有消息通知和用户反馈的展示位置。

需要将插件前端改为两层结构，把消息通知和用户反馈放在首页，配置页作为次级页面。

---

## 架构

```
+-----------------------------------------------------------------+
|  思源笔记顶部工具栏                                                |
|  [齿轮图标 · 思源桥]                                              |
+-----------------------------------------------------------------+
         |
         v
+-----------------------------------------------------------------+
|  第一层：MCP 首页（Dialog）                                        |
|                                                                  |
|  [消息通知区域]                                                    |
|  ┌─────────────────────────────────────────────────────────────┐  |
|  │ 从远端拉取通知列表，每项标题 + 链接（可点击跳转）                │  |
|  │ 每次打开都刷新，已读不隐藏                                     │  |
|  │ 无通知时显示空白或"暂无新消息"                                  │  |
|  └─────────────────────────────────────────────────────────────┘  |
|                                                                  |
|  [提交反馈区域]                                                    |
|  ┌─────────────────────────────────────────────────────────────┐  |
|  │ 反馈类型：下拉选（bug / 功能建议 / 想法）                      │  |
|  │ 标题：文本框                                                  │  |
|  │ 描述：文本框（多行）                                           │  |
|  │ 联系方式：文本框（可选）                                       │  |
|  │ [提交] 按钮 → POST 到 Worker                                  │  |
|  └─────────────────────────────────────────────────────────────┘  |
|                                                                  |
|  [MCP 配置] 按钮 → 打开第二层设置 Dialog                           |
+-----------------------------------------------------------------+
         |
         v  （点击" MCP 配置"按钮）
+-----------------------------------------------------------------+
|  第二层：MCP 配置（Dialog）                                        |
|                                                                  |
|  当前 renderSettings() 的全部内容：                                |
|  - Python 命令、Server 名称                                       |
|  - 插件目录、Bridge 目录、MCP 启动脚本                              |
|  - 工作空间 Profiles（添加/删除）                                  |
|  - MCP JSON 预览 + 复制按钮                                       |
|  - 保存 / 刷新按钮                                                |
|                                                                  |
|  [返回首页] 按钮（关闭当前 Dialog，回到首页）                        |
+-----------------------------------------------------------------+
```

---

## 数据流

### 消息通知

- 每次打开首页时，JS 发送 GET 请求到 Worker 通知端点
- 端点返回 JSON：{ "notifications": [ { "id": "...", "title": "...", "url": "..." } ] }
- 空白数组或请求失败时，首页显示"暂无新消息"
- 通知由你在 D1 中插入数据管理，不需要用户操作
- 通知一直显示，不标记已读

### 提交反馈

- 用户在首页填写反馈表单，点击提交
- JS POST 到 Worker 反馈端点
- 成功后 showMessage("反馈已提交，感谢你的建议")
- 失败时 showMessage("提交失败，请稍后重试")
- 反馈存储到 D1 feedbacks 表

### 通知端点（Worker GET /api/notifications）

```json
{
  "notifications": [
    {
      "id": "v0.3.0",
      "title": "思源桥 v0.3.0 已发布",
      "url": "https://github.com/alone-tree/siyuan-bridge/releases/tag/v0.3.0"
    }
  ]
}
```

通知数据可以硬编码在 Worker 代码中（简单，改动需重新部署），也可以存在 D1 表中（灵活，在 D1 里 INSERT 即可，不需要重新部署）。建议先用 D1 表，一个 sqlite 表加几条记录即可，不值当再去单独弄配置存储方案：

```sql
CREATE TABLE notifications (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

你手动 INSERT 新通知：

```sql
INSERT INTO notifications (id, title, url, created_at)
VALUES ('v0.3.0', '思源桥 v0.3.0 已发布', 'https://github.com/alone-tree/siyuan-bridge/releases/tag/v0.3.0', datetime('now'));
```

GET /api/notifications 直接 SELECT * FROM notifications ORDER BY created_at DESC 返回即可。

### 反馈端点（Worker POST /api/feedback）

接收字段：type、title、description、contact（可选）

```sql
CREATE TABLE feedbacks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  contact TEXT
);
```

---

## 反馈的 MCP 工具

除了首页表单，还应提供一个 MCP 工具 `siyuan_feedback`，让 AI 也能通过对话提交反馈。

工具参数：
- type：enum，bug / feature / idea
- title：string
- description：string
- contact：string，可选

实现位置：在 source_code/mcp_server.py 中新增。数据流与首页反馈一致：POST 到同一个 Worker 端点。

---

## 前端代码位置

- `siyuan-plugin/src/index.js` — 主逻辑（插件类、弹窗、事件绑定）
- `siyuan-plugin/index.css` — 样式
- 构建产物：`siyuan-plugin/dist/index.js`（webpack 打包后的结果，实际加载的是这个，实现后需要重新构建部署，或者直接在思源笔记插件目录中替换 dist 文件。目前插件目录里安装运行的是 D:\Siyuan2test\data\plugins\siyuan-bridge\ 下的 dist 文件和 index.js 文件，而 GitHub 仓库中的 siyuan-plugin/ 是源代码所在目录。两者是同一个插件的不同副本，以实际运行的那个为准，在同步版本时需要保持两者一致。以后实现时待确认具体同步流程。）

---

## 当前状态

设计阶段。尚未实现任何代码。

第一阶段（基础改造）：
1. 首页 Dialog：标题改为"思源桥"，展示消息通知区域 + 提交反馈表单 + MCP 配置入口按钮
2. 配置页 Dialog：现有内容但标题改为"MCP 配置"，加上返回按钮
3. 通知从远端 GET 获取，无通知时静默
4. 反馈表单 POST 到远端

第二阶段（MCP 工具）：
1. 新增 siyuan_feedback 工具
2. 文档化工具契约

第三阶段（Worker 端点）：
1. GET /api/notifications
2. POST /api/feedback
3. D1 建表
