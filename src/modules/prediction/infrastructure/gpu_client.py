"""Client for remote GPU inference server."""

import logging
from typing import Any

import aiohttp
from pydantic import BaseModel

from src.api.prediction.schemas import CoordinatePrediction, LocationInfo, PredictionResult

logger = logging.getLogger(__name__)


class GPUServerConfig(BaseModel):
    """Configuration for GPU server connection."""

    url: str = "http://localhost:8000"
    username: str = "admin"
    password: str = "admin"
    timeout: int = 60


class GPUServerClient:
    """Client for making prediction requests to the remote GPU server."""

    def __init__(self, config: GPUServerConfig):
        self.config = config
        self.auth = aiohttp.BasicAuth(config.username, config.password)

    async def predict_from_bytes(
        self, image_data: bytes, top_k: int = 5
    ) -> PredictionResult:
        """Send image bytes to GPU server for prediction."""
        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field("file", image_data, filename="image.jpg", content_type="image/jpeg")

            try:
                async with session.post(
                    f"{self.config.url}/predict",
                    data=form_data,
                    params={"top_k": top_k},
                    auth=self.auth,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout),
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


# Global GPU client instance
_gpu_client: GPUServerClient | None = None


def get_gpu_client() -> GPUServerClient:
    """Get or create GPU server client."""
    global _gpu_client
    if _gpu_client is None:
        import os

        config = GPUServerConfig(
            url=os.getenv("GPU_SERVER_URL", "http://localhost:8000"),
            username=os.getenv("GPU_SERVER_USERNAME", "admin"),
            password=os.getenv("GPU_SERVER_PASSWORD", "admin"),
            timeout=int(os.getenv("GPU_SERVER_TIMEOUT", "60")),
        )
        _gpu_client = GPUServerClient(config)
        logger.info(f"GPU server client initialized: {config.url}")
    return _gpu_client

