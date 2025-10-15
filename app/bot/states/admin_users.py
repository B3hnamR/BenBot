from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminUserNotesState(StatesGroup):
    editing = State()
