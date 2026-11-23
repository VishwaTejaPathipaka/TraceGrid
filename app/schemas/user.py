from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, StrictBool, StringConstraints, field_validator


NewPassword = Annotated[str, StringConstraints(min_length=12, max_length=128)]
AccountLinkToken = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]


class EmailRequest(BaseModel):
    email: Annotated[EmailStr, StringConstraints(max_length=100)]

    @field_validator("email")
    @classmethod
    def check_normalized_length(cls, value):
        if len(value.lower()) > 100:
            raise ValueError("Email must be at most 100 characters")
        return value


class UserCreate(EmailRequest):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    password: NewPassword


class AccountLink(BaseModel):
    token: AccountLinkToken


class VerifyEmail(AccountLink):
    password: NewPassword


class ResetPassword(AccountLink):
    password: NewPassword
        
        
class UserLogin(BaseModel):
    username: str
    password: str


class NotificationPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_opened: StrictBool
    incident_recovered: StrictBool


class NotificationPreferences(NotificationPreferencesUpdate):
    verified_email: EmailStr | None
