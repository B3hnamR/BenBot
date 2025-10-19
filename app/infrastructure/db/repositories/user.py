from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.infrastructure.db.models import UserProfile

from .base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_telegram_id(self, telegram_id: int) -> UserProfile | None:
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def upsert_from_telegram(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
        last_seen_at: datetime | None,
    ) -> UserProfile:
        profile = await self.get_by_telegram_id(telegram_id)
        if profile is None:
            profile = UserProfile(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                last_seen_at=last_seen_at,
            )
            await self.add(profile)
        else:
            profile.username = username
            profile.first_name = first_name
            profile.last_name = last_name
            profile.language_code = language_code
            profile.last_seen_at = last_seen_at
        return profile

    async def list_recent(self, limit: int = 20) -> list[UserProfile]:
        users, _ = await self.paginate_recent(limit=limit, offset=0)
        return users

    async def paginate_recent(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[UserProfile], bool]:
        result = await self.session.execute(
            select(UserProfile)
            .order_by(
                UserProfile.last_seen_at.is_(None),
                UserProfile.last_seen_at.desc(),
                UserProfile.created_at.desc(),
            )
            .offset(offset)
            .limit(limit + 1)
        )
        users = list(result.scalars().all())
        has_more = len(users) > limit
        return users[:limit], has_more

    async def get_by_id(self, user_id: int) -> UserProfile | None:
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.id == user_id)
        )
        return result.scalar_one_or_none()

    async def set_blocked(self, profile: UserProfile, blocked: bool) -> UserProfile:
        profile.is_blocked = blocked
        await self.session.flush()
        return profile

    async def update_notes(self, profile: UserProfile, notes: str | None) -> UserProfile:
        profile.notes = notes
        await self.session.flush()
        return profile
