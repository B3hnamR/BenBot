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
            "dashboard": (
                "Dashboard overview",
                "Admin → Coupons lists the 10 most recent codes with their status (Active, Inactive, Expired). Buttons on this screen: • Create coupon opens the guided wizard. • Tapping a coupon row opens its detail view. • Refresh list reloads the snapshot. • Back returns to the admin menu.",
            ),
            "create_flow": (
                "Create coupon wizard",
                "After pressing Create coupon the bot asks for: code → optional name → type (fixed, percent, shipping) → value → optional minimum order → optional total redemption limit → optional per-user limit. Every step supports /skip (where allowed) and /cancel. When finished the coupon is immediately active and appears in the list.",
            ),
            "detail_buttons": (
                "Detail view actions",
                "Inside a coupon detail you see code, status, value, limits, schedule, usage counts, and the following actions: • Deactivate/Activate toggles availability. • Auto-apply toggles whether the coupon is applied automatically during checkout if conditions match. • Edit fields opens the field selector (name, description, type, value, min order, max discount, limits, start/end date). • Usage stats shows aggregate usage and recent redemptions. • Delete coupon removes the code and all redemption history (confirmation required).",
            ),
            "edit_fields": (
                "Edit fields menu",
                "When Edit fields is chosen you get buttons for each attribute. Selecting one prompts for a new value. /clear removes optional fields, /cancel backs out. Type changes immediately request a new value to keep the coupon consistent.",
            ),
            "usage_stats": (
                "Usage analytics",
                "Usage stats displays total redemptions, unique customers, remaining quota, and a list of the latest redemptions including order references. Use Refresh usage to update the numbers after new orders.",
            ),
        },
    },
    "loyalty": {
        "title": "Loyalty",
        "items": {
            "main_settings": (
                "Main settings screen",
                "Admin → Loyalty shows current earn ratio, redeem ratio, minimum redeem points, and toggle states. Buttons: • Enable/Disable program • Auto-earn toggle (award points on paid orders) • Prompt toggle (ask customers to redeem during checkout) • Set earn rate • Set redeem ratio • Set minimum redeem. Each input expects a numeric value and accepts /cancel.",
            ),
            "earn_flow": (
                "Earning points",
                "When Auto-earn is ON every paid order multiplies the total by the earn rate and credits the customer. Rewards are recorded in loyalty transactions and reflected in the profile screen.",
            ),
            "redeem_flow": (
                "Redeeming during checkout",
                "If auto prompt is enabled and a customer has enough points, checkout shows instructions: they can type a number or 'max'. The bot reserves the points, subtracts the discount from the order, and annotates the order summary. If the order is cancelled or expires the reservation is released automatically.",
            ),
            "manual_adjustments": (
                "Manual adjustments",
                "Administrators can trigger refunds or adjustments from order detail flows (e.g., Admin → Orders). Loyalty transactions record status changes (reserved, applied, refunded) so you can audit history.",
            ),
        },
    },
    "referrals": {
        "title": "Referrals",
        "items": {
            "program_settings": (
                "Program settings",
                "Admin → Referrals dashboard summarises clicks/sign-ups/orders plus key toggles: • Program ON/OFF • Auto reward (immediate bonus credit) • Public links (allow all users to create links) • Default reward type/value • Manage reseller IDs. Each toggle updates instantly and the summary refreshes in place.",
            ),
            "links_view": (
                "Links view",
                "Selecting Recent links lists partner links with stats. Clicking a link shows: owner ID, code, clicks, sign-ups, orders, and actions: View rewards (list payouts), Adjust reward (change current value), Delete link. Deleting asks for confirmation before removing the link and history.",
            ),
            "pending_commissions": (
                "Pending commissions",
                "The Pending commissions page lists commission rewards (reward type = commission) that are waiting for manual payout. Each entry shows link code, order reference, and amount with a Mark paid button. Once marked paid the reward gains a timestamp and disappears from the pending list.",
            ),
            "user_portal": (
                "User referral center",
                "When the program is enabled, users can open Referral center from the main menu to create links (if allowed), copy share URLs, review click/sign-up/order totals, and see reward history. Bonus rewards are credited instantly; commissions stay pending until you confirm them from the admin panel.",
            ),
            "workflow": (
                "Order workflow",
                "If a customer arrives via a referral link, the system records the click, enrollment, and attaches metadata to every order they place. Paid orders apply the configured reward automatically; cancelled or expired orders flag the referral as cancelled so rewards are not double-counted.",
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
    prefix = f"{HelpCallback.CATEGORY.value}:"
    cat_id = callback.data[len(prefix):]
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
    prefix = f"{HelpCallback.ITEM.value}:"
    payload = callback.data[len(prefix):]
    try:
        cat_id, item_id = payload.split(":", 1)
    except ValueError:
        await callback.answer("Unknown topic.", show_alert=True)
        return
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
