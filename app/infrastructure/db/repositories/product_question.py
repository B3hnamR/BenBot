from __future__ import annotations

from sqlalchemy import func, select

from app.infrastructure.db.models import ProductQuestion

from .base import BaseRepository


class ProductQuestionRepository(BaseRepository):
    async def list_for_product(self, product_id: int) -> list[ProductQuestion]:
        result = await self.session.execute(
            select(ProductQuestion)
            .where(ProductQuestion.product_id == product_id)
            .order_by(ProductQuestion.position.asc(), ProductQuestion.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, question_id: int) -> ProductQuestion | None:
        result = await self.session.execute(
            select(ProductQuestion).where(ProductQuestion.id == question_id)
        )
        return result.scalar_one_or_none()

    async def add_question(self, question: ProductQuestion) -> ProductQuestion:
        self.session.add(question)
        await self.session.flush()
        return question

    async def delete(self, question: ProductQuestion) -> None:
        await self.session.delete(question)

    async def get_next_position(self, product_id: int) -> int:
        result = await self.session.execute(
            select(func.max(ProductQuestion.position)).where(ProductQuestion.product_id == product_id)
        )
        max_position = result.scalar()
        return (max_position or 0) + 1

    async def reorder_positions(self, product_id: int) -> None:
        questions = await self.list_for_product(product_id)
        for index, question in enumerate(questions, start=1):
            question.position = index