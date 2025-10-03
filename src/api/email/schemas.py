from pydantic import BaseModel, EmailStr

from src.emails.render import LocaleType, TemplateType


class SendEmailRequest(BaseModel):
    template_name: TemplateType
    to_email: EmailStr
    locale: LocaleType = "en"


class SendEmailResponse(BaseModel):
    email_id: str
    status: str
