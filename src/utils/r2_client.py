import hashlib
import logging
from pathlib import Path
from uuid import UUID

import aioboto3
from botocore.exceptions import ClientError

from src.utils.settings.r2 import R2Settings

logger = logging.getLogger(__name__)


class R2Client:
    """Client for uploading images to Cloudflare R2 (S3-compatible storage)."""

    def __init__(self, settings: R2Settings | None = None):
        self.settings = settings or R2Settings()
        self._session: aioboto3.Session | None = None

    def _get_session(self) -> aioboto3.Session:
        """Get or create aioboto3 session."""
        if self._session is None:
            self._session = aioboto3.Session(
                aws_access_key_id=self.settings.R2_ACCESS_KEY,
                aws_secret_access_key=self.settings.R2_SECRET_KEY.get_secret_value(),
            )
        return self._session

    def _generate_image_hash(self, image_data: bytes) -> str:
        """Generate a unique hash for the image content."""
        return hashlib.sha256(image_data).hexdigest()[:16]

    def _get_extension_from_filename(self, filename: str) -> str:
        """Get file extension from filename."""
        ext = Path(filename).suffix.lower()
        if ext:
            return ext
        return ".bin"

    def _get_content_type(self, extension: str) -> str:
        """Get MIME type for the given file extension."""
        content_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".webp": "image/webp",
            ".heic": "image/heic",
            ".heif": "image/heif",
        }
        return content_type_map.get(extension.lower(), "application/octet-stream")

    def _generate_key(
        self, organization_id: UUID, image_data: bytes, filename: str
    ) -> str:
        file_hash = self._generate_image_hash(image_data)
        extension = self._get_extension_from_filename(filename)
        return f"raw/organization/{organization_id}/{file_hash}{extension}"

    async def upload_prediction_image(
        self,
        image_data: bytes,
        organization_id: UUID,
        filename: str,
        ip_address: str | None = None,
    ) -> str | None:
        key = self._generate_key(organization_id, image_data, filename)
        extension = self._get_extension_from_filename(filename)
        content_type = self._get_content_type(extension)

        metadata = {}
        if ip_address:
            metadata["ip-address"] = ip_address

        if filename:
            metadata["original-filename"] = filename

        try:
            session = self._get_session()
            async with session.client(
                "s3",
                endpoint_url=self.settings.R2_ENDPOINT,
            ) as s3_client:
                await s3_client.put_object(
                    Bucket=self.settings.R2_BUCKET,
                    Key=key,
                    Body=image_data,
                    ContentType=content_type,
                    Metadata=metadata,
                )

                # Construct R2 URL
                public_url = (
                    f"{self.settings.R2_ENDPOINT}/{self.settings.R2_BUCKET}/{key}"
                )
                return public_url

        except ClientError as e:
            logger.error(f"Failed to upload image to R2: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading to R2: {e}")
            return None
