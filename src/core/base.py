from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.logger import get_logger


class BaseService:
    """Base service class with database dependency injection."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(self.__class__.__name__)
