from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, and_, desc, literal
from sqlalchemy.orm import selectinload

from src.database.models import (
    Organization,
    User,
    UsageRecord,
    ApiKey,
)
from src.core.base import BaseService
from src.api.core.messages import Paginated, PaginationInfo, MessageCode
from src.api.core.exceptions.base import GeoInferException
from src.api.analytics.schemas import UserUsage, GroupByType
from fastapi import status


class AnalyticsService(BaseService):
    """Service for analytics queries and reporting."""

    async def get_usage_timeseries(
        self,
        organization_id: UUID,
        days: int = 30,
        group_by: GroupByType = GroupByType.DAY,
    ) -> list[dict]:
        """
        Get usage timeseries data for the specified period and organization.

        Args:
            organization_id: Organization to get analytics for
            days: Number of days to look back
            group_by: How to group data (day, hour, or week)

        Returns:
            List of timeseries data points
        """
        start_date = datetime.now() - timedelta(days=days)

        # Build date grouping based on group_by parameter
        match group_by:
            case GroupByType.DAY:
                date_format = func.to_char(
                    func.date_trunc("day", UsageRecord.created_at), "YYYY-MM-DD"
                )
                date_alias = "date"
            case GroupByType.HOUR:
                date_format = func.to_char(
                    func.date_trunc("hour", UsageRecord.created_at),
                    "YYYY-MM-DD HH24:00",
                )
                date_alias = "hour"
            case GroupByType.WEEK:
                date_format = func.to_char(
                    func.date_trunc("week", UsageRecord.created_at), "YYYY-MM-DD"
                )
                date_alias = "week"
            case GroupByType.MONTH:
                date_format = func.to_char(
                    func.date_trunc("month", UsageRecord.created_at), "YYYY-MM"
                )
                date_alias = "month"

        # Query for timeseries data - include both user and API key usage
        stmt = (
            select(
                date_format.label(date_alias),
                func.count(UsageRecord.id).label("prediction_count"),
                func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                    "credits_consumed"
                ),
                func.count(func.distinct(UsageRecord.user_id)).label("unique_users"),
                func.count(
                    func.distinct(
                        func.coalesce(UsageRecord.api_key_id, UsageRecord.user_id)
                    )
                ).label("unique_entities"),
            )
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.organization_id == organization_id,
                )
            )
            .group_by(date_format)
            .order_by(date_format)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "period": str(row[0]),
                "predictions": row[1],
                "credits_consumed": row[2] or 0,
                "unique_users": row[3],
                "unique_entities": row[4],  # Includes both users and API keys
            }
            for row in rows
        ]

    async def get_organization_user_usage(
        self, organization_id: UUID, days: int = 30, limit: int = 10, offset: int = 0
    ) -> Paginated[UserUsage]:
        """Get user usage analytics for a specific organization with pagination."""

        start_date = datetime.now() - timedelta(days=days)

        # Query for user usage within the organization
        # Include both actual users and API keys as separate entities
        user_usage_stmt = (
            select(
                User.id.label("entity_id"),
                User.name.label("entity_name"),
                User.email.label("entity_email"),
                func.count(UsageRecord.id).label("prediction_count"),
                func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                    "credits_consumed"
                ),
                func.max(UsageRecord.created_at).label("last_used_at"),
            )
            .join(UsageRecord, User.id == UsageRecord.user_id)
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.organization_id == organization_id,
                    UsageRecord.user_id.is_not(None),  # Only actual user usage
                    UsageRecord.api_key_id.is_(None),  # Exclude API key usage
                )
            )
            .group_by(User.id, User.name, User.email)
        )

        # Query for API key usage within the organization
        api_key_usage_stmt = (
            select(
                ApiKey.id.label("entity_id"),
                ApiKey.name.label("entity_name"),
                literal(None).label("entity_email"),  # API keys don't have email
                func.count(UsageRecord.id).label("prediction_count"),
                func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                    "credits_consumed"
                ),
                func.max(UsageRecord.created_at).label("last_used_at"),
            )
            .join(UsageRecord, ApiKey.id == UsageRecord.api_key_id)
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.organization_id == organization_id,
                    UsageRecord.api_key_id.is_not(None),  # Only API key usage
                )
            )
            .group_by(ApiKey.id, ApiKey.name)
        )

        # Combine both queries
        combined_stmt = user_usage_stmt.union_all(api_key_usage_stmt).order_by(
            desc("prediction_count")
        )

        # Get paginated results
        stmt = combined_stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        rows = result.all()

        # Get total count for pagination - count both users and API keys
        user_count_stmt = (
            select(func.count(func.distinct(User.id)))
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.organization_id == organization_id,
                    UsageRecord.user_id.is_not(None),
                    UsageRecord.api_key_id.is_(None),
                )
            )
            .join(UsageRecord, User.id == UsageRecord.user_id)
        )

        api_key_count_stmt = (
            select(func.count(func.distinct(ApiKey.id)))
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.organization_id == organization_id,
                    UsageRecord.api_key_id.is_not(None),
                )
            )
            .join(UsageRecord, ApiKey.id == UsageRecord.api_key_id)
        )

        # Execute both count queries
        user_count_result = await self.db.execute(user_count_stmt)
        api_key_count_result = await self.db.execute(api_key_count_stmt)
        total_entities = (user_count_result.scalar() or 0) + (
            api_key_count_result.scalar() or 0
        )

        # Convert to UserUsage models - handle both users and API keys
        entities_data = []
        for row in rows:
            entity_data = UserUsage(
                user_id=str(row[0]),  # This is now entity_id (could be user or API key)
                name=row[1],  # This is now entity_name
                email=row[2],  # This could be None for API keys
                prediction_count=row[3],
                credits_consumed=row[4] or 0,
            )
            entities_data.append(entity_data)

        # Create pagination info
        pagination_info = PaginationInfo(
            total=total_entities,
            limit=limit,
            offset=offset,
            has_more=offset + len(entities_data) < total_entities,
        )

        # Return paginated result
        return Paginated[UserUsage](
            items=entities_data,
            pagination=pagination_info,
        )

    async def get_top_users_by_usage(
        self, limit: int = 10, days: int = 30
    ) -> list[dict]:
        """DEPRECATED: Use get_organization_user_usage instead."""
        import warnings

        warnings.warn(
            "get_top_users_by_usage is deprecated. Use get_organization_user_usage instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        start_date = datetime.now() - timedelta(days=days)

        # Query for user usage (exclude API key usage)
        user_usage_stmt = (
            select(
                User.id.label("entity_id"),
                User.name.label("entity_name"),
                User.email.label("entity_email"),
                func.count(UsageRecord.id).label("prediction_count"),
                func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                    "credits_consumed"
                ),
            )
            .join(UsageRecord, User.id == UsageRecord.user_id)
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.user_id.is_not(None),
                    UsageRecord.api_key_id.is_(
                        None
                    ),  # Only count user usage, not API key usage
                )
            )
            .group_by(User.id, User.name, User.email)
        )

        # Query for API key usage
        api_key_usage_stmt = (
            select(
                ApiKey.id.label("entity_id"),
                ApiKey.name.label("entity_name"),
                literal(None).label("entity_email"),
                func.count(UsageRecord.id).label("prediction_count"),
                func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                    "credits_consumed"
                ),
            )
            .join(UsageRecord, ApiKey.id == UsageRecord.api_key_id)
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.api_key_id.is_not(None),
                )
            )
            .group_by(ApiKey.id, ApiKey.name)
        )

        # Combine both queries
        stmt = (
            user_usage_stmt.union_all(api_key_usage_stmt)
            .order_by(desc("prediction_count"))
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "user_id": str(row[0]),  # Now entity_id (could be user or API key)
                "name": row[1],  # Now entity_name
                "email": row[2],  # Could be None for API keys
                "prediction_count": row[3],
                "credits_consumed": row[4] or 0,
            }
            for row in rows
        ]

    async def get_organization_analytics(self, organization_id: UUID) -> dict:
        """Get detailed analytics for a specific organization."""
        # Verify organization exists
        stmt = (
            select(Organization)
            .options(selectinload(Organization.members))
            .where(Organization.id == organization_id)
        )
        result = await self.db.execute(stmt)
        org = result.scalar_one_or_none()

        if not org:
            raise GeoInferException(
                message_code=MessageCode.ORGANIZATION_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Get usage statistics - include both user and API key usage
        usage_stmt = select(
            func.count(UsageRecord.id).label("total_predictions"),
            func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                "total_credits"
            ),
            func.count(
                func.distinct(
                    func.coalesce(UsageRecord.user_id, UsageRecord.api_key_id)
                )
            ).label("active_entities"),
            func.max(UsageRecord.created_at).label("last_prediction_at"),
        ).where(UsageRecord.organization_id == organization_id)
        usage_result = await self.db.execute(usage_stmt)
        usage_stats = usage_result.one_or_none()

        # Get API key usage statistics
        api_key_usage_stmt = select(
            func.count(UsageRecord.id).label("api_key_predictions"),
            func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                "api_key_credits"
            ),
            func.count(func.distinct(UsageRecord.api_key_id)).label("active_api_keys"),
        ).where(
            and_(
                UsageRecord.organization_id == organization_id,
                UsageRecord.api_key_id.is_not(None),
            )
        )
        api_key_usage_result = await self.db.execute(api_key_usage_stmt)
        api_key_stats = api_key_usage_result.one_or_none()

        # Get monthly breakdown
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        monthly_stmt = select(
            func.count(UsageRecord.id).label("monthly_predictions"),
            func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                "monthly_credits"
            ),
            func.count(
                func.distinct(
                    func.coalesce(UsageRecord.user_id, UsageRecord.api_key_id)
                )
            ).label("monthly_active_entities"),
        ).where(
            and_(
                UsageRecord.organization_id == organization_id,
                UsageRecord.created_at >= month_start,
            )
        )
        monthly_result = await self.db.execute(monthly_stmt)
        monthly_stats = monthly_result.one_or_none()

        # Get monthly API key breakdown
        monthly_api_key_stmt = select(
            func.count(UsageRecord.id).label("monthly_api_key_predictions"),
            func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                "monthly_api_key_credits"
            ),
            func.count(func.distinct(UsageRecord.api_key_id)).label(
                "monthly_active_api_keys"
            ),
        ).where(
            and_(
                UsageRecord.organization_id == organization_id,
                UsageRecord.created_at >= month_start,
                UsageRecord.api_key_id.is_not(None),
            )
        )
        monthly_api_key_result = await self.db.execute(monthly_api_key_stmt)
        monthly_api_key_stats = monthly_api_key_result.one_or_none()

        return {
            "organization_id": str(organization_id),
            "organization_name": org.name,
            "member_count": len(org.members),
            # Total statistics (user + API key usage)
            "total_predictions": usage_stats[0] if usage_stats is not None else 0,
            "total_credits_consumed": usage_stats[1] if usage_stats is not None else 0,
            "total_active_entities": usage_stats[2] if usage_stats is not None else 0,
            "last_prediction_at": (
                usage_stats[3].isoformat()
                if usage_stats is not None and usage_stats[3]
                else None
            ),
            # API key usage statistics
            "api_key_predictions": api_key_stats[0] if api_key_stats is not None else 0,
            "api_key_credits_consumed": (
                api_key_stats[1] if api_key_stats is not None else 0
            ),
            "active_api_keys": api_key_stats[2] if api_key_stats is not None else 0,
            # Monthly statistics (user + API key usage)
            "monthly_predictions": monthly_stats[0] if monthly_stats is not None else 0,
            "monthly_credits_consumed": (
                monthly_stats[1] if monthly_stats is not None else 0
            ),
            "monthly_active_entities": (
                monthly_stats[2] if monthly_stats is not None else 0
            ),
            # Monthly API key statistics
            "monthly_api_key_predictions": (
                monthly_api_key_stats[0] if monthly_api_key_stats is not None else 0
            ),
            "monthly_api_key_credits_consumed": (
                monthly_api_key_stats[1] if monthly_api_key_stats is not None else 0
            ),
            "monthly_active_api_keys": (
                monthly_api_key_stats[2] if monthly_api_key_stats is not None else 0
            ),
        }

    async def get_api_key_usage_analytics(
        self, organization_id: UUID, limit: int = 20, days: int = 30
    ) -> list[dict]:
        """Get analytics for API key usage with API key names for a specific organization."""
        start_date = datetime.now() - timedelta(days=days)

        stmt = (
            select(
                UsageRecord.api_key_id,
                ApiKey.name.label("api_key_name"),
                func.count(UsageRecord.id).label("prediction_count"),
                func.coalesce(func.sum(UsageRecord.credits_consumed), 0).label(
                    "credits_consumed"
                ),
                func.count(func.distinct(UsageRecord.user_id)).label("unique_users"),
                func.max(UsageRecord.created_at).label("last_used_at"),
            )
            .join(ApiKey, UsageRecord.api_key_id == ApiKey.id)
            .where(
                and_(
                    UsageRecord.created_at >= start_date,
                    UsageRecord.api_key_id.is_not(None),
                    UsageRecord.organization_id == organization_id,
                )
            )
            .group_by(UsageRecord.api_key_id, ApiKey.name)
            .order_by(desc("prediction_count"))
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "api_key_id": str(row[0]),
                "api_key_name": row[1],
                "prediction_count": row[2],
                "credits_consumed": row[3] or 0,
                "unique_users": row[4],
                "last_used_at": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ]
