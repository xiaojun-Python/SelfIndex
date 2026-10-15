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


def _as_project_path(value: str | None, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _storage_path(override_name: str, child_name: str) -> Path:
    override = os.getenv(override_name)
    if override:
        return _as_project_path(override, BASE_DIR / "data" / child_name)

    data_root = _as_project_path(os.getenv("DATA_DIR"), BASE_DIR / "data")
    target = data_root / child_name
    legacy = BASE_DIR / "data" / child_name
    if data_root.resolve() != legacy.parent.resolve() and not target.exists() and legacy.exists():
        return legacy
    return target


@dataclass(frozen=True)
class Settings:
    """集中保存项目用到的路径、服务和检索配置。"""

    base_dir: Path = BASE_DIR
    data_dir: Path = field(
        default_factory=lambda: _as_project_path(os.getenv("DATA_DIR"), BASE_DIR / "data")
    )
    sqlite_db_path: Path = field(
        default_factory=lambda: _storage_path("SQLITE_DB_PATH", "selfindex.db")
    )
    chroma_db_path: Path = field(
        default_factory=lambda: _storage_path("CHROMA_DB_PATH", "chroma_db")
    )
    raw_exports_dir: Path = field(
        default_factory=lambda: _storage_path("RAW_EXPORTS_DIR", "raw_exports")
    )
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cuda")
    default_search_k: int = int(os.getenv("DEFAULT_SEARCH_K", "150"))
    max_results_display: int = int(os.getenv("MAX_RESULTS_DISPLAY", "50"))
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    debug: bool = _as_bool(os.getenv("DEBUG"), True)
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "5050"))
    sqlite_cipher_key: str = os.getenv("SQLITE_CIPHER_KEY", "")

    # Unlock-style query syntax.
    protected_terms: list[str] = field(default_factory=lambda: _as_csv_list(os.getenv("PROTECTED_TERMS")))
    unlock_prefix_identity: str = os.getenv("UNLOCK_PREFIX_IDENTITY", ":")
    unlock_prefix_sensitive: str = os.getenv("UNLOCK_PREFIX_SENSITIVE", "!")
    search_debug: bool = _as_bool(os.getenv("SEARCH_DEBUG"), False)

    @property
    def storage_layout(self) -> str:
        paths = (self.sqlite_db_path, self.chroma_db_path, self.raw_exports_dir)
        return "unified" if all(path.parent.resolve() == self.data_dir.resolve() for path in paths) else "split"


settings = Settings()
