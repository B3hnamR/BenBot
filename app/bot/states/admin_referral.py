from aiogram.fsm.state import State, StatesGroup


class AdminReferralState(StatesGroup):
    edit_default_value = State()
    edit_reseller_ids = State()
    edit_link_reward_value = State()
