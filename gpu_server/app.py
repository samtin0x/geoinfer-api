import asyncio
import logging
import os
import tempfile
import time
from io import BytesIO

"""
GPU server: only inference. Returns lat, lon, confidence, rank. No geocoding.
"""
import torch
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from geoclip import GeoCLIP
from PIL import Image
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

# Register HEIF plugin to support HEIC images
from pillow_heif import register_heif_opener

register_heif_opener()

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

security = HTTPBasic()

APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "admin")

app = FastAPI(title="GeoCLIP GPU Server", version="0.1.0")

# Global model instance for GPU
_gpu_model = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models (no geocoding metadata here)
class CoordinatePrediction(BaseModel):
    latitude: float
    longitude: float
    confidence: float
    rank: int


class PredictionResult(BaseModel):
    predictions: list[CoordinatePrediction]
    processing_time_ms: int
    top_prediction: CoordinatePrediction | None = None


def basic_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    def _ct_eq(a: str, b: str) -> bool:
        if len(a) != len(b):
            return False
        result = 0
        for x, y in zip(a.encode(), b.encode()):
            result |= x ^ y
        return result == 0

    if not (
        _ct_eq(credentials.username, APP_USERNAME)
        and _ct_eq(credentials.password, APP_PASSWORD)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


async def load_gpu_model():
    """Load GeoCLIP model - will use GPU automatically if CUDA is available."""
    global _gpu_model
    if _gpu_model is None:
        if not torch.cuda.is_available():
            logger.warning("CUDA is not available! Running on CPU (slow)")
        else:
            logger.info(f"CUDA available! Using GPU: {torch.cuda.get_device_name(0)}")
            logger.info(f"CUDA version: {torch.version.cuda}")
            logger.info(f"PyTorch version: {torch.__version__}")

        import logging as py_logging

        py_logging.getLogger("torch").setLevel(py_logging.WARNING)
        py_logging.getLogger("transformers").setLevel(py_logging.WARNING)
        py_logging.getLogger("huggingface_hub").setLevel(py_logging.WARNING)

        start_time = time.time()
        # Load GeoCLIP and move to GPU if available
        _gpu_model = GeoCLIP()

        if torch.cuda.is_available():
            _gpu_model = _gpu_model.to("cuda")
            logger.info("Model moved to CUDA")
        load_time = time.time() - start_time
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"GeoCLIP model loaded in {load_time:.3f}s on {device}")

    return _gpu_model


def get_gpu_model():
    """Get the loaded GPU model."""
    if _gpu_model is None:
        raise RuntimeError("GPU model not loaded. Call load_gpu_model() first.")
    return _gpu_model


def normalize_confidences(raw_scores: list[float]) -> list[float]:
    """Keep raw confidence scores as-is (each between 0-1)."""
    # GeoCLIP returns confidence scores already between 0-1
    # Don't normalize to sum=1, keep individual confidences
    return [float(score) for score in raw_scores]


def _predict_with_device(model, image_path: str, top_k: int):
    """Run prediction on the model with optimizations."""
    # Use inference mode for faster inference (disables grad tracking)
    with torch.inference_mode():
        result = model.predict(image_path, top_k)

    return result


"""Reverse geocoding removed - enrichment happens in core API."""


@app.on_event("startup")
async def _startup() -> None:
    await load_gpu_model()
    logger.info("GPU Server started successfully")
    logger.info("HEIC image format support enabled via pillow-heif")


@app.get("/health")
async def health() -> dict:
    gpu_info = {}
    if torch.cuda.is_available():
        gpu_info = {
            "cuda_available": True,
            "gpu_name": torch.cuda.get_device_name(0),
            "gpu_memory_allocated_gb": round(
                torch.cuda.memory_allocated(0) / 1024**3, 2
            ),
            "gpu_memory_reserved_gb": round(torch.cuda.memory_reserved(0) / 1024**3, 2),
            "cuda_version": torch.version.cuda,
            "model_loaded": _gpu_model is not None,
        }
    else:
        gpu_info = {
            "cuda_available": False,
            "warning": "Running on CPU",
            "model_loaded": _gpu_model is not None,
        }

    return {"status": "ok", "gpu": gpu_info, "pytorch_version": torch.__version__}


@app.get("/predict", response_model=PredictionResult)
async def predict_get(
    image_url: str = Query(..., description="Publicly reachable image URL"),
    top_k: int = Query(5, ge=1, le=50, description="Number of top predictions"),
    _: str = Depends(basic_auth),
) -> JSONResponse:
    try:
        result = await predict_from_url(image_url, top_k)
        return JSONResponse(content=result.model_dump())
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Prediction failed: {type(e).__name__}: {e}"
        )


@app.post("/predict", response_model=PredictionResult)
async def predict_post(
    file: UploadFile = File(..., description="Image file upload"),
    top_k: int = Query(5, ge=1, le=50, description="Number of top predictions"),
    _: str = Depends(basic_auth),
) -> JSONResponse:
    try:
        image_data = await file.read()
        result = await predict_from_bytes(image_data, top_k)
        return JSONResponse(content=result.model_dump())
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Prediction failed: {type(e).__name__}: {e}"
        )


async def predict_from_url(image_url: str, top_k: int = 5) -> PredictionResult:
    """Predict from image URL."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status != 200:
                raise ValueError(f"Failed to download image: HTTP {response.status}")
            image_data = await response.read()

    return await predict_from_bytes(image_data, top_k)


async def predict_from_bytes(image_data: bytes, top_k: int = 5) -> PredictionResult:
    """GPU-accelerated prediction from bytes. Supports JPEG, PNG, HEIC, and other PIL-compatible formats."""
    start_time = time.time()

    if not image_data:
        raise ValueError("Empty image data provided")

    try:
        image_io = BytesIO(image_data)
        image = Image.open(image_io)
        image_format = image.format or "unknown"
        logger.debug(f"Processing image format: {image_format}")
    except Exception as e:
        raise ValueError(f"Failed to open image: {type(e).__name__}: {e}")

    if image.mode != "RGB":
        image = image.convert("RGB")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
        image.save(temp_file, format="JPEG")
        temp_path = temp_file.name

    try:
        loop = asyncio.get_event_loop()
        model = get_gpu_model()

        # Run prediction - GeoCLIP will handle device placement internally
        # since we moved the encoders to GPU
        gps_predictions, probabilities = await loop.run_in_executor(
            None, lambda: _predict_with_device(model, temp_path, top_k)
        )

        raw_scores = [float(prob) for prob in probabilities]
        confidences = normalize_confidences(raw_scores)

        predictions = []
        for i, (coords, conf) in enumerate(zip(gps_predictions, confidences)):
            lat, lon = coords
            predictions.append(
                CoordinatePrediction(
                    latitude=float(lat),
                    longitude=float(lon),
                    confidence=conf,
                    rank=i + 1,
                )
            )

        processing_time_ms = int((time.time() - start_time) * 1000)

        if torch.cuda.is_available():
            gpu_mem_allocated = torch.cuda.memory_allocated(0) / 1024**3
            gpu_mem_reserved = torch.cuda.memory_reserved(0) / 1024**3
            logger.info(
                f"Prediction completed in {processing_time_ms}ms | "
                f"GPU Memory: {gpu_mem_allocated:.2f}GB allocated, {gpu_mem_reserved:.2f}GB reserved"
            )

        return PredictionResult(
            predictions=predictions,
            processing_time_ms=processing_time_ms,
            top_prediction=predictions[0] if predictions else None,
        )

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=bool(int(os.getenv("RELOAD", "0"))),
    )
