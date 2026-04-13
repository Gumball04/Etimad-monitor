from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.keyword import Keyword
from app.schemas.keyword import KeywordCreate, KeywordDeleteResponse, KeywordOut

router = APIRouter(prefix="/keywords")


@router.get("", response_model=list[KeywordOut])
def list_keywords(db: Session = Depends(get_db)) -> list[KeywordOut]:
    return list(
        db.scalars(
            select(Keyword).order_by(Keyword.created_at.desc(), Keyword.id.desc())
        ).all()
    )


@router.post("", response_model=KeywordOut, status_code=status.HTTP_201_CREATED)
def create_keyword(payload: KeywordCreate, db: Session = Depends(get_db)) -> KeywordOut:
    keyword = Keyword(keyword=payload.keyword)
    db.add(keyword)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Keyword already exists")

    db.refresh(keyword)
    return keyword


@router.delete("/{keyword_id}", response_model=KeywordDeleteResponse)
def delete_keyword(keyword_id: int, db: Session = Depends(get_db)) -> KeywordDeleteResponse:
    keyword = db.get(Keyword, keyword_id)
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")

    db.delete(keyword)
    db.commit()
    return KeywordDeleteResponse(id=keyword_id)
