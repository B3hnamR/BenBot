from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import select, update

from app.infrastructure.db.models import RequiredChannel

from .base import BaseRepository


class RequiredChannelRepository(BaseRepository):
    async def list_active(self) -> Sequence[RequiredChannel]:
        result = await self.session.execute(
            select(RequiredChannel)
            .where(RequiredChannel.is_deleted.is_(False))
            .order_by(RequiredChannel.created_at.asc())
        )
        return result.scalars().all()

    async def get_by_channel_id(self, channel_id: int) -> RequiredChannel | None:
        result = await self.session.execute(
            select(RequiredChannel).where(
                RequiredChannel.channel_id == channel_id,
                RequiredChannel.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, channel: RequiredChannel) -> RequiredChannel:
        existing = await self.get_by_channel_id(channel.channel_id)
        if existing is None:
            await self.add(channel)
            return channel

        existing.username = channel.username
        existing.title = channel.title
        existing.invite_link = channel.invite_link
        existing.is_mandatory = channel.is_mandatory
        existing.is_deleted = False
        return existing

    async def bulk_soft_delete(self, channel_ids: Iterable[int]) -> None:
        await self.session.execute(
            update(RequiredChannel)
            .where(RequiredChannel.channel_id.in_(list(channel_ids)))
            .values(is_deleted=True)
        )
