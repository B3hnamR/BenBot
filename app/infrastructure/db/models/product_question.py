from __future__ import annotations

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ProductQuestionType
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class ProductQuestion(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "product_questions"

    product_id: Mapped[int] = mapped_column(
        Integer(), ForeignKey("products.id"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(length=64), nullable=False)
    prompt: Mapped[str] = mapped_column(String(length=512), nullable=False)
    help_text: Mapped[str | None] = mapped_column(String(length=512))
    question_type: Mapped[ProductQuestionType] = mapped_column(
        Enum(ProductQuestionType, native_enum=False, length=32),
        default=ProductQuestionType.TEXT,
        nullable=False,
    )
    is_required: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON())

    product: Mapped["Product"] = relationship("Product", back_populates="questions")

    def as_markup_payload(self) -> dict[str, str | bool | int | dict | None]:
        return {
            "field_key": self.field_key,
            "prompt": self.prompt,
            "help_text": self.help_text,
            "question_type": self.question_type.value,
            "is_required": self.is_required,
        }
