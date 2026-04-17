# Database Structure

The main database is SQLite or SQLCipher, depending on configuration.

## Main Tables

| Table | Purpose |
| --- | --- |
| `raw_documents` | current document state |
| `raw_document_revisions` | historical snapshots |
| `memory_units` | retrieval-facing chunks derived from the current revision |
| `protected_terms` | protected recall rules |
| `import_jobs` | import job history |

## Relationship Model

```text
raw_documents (1) ────< raw_document_revisions (N)
raw_document_revisions (1) ────< memory_units (N)
protected_terms (independent rules)
import_jobs (independent job log)
```

## `raw_documents`

Current-state table.

Important fields:

- `raw_document_id`
- `source`
- `source_type`
- `external_id`
- `root_document_id`
- `sequence`
- `title`
- `author`
- `created_at`
- `content`
- `content_hash`
- `current_content_hash`
- `latest_revision_id`
- `is_active`
- `raw_payload`
- `metadata_json`

Notes:

- `UNIQUE(source, external_id)` is the main identity guard
- `root_document_id` groups messages that belong to the same conversation
- `sequence` stores the current linear order within a conversation when applicable
- `is_active = 0` means the current state should be ignored by default retrieval

## `raw_document_revisions`

Revision history table.

Important fields:

- `revision_id`
- `raw_document_id`
- `content`
- `content_hash`
- `title`
- `author`
- `created_at`
- `raw_payload`
- `metadata_json`
- `change_type`
- `is_current`
- `captured_at`

Notes:

- one raw document can have many revisions
- current revision is marked by `is_current = 1`
- browser capture sequence-only adjustments currently update the current revision metadata without creating a new content revision

## `memory_units`

Retrieval-facing chunk table.

Important fields:

- `memory_unit_id`
- `revision_id`
- `raw_document_id`
- `unit_index`
- `unit_type`
- `recall_domain`
- `content`
- `summary`
- `start_char`
- `end_char`
- `embedding_version`
- `metadata_json`
- `is_embedded`

Notes:

- memory units are derived from the current revision
- retrieval defaults to active documents only
- `recall_domain` is a stored result label, not the original rule definition

## `protected_terms`

Protected recall rule table.

Important fields:

- `term_id`
- `term_encoded`
- `encoding`
- `domain`
- `is_active`
- `notes`
- `created_at`
- `updated_at`

Notes:

- terms are currently stored with lightweight encoding, not strong encryption
- rules are persisted in the database rather than treated as `.env`-only settings

## `import_jobs`

Import execution history.

Important fields:

- `import_id`
- `source`
- `file_name`
- `file_path`
- `file_hash`
- `started_at`
- `finished_at`
- `raw_documents_count`
- `memory_units_count`
- `skipped_count`
- `status`
- `error_message`
- `import_config_json`
- `notes`

## Conversation Ordering Notes

Conversation-like sources rely on `root_document_id` plus `sequence`.

Current behavior:

- ChatGPT exports reconstruct order before import
- ChatGPT browser sync usually appends new tail messages incrementally
- Grok browser sync may merge partial lazy-loaded snapshots and then re-align `sequence` using overlapping message ids as anchors

This means order is stored in the database as a first-class field, even if the original browser source only exposed partial DOM snapshots.
