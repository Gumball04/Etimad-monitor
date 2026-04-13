from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactOut

router = APIRouter(prefix="/contacts")


@router.get("", response_model=list[ContactOut])
def list_contacts(db: Session = Depends(get_db)):
    return list(db.scalars(select(Contact).order_by(Contact.id.desc())).all())


@router.post("", response_model=ContactOut)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db)):
    contact = Contact(**payload.model_dump())
    db.add(contact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Contact email already exists")
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
    return {"deleted": True}
