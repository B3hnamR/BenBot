from aiogram.fsm.state import State, StatesGroup


class AdminCouponState(StatesGroup):
    create_code = State()
    create_name = State()
    create_type = State()
    create_value = State()
    create_min_total = State()
    create_max_redemptions = State()
    create_per_user_limit = State()
    edit_coupon = State()
    edit_name = State()
    edit_description = State()
    edit_type = State()
    edit_value = State()
    edit_min_total = State()
    edit_max_discount = State()
    edit_max_redemptions = State()
    edit_per_user_limit = State()
    edit_start_at = State()
    edit_end_at = State()
