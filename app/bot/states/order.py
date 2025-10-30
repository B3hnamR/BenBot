from aiogram.fsm.state import State, StatesGroup


class OrderFlowState(StatesGroup):
    quantity = State()
    coupon = State()
    loyalty = State()
    collecting_answer = State()
    confirm = State()
    cart_confirm = State()
