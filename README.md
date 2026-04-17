![Index](docs/Index.png)

# SelfIndex

SelfIndex is an alpha personal memory system focused on preserving source material, building searchable memory units, and keeping revision history for changing data.

It is not trying to be a general-purpose AI agent product yet. The current goal is to make the memory pipeline reliable:

- keep raw source material
- keep a current state plus revision history
- derive searchable memory units
- support local vector retrieval with traceability
- support browser-captured AI conversations and file-based imports

## Current Status

SelfIndex is suitable for local, personal use and ongoing experimentation.

It already supports:

- ChatGPT、Grok、DeepSeek export import
- ChatGPT browser capture with semi-automatic sync
- Grok browser capture with lazy-load snapshot merge
- Markdown directory sync
- revision-aware raw document storage
- local vector retrieval with trace-back to source documents
- protected recall domains and unlock-style queries
- SQLite / SQLCipher storage

It is still alpha software:

- browser capture depends on page structure and may break when sites change
- multi-platform support is still early
- conversation replay UX is not finished
- the desktop runtime is local-first and Windows-oriented

## Recommended Start Path

Use the unified service script. It now starts the desktop runtime, system tray icon, and web service together:

```powershell
.\scripts\selfindex_service.ps1 start
```

Useful commands:

```powershell
.\scripts\selfindex_service.ps1 status
.\scripts\selfindex_service.ps1 restart
.\scripts\selfindex_service.ps1 stop
```

If you only want the web service without the tray runtime:

```powershell
.\scripts\selfindex_service.ps1 start -NoTray
```

Default URLs:

- Web UI: `http://127.0.0.1:5000/`
- Browser ingest: `http://127.0.0.1:5000/api/ingest/browser-conversation`

## Main Workflows

### Import exported conversation files

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json
```

Skip embeddings during import:

```bash
python -m scripts.import_exports --file data/raw_exports/your_export.json --skip-embedding
```

Build embeddings later:

```bash
python -m scripts.build_embeddings
python -m scripts.build_embeddings --batch-size 16 --max-units 200
```

### Sync a Markdown directory

```bash
python -m scripts.sync_markdown_directory --dir path/to/notes --ignore-file path/to/notes/.selfindexignore --skip-embedding
```

Example `.selfindexignore`:

```text
archive/
templates/*
draft.md
```

### Manage protected terms

```bash
python -m scripts.manage_protected_terms list
python -m scripts.manage_protected_terms add "Sensitive text" --domain sensitive
python -m scripts.manage_protected_terms add "Real name" --domain identity
```

Backfill recall domains:

```bash
python -m scripts.backfill_recall_domains --dry-run
python -m scripts.backfill_recall_domains
```

### Browser capture

The browser extension lives in:

`browser_capture/ai_capture_extension`

Current browser support:

- ChatGPT: incremental sync for newly appended messages
- Grok: snapshot merge for lazy-loaded history

The extension currently targets local ingestion into the running SelfIndex instance.

## Retrieval Model

SelfIndex uses recall domains to control sensitive retrieval.

- default queries only retrieve `default`
- explicit prefixes unlock protected domains

Current prefixes are configured in `.env`:

```env
UNLOCK_PREFIX_IDENTITY=:
UNLOCK_PREFIX_SENSITIVE=!
```

## Documentation

Recommended reading order:

1. `docs/current-system.md`
2. `docs/architecture.md`
3. `docs/database-structure.md`
4. `docs/code-map.md`

## Running Tests

```bash
python -m unittest discover -s tests -v
```

## Project Positioning

SelfIndex is best described as:

- a local-first personal memory prototype
- a revision-aware archive plus retrieval system
- an active research and implementation repository

It should not yet be presented as a polished end-user product.
