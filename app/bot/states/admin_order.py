from aiogram.fsm.state import State, StatesGroup


class AdminOrderTimelineState(StatesGroup):
    add_note = State()
