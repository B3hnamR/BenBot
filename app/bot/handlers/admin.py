from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import AdminMenuCallback, admin_menu_keyboard
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.services.config_service import ConfigService

router = Router(name="admin")


@router.callback_query(F.data == MainMenuCallback.ADMIN.value)
async def handle_admin_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    enabled = await config_service.subscription_required()

    await callback.message.edit_text(
        "Admin control panel: manage subscription gates, channels, products, and orders.",
        reply_markup=admin_menu_keyboard(subscription_enabled=enabled),
    )
    await callback.answer()


@router.callback_query(F.data == AdminMenuCallback.TOGGLE_SUBSCRIPTION.value)
async def handle_toggle_subscription(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    current = await config_service.subscription_required()
    new_value = not current
    await config_service.set_subscription_required(new_value)

    await callback.message.edit_text(
        f"Admin control panel (subscription gate {'enabled' if new_value else 'disabled'}).",
        reply_markup=admin_menu_keyboard(subscription_enabled=new_value),
    )
    await callback.answer(
        "Subscription gate enabled." if new_value else "Subscription gate disabled."
    )


@router.callback_query(F.data == AdminMenuCallback.MANAGE_CHANNELS.value)
async def handle_manage_channels(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    enabled = await config_service.subscription_required()

    await callback.message.edit_text(
        "Channel management will be available soon. You will be able to configure required subscriptions here.",
        reply_markup=admin_menu_keyboard(subscription_enabled=enabled),
    )
    await callback.answer()


@router.callback_query(F.data == AdminMenuCallback.BACK_TO_MAIN.value)
async def handle_admin_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Welcome to Ben Bot!\nUse the interactive menu below to browse products, manage orders, or contact support.",
        reply_markup=main_menu_keyboard(show_admin=True),
    )
    await callback.answer()
