from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.infrastructure.db.models import ReferralLink
from app.bot.keyboards.main_menu import MainMenuCallback

REFERRAL_CREATE = "user:ref:create"
REFERRAL_REFRESH = "user:ref:refresh"
REFERRAL_LINK_PREFIX = "user:ref:link:"
REFERRAL_DELETE_PREFIX = "user:ref:delete:"
REFERRAL_CONFIRM_DELETE_PREFIX = "user:ref:delete_confirm:"
REFERRAL_REWARDS_PREFIX = "user:ref:rewards:"
REFERRAL_SHARE_PREFIX = "user:ref:share:"
REFERRAL_EDIT_LABEL_PREFIX = "user:ref:edit_label:"
REFERRAL_EDIT_REWARD_PREFIX = "user:ref:edit_reward:"


def referral_dashboard_keyboard(links: Sequence[ReferralLink]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Create new link", callback_data=REFERRAL_CREATE)
    for link in links:
        label = (link.meta or {}).get("label") if link.meta else None
        title = f"{label} ({link.code})" if label else f"Link {link.code}"
        builder.button(text=title, callback_data=f"{REFERRAL_LINK_PREFIX}{link.id}")
    builder.button(text="Refresh", callback_data=REFERRAL_REFRESH)
    builder.button(text="Back to menu", callback_data=MainMenuCallback.HOME.value)
    builder.adjust(1)
    return builder.as_markup()


def referral_link_keyboard(link: ReferralLink) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Share link", callback_data=f"{REFERRAL_SHARE_PREFIX}{link.id}")
    builder.button(text="View rewards", callback_data=f"{REFERRAL_REWARDS_PREFIX}{link.id}")
    builder.button(text="Rename", callback_data=f"{REFERRAL_EDIT_LABEL_PREFIX}{link.id}")
    builder.button(text="Adjust reward", callback_data=f"{REFERRAL_EDIT_REWARD_PREFIX}{link.id}")
    builder.button(text="Delete", callback_data=f"{REFERRAL_DELETE_PREFIX}{link.id}")
    builder.button(text="Back", callback_data=REFERRAL_REFRESH)
    builder.adjust(1)
    return builder.as_markup()


def referral_delete_confirm_keyboard(link_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Yes, remove", callback_data=f"{REFERRAL_CONFIRM_DELETE_PREFIX}{link_id}")
    builder.button(text="Cancel", callback_data=f"{REFERRAL_LINK_PREFIX}{link_id}")
    builder.adjust(1)
    return builder.as_markup()
