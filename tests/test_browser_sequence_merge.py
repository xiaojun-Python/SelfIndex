from __future__ import annotations

import unittest

from scripts.import_exports import _build_browser_sequence_merge_updates


class BrowserSequenceMergeTests(unittest.TestCase):
    def test_build_browser_sequence_merge_updates_reorders_existing_rows_from_overlap(self) -> None:
        snapshot_messages = [
            {"message_id": "msg-1"},
            {"message_id": "msg-2"},
            {"message_id": "msg-3"},
            {"message_id": "msg-4"},
        ]
        previous_sequence_by_external_id = {
            "msg-3": 3,
            "msg-4": 4,
        }
        current_rows = [
            {
                "raw_document_id": "grok:conversation_message:msg-1",
                "external_id": "msg-1",
                "sequence": 0,
                "raw_payload": '{"message":{"message_id":"msg-1","sequence":0}}',
                "metadata_json": '{"sequence":0}',
                "latest_revision_id": "rev-1",
            },
            {
                "raw_document_id": "grok:conversation_message:msg-2",
                "external_id": "msg-2",
                "sequence": 1,
                "raw_payload": '{"message":{"message_id":"msg-2","sequence":1}}',
                "metadata_json": '{"sequence":1}',
                "latest_revision_id": "rev-2",
            },
            {
                "raw_document_id": "grok:conversation_message:msg-3",
                "external_id": "msg-3",
                "sequence": 2,
                "raw_payload": '{"message":{"message_id":"msg-3","sequence":2}}',
                "metadata_json": '{"sequence":2}',
                "latest_revision_id": "rev-3",
            },
            {
                "raw_document_id": "grok:conversation_message:msg-4",
                "external_id": "msg-4",
                "sequence": 3,
                "raw_payload": '{"message":{"message_id":"msg-4","sequence":3}}',
                "metadata_json": '{"sequence":3}',
                "latest_revision_id": "rev-4",
            },
            {
                "raw_document_id": "grok:conversation_message:msg-5",
                "external_id": "msg-5",
                "sequence": 5,
                "raw_payload": '{"message":{"message_id":"msg-5","sequence":5}}',
                "metadata_json": '{"sequence":5}',
                "latest_revision_id": "rev-5",
            },
        ]

        result = _build_browser_sequence_merge_updates(
            snapshot_messages=snapshot_messages,
            previous_sequence_by_external_id=previous_sequence_by_external_id,
            current_rows=current_rows,
        )

        self.assertEqual(result["mode"], "anchored_merge")
        self.assertEqual(result["anchor_count"], 2)

        updates_by_id = {
            update["raw_document_id"]: update["sequence"]
            for update in result["updates"]
        }
        self.assertEqual(
            updates_by_id,
            {
                "grok:conversation_message:msg-5": 4,
            },
        )

    def test_build_browser_sequence_merge_updates_without_anchor_returns_no_updates(self) -> None:
        result = _build_browser_sequence_merge_updates(
            snapshot_messages=[{"message_id": "msg-1"}, {"message_id": "msg-2"}],
            previous_sequence_by_external_id={},
            current_rows=[
                {
                    "raw_document_id": "grok:conversation_message:msg-1",
                    "external_id": "msg-1",
                    "sequence": 0,
                    "raw_payload": '{"message":{"message_id":"msg-1","sequence":0}}',
                    "metadata_json": '{"sequence":0}',
                    "latest_revision_id": "rev-1",
                }
            ],
        )

        self.assertEqual(result["mode"], "no_anchor")
        self.assertEqual(result["anchor_count"], 0)
        self.assertEqual(result["updates"], [])


if __name__ == "__main__":
    unittest.main()
