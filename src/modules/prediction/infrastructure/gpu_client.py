"""Client for remote GPU inference server."""

import logging
from typing import Any

import aiohttp
import reverse_geocoder as rg

from src.api.prediction.schemas import (
    Coordinates,
    CoordinatePredictionResult,
    LocationCluster,
    LocationInfo,
)
from src.modules.prediction.clustering import Point, cluster_points

from src.utils.settings.gpu import gpu_settings

logger = logging.getLogger(__name__)

INTERNAL_TOP_K = 15
CLUSTER_DISTANCE_KM = 25.0
MAX_CLUSTERS = 5


class GPUServerClient:
    """Client for making prediction requests to the remote GPU server."""

    def __init__(self):
        self.url = gpu_settings.GPU_SERVER_URL
        self.timeout = gpu_settings.GPU_SERVER_TIMEOUT
        self.auth = aiohttp.BasicAuth(
            gpu_settings.GPU_SERVER_USERNAME, gpu_settings.GPU_SERVER_PASSWORD
        )

    async def predict_from_bytes(self, image_data: bytes) -> CoordinatePredictionResult:
        """Send image bytes to GPU server and return clustered predictions."""
        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field(
                "file", image_data, filename="image.jpg", content_type="image/jpeg"
            )

            try:
                async with session.post(
                    f"{self.url}/predict",
                    data=form_data,
                    params={"top_k": INTERNAL_TOP_K},
                    auth=self.auth,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return self._parse_result(data)
            except aiohttp.ClientError as e:
                logger.error(f"GPU server request failed: {e}")
                raise RuntimeError(f"GPU server unavailable: {e}")

    def _parse_result(self, data: dict[str, Any]) -> CoordinatePredictionResult:
        """Parse GPU response into clustered result."""
        points = [
            Point(p["latitude"], p["longitude"], p["confidence"])
            for p in data.get("predictions", [])
        ]

        raw_clusters = cluster_points(points, CLUSTER_DISTANCE_KM)[:MAX_CLUSTERS]

        # Reverse geocode cluster centers
        centers = [(c.center_lat, c.center_lon) for c in raw_clusters]
        locations = rg.search(centers) if centers else []

        clusters = []
        for i, c in enumerate(raw_clusters):
            loc_data = locations[i] if i < len(locations) else {}
            clusters.append(
                LocationCluster(
                    center=Coordinates(latitude=c.center_lat, longitude=c.center_lon),
                    location=LocationInfo(
                        name=loc_data.get("name", "Unknown"),
                        admin1=loc_data.get("admin1", ""),
                        admin2=loc_data.get("admin2", ""),
                        country_code=loc_data.get("cc", ""),
                    ),
                    radius_km=round(c.radius_km, 2),
                    points=[
                        Coordinates(latitude=p.lat, longitude=p.lon) for p in c.points
                    ],
                )
            )

        return CoordinatePredictionResult(
            clusters=clusters,
            processing_time_ms=data.get("processing_time_ms", 0),
        )


async def get_gpu_client() -> GPUServerClient:
    return GPUServerClient()
