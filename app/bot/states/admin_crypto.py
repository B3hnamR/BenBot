from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminCryptoState(StatesGroup):
    currencies = State()
    lifetime = State()
    underpaid = State()
    return_url = State()
    callback_url = State()
    callback_secret = State()
    to_currency = State()
