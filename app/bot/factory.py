from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.core.config import Settings


def create_bot(settings: Settings) -> Bot:
    return Bot(token=settings.bot_token, parse_mode="HTML")


def create_dispatcher() -> Dispatcher:
    return Dispatcher(storage=MemoryStorage())
