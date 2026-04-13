from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Tender(Base):
    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tender_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    tender_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_number: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_fee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_duration: Mapped[str | None] = mapped_column(String(255), nullable=True)
    insurance_required: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tender_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    government_entity: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    remaining_time: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submission_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    initial_guarantee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    classification_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tender_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    email_deliveries = relationship("TenderEmailDelivery", back_populates="tender", cascade="all, delete-orphan")
