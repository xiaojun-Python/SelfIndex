import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from app.core.settings import settings
from engine.chunker import smart_chunking
from engine.database import DatabaseManager, VectorManager
from engine.embedder import embedding_manager
from scripts.parsers.chatgpt_parser import parse_format_openai
from scripts.parsers.deepseek_parser import parse_format_deepseek
from scripts.parsers.grok_parser import parse_format_grok

db = DatabaseManager(settings.sqlite_db_path)
vector_db = VectorManager(settings.chroma_db_path)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def get_content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def select_parser(file_path: str):
    lower_path = file_path.lower()
    if "grok" in lower_path:
        return parse_format_grok
    if "deepseek" in lower_path:
        return parse_format_deepseek
    return parse_format_openai


def run_import(file_path: str) -> None:
    parser = select_parser(file_path)
    success_count = 0

    for conv_meta, messages in parser(file_path):
        try:
            raw_meta_json = json.dumps(
                conv_meta["raw_meta"],
                ensure_ascii=False,
                cls=DecimalEncoder,
            )
            conv_tuple = (
                conv_meta["id"],
                conv_meta["title"],
                conv_meta["created_at"],
                conv_meta["source"],
                raw_meta_json,
            )
            msg_tuples = [
                (
                    msg["message_id"],
                    conv_meta["id"],
                    msg["sub_title"],
                    msg["sender_type"],
                    msg["content"],
                    msg["content_length"],
                    msg["model"],
                    get_content_hash(msg["content"]),
                    msg["sequence"],
                    msg["timestamp"],
                )
                for msg in messages
            ]
            db.save_full_conversation(conv_tuple, msg_tuples)
            success_count += 1
        except Exception as exc:
            print(f"Import failed for one conversation: {exc}")

    print(f"Imported conversations: {success_count}")


def run_chunking_task() -> None:
    pending_msgs = db.get_messages_needing_chunks()
    all_new_chunks = []

    for msg in pending_msgs:
        chunks = smart_chunking(msg["content"], msg["title"], msg["sender_type"])
        for index, chunk in enumerate(chunks):
            chunk_hash = get_content_hash(chunk["content"])
            if not db.chunk_exists(chunk_hash):
                all_new_chunks.append(
                    (
                        msg["message_id"],
                        index,
                        chunk["start"],
                        chunk["end"],
                        chunk["content"],
                        chunk_hash,
                        settings.embedding_model,
                    )
                )

    if all_new_chunks:
        db.save_chunks(all_new_chunks)
    print(f"Chunks created: {len(all_new_chunks)}")


def run_embedding_task() -> None:
    while True:
        chunks_to_process = db.get_unprocessed_chunks(limit=100)
        if not chunks_to_process:
            print("All chunks are embedded.")
            break

        texts = [item["content"] for item in chunks_to_process]
        ids = [str(item["chunk_id"]) for item in chunks_to_process]
        metadatas = [
            {
                "message_id": item["message_id"],
                "title": item["title"] or "Untitled conversation",
                "source": item["source"],
                "timestamp": item["timestamp"],
            }
            for item in chunks_to_process
        ]
        vectors = embedding_manager.embed_documents(texts)
        vector_db.add_vectors(ids=ids, embeddings=vectors, metadatas=metadatas, documents=texts)
        db.mark_chunks_as_processed([item["chunk_id"] for item in chunks_to_process])
        print(f"Embedded chunks: {len(chunks_to_process)}")


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import legacy exports into the new SelfIndex layout.")
    parser.add_argument("--file", type=str, help="Path to the exported JSON file.")
    parser.add_argument("--import-only", action="store_true", help="Only run import.")
    parser.add_argument("--chunk-only", action="store_true", help="Only run chunking.")
    parser.add_argument("--embed-only", action="store_true", help="Only run embedding.")
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()

    if args.file:
        run_import(str(Path(args.file)))

    if args.import_only:
        raise SystemExit(0)
    if args.chunk_only:
        run_chunking_task()
        raise SystemExit(0)
    if args.embed_only:
        run_embedding_task()
        raise SystemExit(0)

    if args.file:
        run_chunking_task()
        run_embedding_task()
