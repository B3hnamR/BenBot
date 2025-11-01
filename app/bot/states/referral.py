from aiogram.fsm.state import State, StatesGroup


class ReferralState(StatesGroup):
    create_label = State()
    create_reward_type = State()
    create_reward_value = State()
    edit_label = State()
    edit_reward_value = State()
