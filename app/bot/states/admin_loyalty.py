from aiogram.fsm.state import State, StatesGroup


class AdminLoyaltyState(StatesGroup):
    set_earn_rate = State()
    set_redeem_ratio = State()
    set_min_redeem = State()
