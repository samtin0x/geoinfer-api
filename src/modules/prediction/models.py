"""Model configurations for GeoInfer prediction models."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel

from src.database.models.usage import ModelType


class ModelId(str, Enum):
    """Unique identifiers for each prediction model."""

    GLOBAL_V0_1 = "global_v0.1"
    MADRID_V0_1 = "madrid_v0.1"
    LA_PALMA_V0_1 = "la_palma_v0.1"
    PROPERTY_V0_1 = "property_v0.1"
    CARS_V0_1 = "cars_v0.1"


class ModelGeofence(BaseModel):
    """Geographic boundary for region-specific models."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]  # [lng, lat] pairs


class ModelConfig(BaseModel):
    """Configuration for a prediction model."""

    id: ModelId
    type: ModelType
    name: str
    version: str
    country: str | None = None
    country_name: str | None = None
    center_coordinates: tuple[float, float]  # [lat, lng]
    default_zoom: int
    enabled: bool = True
    search_terms: list[str] | None = None
    geofence: ModelGeofence | None = None


# Credit costs by MODEL TYPE
MODEL_TYPE_CREDIT_COSTS: dict[ModelType, int] = {
    ModelType.GLOBAL: 1,
    ModelType.CARS: 2,
    ModelType.PROPERTY: 3,
    ModelType.ACCURACY: 3,
}


# Map each ModelId → ModelType
MODEL_ID_TO_TYPE: dict[ModelId, ModelType] = {
    ModelId.GLOBAL_V0_1: ModelType.GLOBAL,
    ModelId.MADRID_V0_1: ModelType.ACCURACY,
    ModelId.LA_PALMA_V0_1: ModelType.ACCURACY,
    ModelId.PROPERTY_V0_1: ModelType.PROPERTY,
    ModelId.CARS_V0_1: ModelType.CARS,
}


# Configuration to hide model types from the selector UI
HIDDEN_MODEL_TYPES: dict[str, bool] = {
    "accuracy": True,
    "cars": True,
    "property": True,
}


# Full model configurations
MODELS: dict[ModelId, ModelConfig] = {
    ModelId.GLOBAL_V0_1: ModelConfig(
        id=ModelId.GLOBAL_V0_1,
        type=ModelType.GLOBAL,
        name="Global",
        version="0.1",
        center_coordinates=(40.7128, -74.006),
        default_zoom=13,
        enabled=True,
    ),
    ModelId.MADRID_V0_1: ModelConfig(
        id=ModelId.MADRID_V0_1,
        type=ModelType.ACCURACY,
        name="Madrid",
        version="0.1",
        country="ES",
        country_name="Spain",
        center_coordinates=(40.4168, -3.7038),
        default_zoom=14,
        enabled=False,
        search_terms=["madrid", "spain", "españa", "es"],
        geofence=ModelGeofence(
            type="Polygon",
            coordinates=[
                [
                    (-3.9, 40.3),
                    (-3.5, 40.3),
                    (-3.5, 40.6),
                    (-3.9, 40.6),
                    (-3.9, 40.3),
                ]
            ],
        ),
    ),
    ModelId.LA_PALMA_V0_1: ModelConfig(
        id=ModelId.LA_PALMA_V0_1,
        type=ModelType.ACCURACY,
        name="La Palma",
        version="0.1",
        country="ES",
        country_name="Spain",
        center_coordinates=(28.6835, -17.7643),
        default_zoom=11,
        enabled=False,
        search_terms=["la palma", "palma", "canary islands", "canarias", "spain", "es"],
        geofence=ModelGeofence(
            type="Polygon",
            coordinates=[
                [
                    (-17.95, 28.4),
                    (-17.7, 28.4),
                    (-17.7, 28.9),
                    (-17.95, 28.9),
                    (-17.95, 28.4),
                ]
            ],
        ),
    ),
    ModelId.PROPERTY_V0_1: ModelConfig(
        id=ModelId.PROPERTY_V0_1,
        type=ModelType.PROPERTY,
        name="Property",
        version="0.1",
        center_coordinates=(40.7128, -74.006),
        default_zoom=13,
        enabled=False,
    ),
    ModelId.CARS_V0_1: ModelConfig(
        id=ModelId.CARS_V0_1,
        type=ModelType.CARS,
        name="Vehicle ID",
        version="0.1",
        center_coordinates=(40.7128, -74.006),
        default_zoom=13,
        enabled=False,
    ),
}


def get_model_config(model_id: ModelId) -> ModelConfig:
    """Get model configuration by ID."""
    if model_id not in MODELS:
        raise ValueError(f"Unknown model ID: {model_id}")
    return MODELS[model_id]


def get_credit_cost(model_id: ModelId) -> int:
    """Get credit cost for a model based on its type."""
    model_type = MODEL_ID_TO_TYPE[model_id]
    return MODEL_TYPE_CREDIT_COSTS[model_type]


def get_model_type(model_id: ModelId) -> ModelType:
    """Get model type for database tracking and pricing."""
    return MODEL_ID_TO_TYPE[model_id]


def get_enabled_models() -> list[ModelConfig]:
    """Get all enabled model configurations."""
    return [m for m in MODELS.values() if m.enabled]
