from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    AdminCryptoCallback,
    AdminMenuCallback,
    admin_menu_keyboard,
    crypto_settings_keyboard,
)
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.states.admin_crypto import AdminCryptoState
from app.core.config import get_settings
from app.services.config_service import ConfigService
from app.services.crypto_payment_service import CryptoPaymentService

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


@router.callback_query(F.data == AdminMenuCallback.MANAGE_CRYPTO.value)
async def handle_manage_crypto(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(None)
    await _render_crypto_settings_message(callback.message, session, state)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.BACK.value)
async def handle_crypto_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await handle_admin_menu(callback, session)


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_ENABLED.value)
async def handle_crypto_toggle_enabled(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    settings = get_settings()
    if not config.enabled and not settings.oxapay_api_key:
        await callback.answer("OXAPAY_API_KEY is not configured.", show_alert=True)
        return
    config.enabled = not config.enabled
    config = await config_service.save_crypto_settings(config)
    notice = "Crypto payments enabled." if config.enabled else "Crypto payments disabled."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_MIXED.value)
async def handle_crypto_toggle_mixed(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.mixed_payment = not config.mixed_payment
    config = await config_service.save_crypto_settings(config)
    notice = f"Mixed payments {'enabled' if config.mixed_payment else 'disabled'}."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_FEE_PAYER.value)
async def handle_crypto_toggle_fee_payer(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.fee_payer = "merchant" if config.fee_payer == "payer" else "payer"
    config = await config_service.save_crypto_settings(config)
    notice = f"Fee will be paid by {'customer' if config.fee_payer == 'payer' else 'merchant'}."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_AUTO_WITHDRAWAL.value)
async def handle_crypto_toggle_withdrawal(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.auto_withdrawal = not config.auto_withdrawal
    config = await config_service.save_crypto_settings(config)
    notice = f"Auto withdrawal {'enabled' if config.auto_withdrawal else 'disabled'}."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.REFRESH_ACCEPTED.value)
async def handle_crypto_refresh_accepted(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    service = CryptoPaymentService(session)
    currencies = await service.list_accepted_currencies()
    if currencies:
        notice = "Account accepts: " + ", ".join(currencies)
    else:
        notice = "Unable to fetch accepted currencies. Check API key or permissions."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_CURRENCIES.value)
async def handle_crypto_prompt_currencies(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.currencies)
    service = CryptoPaymentService(session)
    currencies = await service.list_accepted_currencies()
    hint = ""
    if currencies:
        hint = f"\nSupported by OxaPay account: {', '.join(currencies)}"
    await callback.message.answer(
        "Send the comma-separated list of currency symbols to accept (e.g., USDT,BTC)."
        "\nSend /cancel to abort."
        f"{hint}"
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_LIFETIME.value)
async def handle_crypto_prompt_lifetime(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.lifetime)
    await callback.message.answer(
        "Send the invoice lifetime in minutes (15 - 2880)."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_UNDERPAID.value)
async def handle_crypto_prompt_underpaid(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.underpaid)
    await callback.message.answer(
        "Send the acceptable underpaid coverage percentage (0 - 60)."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_TO_CURRENCY.value)
async def handle_crypto_prompt_to_currency(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.to_currency)
    await callback.message.answer(
        "Send the settlement currency symbol (e.g., USDT)."
        "\nSend 'clear' to disable conversion."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_RETURN_URL.value)
async def handle_crypto_prompt_return_url(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.return_url)
    await callback.message.answer(
        "Send the return URL for successful payments."
        "\nSend 'clear' to remove."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_CALLBACK_URL.value)
async def handle_crypto_prompt_callback_url(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.callback_url)
    await callback.message.answer(
        "Send the callback (webhook) URL to receive payment notifications."
        "\nSend 'clear' to remove."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_CALLBACK_SECRET.value)
async def handle_crypto_prompt_callback_secret(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.callback_secret)
    await callback.message.answer(
        "Send the callback secret used to verify webhook signatures."
        "\nSend 'clear' to remove."
        "\nSend /cancel to abort."
    )
    await callback.answer()


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


