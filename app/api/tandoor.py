"""POST /api/import – import recipe to Tandoor."""
from fastapi import APIRouter, HTTPException
from app.models import ExtractResponse
from app.services.tandoor_service import import_to_tandoor
from app.services.history_service import mark_imported

router = APIRouter()


@router.post("/import")
async def import_recipe(data: ExtractResponse):
    try:
        result = await import_to_tandoor(data.recipe)
        tandoor_recipe_id = result.get("id")
        if data.history_id:
            mark_imported(data.history_id, tandoor_recipe_id)
        return {"status": "ok", "recipe_id": tandoor_recipe_id}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import fehlgeschlagen: {e}")
