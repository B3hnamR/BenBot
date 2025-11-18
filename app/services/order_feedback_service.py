from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Order, OrderFeedback
from app.infrastructure.db.repositories import OrderFeedbackRepository, OrderRepository

ORDER_FEEDBACK_PROMPT_FLAG = "feedback_prompted_at"


class OrderFeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = OrderFeedbackRepository(session)
        self._orders = OrderRepository(session)

    async def has_feedback(self, order: Order) -> bool:
        if order.feedback is not None:
            return True
        existing = await self._repo.get_by_order_id(order.id)
        if existing:
            order.feedback = existing
            return True
        return False

    async def create_feedback(
        self,
        order: Order,
        *,
        user_id: int,
        rating: int,
        comment: str | None = None,
    ) -> OrderFeedback:
        feedback = await self._repo.get_by_order_id(order.id)
        if feedback is not None:
            feedback.rating = rating
            feedback.comment = comment
        else:
            feedback = OrderFeedback(order_id=order.id, user_id=user_id, rating=rating, comment=comment)
            self._session.add(feedback)
        await self._session.flush()
        order.feedback = feedback
        return feedback

    async def prompt_feedback(self, bot: Bot, order: Order) -> bool:
        if await self.has_feedback(order):
            return False
        extra = dict(order.extra_attrs or {})
        prompted_at = extra.get(ORDER_FEEDBACK_PROMPT_FLAG)
        if prompted_at:
            return False
        user = order.user
        if user is None or user.telegram_id is None:
            return False
        from app.bot.keyboards.orders import order_feedback_prompt_keyboard  # lazy import

        text = (
            f"We'd love your feedback on order <code>{order.public_id}</code>.\n"
            "Tap below to rate your experience."
        )
        try:
            await bot.send_message(
                user.telegram_id,
                text,
                reply_markup=order_feedback_prompt_keyboard(order),
            )
        except Exception:  # noqa: BLE001
            return False

        extra[ORDER_FEEDBACK_PROMPT_FLAG] = datetime.now(tz=timezone.utc).isoformat()
        await self._orders.merge_extra_attrs(order, extra)
        order.extra_attrs = extra
        return True
