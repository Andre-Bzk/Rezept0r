"""GET /api/extract/stream – SSE endpoint."""
from __future__ import annotations
import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.extractors.base import is_video_url
from app.extractors.website import extract_website
from app.extractors.video import extract_video
from app.models import Recipe, StatusEvent, ErrorEvent, ExtractResponse
from app.services.nutrition import enrich_nutrition
from app.services.tandoor_service import recipe_to_tandoor
from app.services.history_service import save_recipe as save_to_history, update_image_url
from app.services import image_service

log = logging.getLogger(__name__)
router = APIRouter()


async def _cache_image_background(history_id: int, remote_url: str) -> None:
    local_path = await image_service.download_and_cache(history_id, remote_url)
    if local_path:
        try:
            update_image_url(history_id, local_path)
        except Exception as e:
            log.warning("Failed to update image_url in DB: %s", e)


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def _stream(url: str) -> AsyncGenerator[str, None]:
    try:
        recipe: Recipe | None = None
        pipeline = extract_video(url) if is_video_url(url) else extract_website(url)

        async for item in pipeline:
            if isinstance(item, StatusEvent):
                yield _sse("status", item.model_dump_json())
            elif isinstance(item, Recipe):
                recipe = item

        if recipe is None:
            raise RuntimeError("Kein Rezept extrahiert.")

        # Nutrition enrichment (may yield status events in future; here inline)
        yield _sse("status", StatusEvent(
            stage="nutrition", message="Berechne Nährwerte...", progress=90
        ).model_dump_json())

        recipe = await enrich_nutrition(recipe)

        tandoor_json = recipe_to_tandoor(recipe)
        base = ExtractResponse(recipe=recipe, tandoor_json=tandoor_json)
        history_id = None
        try:
            history_id = save_to_history(base.model_dump())
        except Exception as db_err:
            log.warning("History save failed: %s", db_err)
        if history_id and recipe.image_url:
            asyncio.create_task(_cache_image_background(history_id, recipe.image_url))
        response = ExtractResponse(recipe=recipe, tandoor_json=tandoor_json, history_id=history_id)
        yield _sse("result", response.model_dump_json())

    except Exception as e:
        log.exception("Extraction error for %s", url)
        yield _sse("error", ErrorEvent(message=str(e)).model_dump_json())


@router.get("/extract/stream")
async def extract_stream(url: str):
    if not url or not url.startswith(("http://", "https://")):
        async def bad():
            yield _sse("error", ErrorEvent(message="Ungültige URL.").model_dump_json())
        return StreamingResponse(
            bad(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return StreamingResponse(
        _stream(url),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
