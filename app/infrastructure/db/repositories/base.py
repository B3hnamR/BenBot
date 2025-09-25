from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, instance: object) -> object:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: object) -> None:
        await self.session.delete(instance)
