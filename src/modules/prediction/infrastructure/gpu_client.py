"""Client for remote GPU inference server."""

import logging
from typing import Any

import aiohttp

from src.api.prediction.schemas import (
    CoordinatePrediction,
    LocationInfo,
    PredictionResult,
)
from src.utils.settings.gpu import gpu_settings


logger = logging.getLogger(__name__)


class GPUServerClient:
    """Client for making prediction requests to the remote GPU server."""

    def __init__(self):
        self.url = gpu_settings.GPU_SERVER_URL
        self.timeout = gpu_settings.GPU_SERVER_TIMEOUT
        self.auth = aiohttp.BasicAuth(
            gpu_settings.GPU_SERVER_USERNAME, gpu_settings.GPU_SERVER_PASSWORD
        )

    async def predict_from_bytes(
        self, image_data: bytes, top_k: int = 5
    ) -> PredictionResult:
        """Send image bytes to GPU server for prediction."""
        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field(
                "file", image_data, filename="image.jpg", content_type="image/jpeg"
            )

            try:
                async with session.post(
                    f"{self.url}/predict",
                    data=form_data,
                    params={"top_k": top_k},
                    auth=self.auth,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return self._parse_prediction_result(data)
            except aiohttp.ClientError as e:
                logger.error(f"GPU server request failed: {e}")
                raise RuntimeError(f"GPU server unavailable: {e}")
            except Exception as e:
                logger.error(f"Unexpected error calling GPU server: {e}")
                raise

    def _parse_prediction_result(self, data: dict[str, Any]) -> PredictionResult:
        """Parse GPU server response into PredictionResult."""
        predictions = []
        for pred in data.get("predictions", []):
            location_data = pred.get("location")
            location = None
            if location_data:
                location = LocationInfo(
                    name=location_data.get("name", ""),
                    admin1=location_data.get("admin1", ""),
                    admin2=location_data.get("admin2", ""),
                    country_code=location_data.get("country_code", ""),
                )

            predictions.append(
                CoordinatePrediction(
                    latitude=pred["latitude"],
                    longitude=pred["longitude"],
                    confidence=pred["confidence"],
                    rank=pred["rank"],
                    location=location,
                )
            )

        top_prediction = None
        if predictions:
            top_prediction = predictions[0]

        return PredictionResult(
            predictions=predictions,
            processing_time_ms=data.get("processing_time_ms", 0),
            top_prediction=top_prediction,
        )


async def get_gpu_client() -> GPUServerClient:
    """Get GPU server client for dependency injection."""
    return GPUServerClient()
