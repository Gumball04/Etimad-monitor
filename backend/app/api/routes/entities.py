from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entity import Entity
from app.schemas.entity import EntityCreate, EntityOut

router = APIRouter(prefix="/entities")


@router.get("", response_model=list[EntityOut])
def list_entities(db: Session = Depends(get_db)):
    return list(db.scalars(select(Entity).order_by(Entity.id.desc())).all())


@router.post("", response_model=EntityOut)
def create_entity(payload: EntityCreate, db: Session = Depends(get_db)):
    entity = Entity(**payload.model_dump())
    db.add(entity)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Entity already exists")
    db.refresh(entity)
    return entity


@router.delete("/{entity_id}")
def delete_entity(entity_id: int, db: Session = Depends(get_db)):
    entity = db.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    db.delete(entity)
    db.commit()
    return {"deleted": True}
