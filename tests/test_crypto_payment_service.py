from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import OrderStatus
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Order, Product
from app.infrastructure.db.repositories.user import UserRepository
from app.services.config_service import ConfigService
from app.services.crypto_payment_service import CryptoPaymentService, OXAPAY_EXTRA_KEY
from app.services.oxapay_client import OxapayClient, OxapayInvoice, OxapayPayment
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
        name="Crypto Plan",
        slug="crypto-plan",
        summary=None,
        description=None,
        price=Decimal("25.00"),
        currency="USD",
        inventory=None,
        is_active=True,
        position=1,
    )
    session.add(product)
    await session.flush()

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=999,
        username="buyer",
        first_name="Buyer",
        last_name="Example",
        language_code="en",
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    service = OrderService(session)
    order = await service.create_order(
        user_id=profile.id,
        product=product,
        answers=[],
        invoice_timeout_minutes=60,
    )
    await session.flush()
    return order


async def _prepare_crypto_service(session: AsyncSession, api_key: str) -> CryptoPaymentService:
    config_service = ConfigService(session)
    config_service._env_settings.oxapay_api_key = api_key
    await config_service.ensure_defaults()
    config = await config_service.get_crypto_settings()
    config.enabled = True
    await config_service.save_crypto_settings(config)

    service = CryptoPaymentService(session)
    service._settings.oxapay_api_key = api_key
    service._config_service._env_settings.oxapay_api_key = api_key
    return service


@pytest.mark.asyncio()
async def test_create_invoice_requires_api_key(session: AsyncSession) -> None:
    order = await _create_order(session)
    config_service = ConfigService(session)
    await config_service.ensure_defaults()

    service = CryptoPaymentService(session)
    service._settings.oxapay_api_key = None

    result = await service.create_invoice_for_order(order, description="Test order", email=None)

    assert result.enabled is False
    assert result.pay_link is None
    assert result.error is not None and "API key" in result.error
    assert order.invoice_payload is None


@pytest.mark.asyncio()
async def test_create_invoice_success_updates_order(session: AsyncSession) -> None:
    order = await _create_order(session)
    service = await _prepare_crypto_service(session, api_key="token")

    class StubClient:
        async def create_invoice(self, payload: dict) -> OxapayInvoice:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=payload["lifetime"])
            return OxapayInvoice(
                track_id="track123",
                pay_link="https://pay.example/track123",
                status="waiting",
                amount=payload["amount"],
                currency=payload["currency"],
                expires_at=expires_at,
                data={
                    "track_id": "track123",
                    "pay_link": "https://pay.example/track123",
                    "status": "waiting",
                    "expired_at": int(expires_at.timestamp()),
                },
            )

    service._get_client = lambda: StubClient()  # type: ignore[assignment]

    result = await service.create_invoice_for_order(order, description="Test order", email="buyer@example.com")

    assert result.enabled is True
    assert result.track_id == "track123"
    assert order.invoice_payload == "track123"
    assert order.payment_provider == "oxapay"
    assert order.extra_attrs is not None
    assert order.extra_attrs[OXAPAY_EXTRA_KEY]["pay_link"] == "https://pay.example/track123"


@pytest.mark.asyncio()
async def test_refresh_updates_status_to_paid(session: AsyncSession) -> None:
    order = await _create_order(session)
    service = await _prepare_crypto_service(session, api_key="token")

    order.invoice_payload = "track123"
    order.status = OrderStatus.AWAITING_PAYMENT
    order.extra_attrs = {
        OXAPAY_EXTRA_KEY: {
            "pay_link": "https://pay.example/track123",
        }
    }

    class PaymentStub:
        async def get_payment(self, track_id: str) -> OxapayPayment:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
            return OxapayPayment(
                track_id=track_id,
                status="paid",
                amount=25.0,
                currency="USD",
                expired_at=expires_at,
                mixed_payment=False,
                fee_paid_by_payer=0,
                transactions=[{"tx_hash": "hash123"}],
                data={
                    "track_id": track_id,
                    "status": "paid",
                    "txs": [{"tx_hash": "hash123"}],
                    "expired_at": int(expires_at.timestamp()),
                },
            )

    service._get_client = lambda: PaymentStub()  # type: ignore[assignment]

    result = await service.refresh_order_status(order)

    assert result.updated is True
    assert result.order_status is OrderStatus.PAID
    assert order.status is OrderStatus.PAID
    assert order.payment_charge_id == "hash123"
    assert order.extra_attrs[OXAPAY_EXTRA_KEY]["status"] == "paid"


