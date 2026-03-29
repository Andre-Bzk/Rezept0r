"""Tandoor REST API client."""
from __future__ import annotations
import logging
from typing import Optional

import httpx

from app.config import get_settings
from app.models import (
    Ingredient,
    Recipe,
    TandoorIngredient,
    TandoorRecipe,
    TandoorStep,
)

log = logging.getLogger(__name__)


def recipe_to_tandoor(recipe: Recipe) -> TandoorRecipe:
    """Convert internal Recipe to Tandoor-compatible import format."""
    working_time = (recipe.prep_time_minutes or 0) + (recipe.cook_time_minutes or 0)

    # All ingredients go into step[0] (Tandoor convention)
    tandoor_ingredients = [_to_tandoor_ingredient(ing) for ing in recipe.ingredients]

    # Build steps: first step carries all ingredients, subsequent steps are plain text
    steps: list[TandoorStep] = []
    for i, step_text in enumerate(recipe.steps):
        step = TandoorStep(
            instruction=step_text,
            ingredients=tandoor_ingredients if i == 0 else [],
            time=0,
        )
        steps.append(step)

    if not steps:
        # If no steps, create a placeholder with all ingredients
        steps = [TandoorStep(instruction="Zubereitung", ingredients=tandoor_ingredients)]

    keywords = [{"label": tag, "name": tag} for tag in recipe.tags]

    servings_text = "Portionen"
    if recipe.nutrition and recipe.nutrition.kcal_per_serving:
        kcal = round(recipe.nutrition.kcal_per_serving)
        servings_text = f"Portionen (ca. {kcal} kcal)"

    return TandoorRecipe(
        name=recipe.title,
        description=recipe.description or "",
        servings=recipe.servings or 1,
        working_time=working_time,
        source_url=recipe.source_url,
        image=recipe.image_url,
        steps=steps,
        keywords=keywords,
        servings_text=servings_text,
    )


def _to_tandoor_ingredient(ing: Ingredient) -> TandoorIngredient:
    amount = 0.0
    if ing.amount:
        try:
            from app.services.nutrition import _parse_float
            val = _parse_float(ing.amount)
            amount = val if val is not None else 0.0
        except Exception:
            amount = 0.0

    unit = {"name": ing.unit} if ing.unit else None

    return TandoorIngredient(
        food={"name": ing.name},
        amount=amount,
        unit=unit,
        note=ing.note or "",
    )


async def import_to_tandoor(recipe: Recipe) -> dict:
    """Import a recipe to Tandoor via REST API. Returns created recipe data."""
    settings = get_settings()

    if not settings.tandoor_api_token:
        raise RuntimeError("TANDOOR_API_TOKEN nicht konfiguriert.")
    if not settings.tandoor_base_url:
        raise RuntimeError("TANDOOR_BASE_URL nicht konfiguriert.")

    base_url = settings.tandoor_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.tandoor_api_token}",
        "Content-Type": "application/json",
    }

    tandoor_recipe = recipe_to_tandoor(recipe)
    payload = tandoor_recipe.model_dump(exclude={"image"})

    async with httpx.AsyncClient(timeout=30) as client:
        # POST recipe
        resp = await client.post(
            f"{base_url}/api/recipe/",
            json=payload,
            headers=headers,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Tandoor API Fehler {resp.status_code}: {resp.text[:300]}"
            )
        created = resp.json()
        recipe_id = created.get("id")

        # Upload image if available
        if recipe.image_url and recipe_id:
            await _upload_image(client, base_url, recipe_id, recipe.image_url, settings.tandoor_api_token)

    return created


async def _upload_image(
    client: httpx.AsyncClient,
    base_url: str,
    recipe_id: int,
    image_url: str,
    token: str,
) -> None:
    """Download image from URL and upload to Tandoor."""
    try:
        img_resp = await client.get(image_url, follow_redirects=True, timeout=15)
        img_resp.raise_for_status()
        image_data = img_resp.content

        # Determine content type
        content_type = img_resp.headers.get("content-type", "image/jpeg").split(";")[0]
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "jpg")

        files = {"image": (f"recipe.{ext}", image_data, content_type)}
        patch_resp = await client.patch(
            f"{base_url}/api/recipe/{recipe_id}/",
            files=files,
            headers={"Authorization": f"Bearer {token}"},  # NO Content-Type here
        )
        if patch_resp.status_code not in (200, 201):
            log.warning("Image upload failed: %s", patch_resp.text[:200])
    except Exception as e:
        log.warning("Could not upload image: %s", e)
