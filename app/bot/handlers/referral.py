from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import MainMenuCallback
from app.bot.keyboards.referral import (
    REFERRAL_CONFIRM_DELETE_PREFIX,
    REFERRAL_CREATE,
    REFERRAL_DELETE_PREFIX,
    REFERRAL_EDIT_LABEL_PREFIX,
    REFERRAL_EDIT_REWARD_PREFIX,
    REFERRAL_LINK_PREFIX,
    REFERRAL_REFRESH,
    REFERRAL_REWARDS_PREFIX,
    REFERRAL_SHARE_PREFIX,
    referral_dashboard_keyboard,
    referral_delete_confirm_keyboard,
    referral_link_keyboard,
)
from app.bot.states.referral import ReferralState
from app.infrastructure.db.models import ReferralLink
from app.services.config_service import ConfigService
from app.services.referral_service import ReferralService
from app.core.enums import ReferralRewardType

router = Router(name="referral")


@router.message(Command("referral"))
async def handle_referral_command(message: Message, session: AsyncSession, user_profile) -> None:
    await _render_dashboard(message, session, user_profile)


@router.callback_query(F.data == MainMenuCallback.REFERRAL.value)
async def handle_referral_menu(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    await _render_dashboard(callback.message, session, user_profile)
    await callback.answer()


@router.callback_query(F.data == REFERRAL_REFRESH)
async def handle_referral_refresh(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    await _render_dashboard(callback.message, session, user_profile)
    await callback.answer()


@router.callback_query(F.data == REFERRAL_CREATE)
async def handle_referral_create(callback: CallbackQuery, session: AsyncSession, state: FSMContext, user_profile) -> None:
    settings = await ConfigService(session).get_referral_settings()
    if not settings.enabled:
        await callback.answer("Referral program is currently disabled.", show_alert=True)
        return
    if not settings.allow_public_links and user_profile.telegram_id not in settings.reseller_user_ids:
        await callback.answer("Referral links are restricted to approved partners.", show_alert=True)
        return
    await state.clear()
    await state.update_data(referral_settings=settings)
    await state.set_state(ReferralState.create_label)
    await callback.message.answer("Enter a label for this referral link (optional). Send /skip to leave blank or /cancel." )
    await callback.answer()


@router.message(ReferralState.create_label)
async def process_referral_label(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Referral creation cancelled.")
        return
    label = None if text.lower() == "/skip" else text
    await state.update_data(ref_label=label)
    data = await state.get_data()
    settings = data.get("referral_settings")
    if settings is None:
        await state.clear()
        await message.answer("Referral settings unavailable. Please try again.")
        return
    allowed_types = _allowed_reward_types(settings, message.from_user.id)
    if len(allowed_types) == 1:
        await state.update_data(ref_type=allowed_types[0])
        await state.set_state(ReferralState.create_reward_value)
        await _prompt_reward_value(message, allowed_types[0], settings)
        return
    await state.set_state(ReferralState.create_reward_type)
    builder = InlineKeyboardBuilder()
    for reward_type in allowed_types:
        builder.button(
            text=_format_reward_type_label(reward_type),
            callback_data=f"user:ref:choose_type:{reward_type.value}",
        )
    builder.adjust(1)
    await message.answer("Select the reward type for this link:", reply_markup=builder.as_markup())


@router.callback_query(ReferralState.create_reward_type, F.data.startswith("user:ref:choose_type:"))
async def process_referral_type(callback: CallbackQuery, state: FSMContext) -> None:
    reward_value = callback.data.removeprefix("user:ref:choose_type:")
    try:
        reward_type = ReferralRewardType(reward_value)
    except ValueError:
        await callback.answer("Unsupported reward type.", show_alert=True)
        return
    await state.update_data(ref_type=reward_type)
    await state.set_state(ReferralState.create_reward_value)
    data = await state.get_data()
    settings = data.get("referral_settings")
    await _prompt_reward_value(callback.message, reward_type, settings)
    await callback.answer()


@router.message(ReferralState.create_reward_value)
async def process_referral_reward_value(message: Message, session: AsyncSession, state: FSMContext, user_profile) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Referral creation cancelled.")
        return

    data = await state.get_data()
    reward_type: ReferralRewardType = data.get("ref_type")
    settings = data.get("referral_settings")
    if reward_type is None or settings is None:
        await state.clear()
        await message.answer("Referral settings unavailable. Please try again.")
        return

    default_value = Decimal(str(settings.default_reward_value))
    if text.lower() in {"/skip", "skip", ""}:
        value = default_value
    else:
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            await message.answer("Enter a valid number or /skip to use the default value.")
            return
        if reward_type == ReferralRewardType.COMMISSION and value <= 0:
            await message.answer("Commission percentage must be greater than zero.")
            return
        if reward_type == ReferralRewardType.COMMISSION and value > 100:
            await message.answer("Commission percentage cannot exceed 100%.")
            return
        if reward_type == ReferralRewardType.BONUS and value <= 0:
            await message.answer("Bonus points must be greater than zero.")
            return
    label = data.get("ref_label")
    referral_service = ReferralService(session)
    link = await referral_service.create_link(
        owner_user_id=user_profile.id,
        reward_type=reward_type,
        reward_value=value,
        label=label,
    )
    await state.clear()
    await message.answer("Referral link created successfully.")
    await _render_link_details(message, session, user_profile, link, notice=None)


@router.callback_query(F.data.startswith(REFERRAL_LINK_PREFIX))
async def handle_referral_link_view(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    link_id = _extract_int(callback.data, REFERRAL_LINK_PREFIX)
    if link_id is None:
        await callback.answer("Invalid link.", show_alert=True)
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None or link.owner_user_id != user_profile.id:
        await callback.answer("Link not found.", show_alert=True)
        return
    await _render_link_details(callback.message, session, user_profile, link)
    await callback.answer()


@router.callback_query(F.data.startswith(REFERRAL_DELETE_PREFIX))
async def handle_referral_delete_request(callback: CallbackQuery) -> None:
    link_id = _extract_int(callback.data, REFERRAL_DELETE_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        "Are you sure you want to delete this referral link?",
        reply_markup=referral_delete_confirm_keyboard(link_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(REFERRAL_CONFIRM_DELETE_PREFIX))
async def handle_referral_delete_confirm(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    link_id = _extract_int(callback.data, REFERRAL_CONFIRM_DELETE_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None or link.owner_user_id != user_profile.id:
        await callback.answer("Link not found.", show_alert=True)
        return
    await referral_service.delete_link(link)
    await _render_dashboard(callback.message, session, user_profile, notice="Referral link deleted.")
    await callback.answer("Link removed.")


@router.callback_query(F.data.startswith(REFERRAL_SHARE_PREFIX))
async def handle_referral_share(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    link_id = _extract_int(callback.data, REFERRAL_SHARE_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None or link.owner_user_id != user_profile.id:
        await callback.answer("Link not found.", show_alert=True)
        return
    bot_user = await callback.bot.get_me()
    share_link = f"https://t.me/{bot_user.username}?start=ref-{link.code}"
    await callback.message.answer(
        "Share this link with your contacts:\n" f"<code>{share_link}</code>",
        parse_mode="HTML",
    )
    await callback.answer("Share link generated.")


@router.callback_query(F.data.startswith(REFERRAL_REWARDS_PREFIX))
async def handle_referral_rewards(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    link_id = _extract_int(callback.data, REFERRAL_REWARDS_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None or link.owner_user_id != user_profile.id:
        await callback.answer("Link not found.", show_alert=True)
        return
    rewards = await referral_service.list_rewards_for_link(link_id, limit=15)
    if rewards:
        lines = ["<b>Recent rewards</b>"]
        for reward in rewards:
            status = "paid" if reward.rewarded_at else "pending"
            value = reward.reward_value
            label = reward.meta.get("order_public_id") if reward.meta else None
            if label:
                lines.append(f"{status.title()} · {value} ({label})")
            else:
                lines.append(f"{status.title()} · {value}")
    else:
        lines = ["No rewards recorded yet."]
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith(REFERRAL_EDIT_LABEL_PREFIX))
async def handle_referral_edit_label(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user_profile) -> None:
    link_id = _extract_int(callback.data, REFERRAL_EDIT_LABEL_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None or link.owner_user_id != user_profile.id:
        await callback.answer("Link not found.", show_alert=True)
        return
    await state.set_state(ReferralState.edit_label)
    await state.update_data(edit_link_id=link_id)
    await callback.message.answer(
        "Send the new label for this link. Send /clear to remove the label or /cancel to abort."
    )
    await callback.answer()


@router.message(ReferralState.edit_label)
async def process_referral_edit_label(message: Message, session: AsyncSession, state: FSMContext, user_profile) -> None:
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
    if link is None or link.owner_user_id != user_profile.id:
        await state.clear()
        await message.answer("Link not found.")
        return
    label = None if text.lower() == "/clear" else text
    await referral_service.update_link(link, label=label)
    await state.clear()
    await message.answer("Label updated.")
    await _render_link_details(message, session, user_profile, link)


@router.callback_query(F.data.startswith(REFERRAL_EDIT_REWARD_PREFIX))
async def handle_referral_edit_reward(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user_profile) -> None:
    link_id = _extract_int(callback.data, REFERRAL_EDIT_REWARD_PREFIX)
    if link_id is None:
        await callback.answer()
        return
    referral_service = ReferralService(session)
    link = await referral_service.get_link_by_id(link_id)
    if link is None or link.owner_user_id != user_profile.id:
        await callback.answer("Link not found.", show_alert=True)
        return
    await state.set_state(ReferralState.edit_reward_value)
    await state.update_data(edit_link_id=link_id)
    if link.reward_type == ReferralRewardType.BONUS:
        prompt = "Send the new bonus points value (number greater than zero)."
    else:
        prompt = "Send the new commission percentage (0-100)."
    await callback.message.answer(f"{prompt}\nSend /cancel to abort.")
    await callback.answer()


@router.message(ReferralState.edit_reward_value)
async def process_referral_edit_reward(message: Message, session: AsyncSession, state: FSMContext, user_profile) -> None:
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
    if link is None or link.owner_user_id != user_profile.id:
        await state.clear()
        await message.answer("Link not found.")
        return
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        await message.answer("Enter a valid number.")
        return
    if link.reward_type == ReferralRewardType.BONUS and value <= 0:
        await message.answer("Bonus points must be greater than zero.")
        return
    if link.reward_type == ReferralRewardType.COMMISSION and (value <= 0 or value > 100):
        await message.answer("Commission percentage must be between 0 and 100.")
        return
    await referral_service.update_link(link, reward_value=value)
    await state.clear()
    await message.answer("Reward value updated.")
    await _render_link_details(message, session, user_profile, link)


def _allowed_reward_types(settings, telegram_id: int | None) -> list[ReferralRewardType]:
    types = [ReferralRewardType.BONUS]
    if telegram_id in settings.reseller_user_ids:
        types.append(ReferralRewardType.COMMISSION)
    return types


def _format_reward_type_label(reward_type: ReferralRewardType) -> str:
    if reward_type == ReferralRewardType.BONUS:
        return "Bonus (loyalty points)"
    return "Commission (%)"


async def _prompt_reward_value(message: Message, reward_type: ReferralRewardType, settings) -> None:
    if reward_type == ReferralRewardType.BONUS:
        message_text = (
            "Send the number of loyalty points awarded per referred order.\n"
            "Send /skip to use the default value."
        )
    else:
        message_text = (
            "Send the commission percentage (0-100) applied to completed orders.\n"
            "Send /skip to use the default value."
        )
    await message.answer(message_text)


async def _render_dashboard(target, session: AsyncSession, user_profile, notice: str | None = None) -> None:
    settings = await ConfigService(session).get_referral_settings()
    if not settings.enabled:
        builder = InlineKeyboardBuilder()
        builder.button(text="Back", callback_data=MainMenuCallback.PROFILE.value)
        text = "Referral program is currently disabled."
        await _edit_or_send(target, text, builder.as_markup())
        return

    referral_service = ReferralService(session)
    links = await referral_service.list_links_for_owner(user_profile.id, limit=10)
    total_clicks = sum(link.total_clicks for link in links)
    total_signups = sum(link.total_signups for link in links)
    total_orders = sum(link.total_orders for link in links)

    lines = ["<b>Your referral dashboard</b>"]
    lines.append(f"Links created: {len(links)}")
    lines.append(f"Total clicks: {total_clicks}")
    lines.append(f"Sign-ups: {total_signups}")
    lines.append(f"Orders: {total_orders}")
    if notice:
        lines.append("")
        lines.append(notice)

    text = "\n".join(lines)
    keyboard = referral_dashboard_keyboard(links)
    await _edit_or_send(target, text, keyboard)


async def _render_link_details(target, session: AsyncSession, user_profile, link: ReferralLink, notice: str | None = None) -> None:
    if link.meta and "label" in link.meta:
        title = link.meta["label"]
    else:
        title = f"Link {link.code}"
    lines = [f"<b>{title}</b>"]
    lines.append(f"Code: <code>{link.code}</code>")
    lines.append(f"Reward type: {link.reward_type.value}")
    lines.append(f"Reward value: {link.reward_value}")
    lines.append(f"Clicks: {link.total_clicks}")
    lines.append(f"Sign-ups: {link.total_signups}")
    lines.append(f"Orders: {link.total_orders}")
    if notice:
        lines.append("")
        lines.append(notice)
    keyboard = referral_link_keyboard(link)
    await _edit_or_send(target, "\n".join(lines), keyboard, parse_mode="HTML")


async def _edit_or_send(target, text: str, keyboard, *, parse_mode: Optional[str] = None) -> None:
    if hasattr(target, "edit_text"):
        try:
            await target.edit_text(text, reply_markup=keyboard, parse_mode=parse_mode)
            return
        except Exception:
            pass
    await target.answer(text, reply_markup=keyboard, parse_mode=parse_mode)


def _extract_int(payload: str, prefix: str) -> Optional[int]:
    raw = payload.removeprefix(prefix)
    try:
        return int(raw)
    except ValueError:
        return None
