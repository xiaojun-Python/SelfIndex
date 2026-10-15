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
- Windows tray and macOS desktop currently have separate entry points
- the macOS app and background service are still in development packaging

## Recommended Start Path

On macOS, sync dependencies and build the clickable development app:

```bash
uv sync
.venv/bin/python -m scripts.build_macos_dev_app
```

Open `dist-dev/SelfIndex.app` in Finder. It creates or wakes the per-user LaunchAgent when needed; you can also manage it manually:

```bash
.venv/bin/python -m scripts.macos_launch_agent install
.venv/bin/python -m scripts.macos_launch_agent status
.venv/bin/python -m scripts.macos_launch_agent restart
.venv/bin/python -m scripts.macos_launch_agent uninstall
```

The development `.app` still depends on this checkout and `.venv`; it is not yet portable to another Mac. Closing its window keeps the client in the Dock, while the background service runs independently. For one-off debugging, use `.venv/bin/python -m desktop_mac.main`. The existing `selfindex_service.sh` remains available for manual service runs, but do not run it alongside the LaunchAgent on the same port.

Other local apps can query `GET http://127.0.0.1:5050/api/v1/search?query=...&limit=10` and `/api/v1/memory/<id>`. Edits and browser ingestion require the local write token stored at `data/api-write-token` by default.

On Windows, use the PowerShell script. By default it starts the desktop runtime, system tray icon, and web service together:

```powershell
.\scripts\selfindex_service.ps1 start
```

Useful Windows commands:

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

- Legacy Web UI (kept during the transition): `http://127.0.0.1:5050/`
- Browser ingest: `http://127.0.0.1:5050/api/ingest/browser-conversation`

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

Start with the [documentation index](docs/README_ZH.md). Historical system and code maps are preserved in `docs/archive/`; current architecture and database references remain in `docs/architecture.md` and `docs/database-structure.md`.

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
