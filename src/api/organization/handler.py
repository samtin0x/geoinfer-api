from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.messages import APIResponse, MessageCode
from src.modules.organization.use_cases import OrganizationService
from src.api.organization.schemas import (
    OrganizationCreateRequest,
    OrganizationCreateResponse,
    OrganizationUpdateRequest,
    OrganizationUpdateResponse,
    OrganizationModel,
)


async def create_organization_handler(
    db: AsyncSession,
    organization_data: OrganizationCreateRequest,
    user_id: UUID,
) -> OrganizationCreateResponse:
    service = OrganizationService(db)
    org = await service.create_organization(
        name=organization_data.name,
        user_id=user_id,
        logo_url=(
            str(organization_data.logo_url) if organization_data.logo_url else None
        ),
    )
    return APIResponse.success(
        message_code=MessageCode.ORGANIZATION_CREATED,
        data=OrganizationModel.model_validate(org),
    )


async def update_organization_handler(
    db: AsyncSession,
    organization_id: UUID,
    organization_data: OrganizationUpdateRequest,
    requesting_user_id: UUID,
) -> OrganizationUpdateResponse:
    service = OrganizationService(db)
    org = await service.update_organization_details(
        organization_id=organization_id,
        new_name=organization_data.name,
        new_logo_url=(
            str(organization_data.logo_url) if organization_data.logo_url else None
        ),
        requesting_user_id=requesting_user_id,
    )
    assert org is not None
    return APIResponse.success(
        message_code=MessageCode.ORGANIZATION_UPDATED,
        data=OrganizationModel.model_validate(org),
    )
