from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.keyboards.subscription import (
    SUBSCRIPTION_REFRESH_CALLBACK,
    build_subscription_keyboard,
)
from app.core.config import get_settings
from app.infrastructure.db.repositories import RequiredChannelRepository
from app.services.container import membership_service

router = Router(name="common")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(
        text=(
            "Welcome to Ben Bot!\n"
            "Use the interactive menu below to browse products, manage orders, or contact support."
        ),
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(message.from_user.id)),
    )


@router.callback_query(F.data == MainMenuCallback.ACCOUNT.value)
async def handle_account(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Your personal account area is coming soon. You will be able to review orders and invoices here.",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == MainMenuCallback.SUPPORT.value)
async def handle_support(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Support center is under construction. Use this menu later to raise tickets or chat with the team.",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == SUBSCRIPTION_REFRESH_CALLBACK)
async def handle_subscription_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    channel_repo = RequiredChannelRepository(session)
    channels = await channel_repo.list_active()

    is_allowed = await membership_service.user_can_access(
        bot=callback.bot,
        user_id=callback.from_user.id,
        session=session,
        channels=channels,
    )

    if is_allowed:
        membership_service.invalidate_user(callback.from_user.id)
        await callback.answer("Thanks! Access granted.")
        await callback.message.edit_text(
            "Welcome back! Choose an option below.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    keyboard = build_subscription_keyboard(list(channels)) if channels else None
    await callback.answer("You still need to join the required channels.", show_alert=True)
    await callback.message.edit_text(
        text=(
            "Please join the required channel(s) before continuing."
            "\nTap 'I've Joined' once you have access."
        ),
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "subscription:no_link")
async def handle_subscription_no_link(callback: CallbackQuery) -> None:
    await callback.answer(
        "Channel link is not configured. Please contact the administrator.",
        show_alert=True,
    )


def _user_is_owner(user_id: int | None) -> bool:
    if user_id is None:
        return False
    settings = get_settings()
    return user_id in settings.owner_user_ids
