"""Small urllib client for the local SelfIndex API."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.core.local_auth import get_write_token
from app.core.settings import settings


class ApiError(RuntimeError):
    """An API/network error suitable for displaying in the desktop UI."""


class SelfIndexApi:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or f"http://{settings.host}:{settings.port}").rstrip("/")

    def _get(self, path: str, *, timeout: int = 8) -> dict[str, Any]:
        request = Request(self.base_url + path, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError(f"无法连接 SelfIndex API：{exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("API 返回了无效的 JSON。") from exc
        if not isinstance(payload, dict):
            raise ApiError("API 响应格式不正确。")
        return payload

    def _put(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method="PUT",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": "Bearer " + get_write_token(),
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                status = response.status
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                error = json.loads(detail)
                message = error.get("message", detail)
            except json.JSONDecodeError:
                message = detail or exc.reason
            raise ApiError(f"HTTP {exc.code}: {message}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError(f"无法连接 SelfIndex API：{exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("API 返回了无效的 JSON。") from exc
        if status not in (200, 202):
            raise ApiError(f"API 返回了非预期状态：HTTP {status}")
        if not isinstance(payload, dict):
            raise ApiError("API 响应格式不正确。")
        return status, payload

    def health(self) -> dict[str, Any]:
        return self._get("/api/v1/health")

    def search(self, query: str, limit: int = 50) -> dict[str, Any]:
        return self._get("/api/v1/search?" + urlencode({"query": query, "limit": limit}), timeout=60)

    def memory(self, memory_unit_id: str) -> dict[str, Any]:
        return self._get("/api/v1/memory/" + quote(memory_unit_id, safe=""))

    def update_memory(
        self, memory_unit_id: str, *, title: str, author: str, content: str,
        expected_revision_id: str, expected_edit_version: int,
    ) -> tuple[int, dict[str, Any]]:
        return self._put(
            "/api/v1/memory/" + quote(memory_unit_id, safe=""),
            {"title": title, "author": author, "content": content,
             "expected_revision_id": expected_revision_id,
             "expected_edit_version": expected_edit_version},
        )
