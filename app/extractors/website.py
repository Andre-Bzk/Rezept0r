"""Website recipe extraction: recipe-scrapers → LD+JSON → GPT-4 fallback."""
from __future__ import annotations
import json
import logging
import re
from typing import AsyncGenerator

import httpx
from bs4 import BeautifulSoup

from app.models import Ingredient, Recipe, StatusEvent

log = logging.getLogger(__name__)

MAX_GPT_CHARS = 12_000


async def extract_website(
    url: str,
) -> AsyncGenerator[StatusEvent | Recipe, None]:
    """Yields StatusEvents then a final Recipe."""

    yield StatusEvent(stage="detecting", message="Erkenne Rezeptseite...", progress=10)
    yield StatusEvent(stage="fetching", message="Lade Seite...", progress=20)

    # Fetch HTML once — reused by all tiers
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Rezept0r/1.0)"},
            )
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        raise RuntimeError(f"Seite konnte nicht geladen werden: {e}") from e

    soup = BeautifulSoup(html, "lxml")

    # Tier 1: recipe-scrapers (uses already-fetched HTML)
    try:
        from recipe_scrapers import scrape_html, NoSchemaFoundInWildMode
        scraper = scrape_html(html, org_url=url, wild_mode=True)
        recipe = _scraper_to_recipe(scraper, url)
        if recipe.ingredients and recipe.steps:
            yield StatusEvent(stage="parsing", message="Rezept geparst.", progress=70)
            yield recipe
            return
    except Exception as e:
        log.info("recipe-scrapers failed (%s), trying LD+JSON fallback", e)

    yield StatusEvent(stage="parsing", message="Suche nach Schema.org-Daten...", progress=40)

    # Tier 2: LD+JSON in page (including Next.js RSC payloads)
    recipe = _try_ldjson(soup, url)
    if recipe and (recipe.ingredients or recipe.steps):
        yield StatusEvent(stage="parsing", message="Schema.org-Daten gefunden.", progress=70)
        yield recipe
        return

    yield StatusEvent(stage="gpt", message="Extrahiere mit KI...", progress=55)

    # Tier 3: GPT-4 fallback
    from app.services.openai_service import extract_recipe_from_text
    article_text = _extract_article_text(soup)
    if not article_text.strip():
        raise RuntimeError("Kein verwertbarer Text auf der Seite gefunden.")

    truncated = article_text[:MAX_GPT_CHARS]
    recipe = await extract_recipe_from_text(truncated, url)
    yield StatusEvent(stage="done", message="Rezept extrahiert.", progress=100)
    yield recipe


def _scraper_to_recipe(scraper, url: str) -> Recipe:
    def safe(fn):
        try:
            return fn()
        except Exception:
            return None

    raw_ingredients = safe(scraper.ingredients) or []
    ingredients = [Ingredient(name=i) for i in raw_ingredients if i]

    raw_instructions = safe(scraper.instructions_list) or []
    if not raw_instructions:
        instr = safe(scraper.instructions) or ""
        raw_instructions = [s.strip() for s in instr.split("\n") if s.strip()] if instr else []

    nutrition_data = safe(scraper.nutrients) or {}
    nutrition = None
    if nutrition_data:
        from app.models import NutritionInfo
        kcal_str = nutrition_data.get("calories", "")
        kcal = _parse_float(kcal_str)
        if kcal:
            nutrition = NutritionInfo(kcal_per_serving=kcal, source="extracted")

    servings = None
    yields_raw = safe(scraper.yields)
    if yields_raw:
        servings = _parse_int(yields_raw)

    return Recipe(
        title=safe(scraper.title) or "Unbekanntes Rezept",
        description=safe(scraper.description),
        image_url=safe(scraper.image),
        source_url=url,
        servings=servings,
        prep_time_minutes=safe(scraper.prep_time),
        cook_time_minutes=safe(scraper.cook_time),
        ingredients=ingredients,
        steps=raw_instructions,
        nutrition=nutrition,
        tags=list(safe(scraper.category) or []) if isinstance(safe(scraper.category), list)
             else ([safe(scraper.category)] if safe(scraper.category) else []),
    )


def _is_recipe_type(data: dict) -> bool:
    t = data.get("@type")
    if isinstance(t, list):
        return "Recipe" in t
    return t == "Recipe"


def _parse_ldjson_candidates(data) -> list[dict]:
    """Return all Recipe-type dicts from a parsed JSON-LD structure."""
    candidates: list[dict] = []
    if isinstance(data, dict):
        if "@graph" in data:
            for item in data["@graph"]:
                if isinstance(item, dict) and _is_recipe_type(item):
                    candidates.append(item)
        elif _is_recipe_type(data):
            candidates.append(data)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and _is_recipe_type(item):
                candidates.append(item)
    return candidates


