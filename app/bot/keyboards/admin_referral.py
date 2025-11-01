from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.admin import AdminMenuCallback
from app.core.enums import ReferralRewardType
from app.infrastructure.db.models import ReferralLink, ReferralReward

ADMIN_REFERRAL_SETTINGS = "admin:ref:settings"
ADMIN_REFERRAL_LINKS = "admin:ref:links"
ADMIN_REFERRAL_PENDING = "admin:ref:pending"
ADMIN_REFERRAL_LINK_PREFIX = "admin:ref:link:"
ADMIN_REFERRAL_DELETE_PREFIX = "admin:ref:delete:"
ADMIN_REFERRAL_EDIT_REWARD_PREFIX = "admin:ref:edit_reward:"
ADMIN_REFERRAL_MARK_PAID_PREFIX = "admin:ref:mark_paid:"
ADMIN_REFERRAL_VIEW_REWARDS_PREFIX = "admin:ref:rewards:"


def referral_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Referral settings", callback_data=ADMIN_REFERRAL_SETTINGS)
    builder.button(text="Recent links", callback_data=ADMIN_REFERRAL_LINKS)
    builder.button(text="Pending commissions", callback_data=ADMIN_REFERRAL_PENDING)
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def referral_admin_settings_keyboard(settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Program: {'ON' if settings.enabled else 'OFF'}",
        callback_data="admin:ref:toggle_enabled",
    )
    builder.button(
        text=f"Default reward type: {settings.default_reward_type.value}",
        callback_data="admin:ref:toggle_default_type",
    )
    builder.button(
        text=f"Auto reward: {'ON' if settings.auto_reward else 'OFF'}",
        callback_data="admin:ref:toggle_auto_reward",
    )
    builder.button(
        text=f"Public links: {'ON' if settings.allow_public_links else 'OFF'}",
        callback_data="admin:ref:toggle_public",
    )
    builder.button(text="Change default reward", callback_data="admin:ref:edit_default_value")
    builder.button(text="Manage resellers", callback_data="admin:ref:edit_resellers")
    builder.button(text="Back", callback_data=AdminMenuCallback.MANAGE_REFERRALS.value)
    builder.adjust(1)
    return builder.as_markup()


def referral_admin_links_keyboard(links: Sequence[ReferralLink]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for link in links:
        label = (link.meta or {}).get("label") if link.meta else None
        title = f"{label} ({link.code})" if label else f"{link.code}" 
        builder.button(text=title, callback_data=f"{ADMIN_REFERRAL_LINK_PREFIX}{link.id}")
    builder.button(text="Refresh", callback_data=ADMIN_REFERRAL_LINKS)
    builder.button(text="Back", callback_data=AdminMenuCallback.MANAGE_REFERRALS.value)
    builder.adjust(1)
    return builder.as_markup()


def referral_admin_link_keyboard(link: ReferralLink) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="View rewards", callback_data=f"{ADMIN_REFERRAL_VIEW_REWARDS_PREFIX}{link.id}")
    builder.button(text="Adjust reward", callback_data=f"{ADMIN_REFERRAL_EDIT_REWARD_PREFIX}{link.id}")
    builder.button(text="Delete link", callback_data=f"{ADMIN_REFERRAL_DELETE_PREFIX}{link.id}")
    builder.button(text="Back", callback_data=ADMIN_REFERRAL_LINKS)
    builder.adjust(1)
    return builder.as_markup()


def referral_admin_rewards_keyboard(rewards: Sequence[ReferralReward]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for reward in rewards:
        if reward.rewarded_at or reward.reward_type != ReferralRewardType.COMMISSION:
            continue
        builder.button(
            text=f"Mark paid #{reward.id}",
            callback_data=f"{ADMIN_REFERRAL_MARK_PAID_PREFIX}{reward.id}",
        )
    builder.button(text="Back", callback_data=ADMIN_REFERRAL_LINKS)
    builder.adjust(1)
    return builder.as_markup()
