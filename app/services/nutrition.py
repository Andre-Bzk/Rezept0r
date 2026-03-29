"""3-Tier nutrition strategy: extracted → USDA FoodData → GPT-4 estimate."""
from __future__ import annotations
import logging
import re
from typing import Optional

import httpx

from app.config import get_settings
from app.models import Ingredient, NutritionInfo, Recipe

log = logging.getLogger(__name__)

USDA_API_URL = "https://api.nal.usda.gov/fdc/v1"
MIN_USDA_COVERAGE = 0.5  # require ≥50% ingredients resolved


async def enrich_nutrition(recipe: Recipe) -> Recipe:
    """Enrich recipe with nutrition info using 3-tier fallback."""
    # Tier 1: Already extracted from source
    if recipe.nutrition and recipe.nutrition.kcal_per_serving:
        return recipe

    if not recipe.ingredients:
        return recipe

    servings = recipe.servings or 1

    # Tier 2: USDA FoodData
    try:
        nutrition = await _usda_lookup(recipe.ingredients, servings)
        if nutrition and nutrition.kcal_per_serving:
            recipe = recipe.model_copy(update={"nutrition": nutrition})
            return recipe
    except Exception as e:
        log.warning("USDA lookup failed: %s", e)

    # Tier 3: GPT-4 estimate (only if OpenAI key configured)
    settings = get_settings()
    if settings.openai_api_key:
        try:
            from app.services.openai_service import estimate_nutrition_gpt
            nutrition = await estimate_nutrition_gpt(recipe.ingredients, servings)
            recipe = recipe.model_copy(update={"nutrition": nutrition})
        except Exception as e:
            log.warning("GPT-4 nutrition estimate failed: %s", e)

    return recipe


async def _usda_lookup(ingredients: list[Ingredient], servings: int) -> Optional[NutritionInfo]:
    """Look up each ingredient in USDA FoodData API and sum kcal."""
    settings = get_settings()
    api_key = settings.usda_api_key or "DEMO_KEY"

    total_kcal = 0.0
    resolved = 0

    async with httpx.AsyncClient(timeout=10) as client:
        for ing in ingredients:
            try:
                kcal = await _usda_ingredient_kcal(client, ing, api_key)
                if kcal is not None:
                    total_kcal += kcal
                    resolved += 1
            except Exception as e:
                log.debug("USDA lookup for '%s' failed: %s", ing.name, e)

    coverage = resolved / len(ingredients) if ingredients else 0
    if coverage < MIN_USDA_COVERAGE:
        log.info("USDA coverage %.0f%% < 50%%, skipping", coverage * 100)
        return None

    kcal_per_serving = total_kcal / servings if servings else total_kcal
    return NutritionInfo(
        kcal_per_serving=round(kcal_per_serving, 1),
        kcal_total=round(total_kcal, 1),
        servings=servings,
        source="usda",
    )


async def _usda_ingredient_kcal(
    client: httpx.AsyncClient,
    ing: Ingredient,
    api_key: str,
) -> Optional[float]:
    """Search USDA for one ingredient and return estimated kcal."""
    resp = await client.get(
        f"{USDA_API_URL}/foods/search",
        params={
            "query": ing.name,
            "dataType": "Foundation,SR Legacy",
            "pageSize": 1,
            "api_key": api_key,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    foods = data.get("foods", [])
    if not foods:
        return None

    food = foods[0]
    # Find Energy (kcal) nutrient
    nutrients = food.get("foodNutrients", [])
    kcal_per_100g = None
    for n in nutrients:
        name = (n.get("nutrientName") or "").lower()
        unit = (n.get("unitName") or "").upper()
        if "energy" in name and unit == "KCAL":
            kcal_per_100g = n.get("value")
            break

    if kcal_per_100g is None:
        return None

    grams = _estimate_grams(ing)
    if grams is None:
        return None

    return kcal_per_100g * grams / 100


def _estimate_grams(ing: Ingredient) -> Optional[float]:
    """Convert ingredient amount + unit to grams (approximate)."""
    if not ing.amount:
        return None

    amount_val = _parse_float(ing.amount)
    if amount_val is None:
        return None

    unit = (ing.unit or "").lower().strip()

    # Direct weight
    if unit in ("g", "gr", "gramm", "gram"):
        return amount_val
    if unit in ("kg", "kilogramm"):
        return amount_val * 1000
    if unit in ("mg", "milligramm"):
        return amount_val / 1000

    # Volume → grams (approximate, assuming water density)
    if unit in ("ml", "milliliter", "millilitre"):
        return amount_val
    if unit in ("l", "liter", "litre"):
        return amount_val * 1000
    if unit in ("el", "esslöffel", "tbsp", "tablespoon"):
        return amount_val * 15
    if unit in ("tl", "teelöffel", "tsp", "teaspoon"):
        return amount_val * 5
    if unit in ("cup", "cups", "tasse"):
        return amount_val * 240

    # Count → fallback average
    if unit in ("stück", "stk", "piece", "pieces", "", "pcs"):
        return amount_val * 100  # rough average

    # Unknown unit → assume grams
    return amount_val


def _parse_float(s: str) -> Optional[float]:
    if not s:
        return None
    # Handle fractions like "1/2"
    frac = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", s)
    if frac:
        return int(frac.group(1)) / int(frac.group(2))
    # Handle mixed like "1 1/2"
    mixed = re.match(r"^\s*(\d+)\s+(\d+)\s*/\s*(\d+)\s*$", s)
    if mixed:
        return int(mixed.group(1)) + int(mixed.group(2)) / int(mixed.group(3))
    # Range like "2-3" → take first
    range_m = re.match(r"^\s*([\d.]+)\s*[-–]\s*([\d.]+)\s*$", s)
    if range_m:
        return float(range_m.group(1))
    # Plain float
    plain = re.search(r"[\d.]+", s)
    if plain:
        try:
            return float(plain.group())
        except ValueError:
            return None
    return None
