from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.contact import Contact
from app.models.entity import Entity
from app.models.entity_contact_map import EntityContactMap
from app.schemas.entity_contact_map import EntityContactMapCreate, EntityContactMapOut

router = APIRouter(prefix="/entity-contact-map")


@router.get("")
def list_maps(db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(EntityContactMap)
            .options(joinedload(EntityContactMap.entity), joinedload(EntityContactMap.contact))
            .order_by(EntityContactMap.id.desc())
        ).all()
    )
    return [
        {
            "id": row.id,
            "entity_id": row.entity_id,
            "contact_id": row.contact_id,
            "entity_name_ar": row.entity.entity_name_ar if row.entity else None,
            "contact_name": row.contact.full_name if row.contact else None,
            "contact_email": row.contact.email if row.contact else None,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("", response_model=EntityContactMapOut)
def create_map(payload: EntityContactMapCreate, db: Session = Depends(get_db)):
    if not db.get(Entity, payload.entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    if not db.get(Contact, payload.contact_id):
        raise HTTPException(status_code=404, detail="Contact not found")

    row = EntityContactMap(**payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mapping already exists")
    db.refresh(row)
    return row


@router.delete("/{map_id}")
def delete_map(map_id: int, db: Session = Depends(get_db)):
    row = db.get(EntityContactMap, map_id)
    if not row:
        return {"deleted": False}
    db.delete(row)
    db.commit()
    return {"deleted": True}
