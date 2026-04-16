"""Read-only ChatGPT conversation ordering audit helpers and CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ijson

from app.core.settings import settings
from scripts.format_timestamp import format_timestamp

CHATGPT_PLATFORM = "chatgpt"
VALID_SOURCE_LABELS = {"database", "export", "browser"}
VALID_ROLES = {"user", "assistant", "system"}


def _content_hash(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_timestamp(value: Any) -> str | None:
    text = _normalize_text(format_timestamp(value)) if value else None
    return text[:19] if text else None


def _timestamp_sort_key(value: str | None) -> tuple[int, str]:
    normalized = _normalize_timestamp(value)
    if normalized:
        return 0, normalized
    return 1, ""


def _normalize_role(raw_role: Any) -> str:
    role = str(raw_role or "user").strip().lower()
    if role == "assistant":
        return "assistant"
    if role == "system":
        return "system"
    return "user"


def _extract_text_content(message_obj: dict[str, Any]) -> str:
    parts = ((message_obj or {}).get("content") or {}).get("parts") or []
    return "".join(part for part in parts if isinstance(part, str)).strip()


def _load_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    return default


@dataclass(frozen=True)
class NormalizedChatMessage:
    platform: str
    conversation_id: str
    message_id: str
    role: str
    content: str
    content_hash: str
    capture_index: int
    timestamp: str | None = None
    sequence: int | None = None
    parent_message_id: str | None = None
    source_label: str = "database"

    def __post_init__(self) -> None:
        platform = self.platform.lower().strip()
        if platform != CHATGPT_PLATFORM:
            raise ValueError(f"Unsupported platform: {self.platform}")
        if not self.conversation_id.strip():
            raise ValueError("conversation_id is required.")
        if not self.message_id.strip():
            raise ValueError("message_id is required.")
        if self.role not in VALID_ROLES:
            raise ValueError(f"Unsupported role: {self.role}")
        if self.source_label not in VALID_SOURCE_LABELS:
            raise ValueError(f"Unsupported source_label: {self.source_label}")
        if self.capture_index < 0:
            raise ValueError("capture_index must be >= 0.")

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        default_source_label: str = "browser",
        fallback_capture_index: int = 0,
    ) -> "NormalizedChatMessage":
        content = str(payload.get("content") or "")
        content_hash = _normalize_text(payload.get("content_hash")) or _content_hash(content)
        return cls(
            platform=str(payload.get("platform") or CHATGPT_PLATFORM).strip().lower(),
            conversation_id=str(payload.get("conversation_id") or "").strip(),
            message_id=str(payload.get("message_id") or "").strip(),
            role=_normalize_role(payload.get("role")),
            content=content,
            content_hash=content_hash,
            capture_index=_normalize_int(payload.get("capture_index"))
            if _normalize_int(payload.get("capture_index")) is not None
            else fallback_capture_index,
            timestamp=_normalize_timestamp(payload.get("timestamp")),
            sequence=_normalize_int(payload.get("sequence")),
            parent_message_id=_normalize_text(payload.get("parent_message_id")),
            source_label=str(payload.get("source_label") or default_source_label).strip().lower(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "parent_message_id": self.parent_message_id,
            "role": self.role,
            "content": self.content,
            "content_hash": self.content_hash,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "capture_index": self.capture_index,
            "source_label": self.source_label,
        }


@dataclass
class SourceConversationBundle:
    conversation_id: str
    source_label: str
    messages: list[NormalizedChatMessage]
    diagnostics_by_message_id: dict[str, dict[str, Any]]


@dataclass
class ConversationOrderView:
    conversation_id: str
    source_label: str
    order_strategy: str
    messages: list[NormalizedChatMessage]
    duplicates: list[str]
    missing_timestamps: list[str]
    linearization_ambiguities: list[dict[str, Any]]
    diagnostics_by_message_id: dict[str, dict[str, Any]]

    @property
    def message_ids(self) -> list[str]:
        return [message.message_id for message in self.messages]

    def to_dict(self) -> dict[str, Any]:
        serialized_messages: list[dict[str, Any]] = []
        for message in self.messages:
            item = message.to_dict()
            audit_fields = self.diagnostics_by_message_id.get(message.message_id)
            if audit_fields:
                item["audit_fields"] = audit_fields
            serialized_messages.append(item)

        return {
            "conversation_id": self.conversation_id,
            "source_label": self.source_label,
            "order_strategy": self.order_strategy,
            "message_ids": self.message_ids,
            "duplicates": self.duplicates,
            "missing_timestamps": self.missing_timestamps,
            "linearization_ambiguities": self.linearization_ambiguities,
            "messages": serialized_messages,
        }


def _deduplicate_messages(
    messages: list[NormalizedChatMessage],
) -> tuple[list[NormalizedChatMessage], list[str]]:
    seen: dict[str, NormalizedChatMessage] = {}
    duplicates: list[str] = []
    for message in messages:
        if message.message_id in seen:
            if message.message_id not in duplicates:
                duplicates.append(message.message_id)
            continue
        seen[message.message_id] = message
    return list(seen.values()), duplicates


def _try_parent_chain_order(
    messages: list[NormalizedChatMessage],
) -> tuple[list[NormalizedChatMessage] | None, list[dict[str, Any]]]:
    if not messages or not any(message.parent_message_id for message in messages):
        return None, []

    by_id = {message.message_id: message for message in messages}
    child_map: dict[str, list[str]] = defaultdict(list)
    roots: list[str] = []
    ambiguities: list[dict[str, Any]] = []

    for message in messages:
        parent_id = message.parent_message_id
        if parent_id:
            if parent_id not in by_id:
                ambiguities.append(
                    {
                        "type": "missing_parent",
                        "message_id": message.message_id,
                        "parent_message_id": parent_id,
                    }
                )
                continue
            child_map[parent_id].append(message.message_id)
        else:
            roots.append(message.message_id)

    for parent_id, child_ids in sorted(child_map.items()):
        if len(child_ids) > 1:
            ambiguities.append(
                {
                    "type": "branching_children",
                    "parent_message_id": parent_id,
                    "child_message_ids": child_ids,
                }
            )

    if len(messages) > 1 and len(roots) != 1:
        ambiguities.append({"type": "multiple_roots", "message_ids": roots})

    if ambiguities or not roots:
        return None, ambiguities

    ordered: list[NormalizedChatMessage] = []
    current_id = roots[0]
    visited: set[str] = set()

    while current_id:
        if current_id in visited:
            ambiguities.append({"type": "cycle", "message_id": current_id})
            return None, ambiguities

        visited.add(current_id)
        ordered.append(by_id[current_id])
        children = child_map.get(current_id) or []
        if not children:
            current_id = ""
            continue
        current_id = children[0]

    if len(ordered) != len(messages):
        ambiguities.append(
            {
                "type": "disconnected_chain",
                "ordered_message_ids": [message.message_id for message in ordered],
                "remaining_message_ids": [
                    message.message_id for message in messages if message.message_id not in visited
                ],
            }
        )
        return None, ambiguities

    return ordered, []


def build_order_view(bundle: SourceConversationBundle) -> ConversationOrderView:
    unique_messages, duplicates = _deduplicate_messages(bundle.messages)
    missing_timestamps = [
        message.message_id for message in unique_messages if not _normalize_timestamp(message.timestamp)
    ]
    ambiguities: list[dict[str, Any]] = []
    order_strategy = "message_id"
    ordered_messages = list(unique_messages)

    if unique_messages and all(message.sequence is not None for message in unique_messages):
        sequence_groups: dict[int, list[str]] = defaultdict(list)
        for message in unique_messages:
            sequence_groups[int(message.sequence)].append(message.message_id)
        for sequence, message_ids in sorted(sequence_groups.items()):
            if len(message_ids) > 1:
                ambiguities.append(
                    {
                        "type": "duplicate_sequence",
                        "sequence": sequence,
                        "message_ids": message_ids,
                    }
                )

        ordered_messages = sorted(
            unique_messages,
            key=lambda message: (
                int(message.sequence or 0),
                _timestamp_sort_key(message.timestamp),
                message.capture_index,
                message.message_id,
            ),
        )
        order_strategy = "sequence"
    else:
        parent_order, parent_ambiguities = _try_parent_chain_order(unique_messages)
        if parent_order is not None:
            ordered_messages = parent_order
            order_strategy = "parent_message_id"
        else:
            ambiguities.extend(parent_ambiguities)
            if any(_normalize_timestamp(message.timestamp) for message in unique_messages):
                ordered_messages = sorted(
                    unique_messages,
                    key=lambda message: (
                        _timestamp_sort_key(message.timestamp),
                        message.capture_index,
                        message.message_id,
                    ),
                )
                order_strategy = "timestamp"
            elif unique_messages:
                ordered_messages = sorted(
                    unique_messages,
                    key=lambda message: (message.capture_index, message.message_id),
                )
                order_strategy = "capture_index"

    return ConversationOrderView(
        conversation_id=bundle.conversation_id,
        source_label=bundle.source_label,
        order_strategy=order_strategy,
        messages=ordered_messages,
        duplicates=duplicates,
        missing_timestamps=missing_timestamps,
        linearization_ambiguities=ambiguities,
        diagnostics_by_message_id=bundle.diagnostics_by_message_id,
    )


def compare_order_views(
    left_view: ConversationOrderView,
    right_view: ConversationOrderView,
) -> dict[str, Any]:
    left_ids = left_view.message_ids
    right_ids = right_view.message_ids
    right_id_set = set(right_ids)
    left_id_set = set(left_ids)

    shared_left = [message_id for message_id in left_ids if message_id in right_id_set]
    shared_right = [message_id for message_id in right_ids if message_id in left_id_set]

    order_conflicts: list[dict[str, Any]] = []
    for index, (left_id, right_id) in enumerate(zip(shared_left, shared_right)):
        if left_id != right_id:
            order_conflicts.append(
                {
                    "position": index,
                    "left_message_id": left_id,
                    "right_message_id": right_id,
                }
            )

    return {
        "left_source": left_view.source_label,
        "right_source": right_view.source_label,
        "missing_in_left": [message_id for message_id in right_ids if message_id not in left_id_set],
        "missing_in_right": [message_id for message_id in left_ids if message_id not in right_id_set],
        "order_conflicts": order_conflicts,
    }


def _resolve_parent_message_id(
    node_id: str,
    mapping: dict[str, Any],
    node_to_message_id: dict[str, str],
) -> str | None:
    current_parent_id = _normalize_text((mapping.get(node_id) or {}).get("parent"))
    while current_parent_id:
        if current_parent_id in node_to_message_id:
            return node_to_message_id[current_parent_id]
        current_parent = mapping.get(current_parent_id) or {}
        current_parent_id = _normalize_text(current_parent.get("parent"))
    return None


def build_export_conversation_bundle(conversation_obj: dict[str, Any]) -> SourceConversationBundle:
    conversation_id = str(conversation_obj.get("id") or conversation_obj.get("conversation_id") or "").strip()
    mapping = conversation_obj.get("mapping") or {}
    temp_messages: list[dict[str, Any]] = []
    node_to_message_id: dict[str, str] = {}

    for capture_index, (node_id, node_data) in enumerate(mapping.items()):
        message_obj = (node_data or {}).get("message") or {}
        content = _extract_text_content(message_obj)
        if not content:
            continue

        message_id = str(message_obj.get("id") or node_id)
        node_to_message_id[str(node_id)] = message_id
        temp_messages.append(
            {
                "node_id": str(node_id),
                "parent_node_id": _normalize_text((node_data or {}).get("parent")),
                "message_id": message_id,
                "role": _normalize_role((message_obj.get("author") or {}).get("role")),
                "content": content,
                "timestamp": _normalize_timestamp(message_obj.get("create_time")),
                "capture_index": capture_index,
            }
        )

    messages: list[NormalizedChatMessage] = []
    diagnostics_by_message_id: dict[str, dict[str, Any]] = {}
    for item in temp_messages:
        parent_message_id = _resolve_parent_message_id(item["node_id"], mapping, node_to_message_id)
        message = NormalizedChatMessage(
            platform=CHATGPT_PLATFORM,
            conversation_id=conversation_id,
            message_id=item["message_id"],
            role=item["role"],
            content=item["content"],
            content_hash=_content_hash(item["content"]),
            capture_index=item["capture_index"],
            timestamp=item["timestamp"],
            sequence=None,
            parent_message_id=parent_message_id,
            source_label="export",
        )
        messages.append(message)
        diagnostics_by_message_id[message.message_id] = {
            "node_id": item["node_id"],
            "parent_node_id": item["parent_node_id"],
            "payload_timestamp": item["timestamp"],
        }

    return SourceConversationBundle(
        conversation_id=conversation_id,
        source_label="export",
        messages=messages,
        diagnostics_by_message_id=diagnostics_by_message_id,
    )


def load_chatgpt_export_bundles(
    file_path: str | Path,
    *,
    conversation_ids: set[str] | None = None,
) -> dict[str, SourceConversationBundle]:
    selected_ids = conversation_ids or set()
    bundles: dict[str, SourceConversationBundle] = {}

    with Path(file_path).open("rb") as file_obj:
        for conversation_obj in ijson.items(file_obj, "item"):
            conversation_id = str(
                conversation_obj.get("id") or conversation_obj.get("conversation_id") or ""
            ).strip()
            if selected_ids and conversation_id not in selected_ids:
                continue
            bundles[conversation_id] = build_export_conversation_bundle(conversation_obj)

    return bundles


def normalize_browser_sample_bundles(payload: Any) -> dict[str, SourceConversationBundle]:
    raw_messages: list[dict[str, Any]] = []
    if isinstance(payload, list):
        raw_messages = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        raw_messages = [item for item in payload["messages"] if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("conversations"), list):
        for conversation_item in payload["conversations"]:
            if not isinstance(conversation_item, dict):
                continue
            conversation_id = _normalize_text(conversation_item.get("conversation_id"))
            for message in conversation_item.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                item = dict(message)
                if conversation_id and not item.get("conversation_id"):
                    item["conversation_id"] = conversation_id
                raw_messages.append(item)
    else:
        raise ValueError("Browser sample must be a list of messages or a wrapper with messages.")

    grouped_messages: dict[str, list[NormalizedChatMessage]] = defaultdict(list)
    diagnostics_by_conversation: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for fallback_capture_index, item in enumerate(raw_messages):
        message = NormalizedChatMessage.from_payload(
            item,
            default_source_label="browser",
            fallback_capture_index=fallback_capture_index,
        )
        grouped_messages[message.conversation_id].append(message)
        diagnostics_by_conversation[message.conversation_id][message.message_id] = {}

    return {
        conversation_id: SourceConversationBundle(
            conversation_id=conversation_id,
            source_label="browser",
            messages=messages,
            diagnostics_by_message_id=diagnostics_by_conversation[conversation_id],
        )
        for conversation_id, messages in grouped_messages.items()
    }


def load_browser_sample_bundles(file_path: str | Path) -> dict[str, SourceConversationBundle]:
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    return normalize_browser_sample_bundles(payload)


def fetch_database_conversation_bundle(
    conn: Any,
    conversation_id: str,
) -> SourceConversationBundle | None:
    rows = conn.execute(
        """
        SELECT raw_document_id, external_id, root_document_id, author, created_at,
               content, content_hash, metadata_json, raw_payload
        FROM raw_documents
        WHERE source = 'ChatGPT'
          AND source_type = 'conversation_message'
          AND root_document_id = ?
          AND is_active = 1
        ORDER BY raw_document_id
        """,
        (conversation_id,),
    ).fetchall()

    if not rows:
        return None

    messages: list[NormalizedChatMessage] = []
    diagnostics_by_message_id: dict[str, dict[str, Any]] = {}

    for capture_index, row in enumerate(rows):
        metadata = _load_json_dict(_row_value(row, "metadata_json"))
        raw_payload = _load_json_dict(_row_value(row, "raw_payload"))
        payload_message = raw_payload.get("message") if isinstance(raw_payload.get("message"), dict) else {}
        payload_timestamp = _normalize_timestamp(payload_message.get("timestamp"))
        created_at = _normalize_timestamp(_row_value(row, "created_at"))
        content = str(_row_value(row, "content", "") or "")

        message = NormalizedChatMessage(
            platform=CHATGPT_PLATFORM,
            conversation_id=str(_row_value(row, "root_document_id", "") or ""),
            message_id=str(_row_value(row, "external_id", "") or ""),
            role=_normalize_role(_row_value(row, "author")),
            content=content,
            content_hash=str(_row_value(row, "content_hash") or _content_hash(content)),
            capture_index=capture_index,
            timestamp=payload_timestamp or created_at,
            sequence=_normalize_int(metadata.get("sequence")),
            parent_message_id=None,
            source_label="database",
        )
        messages.append(message)
        diagnostics_by_message_id[message.message_id] = {
            "raw_document_id": _row_value(row, "raw_document_id"),
            "created_at": created_at,
            "payload_timestamp": payload_timestamp,
            "metadata_sequence": _normalize_int(metadata.get("sequence")),
        }

    return SourceConversationBundle(
        conversation_id=conversation_id,
        source_label="database",
        messages=messages,
        diagnostics_by_message_id=diagnostics_by_message_id,
    )


def list_chatgpt_conversation_ids(conn: Any, *, limit: int = 5) -> list[str]:
    rows = conn.execute(
        """
        SELECT root_document_id, COUNT(*) AS message_count
        FROM raw_documents
        WHERE source = 'ChatGPT'
          AND source_type = 'conversation_message'
          AND root_document_id IS NOT NULL
          AND is_active = 1
        GROUP BY root_document_id
        ORDER BY message_count DESC, root_document_id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(row["root_document_id"]) for row in rows if row["root_document_id"]]