@router.message(AdminCryptoState.currencies)
async def process_crypto_currencies(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send one or more currency symbols separated by commas, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    tokens = [item.strip().upper() for item in text.replace("\n", ",").split(",") if item.strip()]
    if not tokens:
        await message.answer("Please send at least one currency symbol, or /cancel.")
        return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.currencies = tokens
    await config_service.save_crypto_settings(config)
    await message.answer("Allowed currencies updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Allowed currencies updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.lifetime)
async def process_crypto_lifetime(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send an integer value between 15 and 2880 minutes, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    try:
        value = int(text)
    except ValueError:
        await message.answer("Please send a valid integer number of minutes.")
        return
    if value < 15 or value > 2880:
        await message.answer("The lifetime must be between 15 and 2880 minutes.")
        return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.lifetime_minutes = value
    await config_service.save_crypto_settings(config)
    await message.answer("Invoice lifetime updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Invoice lifetime updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.underpaid)
async def process_crypto_underpaid(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send a percentage between 0 and 60, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    try:
        value = float(text)
    except ValueError:
        await message.answer("Please send a numeric percentage (e.g., 5 or 12.5).")
        return
    if value < 0 or value > 60:
        await message.answer("The underpaid coverage must be between 0 and 60%.")
        return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.underpaid_coverage = value
    await config_service.save_crypto_settings(config)
    await message.answer("Underpaid coverage updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Underpaid coverage updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.to_currency)
async def process_crypto_to_currency(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send a settlement currency symbol (e.g., USDT), 'clear' to disable, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    if text.lower() in {"clear", "none", "-"}:
        token = None
    else:
        token = text.upper()
        if not re.fullmatch(r"[A-Z0-9]{2,10}", token):
            await message.answer("Please send a valid currency symbol (2-10 alphanumeric characters).")
            return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.to_currency = token
    await config_service.save_crypto_settings(config)
    await message.answer("Settlement currency updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Settlement currency updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.return_url)
async def process_crypto_return_url(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the return URL, 'clear' to remove it, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    url = None if text.lower() in {"clear", "none", "-"} else text
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.return_url = url
    await config_service.save_crypto_settings(config)
    await message.answer("Return URL updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Return URL updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.callback_url)
async def process_crypto_callback_url(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the callback URL, 'clear' to remove it, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    url = None if text.lower() in {"clear", "none", "-"} else text
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.callback_url = url
    await config_service.save_crypto_settings(config)
    await message.answer("Callback URL updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Callback URL updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.callback_secret)
async def process_crypto_callback_secret(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the callback secret, 'clear' to remove it, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    secret = None if text.lower() in {"clear", "none", "-"} else text
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.callback_secret = secret
    await config_service.save_crypto_settings(config)
    await message.answer("Callback secret updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Callback secret updated.")
    await state.set_state(None)


async def _render_crypto_settings_message(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    notice: str | None = None,
) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    text = _format_crypto_settings_text(config, api_key_present=bool(get_settings().oxapay_api_key))
    if notice:
        text = f"{notice}\n\n{text}"
    markup = crypto_settings_keyboard(config)
    try:
        await message.edit_text(text, reply_markup=markup)
        target = message
    except Exception:
        target = await message.answer(text, reply_markup=markup)
    await state.update_data(crypto_chat_id=target.chat.id, crypto_message_id=target.message_id)


async def _update_crypto_settings_message_from_state(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    notice: str | None = None,
) -> None:
    data = await state.get_data()
    chat_id = data.get("crypto_chat_id")
    message_id = data.get("crypto_message_id")
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    text = _format_crypto_settings_text(config, api_key_present=bool(get_settings().oxapay_api_key))
    if notice:
        text = f"{notice}\n\n{text}"
    markup = crypto_settings_keyboard(config)
    if chat_id and message_id:
        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass
    target = await message.answer(text, reply_markup=markup)
    await state.update_data(crypto_chat_id=target.chat.id, crypto_message_id=target.message_id)


def _format_crypto_settings_text(
    config: ConfigService.CryptoSettings,
    *,
    api_key_present: bool,
) -> str:
    lines = [
        "<b>OxaPay crypto payments</b>",
        f"Status: {'✅ Enabled' if config.enabled else '❌ Disabled'}",
    ]
    if not api_key_present:
        lines.append("⚠️ OXAPAY_API_KEY is not configured. Enable payments after setting the API key.")
    lines.append(f"Allowed currencies: {', '.join(config.currencies) if config.currencies else '-'}")
    lines.append(f"Invoice lifetime: {config.lifetime_minutes} minutes")
    lines.append(f"Mixed payment: {'ON' if config.mixed_payment else 'OFF'}")
    lines.append(f"Fee payer: {'Customer' if config.fee_payer == 'payer' else 'Merchant'}")
    lines.append(f"Underpaid coverage: {config.underpaid_coverage}%")
    lines.append(f"Auto withdrawal: {'ON' if config.auto_withdrawal else 'OFF'}")
    lines.append(f"Settlement currency: {config.to_currency or '-'}")
    lines.append(f"Return URL: {config.return_url or '-'}")
    lines.append(f"Callback URL: {config.callback_url or '-'}")
    lines.append(f"Callback secret: {'set' if config.callback_secret else '-'}")
    lines.append("\nUse the buttons below to update settings.")
    return "\n".join(lines)


def _is_cancel(text: str) -> bool:
    return text.lower() in {"/cancel", "cancel", "abort"}
