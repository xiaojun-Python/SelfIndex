# Browser Capture Extension

This document describes the current browser capture extension used by SelfIndex.

Despite the folder name, it is no longer ChatGPT-only.

## Scope

The extension is intentionally narrow:

- it captures only the messages currently loaded in the page
- it normalizes them into a SelfIndex-friendly payload
- it can send the payload directly to the local SelfIndex ingest endpoint

Current supported sites:

- ChatGPT
- Grok

## Extension Location

`browser_capture/ai_capture_extension`

## Captured Fields

Each normalized message may contain:

- `platform`
- `source_label`
- `conversation_id`
- `conversation_title`
- `message_id`
- `parent_message_id`
- `role`
- `model`
- `model_slug`
- `content`
- `content_hash`
- `timestamp`
- `sequence`
- `capture_index`
- `dom_turn_testid`
- `dom_turn_id`
- `page_url`

Not every provider exposes every field. Missing values are kept as `null` when necessary.

## Current Provider Behavior

### ChatGPT

- conversation id comes from `/c/<id>`
- message id comes from `data-message-id`
- role comes from `data-message-author-role`
- model comes from `data-message-model-slug`
- order starts from DOM order and can later sync incrementally

### Grok

- conversation id comes from `/c/<id>` or the canonical link
- message id comes from `id="response-..."`
- role is currently inferred from layout classes such as `items-start` and `items-end`
- order is based on the currently loaded DOM snapshot
- sync mode is snapshot merge because Grok lazy-loads older history

## Loading the Extension

1. Open Chrome
2. Go to `chrome://extensions/`
3. Enable Developer Mode
4. Click `Load unpacked`
5. Select:

`C:\Users\xiaoj\PycharmProjects\SelfIndex\browser_capture\ai_capture_extension`

## Using the Extension

1. Open a supported AI conversation page
2. Click the extension icon
3. Review the detected sync status
4. Choose one of the actions:
   - capture the current conversation
   - sync to SelfIndex
   - copy JSON
   - download JSON

## Sync Modes

### ChatGPT

ChatGPT currently uses semi-automatic incremental sync:

- the extension remembers the last synced `message_id` for each conversation
- if the current page contains that anchor, only newer messages are sent
- if the anchor is missing, the extension falls back to a larger re-sync

### Grok

Grok currently uses snapshot merge:

- each sync sends the currently loaded DOM snapshot
- the backend uses overlapping `message_id` values as anchors
- `sequence` is re-aligned for the full conversation without rewriting content

This is necessary because Grok lazy-loads older messages instead of delivering the full conversation immediately.

## Local Ingest Endpoint

Current endpoint:

`POST http://127.0.0.1:5000/api/ingest/browser-conversation`

The route name is still historical, but the payload now accepts multiple browser platforms.

Requirements:

1. SelfIndex is running locally
2. the extension endpoint matches the local runtime
3. the request comes from the local machine

## Manual Debugging

You can also test capture directly in the browser console.

ChatGPT:

```js
window.SELFINDEX_CAPTURE_CHATGPT()
```

Grok:

```js
window.SELFINDEX_CAPTURE_GROK()
```

Generic:

```js
window.SELFINDEX_CAPTURE_CONVERSATION()
```

## Current Limitations

- only currently loaded messages are captured
- browser capture remains DOM-structure dependent
- `parent_message_id` is still missing for most browser-captured sources
- timestamps are not guaranteed
- provider support is still hand-built rather than generic

## Why This Document Matters

Browser capture is no longer just a side experiment.

It is now one of the main ingestion paths in SelfIndex, especially for platforms that do not provide clean export workflows.
