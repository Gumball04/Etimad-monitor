from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EntityContactMapCreate(BaseModel):
    entity_id: int
    contact_id: int


class EntityContactMapOut(EntityContactMapCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
