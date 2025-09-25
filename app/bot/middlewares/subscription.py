from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.subscription import build_subscription_keyboard, SUBSCRIPTION_REFRESH_CALLBACK
from app.core.config import get_settings
from app.infrastructure.db.repositories import RequiredChannelRepository
from app.services.membership_service import MembershipService


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, membership_service: MembershipService) -> None:
        self._membership_service = membership_service
        self._settings = get_settings()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        bot = data.get("bot")
        user = data.get("event_from_user")

        if session is None or bot is None or user is None:
            return await handler(event, data)

        if user.id in self._settings.owner_user_ids:
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data == SUBSCRIPTION_REFRESH_CALLBACK:
            return await handler(event, data)

        channel_repo = RequiredChannelRepository(session)
        channels = await channel_repo.list_active()
        is_allowed = await self._membership_service.user_can_access(
            bot=bot,
            user_id=user.id,
            session=session,
            channels=channels,
        )

        if is_allowed:
            return await handler(event, data)

        keyboard = build_subscription_keyboard(list(channels)) if channels else None
        message_text = (
            "Please join the required channel(s) to access this bot."
            "\nTap 'I've Joined' after subscribing to continue."
        )

        if isinstance(event, Message):
            await event.answer(message_text, reply_markup=keyboard)
        elif isinstance(event, CallbackQuery):
            await event.answer("Access denied. Please join the required channels first.", show_alert=True)
            if event.message:
                await event.message.edit_text(message_text, reply_markup=keyboard)
        return None
