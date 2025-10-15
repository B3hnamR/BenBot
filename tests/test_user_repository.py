from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.base import Base
from app.infrastructure.db.models import UserProfile
from app.infrastructure.db.repositories.user import UserRepository


@pytest_asyncio.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio()
async def test_user_repository_updates(session: AsyncSession) -> None:
    repo = UserRepository(session)
    user = UserProfile(
        telegram_id=100,
        username='tester',
        first_name='Test',
        last_name='User',
        last_seen_at=datetime.now(tz=timezone.utc),
    )
    session.add(user)
    await session.flush()

    await repo.set_blocked(user, True)
    await repo.update_notes(user, 'VIP customer')

    assert user.is_blocked is True
    assert user.notes == 'VIP customer'


@pytest.mark.asyncio()
async def test_user_repository_list_recent(session: AsyncSession) -> None:
    repo = UserRepository(session)
    now = datetime.now(tz=timezone.utc)
    for offset in range(3):
        profile = UserProfile(
            telegram_id=200 + offset,
            username=f'user{offset}',
            first_name='User',
            last_name=str(offset),
            last_seen_at=now - timedelta(minutes=offset),
        )
        session.add(profile)
    await session.flush()

    users = await repo.list_recent(limit=2)
    assert len(users) == 2
    assert users[0].telegram_id == 200
    assert users[1].telegram_id == 201
