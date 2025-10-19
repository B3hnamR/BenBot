from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SupportState(StatesGroup):
    menu = State()
    choosing_category = State()
    choosing_order = State()
    entering_subject = State()
    entering_message = State()
    replying = State()
