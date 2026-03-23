"""项目配置。

所有运行时路径和主要参数都从这里集中读取，便于统一理解和排查。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(",")]
    return [part for part in parts if part]


@dataclass(frozen=True)
class Settings:
    """集中保存项目用到的路径、服务和检索配置。"""

    base_dir: Path = BASE_DIR
    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    sqlite_db_path: Path = Path(os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "data" / "selfindex.db")))
    chroma_db_path: Path = Path(os.getenv("CHROMA_DB_PATH", str(BASE_DIR / "data" / "chroma_db")))
    raw_exports_dir: Path = Path(os.getenv("RAW_EXPORTS_DIR", str(BASE_DIR / "data" / "raw_exports")))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cuda")
    default_search_k: int = int(os.getenv("DEFAULT_SEARCH_K", "150"))
    max_results_display: int = int(os.getenv("MAX_RESULTS_DISPLAY", "50"))
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    debug: bool = _as_bool(os.getenv("DEBUG"), True)
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "5000"))

    # Unlock-style query syntax.
    protected_terms: list[str] = field(default_factory=lambda: _as_csv_list(os.getenv("PROTECTED_TERMS")))
    unlock_prefix_identity: str = os.getenv("UNLOCK_PREFIX_IDENTITY", ":")
    unlock_prefix_sensitive: str = os.getenv("UNLOCK_PREFIX_SENSITIVE", "!")
    search_debug: bool = _as_bool(os.getenv("SEARCH_DEBUG"), False)


settings = Settings()
