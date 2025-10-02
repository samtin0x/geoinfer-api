import hashlib
import logging
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

    def _generate_key(self, organization_id: UUID, image_data: bytes) -> str:
        file_hash = self._generate_image_hash(image_data)
        return f"raw/organization/{organization_id}/{file_hash}"

    async def upload_prediction_image(
        self,
        image_data: bytes,
        organization_id: UUID,
    ) -> str | None:
        key = self._generate_key(organization_id, image_data)

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
                    ContentType="application/octet-stream",
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
