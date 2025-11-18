from aiogram.fsm.state import State, StatesGroup


class OrderFeedbackState(StatesGroup):
    waiting_comment = State()
