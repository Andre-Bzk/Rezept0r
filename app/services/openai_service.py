"""OpenAI integration: Whisper transcription + GPT-4o-mini recipe extraction."""
from __future__ import annotations
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI, AuthenticationError, RateLimitError, APIConnectionError

from app.config import get_settings
from app.models import Ingredient, NutritionInfo, Recipe

log = logging.getLogger(__name__)

_RECIPE_SYSTEM_PROMPT = """Du bist ein Rezept-Extraktor. Extrahiere das Rezept aus dem Text und antworte NUR mit einem JSON-Objekt (kein Markdown).

JSON-Schema:
{
  "title": "string",
  "description": "string oder null",
  "servings": integer oder null,
  "prep_time_minutes": integer oder null,
  "cook_time_minutes": integer oder null,
  "ingredients": [
    {"name": "string", "amount": "string oder null", "unit": "string oder null", "note": "string oder null"}
  ],
  "steps": ["string"],
  "kcal_per_serving": number oder null,
  "tags": ["string"]
}

Regeln:
- amount ist immer ein String (z.B. "200", "1/2", "2-3")
- unit ist die Maßeinheit (g, ml, EL, TL, Stück, etc.)
- Wenn keine Kalorien erkennbar sind, setze kcal_per_serving auf null
- steps sind vollständige Zubereitungsschritte
- tags: maximal 5 relevante Schlagwörter
"""

_CAPTION_CHECK_PROMPT = """Enthält der folgende Text ein vollständiges Rezept mit Zutaten UND Zubereitungsschritten?
Antworte NUR mit einem JSON-Objekt: {"has_recipe": true} oder {"has_recipe": false}

Text:
"""


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=get_settings().openai_api_key)


def _openai_error(e: Exception) -> RuntimeError:
    if isinstance(e, AuthenticationError):
        return RuntimeError("OpenAI API-Schlüssel ungültig oder abgelaufen.")
    if isinstance(e, RateLimitError):
        return RuntimeError("OpenAI Rate-Limit erreicht. Bitte kurz warten und erneut versuchen.")
    if isinstance(e, APIConnectionError):
        return RuntimeError("OpenAI nicht erreichbar. Internetverbindung prüfen.")
    return RuntimeError(f"OpenAI-Fehler: {e}")


async def check_caption_has_recipe(text: str) -> bool:
    """Check if a video description/caption contains a complete recipe."""
    client = _get_client()
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": _CAPTION_CHECK_PROMPT + text[:3000]}
            ],
            max_tokens=20,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return bool(data.get("has_recipe", False))
    except (AuthenticationError, RateLimitError, APIConnectionError) as e:
        raise _openai_error(e) from e
    except Exception as e:
        log.warning("Caption check failed: %s", e)
        return False


async def transcribe_audio(audio_path: Path) -> str:
    """Transcribe audio file with Whisper API."""
    client = _get_client()
    try:
        with open(audio_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="de",
                response_format="text",
            )
        return str(transcript)
    except (AuthenticationError, RateLimitError, APIConnectionError) as e:
        raise _openai_error(e) from e


async def extract_recipe_from_text(text: str, source_url: str) -> Recipe:
    """Use GPT-4o-mini to extract a structured recipe from text."""
    client = _get_client()
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _RECIPE_SYSTEM_PROMPT},
                {"role": "user", "content": text[:12000]},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
    except (AuthenticationError, RateLimitError, APIConnectionError) as e:
        raise _openai_error(e) from e
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    return _gpt_json_to_recipe(data, source_url)


async def estimate_nutrition_gpt(ingredients: list[Ingredient], servings: int) -> NutritionInfo:
    """Estimate kcal using GPT-4o-mini as last resort."""
    client = _get_client()
    ing_text = "\n".join(
        f"- {i.amount or ''} {i.unit or ''} {i.name} {('(' + i.note + ')') if i.note else ''}".strip()
        for i in ingredients
    )
    prompt = (
        f"Schätze die Gesamtkalorienzahl und Kalorien pro Portion für folgende Zutaten "
        f"({servings} Portionen):\n{ing_text}\n\n"
        'Antworte NUR mit JSON: {"kcal_total": number, "kcal_per_serving": number}'
    )
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return NutritionInfo(
            kcal_per_serving=data.get("kcal_per_serving"),
            kcal_total=data.get("kcal_total"),
            servings=servings,
            source="gpt4_estimate",
        )
    except (AuthenticationError, RateLimitError, APIConnectionError) as e:
        log.warning("GPT nutrition estimate failed (API): %s", _openai_error(e))
        return NutritionInfo(source="gpt4_estimate")
    except Exception as e:
        log.warning("GPT nutrition estimate failed: %s", e)
        return NutritionInfo(source="gpt4_estimate")


def _gpt_json_to_recipe(data: dict, source_url: str) -> Recipe:
    ingredients = [
        Ingredient(
            name=i.get("name", ""),
            amount=i.get("amount"),
            unit=i.get("unit"),
            note=i.get("note"),
        )
        for i in data.get("ingredients", [])
        if i.get("name")
    ]

    nutrition = None
    kcal = data.get("kcal_per_serving")
    if kcal:
        try:
            nutrition = NutritionInfo(kcal_per_serving=float(kcal), source="extracted")
        except (ValueError, TypeError):
            pass

    return Recipe(
        title=data.get("title", "Unbekanntes Rezept"),
        description=data.get("description"),
        image_url=None,
        source_url=source_url,
        servings=data.get("servings"),
        prep_time_minutes=data.get("prep_time_minutes"),
        cook_time_minutes=data.get("cook_time_minutes"),
        ingredients=ingredients,
        steps=data.get("steps", []),
        nutrition=nutrition,
        tags=data.get("tags", [])[:10],
    )
