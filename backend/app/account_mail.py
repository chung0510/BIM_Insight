from email.message import EmailMessage
import re
import smtplib
import ssl

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.settings import load_settings, save_settings


def normalize_email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", value):
        raise ValueError("Invalid email")
    return value


class GmailSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    app_password: SecretStr = Field(min_length=16, max_length=32)

    @field_validator("email")
    @classmethod
    def gmail(cls, value):
        value = normalize_email(value)
        if not value.endswith(("@gmail.com", "@googlemail.com")):
            raise ValueError("Use a personal Gmail sender")
        return value

    @field_validator("app_password", mode="before")
    @classmethod
    def password(cls, value):
        if isinstance(value, str):
            value = "".join(value.split())
            if not re.fullmatch(r"[A-Za-z0-9]{16}", value):
                raise ValueError("Use a 16-character Gmail app password")
        return value


class GmailMailer:
    def __init__(self, directory):
        self.directory = directory

    def configuration(self):
        try:
            raw = load_settings(self.directory, "mail")
            return GmailSettings.model_validate(raw) if raw else None
        except ValueError:
            raise HTTPException(503, "mail_configuration_invalid") from None

    def require_configuration(self):
        config = self.configuration()
        if config is None:
            raise HTTPException(503, "mail_not_configured")
        return config

    def status(self):
        config = self.configuration()
        return {"configured": bool(config), "email": config.email if config else ""}

    def connection(self, config):
        return smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15, context=ssl.create_default_context())

    def configure(self, config):
        try:
            with self.connection(config) as smtp:
                smtp.login(config.email, config.app_password.get_secret_value())
            save_settings(self.directory, "mail", {"email": config.email, "app_password": config.app_password.get_secret_value()})
        except (OSError, smtplib.SMTPException, ValueError):
            raise HTTPException(503, "mail_connection_failed") from None
        return self.status()

    def send(self, recipient, code, *, recovery):
        config = self.require_configuration()
        message = EmailMessage()
        message["From"] = f"BIM Insight <{config.email}>"
        message["To"] = recipient
        message["Subject"] = "BIM Insight — Khôi phục mật khẩu" if recovery else "BIM Insight — Xác nhận email"
        message.set_content(f"Mã xác nhận của bạn: {code}\n\nMã có hiệu lực trong 10 phút và chỉ dùng một lần. Không chia sẻ mã này.\nNếu bạn không yêu cầu, hãy bỏ qua email này.\n\nBIM Insight")
        with self.connection(config) as smtp:
            smtp.login(config.email, config.app_password.get_secret_value())
            smtp.send_message(message)
