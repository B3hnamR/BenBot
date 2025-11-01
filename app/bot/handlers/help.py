from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.help import HelpCallback, help_categories_keyboard, help_items_keyboard
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.infrastructure.db.repositories import UserRepository
from app.core.config import get_settings

router = Router(name="help")

ADMIN_HELP_CONTENT = {
    "coupons": {
        "title": "Coupons",
        "items": {
            "overview": (
                "Overview",
                "The Coupons dashboard (Admin → Coupons) lists recent codes, their status, and quick actions to activate, deactivate, or delete.",
            ),
            "editing": (
                "Editing fields",
                "Use Edit fields to change name, description, type, amount/percentage, minimum order, caps, usage limits, and validity window without leaving the current message.",
            ),
            "usage": (
                "Usage analytics",
                "Usage stats shows the total redemptions, unique customers, and the most recent uses so you can diagnose failed or exhausted coupons.",
            ),
        },
    },
    "loyalty": {
        "title": "Loyalty",
        "items": {
            "settings": (
                "Configuration",
                "Admin → Loyalty lets you switch the program on/off, adjust earn rate, redeem ratio, minimum redeem points, and toggles for auto-earn/prompt.",
            ),
            "reservation": (
                "Reservations",
                "When a customer redeems points the balance is reserved. If the order fails or is cancelled, the reservation automatically rolls back so balances stay accurate.",
            ),
        },
    },
    "referrals": {
        "title": "Referrals",
        "items": {
            "settings": (
                "Program settings",
                "In Admin → Referrals you can enable the program, choose default reward type (bonus points or commission), configure default reward value, auto-reward, and approved reseller IDs.",
            ),
            "links": (
                "Managing links",
                "The Links view shows recent partner links. You can inspect statistics, tweak reward values, or delete links. Pending commissions can be reviewed and marked as paid.",
            ),
            "workflow": (
                "Order workflow",
                "When an order is paid the referral metadata is attached automatically. Bonus rewards are applied instantly; commission rewards stay pending until you mark them paid from the admin panel.",
            ),
        },
    },
}


@router.message(Command("help"))
async def handle_help_command(message: Message, session: AsyncSession, user_profile) -> None:
    if not _user_is_owner(message.from_user.id):
        await message.answer("Help is available to administrators only.")
        return
    await _render_help_menu(message, session, user_profile)


@router.callback_query(F.data == MainMenuCallback.HELP.value)
async def handle_help_menu(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    if not _user_is_owner(callback.from_user.id):
        await callback.answer("Help is available to administrators only.", show_alert=True)
        return
    await _render_help_menu(callback.message, session, user_profile)
    await callback.answer()


@router.callback_query(F.data == HelpCallback.MAIN_MENU.value)
async def handle_help_main(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    if not _user_is_owner(callback.from_user.id):
        await callback.answer("Help is available to administrators only.", show_alert=True)
        return
    await _render_help_menu(callback.message, session, user_profile)
    await callback.answer()


@router.callback_query(F.data == HelpCallback.BACK_TO_MENU.value)
async def handle_help_back_to_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Main menu",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{HelpCallback.CATEGORY.value}:"))
async def handle_help_category(callback: CallbackQuery) -> None:
    if not _user_is_owner(callback.from_user.id):
        await callback.answer("Help is available to administrators only.", show_alert=True)
        return
    cat_id = callback.data.split(":", 1)[1]
    content = ADMIN_HELP_CONTENT.get(cat_id)
    if content is None:
        await callback.answer("Unknown section.", show_alert=True)
        return
    items = [(item_id, title) for item_id, (title, _) in content["items"].items()]
    text = f"<b>{content['title']}</b>\nSelect a topic to view its description."
    await callback.message.edit_text(
        text,
        reply_markup=help_items_keyboard(cat_id, items),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{HelpCallback.ITEM.value}:"))
async def handle_help_item(callback: CallbackQuery) -> None:
    if not _user_is_owner(callback.from_user.id):
        await callback.answer("Help is available to administrators only.", show_alert=True)
        return
    _, cat_id, item_id = callback.data.split(":", 2)
    content = ADMIN_HELP_CONTENT.get(cat_id)
    if content is None:
        await callback.answer("Unknown section.", show_alert=True)
        return
    item = content["items"].get(item_id)
    if item is None:
        await callback.answer("Unknown topic.", show_alert=True)
        return
    title, description = item
    builder = InlineKeyboardBuilder()
    builder.button(text="Back", callback_data=f"{HelpCallback.CATEGORY.value}:{cat_id}")
    await callback.message.edit_text(
        f"<b>{title}</b>\n{description}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


async def _render_help_menu(target, session: AsyncSession, user_profile) -> None:
    profile = user_profile
    if profile is None or getattr(profile, "telegram_id", None) is None:
        telegram_id = None
        if hasattr(target, "from_user") and getattr(target.from_user, "id", None) is not None:
            telegram_id = target.from_user.id
        elif hasattr(target, "chat") and getattr(target.chat, "id", None) is not None:
            telegram_id = target.chat.id
        if telegram_id is not None:
            repo = UserRepository(session)
            profile = await repo.get_by_telegram_id(telegram_id)
    is_owner = _user_is_owner(getattr(profile, "telegram_id", None))
    if not is_owner:
        if hasattr(target, "answer"):
            await target.answer("Help is available to administrators only.")
        return
    categories = [(cat_id, block["title"]) for cat_id, block in ADMIN_HELP_CONTENT.items()]
    text = "<b>Help center</b>\nSelect a section to learn how to manage it."
    keyboard = help_categories_keyboard(categories)
    await _edit_or_send(target, text, keyboard, parse_mode="HTML")


async def _edit_or_send(target, text: str, keyboard, *, parse_mode: Optional[str] = None) -> None:
    if hasattr(target, "edit_text"):
        try:
            await target.edit_text(text, reply_markup=keyboard, parse_mode=parse_mode)
            return
        except Exception:  # noqa: BLE001
            pass
    await target.answer(text, reply_markup=keyboard, parse_mode=parse_mode)


def _user_is_owner(user_id: int | None) -> bool:
    if user_id is None:
        return False
    settings = get_settings()
    return user_id in settings.owner_user_ids