def _build_diagnosis(
    conversation_id: str,
    views: dict[str, ConversationOrderView],
    comparisons: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    database_view = views.get("database")
    export_view = views.get("export")
    browser_view = views.get("browser")

    parser_ordering_issue = False
    storage_field_gap: bool | None = None
    browser_capture_gap: bool | None = None
    sortable_retrieval_supported: bool | None = None
    notes: list[str] = []

    if database_view is not None:
        db_has_complete_sequence = all(
            message.sequence is not None for message in database_view.messages
        )
        db_has_complete_timestamps = all(
            _normalize_timestamp(message.timestamp) for message in database_view.messages
        )
        storage_field_gap = not (db_has_complete_sequence or db_has_complete_timestamps)
        sortable_retrieval_supported = not storage_field_gap
        if storage_field_gap:
            notes.append(
                f"{conversation_id}: database rows do not have a complete sequence or timestamp key."
            )

    database_vs_export = comparisons.get("database_vs_export")
    if (
        database_view is not None
        and export_view is not None
        and database_vs_export is not None
        and not database_vs_export["missing_in_left"]
        and not database_vs_export["missing_in_right"]
        and database_vs_export["order_conflicts"]
        and not export_view.linearization_ambiguities
    ):
        parser_ordering_issue = True
        notes.append(
            f"{conversation_id}: database order disagrees with export reference while message sets match."
        )

    if browser_view is not None:
        browser_capture_gap = False
        if browser_view.duplicates:
            browser_capture_gap = True
            notes.append(
                f"{conversation_id}: browser sample contains duplicate message ids: {browser_view.duplicates}."
            )

        browser_vs_export = comparisons.get("browser_vs_export")
        if browser_vs_export is not None:
            if browser_vs_export["missing_in_left"]:
                browser_capture_gap = True
                notes.append(
                    f"{conversation_id}: browser sample is missing export messages {browser_vs_export['missing_in_left']}."
                )
            if browser_vs_export["order_conflicts"] and browser_view.order_strategy in {
                "capture_index",
                "message_id",
            }:
                browser_capture_gap = True
                notes.append(
                    f"{conversation_id}: browser sample order does not align with export reference."
                )

    if parser_ordering_issue and storage_field_gap is False:
        summary = "Storage fields are sufficient for sortable retrieval, but parser ordering is suspect."
    elif storage_field_gap:
        summary = "Current database fields are not sufficient to support reliable sortable retrieval."
    elif browser_capture_gap:
        summary = "Browser sample does not yet prove stable ordering/completeness."
    elif sortable_retrieval_supported:
        summary = "Current fields are sufficient for sortable retrieval in this conversation."
    else:
        summary = "Insufficient evidence to reach a storage conclusion for this conversation."

    return {
        "parser_ordering_issue": parser_ordering_issue,
        "storage_field_gap": storage_field_gap,
        "browser_capture_gap": browser_capture_gap,
        "sortable_retrieval_supported": sortable_retrieval_supported,
        "summary": summary,
        "notes": notes,
    }


def audit_chatgpt_conversation(
    conversation_id: str,
    *,
    database_bundle: SourceConversationBundle | None = None,
    export_bundle: SourceConversationBundle | None = None,
    browser_bundle: SourceConversationBundle | None = None,
) -> dict[str, Any]:
    raw_views: dict[str, ConversationOrderView] = {}
    if database_bundle is not None:
        raw_views["database"] = build_order_view(database_bundle)
    if export_bundle is not None:
        raw_views["export"] = build_order_view(export_bundle)
    if browser_bundle is not None:
        raw_views["browser"] = build_order_view(browser_bundle)

    comparisons: dict[str, dict[str, Any]] = {}
    if "database" in raw_views and "export" in raw_views:
        comparisons["database_vs_export"] = compare_order_views(
            raw_views["database"],
            raw_views["export"],
        )
    if "browser" in raw_views and "export" in raw_views:
        comparisons["browser_vs_export"] = compare_order_views(
            raw_views["browser"],
            raw_views["export"],
        )
    if "database" in raw_views and "browser" in raw_views:
        comparisons["database_vs_browser"] = compare_order_views(
            raw_views["database"],
            raw_views["browser"],
        )

    diagnosis = _build_diagnosis(conversation_id, raw_views, comparisons)

    return {
        "conversation_id": conversation_id,
        "views": {source: view.to_dict() for source, view in raw_views.items()},
        "comparisons": comparisons,
        "diagnosis": diagnosis,
    }


def audit_chatgpt_sources(
    *,
    db_path: str | Path | None = None,
    export_path: str | Path | None = None,
    browser_sample_path: str | Path | None = None,
    conversation_ids: list[str] | None = None,
    limit: int = 1,
) -> dict[str, Any]:
    selected_ids = [conversation_id.strip() for conversation_id in (conversation_ids or []) if conversation_id.strip()]
    selected_id_set = set(selected_ids)

    export_bundles = (
        load_chatgpt_export_bundles(export_path, conversation_ids=selected_id_set)
        if export_path
        else {}
    )
    browser_bundles = load_browser_sample_bundles(browser_sample_path) if browser_sample_path else {}

    database_bundles: dict[str, SourceConversationBundle] = {}
    resolved_ids = list(selected_ids)

    if db_path:
        from engine.sqlite_backend import connect_database

        with connect_database(db_path) as conn:
            if not resolved_ids:
                resolved_ids = list_chatgpt_conversation_ids(conn, limit=limit)

            for conversation_id in resolved_ids:
                bundle = fetch_database_conversation_bundle(conn, conversation_id)
                if bundle is not None:
                    database_bundles[conversation_id] = bundle

    if not resolved_ids:
        resolved_ids = sorted(
            set(export_bundles.keys()) | set(browser_bundles.keys()) | set(database_bundles.keys())
        )

    reports = []
    for conversation_id in resolved_ids:
        reports.append(
            audit_chatgpt_conversation(
                conversation_id,
                database_bundle=database_bundles.get(conversation_id),
                export_bundle=export_bundles.get(conversation_id),
                browser_bundle=browser_bundles.get(conversation_id),
            )
        )

    return {
        "conversation_ids": resolved_ids,
        "reports": reports,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only ChatGPT conversation ordering audit for database/export/browser PoC."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(settings.sqlite_db_path),
        help="Path to the SQLite / SQLCipher database. Defaults to SQLITE_DB_PATH.",
    )
    parser.add_argument(
        "--conversation-id",
        action="append",
        dest="conversation_ids",
        help="Conversation id to audit. Repeat for multiple conversations.",
    )
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="Optional ChatGPT export JSON for reference-order comparison.",
    )
    parser.add_argument(
        "--browser-sample",
        type=str,
        default=None,
        help="Optional normalized browser sample JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="When no conversation ids are provided, audit this many database conversations.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional JSON output path. Prints to stdout when omitted.",
    )
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    result = audit_chatgpt_sources(
        db_path=Path(args.db),
        export_path=Path(args.export) if args.export else None,
        browser_sample_path=Path(args.browser_sample) if args.browser_sample else None,
        conversation_ids=args.conversation_ids,
        limit=max(1, args.limit),
    )

    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
