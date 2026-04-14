"""Local image caching for recipe history."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def images_dir() -> Path:
    p = Path(get_settings().images_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def find_cached_image(history_id: int) -> Optional[Path]:
    """Return the cached image Path for a history entry, or None."""
    for ext in MIME_TO_EXT.values():
        p = images_dir() / f"{history_id}.{ext}"
        if p.exists():
            return p
    return None


async def download_and_cache(history_id: int, remote_url: str) -> Optional[str]:
    """Download image from remote_url, save locally, return local API path or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(remote_url, follow_redirects=True)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            ext = MIME_TO_EXT.get(ct, "jpg")
            dest = images_dir() / f"{history_id}.{ext}"
            dest.write_bytes(resp.content)
            log.info("Cached image for history %d → %s", history_id, dest)
            return f"/api/history/{history_id}/image"
    except Exception as exc:
        log.warning("Image cache failed for history %d: %s", history_id, exc)
        return None
