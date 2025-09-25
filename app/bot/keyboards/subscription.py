from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.infrastructure.db.models import RequiredChannel

SUBSCRIPTION_REFRESH_CALLBACK = "subscription:refresh"


def build_subscription_keyboard(channels: list[RequiredChannel]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for channel in channels:
        if channel.username:
            url = f"https://t.me/{channel.username.lstrip('@')}"
        elif channel.invite_link:
            url = channel.invite_link
        else:
            url = None

        label = channel.title or channel.username or "Channel"
        if url:
            builder.button(text=f"Join {label}", url=url)
        else:
            builder.button(text=label, callback_data="subscription:no_link")

    builder.button(text="I've Joined", callback_data=SUBSCRIPTION_REFRESH_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
