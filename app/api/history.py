"""GET /api/history, DELETE /api/history/{id}"""
from fastapi import APIRouter, HTTPException
from app.services.history_service import get_all, delete_recipe

router = APIRouter()


@router.get("/history")
async def get_history():
    try:
        return get_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history/{history_id}")
async def delete_history_entry(history_id: int):
    try:
        delete_recipe(history_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