def _try_ldjson(soup: BeautifulSoup, url: str) -> Recipe | None:
    # Standard <script type="application/ld+json"> tags
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _parse_ldjson_candidates(data):
            return _ldjson_to_recipe(item, url)

    # Next.js RSC streaming payloads: self.__next_f.push([1,"<json-encoded-string>"])
    for script in soup.find_all("script"):
        text = script.string or ""
        if "recipeInstructions" not in text and "@type" not in text:
            continue
        m = re.search(r'self\.__next_f\.push\(\[1,"(.+)"\]\)\s*$', text, re.DOTALL)
        if not m:
            continue
        try:
            decoded = json.loads('"' + m.group(1) + '"')
            data = json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            continue
        for item in _parse_ldjson_candidates(data):
            return _ldjson_to_recipe(item, url)

    return None


def _ldjson_to_recipe(data: dict, url: str) -> Recipe:
    from app.models import NutritionInfo

    ingredients_raw = data.get("recipeIngredient", [])
    ingredients = [Ingredient(name=i) for i in ingredients_raw if isinstance(i, str)]

    instructions_raw = data.get("recipeInstructions", [])
    steps: list[str] = []
    if isinstance(instructions_raw, str):
        steps = [s.strip() for s in instructions_raw.split("\n") if s.strip()]
    elif isinstance(instructions_raw, list):
        for item in instructions_raw:
            if isinstance(item, str):
                steps.append(item)
            elif isinstance(item, dict):
                item_type = item.get("@type", "")
                # HowToSection: recurse into itemListElement
                if item_type == "HowToSection":
                    for sub in item.get("itemListElement", []):
                        if isinstance(sub, dict):
                            text = sub.get("text", "") or sub.get("name", "")
                            if text:
                                steps.append(text)
                else:
                    text = item.get("text", "") or item.get("name", "")
                    if text:
                        steps.append(text)

    nutrition = None
    nutr_data = data.get("nutrition", {})
    if isinstance(nutr_data, dict):
        kcal = _parse_float(nutr_data.get("calories", ""))
        if kcal:
            nutrition = NutritionInfo(kcal_per_serving=kcal, source="extracted")

    yields_raw = data.get("recipeYield", data.get("yield", ""))
    servings = None
    if isinstance(yields_raw, list) and yields_raw:
        servings = _parse_int(str(yields_raw[0]))
    elif isinstance(yields_raw, (str, int)):
        servings = _parse_int(str(yields_raw))

    keywords = data.get("keywords", "")
    if isinstance(keywords, str):
        tags = [k.strip() for k in keywords.split(",") if k.strip()]
    elif isinstance(keywords, list):
        tags = [str(k).strip() for k in keywords if k]
    else:
        tags = []

    categories = data.get("recipeCategory", [])
    if isinstance(categories, str):
        tags += [categories]
    elif isinstance(categories, list):
        tags += categories

    return Recipe(
        title=data.get("name", "Unbekanntes Rezept"),
        description=data.get("description"),
        image_url=_extract_image_url(data.get("image")),
        source_url=url,
        servings=servings,
        prep_time_minutes=_parse_duration(data.get("prepTime")),
        cook_time_minutes=_parse_duration(data.get("cookTime")),
        ingredients=ingredients,
        steps=steps,
        nutrition=nutrition,
        tags=list(set(tags))[:10],
    )


def _extract_article_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    for selector in ["article", "main", '[class*="recipe"]', '[id*="recipe"]']:
        el = soup.select_one(selector)
        if el:
            return el.get_text(separator="\n", strip=True)
    return soup.get_text(separator="\n", strip=True)


def _extract_image_url(image) -> str | None:
    if not image:
        return None
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        first = image[0]
        return first.get("url") if isinstance(first, dict) else str(first)
    if isinstance(image, dict):
        return image.get("url") or image.get("contentUrl")
    return None


def _parse_float(s: str | None) -> float | None:
    if not s:
        return None
    import re
    m = re.search(r"[\d.]+", str(s))
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


def _parse_int(s: str | None) -> int | None:
    if not s:
        return None
    import re
    m = re.search(r"\d+", str(s))
    try:
        return int(m.group()) if m else None
    except ValueError:
        return None


def _parse_duration(iso: str | None) -> int | None:
    """Parse ISO 8601 duration (PT1H30M) → minutes."""
    if not iso:
        return None
    import re
    hours = re.search(r"(\d+)H", iso)
    minutes = re.search(r"(\d+)M", iso)
    total = 0
    if hours:
        total += int(hours.group(1)) * 60
    if minutes:
        total += int(minutes.group(1))
    return total or None
