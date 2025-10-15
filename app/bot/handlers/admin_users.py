from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import AdminMenuCallback
from app.bot.keyboards.admin_users import (
    ADMIN_USER_BACK,
    ADMIN_USER_EDIT_NOTES_PREFIX,
    ADMIN_USER_SEARCH,
    ADMIN_USER_TOGGLE_BLOCK_PREFIX,
    ADMIN_USER_VIEW_ORDERS_PREFIX,
    ADMIN_USER_VIEW_PREFIX,
    user_detail_keyboard,
    user_orders_keyboard,
    users_overview_keyboard,
)
from app.bot.states.admin_users import AdminUserState
from app.infrastructure.db.models import Order, UserProfile
from app.infrastructure.db.repositories import OrderRepository, UserRepository

router = Router(name="admin_users")


@router.callback_query(F.data == AdminMenuCallback.MANAGE_USERS.value)
async def handle_manage_users(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_users_overview(callback.message, session)
    await callback.answer()


@router.callback_query(F.data == ADMIN_USER_BACK)
async def handle_users_back(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_users_overview(callback.message, session)
    await callback.answer()


@router.callback_query(F.data == ADMIN_USER_SEARCH)
async def handle_user_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminUserState.searching)
    await state.update_data(
        list_chat_id=callback.message.chat.id,
        list_message_id=callback.message.message_id,
    )
    await callback.message.answer("Enter the Telegram user ID (numeric). Send /cancel to abort.")
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_USER_VIEW_PREFIX))
async def handle_user_view(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.removeprefix(ADMIN_USER_VIEW_PREFIX))
    user = await session.get(UserProfile, user_id)
    if user is None:
        await callback.answer("User not found.", show_alert=True)
        await _render_users_overview(callback.message, session)
        return
    await _render_user_detail(callback.message, session, user)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_USER_TOGGLE_BLOCK_PREFIX))
async def handle_user_toggle_block(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.removeprefix(ADMIN_USER_TOGGLE_BLOCK_PREFIX))
    user_repo = UserRepository(session)
    user = await session.get(UserProfile, user_id)
    if user is None:
        await callback.answer("User not found.", show_alert=True)
        await _render_users_overview(callback.message, session)
        return
    await user_repo.set_blocked(user, not user.is_blocked)
    notice = "User blocked." if user.is_blocked else "User unblocked."
    await _render_user_detail(callback.message, session, user, notice=notice)
    await callback.answer("Status updated.")


