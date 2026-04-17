# Current System

This document answers a simple question:

What SelfIndex already is, and what it is not yet.

## Current Definition

SelfIndex is no longer just a renamed chat log search tool.

At this stage, it is a personal memory system prototype with these active boundaries:

- Archive: preserve raw source material and current document state
- Revision history: keep snapshots for changing sources
- Memory: derive retrieval-friendly memory units from the current revision
- Retrieval: vector search with trace-back into source documents
- Protection: protected recall domains with explicit unlock-style queries

## Core Data Flow

### On import

```text
source data
-> normalize into raw_document
-> upsert current raw_document
-> create or update raw_document_revision when content changes
-> build memory_units from the current revision
-> optionally write vectors into Chroma
```

### On retrieval

```text
query
-> embed query
-> Chroma returns candidate memory_units
-> SQLite loads detail rows in batch
-> filter by recall_domain and active state
-> return result plus trace-back payload
```

### On Markdown sync

```text
scan directory
-> apply ignore rules
-> use relative path as external_id
-> detect create / skip / update by content hash
-> mark missing files as inactive and append a deleted revision
```

### On browser capture

```text
AI web page
-> capture visible conversation snapshot
-> normalize messages into browser payload
-> import into raw_documents / memory_units
-> optionally merge sequence with existing conversation anchors
```

## Design Principles Already In Place

### 1. Current state and history are separated

- `raw_documents` stores the current state
- `raw_document_revisions` stores history

This allows Markdown notes, exported conversations, and browser-captured conversations to share one storage model.

### 2. Memory units are revision-bound

`memory_units` are attached to `revision_id`, not just `raw_document_id`.

That means:

- memory can be traced to a specific version
- updated documents can generate new memory units
- old versions do not need to be overwritten

### 3. Protected rules and protected results are separated

- `protected_terms` stores rules
- `memory_units.recall_domain` stores the resulting label

This keeps retrieval fast because the whole database does not need to be re-judged at query time.

### 4. Inactive is not deletion

For mutable sources such as Markdown sync:

- missing files are not physically removed from history
- current state is marked with `is_active = 0`
- default retrieval ignores inactive items
- historical revisions remain available

## What Is Already Working

- revision-aware storage for imported and synced content
- independent embedding workflow
- Markdown directory sync with ignore rules and delete detection
- ChatGPT export import
- ChatGPT browser sync
- Grok browser sync with lazy-load merge behavior
- protected recall domains
- SQLite / SQLCipher storage

## What Is Still Incomplete

- no polished revision browser UI yet
- no finished conversation replay UI yet
- browser capture still depends on site-specific DOM structure
- browser support is still early and provider-specific
- the desktop runtime is still Windows-first

## Best Next Directions

1. tighten documentation and onboarding
2. improve replay and inspection tools for full conversations
3. add more browser/platform adapters
4. keep reducing startup and runtime ambiguity
