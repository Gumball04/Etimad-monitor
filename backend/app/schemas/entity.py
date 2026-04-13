from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EntityCreate(BaseModel):
    entity_name_ar: str


class EntityOut(EntityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
