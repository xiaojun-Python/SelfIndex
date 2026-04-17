# Code Map

This document answers a practical question:

If you are new to the repository, which files are worth reading first?

## Entry Points

### `app/main.py`

Minimal local web entry point.

### `app/__init__.py`

Application factory.

It wires together:

- settings
- SQLite / SQLCipher
- Chroma
- Flask routes

### `scripts/selfindex_service.ps1`

Recommended local start entry.

It manages:

- unified startup
- shutdown
- restart
- status checks

By default it starts the desktop runtime and tray, which then starts the local web service.

## Web Layer

### `app/api/routes.py`

Main Flask route file.

It contains:

- search routes
- detail view routes
- edit / update routes
- minimal JSON memory API
- browser ingestion endpoint

## Desktop Runtime

### `desktop/main.py`

Desktop runtime entry point.

It sets up:

- system tray
- backend control window
- single-instance guard
- unified runtime pid handoff

### `desktop/controller.py`

Controls the local service process and helper commands.

Important for:

- starting and stopping the web service
- restart behavior
- attaching to an already-running listener
- runtime log streaming

### `desktop/tray.py`

Native Windows tray icon and popup menu.

## Settings

### `app/core/settings.py`

Central `.env` and default configuration loader.

Important values include:

- database paths
- Chroma path
- embedding configuration
- unlock prefixes
- host and port

## Engine Layer

### `engine/init_db.py`

Schema initialization and lightweight migrations.

Important tables:

- `raw_documents`
- `raw_document_revisions`
- `memory_units`
- `protected_terms`
- `import_jobs`

### `engine/database.py`

Core backend persistence layer.

Responsibilities:

- SQLite read/write
- revision storage
- sequence updates
- inactive marking
- protected term storage
- memory detail loading
- Chroma wrapper integration

### `engine/memory.py`

Builds normalized raw documents, revisions, and memory units.

### `engine/retriever.py`

Retrieval assembly layer.

Responsibilities:

- query embedding
- Chroma search
- recall-domain filtering
- inactive filtering
- trace-back payload assembly

### `engine/query_syntax.py`

Unlock-prefix parsing for recall-domain aware search.

### `engine/protected_terms.py`

Encoding and decoding helpers for protected terms.

## Import and Sync Scripts

### `scripts/import_exports.py`

Main import entry for exported conversation files and browser payloads.

### `scripts/parsers/chatgpt_parser.py`

ChatGPT export parser with sequence reconstruction for exported conversations.

### `scripts/parsers/browser_capture_parser.py`

Parser for browser-captured payloads.

It now supports browser payloads from multiple platforms, including ChatGPT and Grok.

### `scripts/parsers/grok_parser.py`

Parser for Grok export files.

### `scripts/sync_markdown_directory.py`

Markdown directory sync with:

- ignore rules
- update detection
- inactive detection for missing files

### `scripts/build_embeddings.py`

Run embeddings as a separate workflow.

## Browser Capture

### `browser_capture/ai_capture_extension/manifest.json`

Chrome extension manifest.

### `browser_capture/ai_capture_extension/content.js`

DOM capture logic for supported AI sites.

Currently used for:

- ChatGPT visible conversation capture
- Grok visible conversation capture

### `browser_capture/ai_capture_extension/popup.js`

Popup logic for:

- capture
- semi-automatic sync
- Grok snapshot merge behavior
- local endpoint submission

## Tests

### `tests/test_browser_capture_parser.py`

Covers browser payload parsing and source mapping.

### `tests/test_browser_sequence_merge.py`

Covers anchor-based sequence merge for lazy-loaded browser sources.

### `tests/test_chatgpt_parser_order.py`

Covers ChatGPT export sequence reconstruction.
