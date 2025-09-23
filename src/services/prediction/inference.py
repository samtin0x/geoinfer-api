import asyncio
import logging
import os
import tempfile
import time
from io import BytesIO

import aiohttp
import torch
from fastapi import status
from geoclip import GeoCLIP  # type: ignore
from PIL import Image, UnidentifiedImageError
import pillow_heif  # type: ignore

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.prediction.models import CoordinatePrediction, PredictionResult

logger = logging.getLogger(__name__)

# Register HEIF support for PIL
pillow_heif.register_heif_opener()

# Global model instance - loaded once at startup
_model: GeoCLIP | None = None


async def load_geoclip_model() -> GeoCLIP:
    """Load GeoCLIP model with CPU optimization. Should be called at startup."""
    global _model
    if _model is None:
        logger.info("Loading GeoCLIP model...")

        # CPU optimization settings
        torch.set_num_threads(torch.get_num_threads())
        logger.info(f"PyTorch using {torch.get_num_threads()} CPU threads")
        logger.info(f"CUDA available: {torch.cuda.is_available()}")

        start_time = time.time()
        _model = GeoCLIP()
        load_time = time.time() - start_time
        logger.info(f"GeoCLIP model loaded in {load_time:.3f} seconds")
    return _model


def get_model() -> GeoCLIP:
    """Get the loaded GeoCLIP model."""
    if _model is None:
        raise RuntimeError("GeoCLIP model not loaded. Call load_geoclip_model() first.")
    return _model


async def download_image(image_url: str) -> Image.Image:
    """Download and open an image from a URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status != 200:
                raise GeoInferException(
                    MessageCode.EXTERNAL_SERVICE_ERROR,
                    status.HTTP_400_BAD_REQUEST,
                    details={
                        "description": f"Failed to download image: HTTP {response.status}"
                    },
                )

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                raise GeoInferException(
                    MessageCode.INVALID_FILE_TYPE,
                    status.HTTP_400_BAD_REQUEST,
                    details={"description": f"Invalid content type: {content_type}"},
                )

            image_data = await response.read()

            try:
                image = Image.open(BytesIO(image_data))
            except UnidentifiedImageError as e:
                logger.error(f"Cannot identify downloaded image format: {e}")
                raise GeoInferException(
                    MessageCode.IMAGE_PROCESSING_ERROR,
                    status.HTTP_400_BAD_REQUEST,
                    details={
                        "description": "Cannot identify image format from URL. Please ensure the URL points to a valid image file."
                    },
                )

            # Convert to RGB if necessary
            if image.mode != "RGB":
                image = image.convert("RGB")

            return image


async def predict_coordinates_from_url(
    image_url: str, top_k: int = 5
) -> PredictionResult:
    """
    Predict GPS coordinates from an image URL.

    Returns:
        PredictionResult with multiple predictions and timing info
    """
    start_time = time.time()

    try:
        # Download image
        image = await download_image(image_url)

        # Save to temporary file for GeoCLIP (it expects file paths)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            image.save(temp_file, format="JPEG")
            temp_path = temp_file.name

        try:
            # Run prediction in thread pool to avoid blocking
            model = get_model()
            loop = asyncio.get_event_loop()

            gps_predictions, probabilities = await loop.run_in_executor(
                None, model.predict, temp_path, top_k
            )

            # Convert to our format
            predictions = []
            for i, (coords, prob) in enumerate(zip(gps_predictions, probabilities)):
                lat, lon = coords
                predictions.append(
                    CoordinatePrediction(
                        latitude=float(lat),
                        longitude=float(lon),
                        confidence=float(prob),
                        rank=i + 1,
                    )
                )

            processing_time_ms = int((time.time() - start_time) * 1000)

            # Create result with top prediction for convenience
            return PredictionResult(
                predictions=predictions,
                processing_time_ms=processing_time_ms,
                top_prediction=predictions[0] if predictions else None,
            )

        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    except Exception as e:
        logger.error(f"Error predicting coordinates from URL {image_url}: {e}")
        raise


async def predict_coordinates_from_file(
    image_path: str, top_k: int = 5
) -> PredictionResult:
    """
    Predict GPS coordinates from a local image file.

    Returns:
        PredictionResult with multiple predictions and timing info
    """
    start_time = time.time()

    try:
        model = get_model()
        loop = asyncio.get_event_loop()

        gps_predictions, probabilities = await loop.run_in_executor(
            None, model.predict, image_path, top_k
        )

        # Convert to our format
        predictions = []
        for i, (coords, prob) in enumerate(zip(gps_predictions, probabilities)):
            lat, lon = coords
            predictions.append(
                CoordinatePrediction(
                    latitude=float(lat),
                    longitude=float(lon),
                    confidence=float(prob),
                    rank=i + 1,
                )
            )

        processing_time_ms = int((time.time() - start_time) * 1000)

        return PredictionResult(
            predictions=predictions,
            processing_time_ms=processing_time_ms,
            top_prediction=predictions[0] if predictions else None,
        )

    except Exception as e:
        logger.error(f"Error predicting coordinates from file {image_path}: {e}")
        raise


async def predict_coordinates_from_upload(
    image_data: bytes, top_k: int = 5
) -> PredictionResult:
    """
    Predict GPS coordinates from uploaded image data.

    Returns:
        PredictionResult with multiple predictions and timing info
    """
    start_time = time.time()

    # Validate image data
    if not image_data:
        raise GeoInferException(
            MessageCode.IMAGE_PROCESSING_ERROR,
            status.HTTP_400_BAD_REQUEST,
            details={"description": "Empty image data provided"},
        )

    try:
        # Convert bytes to PIL Image
        image_io = BytesIO(image_data)
        image = Image.open(image_io)

        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Save to temporary file for GeoCLIP
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            image.save(temp_file, format="JPEG")
            temp_path = temp_file.name

        try:
            # Run prediction in thread pool to avoid blocking
            model = get_model()
            loop = asyncio.get_event_loop()

            gps_predictions, probabilities = await loop.run_in_executor(
                None, model.predict, temp_path, top_k
            )

            # Convert to our format
            predictions = []
            for i, (coords, prob) in enumerate(zip(gps_predictions, probabilities)):
                lat, lon = coords
                predictions.append(
                    CoordinatePrediction(
                        latitude=float(lat),
                        longitude=float(lon),
                        confidence=float(prob),
                        rank=i + 1,
                    )
                )

            processing_time_ms = int((time.time() - start_time) * 1000)

            return PredictionResult(
                predictions=predictions,
                processing_time_ms=processing_time_ms,
                top_prediction=predictions[0] if predictions else None,
            )

        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    except UnidentifiedImageError as e:
        logger.error(f"Cannot identify image format: {e}")
        raise GeoInferException(
            MessageCode.IMAGE_PROCESSING_ERROR,
            status.HTTP_400_BAD_REQUEST,
            details={
                "description": "Cannot identify image format. Please ensure you're uploading a valid image file (JPEG, PNG, etc.)"
            },
        )
    except (OSError, IOError) as e:
        # Handle PIL image processing errors (corrupted files, truncated files, etc.)
        logger.error(f"Image processing error: {e}")
        raise GeoInferException(
            MessageCode.IMAGE_PROCESSING_ERROR,
            status.HTTP_400_BAD_REQUEST,
            details={
                "description": "Error processing image file. The image may be corrupted or in an unsupported format."
            },
        )
    except Exception as e:
        logger.error(f"Error predicting coordinates from uploaded image: {e}")
        raise GeoInferException(
            MessageCode.PREDICTION_FAILED,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"description": f"Prediction failed: {str(e)}"},
        )
