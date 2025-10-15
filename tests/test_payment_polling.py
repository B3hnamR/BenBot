from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import OrderStatus
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Product
from app.infrastructure.db.repositories.user import UserRepository
from app.services.payment_polling import poll_pending_orders
from app.services.crypto_payment_service import CryptoSyncResult
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


class DummyBot:
    async def send_message(self, *args, **kwargs) -> None:  # pragma: no cover - not exercised here
        pass

    async def send_document(self, *args, **kwargs) -> None:  # pragma: no cover - not exercised here
        pass


class DummySessionFactory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass


class StubCryptoService:
    def __init__(self, _session: AsyncSession) -> None:
        pass

    async def refresh_order_status(self, order):
        order.status = OrderStatus.PAID
        order.payment_charge_id = "charge123"
        return CryptoSyncResult(
            updated=True,
            status="paid",
            order_status=order.status,
            pay_link=None,
            expires_at=datetime.now(tz=timezone.utc),
        )


@pytest.mark.asyncio()
async def test_poll_pending_orders_marks_paid(monkeypatch, session: AsyncSession) -> None:
    product = Product(
        name="Poller",
        slug="poller",
        summary=None,
        description=None,
        price=Decimal("7.00"),
        currency="USD",
        inventory=None,
        is_active=True,
        position=1,
    )
    session.add(product)
    await session.flush()

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=10,
        username="poll_user",
        first_name="Poll",
        last_name="User",
        language_code="en",
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    order_service = OrderService(session)
    order = await order_service.create_order(
        user_id=profile.id,
        product=product,
        answers=[],
        invoice_timeout_minutes=30,
    )
    order.status = OrderStatus.AWAITING_PAYMENT
    order.invoice_payload = "track123"
    await session.flush()

    monkeypatch.setattr("app.services.payment_polling.session_factory", lambda: DummySessionFactory(session))
    monkeypatch.setattr("app.services.payment_polling.CryptoPaymentService", StubCryptoService)

    async def _fake_ensure(*_args, **_kwargs):
        return True

    monkeypatch.setattr("app.services.payment_polling.ensure_fulfillment", _fake_ensure)

    updated = await poll_pending_orders(DummyBot(), batch_size=5)
    assert updated == 1

    await session.refresh(order)
    assert order.status is OrderStatus.PAID
