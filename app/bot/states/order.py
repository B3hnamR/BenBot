from aiogram.fsm.state import State, StatesGroup


class OrderFlowState(StatesGroup):
    collecting_answer = State()
    confirm = State()
