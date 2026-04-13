from typing import Literal

from pydantic import BaseModel, EmailStr


class SendEmailsRequest(BaseModel):
    reference_numbers: list[str] | None = None
    subject_prefix: str = "تنبيهات المنافسات - اعتماد"
    delivery_mode: Literal["mapped", "fixed", "mapped_with_copy"] = "mapped_with_copy"
    recipient: EmailStr | None = None
