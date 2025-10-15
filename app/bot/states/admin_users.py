from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminUserState(StatesGroup):
    editing_notes = State()
    searching = State()
