from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.enums import OrderStatus
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Order, Product
from app.infrastructure.db.repositories.user import UserRepository
from app.services.config_service import ConfigService
from app.services.order_notification_service import OrderNotificationService
from app.services.order_service import OrderService


@pytest_asyncio.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _create_order(session: AsyncSession) -> Order:
    product = Product(
        name="Test Plan",
        slug="test-plan",
        summary=None,
        description=None,
        price=Decimal("10.00"),
        currency="USD",
        inventory=5,
        is_active=True,
        position=1,
    )
    session.add(product)
    await session.flush()

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=111,
        username="buyer",
        first_name="Buyer",
        last_name="Example",
        language_code="en",
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    order_service = OrderService(session)
    order = await order_service.create_order(
        user_id=profile.id,
        product=product,
        answers=[],
        invoice_timeout_minutes=60,
    )
    await session.flush()
    return order


@pytest_asyncio.fixture(autouse=True)
async def reset_owner_ids():
    settings = get_settings()
    original = list(settings.owner_user_ids)
    yield
    settings.owner_user_ids = original


class StubBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


@pytest.mark.asyncio()
async def test_notify_cancelled_records_once(session: AsyncSession) -> None:
    settings = get_settings()
    settings.owner_user_ids = [999]

    config_service = ConfigService(session)
    await config_service.ensure_defaults()

    order = await _create_order(session)
    order.status = OrderStatus.CANCELLED

    notifier = OrderNotificationService(session)
    bot = StubBot()

    sent_first = await notifier.notify_cancelled(bot, order, reason="user_cancelled")
    assert sent_first is True
    assert bot.messages and bot.messages[0][0] == 999

    meta = (order.extra_attrs or {}).get("notifications") or {}
    assert "cancel_sent" in meta
    assert meta["cancel_sent"]["reason"] == "user_cancelled"

    sent_second = await notifier.notify_cancelled(bot, order, reason="user_cancelled")
    assert sent_second is False
    assert len(bot.messages) == 1


@pytest.mark.asyncio()
async def test_notify_cancelled_respects_setting(session: AsyncSession) -> None:
    settings = get_settings()
    settings.owner_user_ids = [999]

    config_service = ConfigService(session)
    await config_service.ensure_defaults()
    alerts = await config_service.get_alert_settings()
    alerts.notify_cancellation = False
    await config_service.save_alert_settings(alerts)

    order = await _create_order(session)
    order.status = OrderStatus.CANCELLED

    notifier = OrderNotificationService(session)
    bot = StubBot()

    sent = await notifier.notify_cancelled(bot, order, reason="user_cancelled")
    assert sent is False
    assert not bot.messages
