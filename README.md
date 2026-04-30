# SiYuan Enhance

[中文说明](README.zh-CN.md)

SiYuan Enhance is a private, local-first adapter that lets external AI agents use your SiYuan notes as a structured personal knowledge base.

It is not a SiYuan plugin, not a public package, and not a vector-search system. Your notes stay in SiYuan. This project creates safe read-only indexes and exposes controlled CLI / MCP tools for AI agents.

## Current Capabilities

- Scans SiYuan notebooks and the full document tree, including child documents.
- Hides notebooks, single documents, or document subtrees through `siyuan.ignore.local.json`.
- Temporarily opens hidden items through `siyuan.allow.local.json`.
- Generates safe indexes, overview files, and notebook maps under `knowledge_base/`.
- Provides MCP tools for Claude Code, Codex, OpenCode, and similar agents.
- Chunks long documents. The default chunk size is 10,000 characters and can be adjusted with `max_chars`.
- Preserves Markdown image references inside document chunks, so image-heavy notes keep surrounding text context.
- Supports CC Switch skill import and MCP registration.

## Normal Workflow

Most of the time, the human user does not need to use the command line.

You mainly maintain:

- `knowledge_base/guide.md`: the curated reading guide for AI agents.
- `siyuan.ignore.local.json`: long-term hide rules.
- `siyuan.allow.local.json`: temporary allow rules.
- `ai_workspace/`: agent-generated analysis, task context, drafts, and outputs.

Typical flow:

1. Write notes in SiYuan as usual.
2. Edit `siyuan.ignore.local.json` if some content should be hidden.
3. Ask the AI agent to refresh the knowledge-base index.
4. The agent calls `siyuan_refresh_index` or runs `python -m source_code refresh`.
5. The AI only sees the visible safe index after refresh.

## Agent Startup

When MCP is available, the agent should call:

```text
siyuan_start
```

This checks the local SiYuan service and returns the existing startup packet. It does not refresh indexes.

If MCP is unavailable, run this from the repository root:

```bash
python -m source_code start
```

## MCP Tools

- `siyuan_start`: check SiYuan connectivity and return the startup packet.
- `siyuan_refresh_index`: refresh safe indexes when the user asks, the index is missing, or it is clearly stale.
- `siyuan_list_notebooks`: list visible notebooks from the safe index.
- `siyuan_list_documents`: read an existing notebook map.
- `siyuan_find_documents`: find visible documents by keyword.
- `siyuan_read_document`: read a document preview; long documents return chunk guidance instead of the whole text.
- `siyuan_describe_document_chunks`: return a chunk map for a long document.
- `siyuan_read_document_chunk`: read one numbered chunk while preserving local text and image references.
- `siyuan_propose_guide_update`: save a proposed guide update in `ai_workspace/`.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval.

## Long Documents And Images

Long documents are not returned in one large MCP response, because clients and model UIs may truncate the output.

Default chunk size:

```text
10,000 characters
```

Agents can pass `max_chars` to adjust the size. The current range is 2,000 to 30,000 characters.

Recommended flow:

1. Call `siyuan_read_document` for a preview.
2. If the document is long, call `siyuan_describe_document_chunks`.
3. Choose relevant chunks from the chunk map.
4. Call `siyuan_read_document_chunk` for those chunks.

Image references remain in place, for example:

```md
![image](assets/image-xxx.png)
```

This keeps mixed text/image notes usable because the image stays near its surrounding explanation.

## Ignore Rules

Open:

```text
siyuan.ignore.local.json
```

Hide a notebook:

```json
{
  "scope": "notebook",
  "name": "Notebook Name",
  "reason": "Hide this notebook."
}
```

Hide one document:

```json
{
  "scope": "document",
  "id": "document-id",
  "reason": "Hide exactly this document."
}
```

Hide one document and all child documents:

```json
{
  "scope": "subtree",
  "id": "root-document-id",
  "reason": "Hide this document and all children."
}
```

After editing, ask the AI agent to refresh the index. Previously visible documents that now match ignore rules are removed from the regenerated `knowledge_base/` index.

## CC Switch

The latest skill zip is:

```text
dist/siyuan-knowledge-skill-latest.zip
```

For MCP registration, use this custom stdio config:

```json
{
  "type": "stdio",
  "command": "python",
  "args": [
    "D:\\Github\\siyuan-enhance\\plugins\\siyuan-knowledge\\scripts\\run_mcp.py"
  ],
  "env": {
    "PYTHONUTF8": "1"
  }
}
```

Reference files:

```text
dist/siyuan-knowledge-mcp.json
dist/siyuan-knowledge-mcp-deeplink.txt
```

## Project Structure

```text
siyuan-enhance/
  AGENTS.md                  # Rules for AI agents
  START_HERE.md              # Agent entrypoint
  README.md                  # English documentation
  README.zh-CN.md            # Chinese documentation
  config.example.json        # Config example
  config.local.json          # Local token, ignored by Git
  siyuan.ignore.local.json   # Long-term hide rules
  siyuan.allow.local.json    # Temporary allow rules
  source_code/               # Python tool code
  plugins/siyuan-knowledge/  # Skill and MCP plugin materials
  knowledge_base/            # Generated safe indexes
  ai_workspace/              # Agent workspace
  tests/                     # Tests
```

Main generated files:

- `knowledge_base/guide.md`: human-maintained knowledge-base guide.
- `knowledge_base/overview.md`: top-level overview.
- `knowledge_base/tree.md`: full document tree. Agents should not scan it by default.
- `knowledge_base/docs.jsonl`: document-level index.
- `knowledge_base/notebooks.json`: notebook index.
- `knowledge_base/notebooks/`: per-notebook document maps.

Main code modules:

- `source_code/client.py`: read-only SiYuan API client.
- `source_code/indexer.py`: scanning and index generation.
- `source_code/ignore.py`: privacy ignore and temporary allow rules.
- `source_code/cli.py`: CLI entrypoint.
- `source_code/mcp_server.py`: MCP stdio server.

## Privacy Model

This project is designed as a private project.

- Do not commit tokens.
- Do not publish `knowledge_base/` or `ai_workspace/` unless personal content has been cleaned.
- Agents should not read `config.local.json`, `siyuan.ignore.local.json`, or `siyuan.allow.local.json` unless explicitly asked.
- Agents must not modify SiYuan notes or call SiYuan write APIs.

If this project ever becomes public, redesign the privacy model and remove personal note indexes and workspace material first.
