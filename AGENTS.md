# Agent Instructions

This is a private, read-only adapter for using the owner's SiYuan notes as an AI knowledge base.

## Reading Order

1. Read `kb_cache/guide.md` first.
2. Read `kb_cache/tree.md` to inspect the note structure.
3. Use `python -m siyuan_kb find <keyword>` to locate candidate documents.
4. Use `python -m siyuan_kb read <doc-id>` when full document Markdown is needed.
5. Put derived analysis, task context, drafts, and outputs in `ai_workspace/`.

## Hard Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not commit or print API tokens.
- Treat `kb_cache/` and `ai_workspace/` as private personal data.

## Useful Commands

```bash
python -m siyuan_kb doctor
python -m siyuan_kb notebooks
python -m siyuan_kb refresh
python -m siyuan_kb tree
python -m siyuan_kb find <keyword>
python -m siyuan_kb read <doc-id>
```
