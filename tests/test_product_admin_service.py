import pytest
import pytest_asyncio
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ProductQuestionType
from app.infrastructure.db.base import Base
from app.services.product_admin_service import (
    ProductAdminService,
    ProductInput,
    ProductValidationError,
    QuestionInput,
)


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
async def test_create_product_assigns_slug_and_position(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    product = await service.create_product(
        ProductInput(
            name='Test Product',
            summary='Summary',
            description='Description',
            price=Decimal('10.00'),
            currency='USD',
            inventory=5,
            position=None,
        )
    )

    assert product.slug == 'test-product'
    assert product.position == 1
    assert product.is_active is False


@pytest.mark.asyncio()
async def test_update_product_refreshes_slug_when_name_changes(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    product = await service.create_product(
        ProductInput(
            name='Initial Name',
            summary=None,
            description=None,
            price=Decimal('15.00'),
            currency='USD',
            inventory=None,
            position=None,
        )
    )

    updated = await service.update_product(product.id, name='Updated Name')
    assert updated.slug == 'updated-name'



@pytest.mark.asyncio()
async def test_create_product_accepts_long_summary(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    long_summary = "x" * 2048
    product = await service.create_product(
        ProductInput(
            name='Long Summary Product',
            summary=long_summary,
            description=None,
            price=Decimal('49.99'),
            currency='USD',
            inventory=None,
            position=None,
        )
    )

    assert product.summary == long_summary

@pytest.mark.asyncio()
async def test_toggle_product_flips_active_flag(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    product = await service.create_product(
        ProductInput(
            name='Toggle Product',
            summary=None,
            description=None,
            price=Decimal('20.00'),
            currency='USD',
            inventory=None,
            position=None,
        )
    )

    toggled = await service.toggle_product_active(product.id)
    assert toggled.is_active is True


@pytest.mark.asyncio()
async def test_add_and_delete_question(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    product = await service.create_product(
        ProductInput(
            name='Question Product',
            summary=None,
            description=None,
            price=Decimal('30.00'),
            currency='USD',
            inventory=None,
            position=None,
        )
    )

    question = await service.add_question(
        QuestionInput(
            product_id=product.id,
            field_key='email',
            prompt='Enter your email',
            help_text=None,
            question_type=ProductQuestionType.EMAIL,
            is_required=True,
            config=None,
        )
    )

    assert question.position == 1
    assert question.field_key == 'email'

    await service.delete_question(question.id)
    questions = await service.list_questions(product.id)
    assert questions == []


@pytest.mark.asyncio()
async def test_add_question_rejects_duplicate_field_keys(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    product = await service.create_product(
        ProductInput(
            name='Duplicate Field Product',
            summary=None,
            description=None,
            price=Decimal('25.00'),
            currency='USD',
            inventory=None,
            position=None,
        )
    )

    input_payload = QuestionInput(
        product_id=product.id,
        field_key='notes',
        prompt='Provide notes',
        help_text=None,
        question_type=ProductQuestionType.TEXT,
        is_required=False,
        config=None,
    )
    await service.add_question(input_payload)

    with pytest.raises(ProductValidationError):
        await service.add_question(input_payload)


@pytest.mark.asyncio()
async def test_delete_question_reorders_positions(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    product = await service.create_product(
        ProductInput(
            name='Reorder Product',
            summary=None,
            description=None,
            price=Decimal('40.00'),
            currency='USD',
            inventory=None,
            position=None,
        )
    )

    first = await service.add_question(
        QuestionInput(
            product_id=product.id,
            field_key='first',
            prompt='First question',
            help_text=None,
            question_type=ProductQuestionType.TEXT,
            is_required=True,
            config=None,
        )
    )
    second = await service.add_question(
        QuestionInput(
            product_id=product.id,
            field_key='second',
            prompt='Second question',
            help_text=None,
            question_type=ProductQuestionType.TEXT,
            is_required=True,
            config=None,
        )
    )

    await service.delete_question(first.id)
    questions = await service.list_questions(product.id)

    assert len(questions) == 1
    assert questions[0].id == second.id
    assert questions[0].position == 1


@pytest.mark.asyncio()
async def test_question_type_round_trip(session: AsyncSession) -> None:
    service = ProductAdminService(session)
    product = await service.create_product(
        ProductInput(
            name='Enum Product',
            summary=None,
            description=None,
            price=Decimal('12.00'),
            currency='USD',
            inventory=None,
            position=None,
        )
    )

    await service.add_question(
        QuestionInput(
            product_id=product.id,
            field_key='email',
            prompt='Your email',
            help_text=None,
            question_type=ProductQuestionType.EMAIL,
            is_required=True,
            config=None,
        )
    )

    fetched = await service.get_product(product.id)
    assert fetched.questions[0].question_type is ProductQuestionType.EMAIL
