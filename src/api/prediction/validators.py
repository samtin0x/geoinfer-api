from fastapi import UploadFile, status

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.core.constants import (
    PREDICTION_DATA_TYPES,
    HEIC_HEIF_EXTENSIONS,
)


async def validate_image_upload(file: UploadFile, max_size_bytes: int) -> bytes:
    """Validate uploaded image content type and size, return bytes."""
    # Read file bytes
    content = await file.read()

    # Validate content type (allow HEIC/HEIF by extension as fallback)
    if not file.content_type or (
        not file.content_type.startswith("image/")
        and file.content_type not in PREDICTION_DATA_TYPES
    ):
        if not (file.filename and file.filename.lower().endswith(HEIC_HEIF_EXTENSIONS)):
            raise GeoInferException(
                MessageCode.INVALID_FILE_TYPE, status.HTTP_400_BAD_REQUEST
            )

    # Validate size
    if len(content) > max_size_bytes:
        raise GeoInferException(MessageCode.FILE_TOO_LARGE, status.HTTP_400_BAD_REQUEST)

    return content
