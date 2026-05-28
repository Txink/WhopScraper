"""Shared image downloader — fetches a remote (whop CDN) image and caches it
under ``<data_dir>/chat-images/<msg_id><ext>``.

Used by both ``app.whop.chat_writer`` (chat-source messages) and
``app.parser.service`` (stock/option image messages). whop attachment image
URLs are public CDN links, so no auth headers are needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)

_CONTENT_TYPE_EXT: dict[str, str] = {
    "image/avif": ".avif",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def download_image(
    msg_id: str, remote_url: str, data_dir: Path
) -> str | None:
    """Download *remote_url* into ``<data_dir>/chat-images/<msg_id><ext>``.

    Returns the filename (basename only) on success, or None on any failure
    (network error, HTTP error, timeout). All errors are caught and logged —
    image cache failures must not break message ingestion.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(remote_url)
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = _CONTENT_TYPE_EXT.get(ct, ".bin")
            target_dir = data_dir / "chat-images"
            target_dir.mkdir(parents=True, exist_ok=True)
            # Path(...).name strips any "../" or "/" segments — defensive
            # against a malicious msg_id.
            filename = f"{Path(msg_id).name}{ext}"
            (target_dir / filename).write_bytes(resp.content)
            return filename
    except Exception:  # noqa: BLE001
        _log.warning(
            "image download failed for msg_id=%s url=%s",
            msg_id,
            remote_url,
            exc_info=True,
        )
        return None
