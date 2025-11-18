import asyncio

from aiogram import Dispatcher

from app.bot import (
    OwnerAccessMiddleware,
    create_bot,
    create_dispatcher,
    register_handlers,
)
from app.bot.middlewares import DbSessionMiddleware, SubscriptionMiddleware, UserContextMiddleware
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.infrastructure.db.session import init_engine, session_factory
from app.services.container import membership_service
from app.services.timeline_status_service import TimelineStatusService


async def setup_middlewares(dispatcher: Dispatcher, owner_middleware: OwnerAccessMiddleware) -> None:
    db_middleware = DbSessionMiddleware(session_factory)
    user_middleware = UserContextMiddleware()
    subscription_middleware = SubscriptionMiddleware(membership_service)

    dispatcher.message.outer_middleware(db_middleware)
    dispatcher.callback_query.outer_middleware(db_middleware)

    dispatcher.message.outer_middleware(user_middleware)
    dispatcher.callback_query.outer_middleware(user_middleware)

    dispatcher.message.outer_middleware(subscription_middleware)
    dispatcher.callback_query.outer_middleware(subscription_middleware)

    register_handlers(dispatcher, owner_middleware)


async def bootstrap_default_settings() -> None:
    async with session_factory() as session:
        await membership_service.ensure_default_settings(session)
        await TimelineStatusService(session).ensure_defaults()
        await session.commit()


async def start_bot(dispatcher: Dispatcher) -> None:
    settings = get_settings()
    bot = create_bot(settings)

    owner_middleware = OwnerAccessMiddleware(owner_ids=set(settings.owner_user_ids))

    await setup_middlewares(dispatcher, owner_middleware)
    await bootstrap_default_settings()

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger(__name__)

    await init_engine()
    dispatcher = create_dispatcher()

    log.info("bot_starting")
    await start_bot(dispatcher)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
