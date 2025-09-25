from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.core.logging import get_logger


class OwnerAccessMiddleware(BaseMiddleware):
    def __init__(self, owner_ids: set[int]) -> None:
        self.owner_ids = owner_ids
        self._log = get_logger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if self.owner_ids and user.id not in self.owner_ids:
            self._log.warning("unauthorized_access", user_id=user.id, username=user.username)
            bot = data.get("bot")
            if bot is not None:
                await bot.send_message(chat_id=user.id, text="Access is restricted to the bot owner.")
            return None

        return await handler(event, data)
