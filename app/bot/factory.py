from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.core.config import Settings


def create_bot(settings: Settings) -> Bot:
    default_props = DefaultBotProperties(parse_mode="HTML")
    return Bot(token=settings.bot_token, default=default_props)


def create_dispatcher() -> Dispatcher:
    return Dispatcher(storage=MemoryStorage())