@pytest.mark.asyncio()
async def test_invalidate_invoice_clears_link(session: AsyncSession) -> None:
    order = await _create_order(session)
    service = await _prepare_crypto_service(session, api_key="token")

    class StubClient:
        async def create_invoice(self, payload: dict) -> OxapayInvoice:
            return OxapayInvoice(
                track_id="track123",
                pay_link="https://pay.example/track123",
                status="waiting",
                amount=payload["amount"],
                currency=payload["currency"],
                expires_at=datetime.now(tz=timezone.utc),
                data={"track_id": "track123", "pay_link": "https://pay.example/track123"},
            )

    service._get_client = lambda: StubClient()  # type: ignore[assignment]
    await service.create_invoice_for_order(order, description="Test", email="buyer@example.com")

    await service.invalidate_invoice(order, reason="cancelled")

    assert order.invoice_payload is None
    assert order.payment_provider is None
    assert order.extra_attrs[OXAPAY_EXTRA_KEY]["pay_link"] is None
    assert order.extra_attrs[OXAPAY_EXTRA_KEY]["status"] == "cancelled"


def test_normalise_payload_converts_values() -> None:
    payload = OxapayClient._normalise_payload(
        {
            "amount": 5,
            "currency": "USD",
            "mixed_payment": True,
            "auto_withdrawal": False,
            "note": "test",
            "optional": None,
        }
    )

    assert payload == {
        "amount": 5,
        "currency": "USD",
        "mixed_payment": True,
        "auto_withdrawal": False,
        "note": "test",
    }


class StubBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


@pytest.mark.asyncio()
async def test_ensure_fulfillment_marks_delivered(session: AsyncSession) -> None:
    order = await _create_order(session)
    await session.refresh(order, attribute_names=["product", "user"])
    service = await _prepare_crypto_service(session, api_key="token")
    order.product.extra_attrs = {
        "fulfillment_plan": [
            {"action": "generate_license", "prefix": "BEN-", "length": 8},
            {"action": "send_text", "text": "Your license: {license_code}"},
        ]
    }

    class StubClient:
        async def create_invoice(self, payload: dict) -> OxapayInvoice:
            return OxapayInvoice(
                track_id="track123",
                pay_link="https://pay.example/track123",
                status="waiting",
                amount=payload["amount"],
                currency=payload["currency"],
                expires_at=datetime.now(tz=timezone.utc),
                data={"track_id": "track123", "pay_link": "https://pay.example/track123"},
            )

    service._get_client = lambda: StubClient()  # type: ignore[assignment]
    await service.create_invoice_for_order(order, description="Test", email="buyer@example.com")

    order.status = OrderStatus.PAID

    from app.services.order_fulfillment import ensure_fulfillment

    bot = StubBot()
    delivered = await ensure_fulfillment(session, bot, order, source="test")

    assert delivered is True
    assert len(bot.messages) >= 2
    meta = order.extra_attrs.get(OXAPAY_EXTRA_KEY, {})
    fulfillment = meta.get("fulfillment")
    assert fulfillment is not None and fulfillment.get("delivered_at")
    context = fulfillment.get("context") or {}
    assert context.get("license_code", "").startswith("BEN-")


@pytest.mark.asyncio()
async def test_ensure_fulfillment_updates_inventory(session: AsyncSession) -> None:
    order = await _create_order(session)
    await session.refresh(order, attribute_names=["product", "user"])
    order.product.inventory = 1
    order.product.is_active = True
    order.product.extra_attrs = {
        "fulfillment_plan": [
            {"action": "generate_license", "prefix": "BEN-", "length": 6},
        ]
    }

    from app.services.order_fulfillment import ensure_fulfillment

    bot = StubBot()
    delivered = await ensure_fulfillment(session, bot, order, source="test")

    assert delivered is True
    assert order.product.inventory == 0
    assert order.product.is_active is False

    meta = order.extra_attrs.get(OXAPAY_EXTRA_KEY, {})
    fulfillment = meta.get("fulfillment") or {}
    inventory_meta = fulfillment.get("inventory") or {}
    assert inventory_meta.get("before") == 1
    assert inventory_meta.get("after") == 0
    assert inventory_meta.get("product_deactivated") is True
    context = fulfillment.get("context") or {}
    assert context.get("license_code")

    delivered_again = await ensure_fulfillment(session, bot, order, source="repeat")
    assert delivered_again is False
