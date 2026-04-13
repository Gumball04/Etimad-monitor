from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class ContactCreate(BaseModel):
    full_name: str
    email: EmailStr
    is_active: bool = True


class ContactOut(ContactCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
