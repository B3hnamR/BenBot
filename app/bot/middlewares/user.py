from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import UserRepository


class UserContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        user = data.get("event_from_user")

        if session is None or user is None:
            return await handler(event, data)

        repo = UserRepository(session)
        profile = await repo.upsert_from_telegram(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
            last_seen_at=datetime.now(tz=timezone.utc),
        )

        data["user_profile"] = profile

        if profile.is_blocked:
            if isinstance(event, CallbackQuery):
                await event.answer("Access to this bot has been restricted.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Access to this bot has been restricted.")
            else:
                bot = data.get("bot")
                if bot is not None:
                    await bot.send_message(chat_id=user.id, text="Access to this bot has been restricted.")
            return None

        return await handler(event, data)
