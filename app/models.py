from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class Ingredient(BaseModel):
    name: str
    amount: Optional[str] = None
    unit: Optional[str] = None
    note: Optional[str] = None


class NutritionInfo(BaseModel):
    kcal_per_serving: Optional[float] = None
    kcal_total: Optional[float] = None
    servings: Optional[int] = None
    source: str = "extracted"  # "extracted" | "usda" | "gpt4_estimate"


class Recipe(BaseModel):
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    source_url: str
    servings: Optional[int] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    ingredients: list[Ingredient] = []
    steps: list[str] = []
    nutrition: Optional[NutritionInfo] = None
    tags: list[str] = []


class TandoorStep(BaseModel):
    instruction: str
    ingredients: list[TandoorIngredient] = []
    time: int = 0


class TandoorIngredient(BaseModel):
    food: dict  # {"name": str}
    amount: float = 0
    unit: Optional[dict] = None  # {"name": str} or None
    note: str = ""


class TandoorRecipe(BaseModel):
    name: str
    description: str = ""
    servings: int = 1
    working_time: int = 0
    source_url: str = ""
    image: Optional[str] = None
    steps: list[TandoorStep] = []
    keywords: list[dict] = []
    internal: bool = True
    show_ingredient_overview: bool = False
    servings_text: str = "Portionen"


class ExtractResponse(BaseModel):
    recipe: Recipe
    tandoor_json: TandoorRecipe
    history_id: Optional[int] = None


class StatusEvent(BaseModel):
    stage: str
    message: str
    progress: int


class ErrorEvent(BaseModel):
    message: str
