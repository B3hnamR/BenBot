from __future__ import annotations

import time
from typing import Dict, Iterable, Sequence, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import MembershipStatus
from app.infrastructure.db.models import RequiredChannel
from app.infrastructure.db.repositories import RequiredChannelRepository

from .config_service import ConfigService

CacheKey = Tuple[int, int | str]
CacheValue = Tuple[MembershipStatus, float]


class MembershipService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache: Dict[CacheKey, CacheValue] = {}

    async def ensure_default_settings(self, session: AsyncSession) -> None:
        config_service = ConfigService(session)
        await config_service.ensure_defaults()

    async def is_subscription_required(self, session: AsyncSession) -> bool:
        config_service = ConfigService(session)
        return await config_service.subscription_required()

    async def user_can_access(
        self,
        bot: Bot,
        user_id: int,
        session: AsyncSession,
        channels: Sequence[RequiredChannel] | None = None,
    ) -> bool:
        if not await self.is_subscription_required(session):
            return True

        if channels is None:
            channel_repo = RequiredChannelRepository(session)
            channels = await channel_repo.list_active()

        if not channels:
            return True

        for channel in channels:
            status = await self._check_membership(bot, user_id, channel)
            if status != MembershipStatus.MEMBER:
                return False
        return True

    async def _check_membership(
        self,
        bot: Bot,
        user_id: int,
        channel: RequiredChannel,
    ) -> MembershipStatus:
        cache_key = self._cache_key(user_id, channel)
        cached_status = self._cache.get(cache_key)
        now = time.monotonic()
        if cached_status and now - cached_status[1] < self._settings.membership_cache_ttl:
            return cached_status[0]

        try:
            target = channel.channel_id or (f"@{channel.username}" if channel.username else None)
            if target is None:
                status = MembershipStatus.UNKNOWN
            else:
                member = await bot.get_chat_member(target, user_id)
                if member.status in {"creator", "administrator", "member"}:
                    status = MembershipStatus.MEMBER
                else:
                    status = MembershipStatus.NOT_MEMBER
        except TelegramAPIError:
            status = MembershipStatus.UNKNOWN

        self._cache[cache_key] = (status, now)
        return status

    def invalidate_user(self, user_id: int) -> None:
        keys_to_delete = [key for key in self._cache if key[0] == user_id]
        for key in keys_to_delete:
            self._cache.pop(key, None)

    @staticmethod
    def _cache_key(user_id: int, channel: RequiredChannel) -> CacheKey:
        return (user_id, channel.channel_id or channel.username or "unknown")
