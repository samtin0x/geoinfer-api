import resend
from fastapi import APIRouter, Request, status

from src.api.core.decorators.admin import admin
from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import APIResponse, MessageCode
from src.api.email.schemas import SendEmailRequest, SendEmailResponse
from src.emails import render_email
from src.utils.logger import get_logger
from src.utils.settings.email import EmailSettings

logger = get_logger(__name__)

router = APIRouter(prefix="/email", tags=["email"])


email_settings = EmailSettings()


@router.post("/send", response_model=APIResponse[SendEmailResponse])
@admin()
async def send_email(
    request: Request,
    email_request: SendEmailRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> APIResponse[SendEmailResponse]:
    """
    Send an email using a template (Admin only).

    This endpoint requires admin authentication and sends emails via Resend.
    """
    try:

        resend.api_key = email_settings.RESEND_API_KEY

        email_data = render_email(
            template_name=email_request.template_name,
            locale=email_request.locale,
        )

        from_address = f"{email_settings.EMAIL_FROM_NAME} <{email_settings.EMAIL_FROM_ADDRESS}@{email_settings.EMAIL_FROM_DOMAIN}>"

        response = resend.Emails.send(
            {
                "from": from_address,
                "to": email_request.to_email,
                "subject": email_data["subject"],
                "html": email_data["html"],
                "reply_to": email_data["reply_to"],
                "tags": [
                    {
                        "name": "category",
                        "value": email_request.template_name,
                    }
                ],
                "headers": {
                    "X-Entity-Ref-ID": str(current_user.user.id),
                },
            }
        )

        logger.info(
            "Email sent successfully",
            email_id=response["id"],
            to=email_request.to_email,
            template=email_request.template_name,
            locale=email_request.locale,
            admin_user_id=str(current_user.user.id),
        )

        return APIResponse.success(
            message_code=MessageCode.SUCCESS,
            data=SendEmailResponse(email_id=response["id"], status="sent"),
        )

    except Exception as e:
        logger.error(
            "Failed to send email",
            error=str(e),
            to=email_request.to_email,
            template=email_request.template_name,
        )
        raise GeoInferException(
            MessageCode.INTERNAL_ERROR,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            {"description": f"Failed to send email: {str(e)}"},
        )
