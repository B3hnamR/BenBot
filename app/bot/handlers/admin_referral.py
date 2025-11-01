from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import AdminMenuCallback
from app.bot.keyboards.admin_referral import (
    ADMIN_REFERRAL_DELETE_PREFIX,
    ADMIN_REFERRAL_EDIT_REWARD_PREFIX,
    ADMIN_REFERRAL_LINK_PREFIX,
    ADMIN_REFERRAL_LINKS,
    ADMIN_REFERRAL_MARK_PAID_PREFIX,
    ADMIN_REFERRAL_PENDING,
    ADMIN_REFERRAL_SETTINGS,
    ADMIN_REFERRAL_VIEW_REWARDS_PREFIX,
    referral_admin_dashboard_keyboard,
    referral_admin_link_keyboard,
    referral_admin_links_keyboard,
    referral_admin_rewards_keyboard,
    referral_admin_settings_keyboard,
)
from app.bot.states.admin_referral import AdminReferralState
from app.core.enums import ReferralRewardType
from app.infrastructure.db.models import ReferralLink, ReferralReward
from app.services.config_service import ConfigService
from app.services.referral_service import ReferralService

router = Router(name="admin_referral")


@router.callback_query(F.data == AdminMenuCallback.MANAGE_REFERRALS.value)
async def handle_manage_referrals(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    settings = await config_service.get_referral_settings()
    referral_service = ReferralService(session)
    links = await referral_service.list_recent_links(limit=25)
    pending = await referral_service.list_pending_commission_rewards(limit=25)

    total_links = len(links)
    total_clicks = sum(link.total_clicks for link in links)
    total_signups = sum(link.total_signups for link in links)
    total_orders = sum(link.total_orders for link in links)

    lines = ["<b>Referral overview</b>"]
    lines.append(f"Program: {'ENABLED' if settings.enabled else 'DISABLED'}")
    lines.append(f"Auto reward: {'ON' if settings.auto_reward else 'OFF'}")
    lines.append(f"Public links: {'ON' if settings.allow_public_links else 'OFF'}")
    lines.append(f"Default reward: {settings.default_reward_type.value} · {settings.default_reward_value}")
    lines.append(f"Partners: {len(settings.reseller_user_ids)}")
    lines.append("")
    lines.append(f"Recent links tracked: {total_links}")
    lines.append(f"Clicks: {total_clicks} · Sign-ups: {total_signups} · Orders: {total_orders}")
    lines.append(f"Pending commissions: {len(pending)}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=referral_admin_dashboard_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == ADMIN_REFERRAL_SETTINGS)
async def handle_referral_settings(callback: CallbackQuery, session: AsyncSession, *, auto_answer: bool = True) -> None:
    settings = await ConfigService(session).get_referral_settings()
    lines = ["<b>Referral settings</b>"]
    lines.append(f"Program enabled: {'Yes' if settings.enabled else 'No'}")
    lines.append(f"Auto reward on paid: {'Yes' if settings.auto_reward else 'No'}")
    lines.append(f"Public links allowed: {'Yes' if settings.allow_public_links else 'No'}")
    lines.append(f"Default reward type: {settings.default_reward_type.value}")
    lines.append(f"Default reward value: {settings.default_reward_value}")
    reseller_ids = ", ".join(str(item) for item in settings.reseller_user_ids) or "(none)"
    lines.append(f"Reseller user IDs: {reseller_ids}")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=referral_admin_settings_keyboard(settings),
        parse_mode="HTML",
    )
    if auto_answer:
        await callback.answer()


@router.callback_query(F.data == "admin:ref:toggle_enabled")
async def handle_toggle_enabled(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    settings = await config_service.get_referral_settings()
    settings.enabled = not settings.enabled
    updated = await config_service.save_referral_settings(settings)
    await handle_referral_settings(callback, session, auto_answer=False)
    await callback.answer(f"Program {'enabled' if updated.enabled else 'disabled'}.")


@router.callback_query(F.data == "admin:ref:toggle_auto_reward")
async def handle_toggle_auto_reward(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    settings = await config_service.get_referral_settings()
    settings.auto_reward = not settings.auto_reward
    updated = await config_service.save_referral_settings(settings)
    await handle_referral_settings(callback, session, auto_answer=False)
    await callback.answer(f"Auto reward {'enabled' if updated.auto_reward else 'disabled'}.")


@router.callback_query(F.data == "admin:ref:toggle_public")
async def handle_toggle_public(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    settings = await config_service.get_referral_settings()
    settings.allow_public_links = not settings.allow_public_links
    updated = await config_service.save_referral_settings(settings)
    await handle_referral_settings(callback, session, auto_answer=False)
    await callback.answer(f"Public links {'enabled' if updated.allow_public_links else 'disabled'}.")


@router.callback_query(F.data == "admin:ref:toggle_default_type")
async def handle_toggle_default_type(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    settings = await config_service.get_referral_settings()
    settings.default_reward_type = (
        ReferralRewardType.COMMISSION
        if settings.default_reward_type == ReferralRewardType.BONUS
        else ReferralRewardType.BONUS
    )
    await config_service.save_referral_settings(settings)
    await handle_referral_settings(callback, session, auto_answer=False)
    await callback.answer("Default reward type updated.")


@router.callback_query(F.data == "admin:ref:edit_default_value")
async def handle_edit_default_value(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminReferralState.edit_default_value)
    await callback.message.answer(
        "Send the new default reward value. For bonus mode this is loyalty points.\n"
        "For commission it is the percentage (0-100). Send /cancel to abort."
    )
    await callback.answer()


@router.message(AdminReferralState.edit_default_value)
async def process_edit_default_value(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Update cancelled.")
        return
    config_service = ConfigService(session)
    settings = await config_service.get_referral_settings()
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        await message.answer("Enter a valid number.")
        return
    if settings.default_reward_type == ReferralRewardType.BONUS and value <= 0:
        await message.answer("Value must be greater than zero.")
        return
    if settings.default_reward_type == ReferralRewardType.COMMISSION and (value <= 0 or value > 100):
        await message.answer("Commission percentage must be between 0 and 100.")
        return
    settings.default_reward_value = value
    await config_service.save_referral_settings(settings)
    await state.clear()
    await message.answer("Default reward value updated.")


@router.callback_query(F.data == "admin:ref:edit_resellers")
async def handle_edit_resellers(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminReferralState.edit_reseller_ids)
    await callback.message.answer(
        "Send the reseller Telegram user IDs separated by commas. Send /clear to remove all or /cancel to abort."
    )
    await callback.answer()


@router.message(AdminReferralState.edit_reseller_ids)
async def process_edit_resellers(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Update cancelled.")
        return
    config_service = ConfigService(session)
    settings = await config_service.get_referral_settings()
    if text.lower() == "/clear":
        settings.reseller_user_ids = []
    else:
        ids: list[int] = []
        for item in text.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                ids.append(int(item))
            except ValueError:
                await message.answer(f"Invalid ID: {item}. Please send numbers.")
                return
        settings.reseller_user_ids = sorted(set(ids))
    await config_service.save_referral_settings(settings)
    await state.clear()
    await message.answer("Reseller list updated.")


@router.callback_query(F.data == ADMIN_REFERRAL_LINKS)
async def handle_admin_referral_links(callback: CallbackQuery, session: AsyncSession) -> None:
    referral_service = ReferralService(session)
    links = await referral_service.list_recent_links(limit=25)
    if not links:
        await callback.message.edit_text(
            "No referral links found.",
            reply_markup=referral_admin_links_keyboard(links),
        )
    else:
        await callback.message.edit_text(
            "Select a referral link to view details.",
            reply_markup=referral_admin_links_keyboard(links),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_REFERRAL_LINK_PREFIX))
async def handle_admin_referral_link(callback: CallbackQuery, session: AsyncSession) -> None:
    link_id = _extract_int(callback.data, ADMIN_REFERRAL_LINK_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None:
        await callback.answer("Link not found.", show_alert=True)
        return
    text = _format_admin_link_details(link)
    await callback.message.edit_text(
        text,
        reply_markup=referral_admin_link_keyboard(link),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_REFERRAL_DELETE_PREFIX))
async def handle_admin_referral_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    link_id = _extract_int(callback.data, ADMIN_REFERRAL_DELETE_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None:
        await callback.answer("Link not found.", show_alert=True)
        return
    await referral_service.delete_link(link)
    await handle_admin_referral_links(callback, session)
    await callback.answer("Link deleted.")


@router.callback_query(F.data.startswith(ADMIN_REFERRAL_EDIT_REWARD_PREFIX))
async def handle_admin_referral_edit_reward(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    link_id = _extract_int(callback.data, ADMIN_REFERRAL_EDIT_REWARD_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None:
        await callback.answer("Link not found.", show_alert=True)
        return
    await state.set_state(AdminReferralState.edit_link_reward_value)
    await state.update_data(edit_link_id=link_id)
    if link.reward_type == ReferralRewardType.BONUS:
        prompt = "Send the new bonus points value (>0)."
    else:
        prompt = "Send the new commission percentage (0-100)."
    await callback.message.answer(f"{prompt}\nSend /cancel to abort.")
    await callback.answer()


@router.message(AdminReferralState.edit_link_reward_value)
async def process_admin_referral_edit_reward(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Update cancelled.")
        return
    data = await state.get_data()
    link_id = data.get("edit_link_id")
    if link_id is None:
        await state.clear()
        await message.answer("Link context lost.")
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(int(link_id))
    if link is None:
        await state.clear()
        await message.answer("Link not found.")
        return
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        await message.answer("Enter a valid number.")
        return
    if link.reward_type == ReferralRewardType.BONUS and value <= 0:
        await message.answer("Value must be greater than zero.")
        return
    if link.reward_type == ReferralRewardType.COMMISSION and (value <= 0 or value > 100):
        await message.answer("Commission percentage must be between 0 and 100.")
        return
    await referral_service.update_link(link, reward_value=value)
    await state.clear()
    await message.answer("Reward value updated.")


@router.callback_query(F.data.startswith(ADMIN_REFERRAL_VIEW_REWARDS_PREFIX))
async def handle_admin_referral_rewards(callback: CallbackQuery, session: AsyncSession) -> None:
    link_id = _extract_int(callback.data, ADMIN_REFERRAL_VIEW_REWARDS_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None:
        await callback.answer("Link not found.", show_alert=True)
        return
    rewards = await referral_service.list_rewards_for_link(link_id, limit=20)
    lines = ["<b>Rewards</b>"]
    if rewards:
        for reward in rewards:
            status = "Paid" if reward.rewarded_at else "Pending"
            value = reward.reward_value
            order_label = reward.meta.get("order_public_id") if reward.meta else None
            if order_label:
                lines.append(f"#{reward.id} · {status} · {value} ({order_label})")
            else:
                lines.append(f"#{reward.id} · {status} · {value}")
    else:
        lines.append("No rewards recorded.")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=referral_admin_rewards_keyboard(rewards),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_REFERRAL_MARK_PAID_PREFIX))
async def handle_admin_mark_paid(callback: CallbackQuery, session: AsyncSession) -> None:
    reward_id = _extract_int(callback.data, ADMIN_REFERRAL_MARK_PAID_PREFIX)
    if reward_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    reward = await referral_service.get_reward_by_id(reward_id)
    if reward is None:
        await callback.answer("Reward not found.", show_alert=True)
        return
    await referral_service.mark_reward_paid(reward)
    await handle_admin_pending(callback, session, auto_answer=False)
    await callback.answer("Commission marked as paid.")


@router.callback_query(F.data == ADMIN_REFERRAL_PENDING)
async def handle_admin_pending(callback: CallbackQuery, session: AsyncSession, *, auto_answer: bool = True) -> None:
    referral_service = ReferralService(session)
    rewards = await referral_service.list_pending_commission_rewards(limit=25)
    if rewards:
        lines = ["<b>Pending commissions</b>"]
        for reward in rewards:
            amount = reward.reward_value
            link = reward.link
            order_label = reward.meta.get("order_public_id") if reward.meta else None
            descriptor = f"Link {link.code}" if link else "Unknown link"
            if order_label:
                lines.append(f"#{reward.id} · {amount} · {descriptor} · {order_label}")
            else:
                lines.append(f"#{reward.id} · {amount} · {descriptor}")
    else:
        lines = ["No pending commissions."]
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=referral_admin_rewards_keyboard(rewards if rewards else []),
        parse_mode="HTML",
    )
    if auto_answer:
        await callback.answer()


def _format_admin_link_details(link: ReferralLink) -> str:
    owner = link.owner_user_id
    label = (link.meta or {}).get("label") if link.meta else None
    lines = ["<b>Referral link details</b>"]
    lines.append(f"Owner user ID: {owner}")
    if label:
        lines.append(f"Label: {label}")
    lines.append(f"Code: <code>{link.code}</code>")
    lines.append(f"Reward type: {link.reward_type.value}")
    lines.append(f"Reward value: {link.reward_value}")
    lines.append(f"Clicks: {link.total_clicks}")
    lines.append(f"Sign-ups: {link.total_signups}")
    lines.append(f"Orders: {link.total_orders}")
    return "\n".join(lines)


def _extract_int(payload: str, prefix: str) -> Optional[int]:
    raw = payload.removeprefix(prefix)
    try:
        return int(raw)
    except ValueError:
        return None
