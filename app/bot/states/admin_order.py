from aiogram.fsm.state import State, StatesGroup


class AdminOrderTimelineState(StatesGroup):
    add_note = State()
    add_status = State()
    rename_status = State()
    edit_status_message = State()
