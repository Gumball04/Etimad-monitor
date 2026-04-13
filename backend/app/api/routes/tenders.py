from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.tender import TenderOut
from app.services.tender_service import export_tenders_excel, list_tenders

router = APIRouter(prefix="/tenders")


@router.get("", response_model=list[TenderOut])
def get_tenders(
    limit: int = Query(default=100, le=500),
    government_entity: str | None = None,
    db: Session = Depends(get_db),
) -> list[TenderOut]:
    return list_tenders(db, limit=limit, government_entity=government_entity)


@router.get("/export")
def export_tenders(reference_numbers: list[str] | None = Query(default=None), db: Session = Depends(get_db)):
    content = export_tenders_excel(db, reference_numbers)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="etimad_tenders.xlsx"'},
    )


@router.delete("/reset-db")
def reset_db(db: Session = Depends(get_db)):
    db.execute(
        text(
            "TRUNCATE TABLE tender_email_deliveries, entity_contact_map, contacts, entities, tenders "
            "RESTART IDENTITY CASCADE"
        )
    )
    db.commit()
    return {"message": "done"}
