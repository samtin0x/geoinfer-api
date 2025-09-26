import logging
import time

import numpy as np
import reverse_geocoder as rg  # type: ignore
import torch
from geoclip import GeoCLIP  # type: ignore
import pillow_heif  # type: ignore

from src.api.prediction.schemas import (
    LocationInfo,
)

logger = logging.getLogger(__name__)

# Register HEIF support for PIL
pillow_heif.register_heif_opener()

# Global model instance - loaded once at startup
_model: GeoCLIP | None = None


async def load_geoclip_model() -> GeoCLIP:
    """Load GeoCLIP model with CPU optimization. Should be called at startup."""
    global _model
    if _model is None:
        # Suppress verbose logging from PyTorch and transformers
        import logging as py_logging

        py_logging.getLogger("torch").setLevel(py_logging.WARNING)
        py_logging.getLogger("transformers").setLevel(py_logging.WARNING)
        py_logging.getLogger("huggingface_hub").setLevel(py_logging.WARNING)
        py_logging.getLogger("urllib3").setLevel(py_logging.WARNING)

        # CPU optimization settings
        torch.set_num_threads(torch.get_num_threads())

        start_time = time.time()
        _model = GeoCLIP()
        load_time = time.time() - start_time
        logger.info(f"GeoCLIP model loaded in {load_time:.3f}s")
    return _model


def get_model() -> GeoCLIP:
    """Get the loaded GeoCLIP model."""
    if _model is None:
        raise RuntimeError("GeoCLIP model not loaded. Call load_geoclip_model() first.")
    return _model


def normalize_confidences(raw_scores: list[float]) -> list[float]:
    """
    Normalize raw GeoCLIP similarity scores into probabilities using softmax.

    Args:
        raw_scores: List of raw similarity scores from GeoCLIP

    Returns:
        List of normalized probabilities that sum to 1.0
    """
    if not raw_scores:
        return []

    scores_array = np.array(raw_scores, dtype=np.float64)

    # Apply softmax normalization
    # Subtract max for numerical stability
    scores_array = scores_array - np.max(scores_array)
    exp_scores = np.exp(scores_array)
    probabilities = exp_scores / np.sum(exp_scores)

    return probabilities.tolist()


def get_location_info(latitude: float, longitude: float) -> LocationInfo | None:
    """
    Get location information for given coordinates using reverse geocoding.

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate

    Returns:
        LocationInfo object with place details, or None if lookup fails
    """
    try:
        # Perform reverse geocoding lookup
        result = rg.search((latitude, longitude))

        if result and len(result) > 0:
            place = result[0]
            return LocationInfo(
                name=place.get("name", ""),
                admin1=place.get("admin1", ""),
                admin2=place.get("admin2", ""),
                country_code=place.get("cc", ""),
            )
    except Exception as e:
        logger.warning(f"Reverse geocoding failed for ({latitude}, {longitude}): {e}")

    return None
