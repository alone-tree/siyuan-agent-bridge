# SiYuan Bridge

![](icon.png)

Give your AI agent safe read, search, and edit access to your SiYuan notes.

---

## Highlights

### Efficient: Built for the AI Coding Mindset

Core tools mirror the programming tools you already know, while respecting SiYuan's block structure design.

| Tool | What it does | Analogy |
|------|-------------|---------|
| `siyuan_start` | Injects your notebook index and preferences | `CLAUDE.md` |
| `siyuan_list` | List notebooks and document trees | `ls` |
| `siyuan_find` | Search your knowledge base | `grep` |
| `siyuan_read` | Read documents in blocks, with outline and block ID references | `read` |
| `siyuan_edit` | Edit documents: single/multi-block replace, table cell editing | `edit` |
| `siyuan_create` | Create or overwrite documents | `write` |
| `siyuan_doc_manage` | Rename, move, delete, copy, export | file manager |

Every tool wraps multiple low-level SiYuan APIs — precise operations with fewer chances for errors. Editing your notes feels as natural as editing code, without giving up SiYuan's block-level structure.

No kitchen-sink MCP. Just the tools you actually use every day.

### Human in the Loop

Privacy rules and AI preferences live right inside your SiYuan notes — no config files to hunt down:

- **Privacy Rules**: Edit the rules document directly in your notebook. Changes take effect after telling the AI to "refresh". The AI cannot see or modify the rules themselves. Note: closed notebooks are NOT hidden from AI — they are transparently opened for search and reading, then closed again. To truly hide a notebook, add it to the hidden list or set it to read-only in your privacy rules.
- **AI Guide**: Tell the AI your preferences and rules right inside SiYuan. Edit anytime, effective immediately.
- **Workspace Index**: An AI-generated navigation map of your notebooks. You can review, edit, and annotate it to help the AI locate knowledge more accurately.

You're always in control.

### Stable and Hassle-Free

- **MCP decoupled from SiYuan**: The MCP server registers successfully whether SiYuan is running or not. Close SiYuan anytime — it won't break your tools. Open it when you need it.
- **Zero dependencies**: Python standard library only. No third-party packages. Python 3.11+ is all you need.
- **One-click setup**: The plugin reads your workspace token, generates the MCP JSON — copy, paste, done.
- **Permission inheritance**: Privacy rules cascade down — a read-only parent makes all children read-only; a hidden parent hides the entire subtree. Deleting a child checks upward: if the parent is read-only, the child can't be deleted. To modify read-only content, the AI can copy it to a writable location first. You can also temporarily change permissions to read-write in your privacy rules, then revert when done.
- **Closed notebooks are still searchable**: Closed notebooks represent accumulated knowledge — just not currently active, not worthless. SiYuan Bridge transparently opens closed notebooks for search and reading, then closes them afterward. To truly block AI access, use the hidden list or set to read-only in your privacy rules.

---

## Use Cases

**Let AI organize your knowledge base**: After reading your notes, AI can rewrite documents, add tags, restructure folders — refactoring your notes the way you refactor code.

**Cross-document synthesis**: AI reads multiple related notes at once and gives you a comprehensive answer with block-indexed evidence, not just document titles.

---

## Installation

1. Search "SiYuan Bridge" in the SiYuan bazaar and install the plugin
2. Save your workspace token in the plugin settings page
3. Copy the generated MCP JSON to your AI client
4. Restart your AI client and say "search my notes for XXX"

**Requirements**: Python 3.11+, SiYuan running.

---

## Not Yet Supported

- **Mobile** — Local Python program, not applicable to mobile platforms
- **Database (SiYuan Database)** — Read-only rendered as tables; editing not yet supported
- **Flashcards, tags, block styling** — Not core to knowledge base editing; will be added as needed

---

## FAQ

- **Does it support multiple workspaces?** Yes. Don't install the plugin in every workspace — the AI would see duplicate MCP tools. Install in your primary workspace and manually add tokens for other workspaces in the plugin settings. Privacy rules, AI Guide, etc. are stored per workspace and follow automatically. Note: only one workspace can run at a time. To switch: 1) open the target workspace, 2) close other workspaces, 3) close the target workspace, 4) restart SiYuan. The four-step process is needed because the first-launched workspace uses a fixed port, while subsequent ones get random ports that are hard to auto-detect.
- **"SiYuan not running" error**: Open the SiYuan desktop app and confirm the correct workspace. If SiYuan is already running, the issue may be with the AI agent or network proxy — try restarting the AI agent. Claude Code is known to occasionally lose MCP tools under certain conditions (e.g., opening Claude Code with a VPN on, then turning it off).
- **AI can't see the tools after setup**: Verify the MCP JSON was copied to the correct client in the right format, then restart the client. Different AI agents have slightly different MCP registration formats — currently only the Claude Code format is provided; more will be added. You can also ask the AI to adjust the format for you.
- **Does it upload my notes?** No. The telemetry program only records version info, tool names, duration, success/failure, and error types — used to identify frequently-used but error-prone features for targeted improvement. No note content or conversation content is ever uploaded. Telemetry is off by default; you can also choose local-only storage for your own analysis.
- **Content disappears / conflicts / crashes after editing**: This happens when the same workspace is open on two computers with auto cloud sync enabled. Switch to manual sync (sync only on startup and shutdown).
- **Snapshots not created before editing**: Also caused by auto cloud sync. Cloud sync generates snapshots automatically, which can cause the pre-edit snapshot check to see "no changes" and skip creating one. Switch to manual sync (sync only on startup and shutdown).
- **Will snapshots bloat over time?** A snapshot is created before every edit, so the count grows with frequent use. SiYuan has built-in automatic cleanup (keeps 2 per day, deletes after 180 days), but it only triggers if cloud sync is enabled. If you use a local workspace without cloud sync, periodically go to Settings → Data Repo → Purge to manually clean up. A snapshot cleanup feature is under development and will handle this automatically in a future version.
- **What can siyuan_doc_manage do?** It mirrors SiYuan's native document management. Rename, copy, and export work on a single document. Move and delete work on the entire document subtree (the document and all its children) — consistent with SiYuan's own behavior.

---

## Feedback

- Community discussion: [ld246.com](https://ld246.com/article/1777909344378)
- Bugs or ideas? Open an [issue or PR on GitHub](https://github.com/alone-tree/siyuan-bridge), or just tell the AI to "submit feedback" — SiYuan Bridge has a built-in feedback tool.
- Visit my [personal site](https://zingerplayground.top/) (perpetually under renovation)

If this project helps you, give it a Star, or consider donating / sponsoring tokens.

![](../image/README/1778197765819.png)

---

## License

Apache-2.0
