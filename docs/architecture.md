# Architecture

## Goal

The current goal of SelfIndex is:

- preserve personal source material as faithfully as practical
- build a lightweight but durable searchable memory layer
- support changing sources without losing historical state
- stay local-first and maintainable

## Three Layers

### 1. Archive Layer

Responsibilities:

- store raw source material
- store the current document state
- store revision history
- handle create, duplicate, update, and inactive transitions

Current implementation:

- `raw_documents`
- `raw_document_revisions`

### 2. Memory Layer

Responsibilities:

- derive retrieval-friendly units from the current revision
- store chunk content and summary
- store recall-domain labels
- provide stable input for embedding workflows

Current implementation:

- `memory_units`
- `Chroma` collection

### 3. Recall Layer

Responsibilities:

- parse queries
- retrieve by vector similarity
- filter by recall domain
- ignore inactive source documents by default
- trace hits back to raw documents

Current implementation:

- `engine/query_syntax.py`
- `engine/retriever.py`
- `/api/memory/search`

## Why Revisions Exist

SelfIndex is not a one-time import tool anymore.

It already needs to support:

- Markdown notes that change over time
- exported conversations
- browser-captured conversations that may grow incrementally
- lazy-loaded sources that become more complete across multiple syncs

Without revisions, a later import would simply overwrite the earlier state.

## Why Memory Units Still Matter

`memory_units` are not the archive.

They are the memory representation layer, responsible for:

- search-friendly chunking
- summary storage
- recall-domain labeling
- embedding state

The archive preserves source truth. The memory layer preserves retrieval usefulness.

## Why Browser Capture Fits This Architecture

Browser capture is not a separate storage model.

It is another ingestion path that still ends up in the same archive and memory structure:

- source page -> normalized browser payload
- browser payload -> `raw_documents`
- `raw_documents` -> `raw_document_revisions`
- current revision -> `memory_units`

For lazy-loaded sources such as Grok, SelfIndex now supports a merge step that uses overlapping message ids as anchors and reorders `sequence` without rewriting content or embeddings.

## Deliberate Non-Goals

At this stage, SelfIndex is intentionally not trying to become:

- a knowledge graph platform
- a multi-user SaaS system
- a personality-driven agent product
- a full browser automation system

The project is still optimizing for a local-first memory pipeline rather than a broad product layer.
