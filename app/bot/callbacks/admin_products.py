from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class ProductAdminCallback(CallbackData, prefix="prodadm"):
    action: str
    product_id: int | None = None
    question_id: int | None = None
    target_id: int | None = None
    value: str | None = None
