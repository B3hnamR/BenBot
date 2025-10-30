from aiogram.fsm.state import State, StatesGroup


class AdminCouponState(StatesGroup):
    create_code = State()
    create_name = State()
    create_type = State()
    create_value = State()
    create_min_total = State()
    create_max_redemptions = State()
    create_per_user_limit = State()
