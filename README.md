# SiYuan Enhance

Private, local-first tooling for letting external AI agents read a SiYuan knowledge base.

This project is intentionally small: it does not implement vector search, a SiYuan plugin, public packaging, or write-back workflows. It reads the local SiYuan API, creates structured local indexes, and lets agents decide what to inspect next.

## Setup

1. Start SiYuan on this Windows machine.
2. Copy `config.example.json` to `config.local.json`.
3. Fill in the API token, or set `SIYUAN_TOKEN` in the environment.
4. Run:

```bash
python -m siyuan_kb doctor
python -m siyuan_kb refresh
```

Generated indexes live in `kb_cache/`. Agent-generated working files live in `ai_workspace/`.

`config.local.json` and tokens are ignored by Git. `kb_cache/` and `ai_workspace/` are intentionally not ignored because this repository is currently treated as private.