@router.callback_query(F.data.startswith(ADMIN_USER_EDIT_NOTES_PREFIX))
async def handle_user_edit_notes(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user_id = int(callback.data.removeprefix(ADMIN_USER_EDIT_NOTES_PREFIX))
    user = await session.get(UserProfile, user_id)
    if user is None:
        await callback.answer("User not found.", show_alert=True)
        await _render_users_overview(callback.message, session)
        return
    await state.set_state(AdminUserState.editing_notes)
    await state.update_data(
        user_id=user_id,
        detail_chat_id=callback.message.chat.id,
        detail_message_id=callback.message.message_id,
    )
    current = user.notes or "-"
    await callback.message.answer(
        f"Current notes: {current}\nSend new notes, or /skip to clear, /cancel to abort."
    )
    await callback.answer()


@router.message(AdminUserState.editing_notes)
async def handle_user_notes_update(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if text.lower() in {"/cancel", "cancel"}:
        await state.clear()
        await message.answer("Operation cancelled.")
        return
    clear = text.lower() in {"/skip", "skip"}
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await message.answer("State expired. Try again.")
        return

    user_repo = UserRepository(session)
    user = await session.get(UserProfile, user_id)
    if user is None:
        await state.clear()
        await message.answer("User not found.")
        return

    await user_repo.update_notes(user, None if clear else text)
    await state.clear()
    await message.answer("Notes updated.")
    detail_chat = data.get("detail_chat_id")
    detail_message = data.get("detail_message_id")
    target = (detail_chat, detail_message) if detail_chat and detail_message else None
    await _render_user_detail(message, session, user, target=target)


@router.message(AdminUserState.searching)
async def handle_user_search_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if text.lower() in {"/cancel", "cancel"}:
        await state.clear()
        await message.answer("Search cancelled.")
        return

    try:
        telegram_id = int(text)
    except ValueError:
        await message.answer("Provide a numeric Telegram user ID or /cancel.")
        return

    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(telegram_id)
    data = await state.get_data()
    list_chat = data.get("list_chat_id")
    list_message = data.get("list_message_id")
    target = (list_chat, list_message) if list_chat and list_message else None

    if user is None:
        await state.clear()
        await message.answer("User not found.")
        return

    await state.clear()
    await message.answer(f"User {telegram_id} found.")
    await _render_user_detail(message, session, user, target=target)


@router.callback_query(F.data.startswith(ADMIN_USER_VIEW_ORDERS_PREFIX))
async def handle_user_view_orders(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.removeprefix(ADMIN_USER_VIEW_ORDERS_PREFIX))
    user = await session.get(UserProfile, user_id)
    if user is None:
        await callback.answer("User not found.", show_alert=True)
        await _render_users_overview(callback.message, session)
        return

    repo = OrderRepository(session)
    orders = await repo.list_for_user(user.id)
    if not orders:
        await callback.answer("User has no orders.", show_alert=True)
        await _render_user_detail(callback.message, session, user)
        return

    text = _format_user_orders(user, orders[:10])
    markup = user_orders_keyboard(user.id, orders[:10])
    try:
        await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    await callback.answer()


async def _render_users_overview(message: Message, session: AsyncSession) -> None:
    repo = UserRepository(session)
    users = await repo.list_recent(limit=15)
    text = _format_users_overview(users)
    markup = users_overview_keyboard(users)
    try:
        await message.edit_text(text, reply_markup=markup)
    except Exception:
        await message.answer(text, reply_markup=markup)


async def _render_user_detail(
    message: Message,
    session: AsyncSession,
    user: UserProfile,
    *,
    notice: str | None = None,
    target: tuple[int, int] | None = None,
) -> None:
    text = _format_user_detail(user)
    if notice:
        text = f"{notice}\n\n{text}"
    markup = user_detail_keyboard(user)
    if target:
        chat_id, message_id = target
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
        except Exception:
            await message.bot.send_message(chat_id, text, reply_markup=markup)
        return
    try:
        await message.edit_text(text, reply_markup=markup)
    except Exception:
        await message.answer(text, reply_markup=markup)


def _format_users_overview(users: list[UserProfile]) -> str:
    if not users:
        return "No users seen yet."
    lines = ["<b>Recent users</b>"]
    for user in users:
        name = user.display_name()
        last_seen = user.last_seen_at.strftime("%Y-%m-%d %H:%M") if user.last_seen_at else "-"
        status = "BLOCKED" if user.is_blocked else "ACTIVE"
        lines.append(f"{name} - {status} - last seen {last_seen}")
    lines.append("")
    lines.append("Select a user to view details.")
    return "\n".join(lines)


def _format_user_detail(user: UserProfile) -> str:
    last_seen = user.last_seen_at.strftime("%Y-%m-%d %H:%M:%S UTC") if user.last_seen_at else "-"
    lines = [
        f"<b>{user.display_name()}</b>",
        f"Telegram ID: {user.telegram_id}",
        f"Username: @{user.username}" if user.username else "Username: -",
        f"First name: {user.first_name or '-'}",
        f"Last name: {user.last_name or '-'}",
        f"Language: {user.language_code or '-'}",
        f"Last seen: {last_seen}",
        f"Blocked: {'YES' if user.is_blocked else 'no'}",
    ]
    if user.notes:
        lines.append("")
        lines.append("<b>Notes</b>")
        lines.append(user.notes)
    return "\n".join(lines)


def _format_user_orders(user: UserProfile, orders: list[Order]) -> str:
    lines = [f"<b>Orders for {user.display_name()}</b>"]
    for order in orders:
        status = order.status.value.replace("_", " ").title()
        created = order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "-"
        lines.append(f"{status} - {order.total_amount} {order.currency} - {created}")
    return "\n".join(lines)

