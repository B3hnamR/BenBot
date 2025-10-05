from aiogram.fsm.state import State, StatesGroup


class ProductCreateState(StatesGroup):
    name = State()
    summary = State()
    description = State()
    price = State()
    currency = State()
    inventory = State()
    position = State()
    confirm = State()


class ProductEditState(StatesGroup):
    awaiting_value = State()


class ProductQuestionCreateState(StatesGroup):
    field_key = State()
    prompt = State()
    help_text = State()
    question_type = State()
    required = State()
    options = State()
    confirm = State()
