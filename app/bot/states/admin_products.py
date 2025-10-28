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


class CategoryCreateState(StatesGroup):
    name = State()
    description = State()
    position = State()
    confirm = State()


class CategoryEditState(StatesGroup):
    awaiting_value = State()


class CategoryAssignState(StatesGroup):
    awaiting_product_id = State()


class BundleComponentState(StatesGroup):
    awaiting_product_id = State()
    awaiting_quantity = State()


class RelationCreateState(StatesGroup):
    awaiting_product_id = State()
    awaiting_type = State()
    awaiting_weight = State()
