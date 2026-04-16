"""Video recipe extraction: yt-dlp → caption check → Whisper → GPT-4."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import subprocess
import uuid
from functools import partial
from pathlib import Path
from typing import AsyncGenerator

from app.config import get_settings
from app.models import Recipe, StatusEvent
from app.services.openai_service import (
    check_caption_has_recipe,
    extract_recipe_from_text,
    transcribe_audio,
)

log = logging.getLogger(__name__)

MAX_DURATION_WARN = 20 * 60  # 20 minutes in seconds
MAX_FILESIZE = "50m"
WHISPER_MAX_BYTES = 24 * 1024 * 1024  # 25MB limit, buffer to 24MB


async def extract_video(url: str) -> AsyncGenerator[StatusEvent | Recipe, None]:
    yield StatusEvent(stage="detecting", message="Erkenne Plattform...", progress=5)

    # Step 1: Get metadata without downloading
    yield StatusEvent(stage="metadata", message="Lade Video-Metadaten...", progress=10)
    metadata = await _get_metadata(url)

    title = metadata.get("title", "")
    description = metadata.get("description", "") or ""
    tags = metadata.get("tags") or []
    duration = metadata.get("duration") or 0

    # Step 2: Check if caption/description contains a complete recipe
    yield StatusEvent(stage="caption", message="Prüfe Video-Beschreibung...", progress=20)

    caption_text = f"{title}\n\n{description}"
    has_recipe_in_caption = await check_caption_has_recipe(caption_text)

    if has_recipe_in_caption:
        yield StatusEvent(stage="extracting", message="Extrahiere Rezept aus Beschreibung...", progress=50)
        enriched_text = f"Titel: {title}\n\nBeschreibung:\n{description}"
        recipe = await extract_recipe_from_text(enriched_text, url)
        if recipe.image_url is None:
            recipe.image_url = _get_thumbnail(metadata)
        if not recipe.tags and tags:
            recipe.tags = [str(t) for t in tags[:5]]
        yield StatusEvent(stage="done", message="Rezept aus Beschreibung extrahiert.", progress=95)
        yield recipe
        return

    # Step 3: Audio download + transcription fallback
    if duration > MAX_DURATION_WARN:
        yield StatusEvent(
            stage="warning",
            message=f"Video ist {duration // 60} Min. lang – Transkription kann dauern.",
            progress=25,
        )

    yield StatusEvent(stage="downloading", message="Lade Audio herunter...", progress=30)

    settings = get_settings()
    audio_path = Path(settings.tmp_dir) / f"{uuid.uuid4()}.mp3"

    try:
        await _download_audio(url, audio_path)

        # Check file size for Whisper limit
        if audio_path.exists():
            size = audio_path.stat().st_size
            if size > WHISPER_MAX_BYTES:
                raise RuntimeError(
                    f"Audio-Datei zu groß ({size // 1024 // 1024} MB). "
                    "Whisper unterstützt max. 25MB. Bitte kürzeres Video verwenden."
                )
        else:
            raise RuntimeError("Audio-Download fehlgeschlagen.")

        yield StatusEvent(stage="transcribing", message="Transkribiere Audio (Whisper)...", progress=55)
        transcript = await transcribe_audio(audio_path)

        if not transcript.strip():
            raise RuntimeError("Transkription leer. Kein gesprochener Text erkannt.")

        yield StatusEvent(stage="extracting", message="Extrahiere Rezept aus Transkription...", progress=75)

        enriched_text = (
            f"Video-Titel: {title}\n"
            f"Beschreibung: {description[:500]}\n\n"
            f"Transkription:\n{transcript}"
        )
        recipe = await extract_recipe_from_text(enriched_text, url)
        if recipe.image_url is None:
            recipe.image_url = _get_thumbnail(metadata)
        if not recipe.tags and tags:
            recipe.tags = [str(t) for t in tags[:5]]

        yield StatusEvent(stage="done", message="Rezept extrahiert.", progress=95)
        yield recipe

    except FileNotFoundError:
        raise RuntimeError(
            "yt-dlp nicht gefunden. Bitte sicherstellen, dass yt-dlp installiert ist."
        )
    except Exception:
        raise
    finally:
        if audio_path.exists():
            try:
                audio_path.unlink()
            except Exception as e:
                log.warning("Could not delete tmp file %s: %s", audio_path, e)


def _ytdlp_extra_args() -> list[str]:
    """Return optional yt-dlp flags from settings (ffmpeg, proxy, cookies)."""
    settings = get_settings()
    args: list[str] = []
    if settings.ffmpeg_location and Path(settings.ffmpeg_location).exists():
        args += ["--ffmpeg-location", settings.ffmpeg_location]
    return args


async def _run_yt_dlp(*args: str, timeout: int) -> tuple[bytes, bytes, int]:
    """Run yt-dlp in a thread executor — works on any event loop (Windows + Linux)."""
    loop = asyncio.get_event_loop()
    func = partial(subprocess.run, args, capture_output=True, timeout=timeout)
    result = await loop.run_in_executor(None, func)
    return result.stdout, result.stderr, result.returncode


async def _get_metadata(url: str) -> dict:
    """Run yt-dlp --dump-json to get metadata without downloading."""
    stdout, stderr, returncode = await _run_yt_dlp(
        "yt-dlp", "--dump-json", "--no-playlist", *_ytdlp_extra_args(), url, timeout=60
    )
    if returncode != 0:
        err = stderr.decode(errors="replace")
        _check_tiktok_error(err, url)
        raise RuntimeError(f"yt-dlp Metadaten-Fehler: {err[:500]}")
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {}


async def _download_audio(url: str, output_path: Path) -> None:
    """Download audio only via yt-dlp subprocess (non-blocking)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        stdout, stderr, returncode = await _run_yt_dlp(
            "yt-dlp",
            "--no-playlist",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "--max-filesize", MAX_FILESIZE,
            *_ytdlp_extra_args(),
            "--output", str(output_path).replace(".mp3", ".%(ext)s"),
            url,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Audio-Download Timeout (5 Min.) überschritten.")

    if returncode != 0:
        err = stderr.decode(errors="replace")
        _check_tiktok_error(err, url)
        raise RuntimeError(f"Audio-Download fehlgeschlagen: {err[:500]}")

    # yt-dlp may output with different extension before conversion
    # Try to find the actual file
    if not output_path.exists():
        parent = output_path.parent
        stem = output_path.stem
        for f in parent.glob(f"{stem}*"):
            if f.suffix in (".mp3", ".m4a", ".webm", ".opus"):
                f.rename(output_path)
                break


def _get_thumbnail(metadata: dict) -> str | None:
    thumbnail = metadata.get("thumbnail")
    if thumbnail:
        return thumbnail
    thumbnails = metadata.get("thumbnails") or []
    if thumbnails:
        # prefer largest
        best = max(thumbnails, key=lambda t: (t.get("width", 0) or 0), default=None)
        if best:
            return best.get("url")
    return None


def _check_tiktok_error(stderr: str, url: str) -> None:
    """Raise a clear error for TikTok connectivity/auth issues."""
    if "tiktok" not in url.lower():
        return
    err_lower = stderr.lower()
    if any(p in err_lower for p in ["connection refused", "failed to establish", "unable to download webpage"]):
        raise RuntimeError(
            "TikTok ist vom Server nicht erreichbar (Verbindung verweigert). "
            "Möglicherweise blockiert die installierte yt-dlp-Version TikTok. "
            "Bitte Docker-Image neu bauen: docker compose up -d --build"
        )
    if any(p in err_lower for p in ["login", "cookie", "captcha", "403"]):
        raise RuntimeError(
            "TikTok erfordert Cookies für dieses Video. "
            "Exportiere Browser-Cookies und setze YTDLP_COOKIES_FILE=/pfad/cookies.txt in der .env."
        )
