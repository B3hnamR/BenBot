
import pytest
import pytest_asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import OrderStatus, ProductQuestionType
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Product, ProductQuestion, UserProfile
from app.infrastructure.db.repositories.user import UserRepository
from app.services.order_service import OrderService


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
