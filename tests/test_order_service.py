
import pytest
import pytest_asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import OrderStatus, ProductQuestionType
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Product, ProductQuestion, UserProfile
from app.infrastructure.db.repositories.order import OrderRepository
from app.infrastructure.db.repositories.user import UserRepository
from app.services.order_service import OrderService, OrderCreationError


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
async def test_create_order_with_answers(session: AsyncSession) -> None:
    product = Product(
        name='Test',
        slug='test',
        summary=None,
        description=None,
        price=Decimal('19.99'),
        currency='USD',
        inventory=None,
        is_active=True,
        position=1,
    )
    session.add(product)
    await session.flush()

    question = ProductQuestion(
        product_id=product.id,
        field_key='email',
        prompt='Email',
        question_type=ProductQuestionType.EMAIL,
        is_required=True,
    )
    session.add(question)

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=1,
        username='tester',
        first_name='Test',
        last_name='User',
        language_code='en',
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    service = OrderService(session)
    order = await service.create_order(
        user_id=profile.id,
        product=product,
        answers=[('email', 'user@example.com')],
        invoice_timeout_minutes=30,
    )

    assert order.status is OrderStatus.AWAITING_PAYMENT
    assert order.payment_expires_at is not None
    assert order.answers[0].answer_text == 'user@example.com'


@pytest.mark.asyncio()
async def test_enforce_expiration(session: AsyncSession) -> None:
    product = Product(
        name='Expired',
        slug='expired',
        summary=None,
        description=None,
        price=Decimal('10.00'),
        currency='USD',
        inventory=None,
        is_active=True,
        position=1,
    )
    session.add(product)
    await session.flush()

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=2,
        username='expired',
        first_name='Expired',
        last_name='User',
        language_code='en',
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    service = OrderService(session)
    order = await service.create_order(
        user_id=profile.id,
        product=product,
        answers=[],
        invoice_timeout_minutes=0,
    )

    order.payment_expires_at = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    await service.enforce_expiration(order)
    assert order.status is OrderStatus.EXPIRED


@pytest.mark.asyncio()
async def test_reopen_for_payment_resets_invoice(session: AsyncSession) -> None:
    product = Product(
        name='Reissue',
        slug='reissue',
        summary=None,
        description=None,
        price=Decimal('15.00'),
        currency='USD',
        inventory=None,
        is_active=True,
        position=1,
    )
    session.add(product)
    await session.flush()

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=3,
        username='reissue_user',
        first_name='Reissue',
        last_name='User',
        language_code='en',
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    service = OrderService(session)
    order = await service.create_order(
        user_id=profile.id,
        product=product,
        answers=[],
        invoice_timeout_minutes=30,
    )

    order.status = OrderStatus.CANCELLED
    order.invoice_payload = 'old-track'
    order.payment_provider = 'oxapay'

    await service.reopen_for_payment(order, invoice_timeout_minutes=45)

    assert order.status is OrderStatus.AWAITING_PAYMENT
    assert order.invoice_payload is None
    assert order.payment_provider is None
    assert order.payment_expires_at is not None


@pytest.mark.asyncio()
async def test_reopen_for_payment_requires_active_product(session: AsyncSession) -> None:
    product = Product(
        name='Inactive',
        slug='inactive',
        summary=None,
        description=None,
        price=Decimal('20.00'),
        currency='USD',
        inventory=None,
        is_active=False,
        position=1,
    )
    session.add(product)
    await session.flush()

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=4,
        username='inactive',
        first_name='Inactive',
        last_name='User',
        language_code='en',
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    service = OrderService(session)
    order = await service.create_order(
        user_id=profile.id,
        product=product,
        answers=[],
        invoice_timeout_minutes=30,
    )

    order.status = OrderStatus.CANCELLED

    with pytest.raises(OrderCreationError):
        await service.reopen_for_payment(order, invoice_timeout_minutes=30)


@pytest.mark.asyncio()
async def test_order_repository_list_recent_returns_latest(session: AsyncSession) -> None:
    product = Product(
        name='Recent',
        slug='recent',
        summary=None,
        description=None,
        price=Decimal('5.00'),
        currency='USD',
        inventory=None,
        is_active=True,
        position=1,
    )
    session.add(product)
    await session.flush()

    user_repo = UserRepository(session)
    profile = await user_repo.upsert_from_telegram(
        telegram_id=5,
        username='recent_user',
        first_name='Recent',
        last_name='User',
        language_code='en',
        last_seen_at=datetime.now(tz=timezone.utc),
    )

    service = OrderService(session)
    created_orders = []
    for offset in range(3):
        order = await service.create_order(
            user_id=profile.id,
            product=product,
            answers=[],
            invoice_timeout_minutes=30,
        )
        order.status = OrderStatus.PAID
        order.created_at = datetime.now(tz=timezone.utc) - timedelta(minutes=offset)
        created_orders.append(order)
    await session.flush()

    repo = OrderRepository(session)
    recent = await repo.list_recent(limit=2)
    assert len(recent) == 2
    assert recent[0].public_id == created_orders[0].public_id
    assert recent[1].public_id == created_orders[1].public_id
    assert recent[0].user is not None and recent[0].product is not None
