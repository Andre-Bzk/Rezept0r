"""GET /api/history, DELETE /api/history/{id}, GET /api/history/{id}/image"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services.history_service import get_all, delete_recipe
from app.services import image_service

router = APIRouter()


@router.get("/history")
async def get_history():
    try:
        return get_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{history_id}/image")
async def get_history_image(history_id: int):
    path = image_service.find_cached_image(history_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No cached image")
    ext_to_mime = {v: k for k, v in image_service.MIME_TO_EXT.items()}
    media_type = ext_to_mime.get(path.suffix.lstrip("."), "image/jpeg")
    return FileResponse(path, media_type=media_type)


@router.delete("/history/{history_id}")
async def delete_history_entry(history_id: int):
    cached = image_service.find_cached_image(history_id)
    if cached:
        cached.unlink(missing_ok=True)
    try:
        delete_recipe(history_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
