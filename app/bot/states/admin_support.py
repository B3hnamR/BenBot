from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminSupportState(StatesGroup):
    replying = State()
