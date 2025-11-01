from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.help import (
    HelpCallback,
    admin_help_categories_keyboard,
    admin_help_items_keyboard,
    generic_back_keyboard,
    help_categories_keyboard,
    help_items_keyboard,
)
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.infrastructure.db.repositories import UserRepository
from app.core.config import get_settings

router = Router(name="help")

USER_HELP_CONTENT = {
    "general": {
        "title": "آغاز سریع",
        "items": {
            "overview": (
                "معرفی کلی ربات",
                "از منوی اصلی می‌توانی محصولات را ببینی، سبد خرید را مدیریت کنی، سفارش‌ها را بررسی کنی و با پشتیبانی در ارتباط باشی. هر بخش با دکمه‌های تعاملی به‌روز می‌شود تا نیاز به پیام‌های متعدد نباشد.",
            ),
            "order": (
                "سفارش مستقیم محصول",
                "در بخش Products روی هر محصول که کلیک کنی، اطلاعات، سؤالات سفارشی و گزینه‌ی افزودن به سبد را می‌بینی. پس از تکمیل فرم‌ها، صفحه تأیید سفارش نمایش داده می‌شود و لینک پرداخت (کریپتو یا سایر روش‌ها) ارائه می‌گردد.",
            ),
            "cart": (
                "سبد خرید چندمحصولی",
                "بخش View cart تمام آیتم‌های انتخابی را با تعداد، تخفیف و جمع نهایی نشان می‌دهد. می‌توانی مقدار هر آیتم را ویرایش یا حذف کنی و در نهایت با یک فاکتور برای همه اجناس پرداخت را انجام دهی.",
            ),
            "support": (
                "پشتیبانی",
                "اگر به مشکلی خوردی از دکمه Support استفاده کن تا تیکت جدید بسازی یا وضعیت تیکت‌های قبلی را ببینی. محدودیت ضداسپم اجازه می‌دهد درخواست‌ها منظم باقی بمانند.",
            ),
        },
    },
    "discounts": {
        "title": "تخفیف و وفاداری",
        "items": {
            "coupons": (
                "کوپن تخفیف",
                "هنگام ثبت سفارش یا در مرحله‌ی سبد خرید، گزینه‌ای برای ورود کد تخفیف ظاهر می‌شود. کد معتبر باعث می‌شود مبلغ تخفیف در خلاصه سفارش ثبت و در پیام تأیید نمایش داده شود. اگر کد نامعتبر باشد، پیام خطا دریافت می‌کنی و می‌توانی دوباره امتحان کنی.",
            ),
            "loyalty": (
                "امتیاز وفاداری",
                "با هر سفارش پرداخت‌شده امتیاز جمع می‌کنی. اگر تنظیمات فعال باشد، در زمان پرداخت پیشنهاد می‌شود نقطه‌ها را تبدیل به تخفیف کنی. با ارسال مقدار امتیاز (یا دستور max) تخفیف اعمال و در پیام سفارش ثبت می‌شود.",
            ),
            "referrals": (
                "ارجاع کاربران",
                "در Referral Center لینک دعوت می‌سازی. هر بار کسی با لینک تو وارد شود و خرید انجام دهد، آمار کلیک/ثبت‌نام/سفارش در داشبوردت دیده می‌شود و بر اساس نوع پاداش، امتیاز یا کمیسیون دریافت می‌کنی.",
            ),
        },
    },
    "payments": {
        "title": "پرداخت و تحویل",
        "items": {
            "payment": (
                "روش‌های پرداخت",
                "سفارش‌ها با لینک پرداخت کریپتو (OxaPay) ایجاد می‌شوند. اگر پرداخت موفق باشد، وضعیت سفارش به PAID تغییر کرده و پیام تأیید با جزئیات و مهلت تحویل برایت فرستاده می‌شود.",
            ),
            "delivery": (
                "پس از پرداخت",
                "بعد از تایید پرداخت، سیستم موجودی را به‌روزرسانی می‌کند و پیام تحویل/فعال‌سازی به صورت خودکار ارسال می‌شود. اگر مشکل پیش بیاید، از بخش پشتیبانی پیگیری کن.",
            ),
        },
    },
}

ADMIN_HELP_CONTENT = {
    "coupons": {
        "title": "مدیریت کوپن",
        "items": {
            "dashboard": (
                "داشبورد کوپن‌ها",
                "در Admin → Coupons آخرین کوپن‌ها و وضعیت فعال/غیرفعال نمایش داده می‌شود. از همین صفحه می‌توان کوپن را ایجاد، فعال/غیرفعال یا حذف کرد.",
            ),
            "editing": (
                "ویرایش پیشرفته",
                "دکمه Edit fields امکان تغییر نام، توضیح، نوع، مقدار، حداقل سفارش، سقف تخفیف، محدودیت مصرف و بازه زمانی را فراهم می‌کند. همه چیز در یک پیام به‌روزرسانی می‌شود تا سرعت کار بالا بماند.",
            ),
            "usage": (
                "گزارش استفاده",
                "گزینه Usage stats مجموع دفعات استفاده، کاربران یکتا و ریدمپشن‌های اخیر را نشان می‌دهد. اگر کوپن اعمال نشود، وضعیت آن در سفارش به failed تغییر می‌کند و از اینجا می‌توان علت را بررسی کرد.",
            ),
        },
    },
    "loyalty": {
        "title": "پیکربندی وفاداری",
        "items": {
            "settings": (
                "تنظیمات اصلی",
                "در Admin → Loyalty مقادیر پایه مثل امتیاز به ازای هر واحد پول، نسبت تبدیل، حداقل امتیاز و فعال بودن Auto earn/Auto prompt قابل تغییر است. هر تغییر بلافاصله در فرآیند checkout اعمال می‌شود.",
            ),
            "reservation": (
                "حجز امتیاز",
                "وقتی کاربر از امتیاز استفاده می‌کند، سیستم ابتدا موجودی را رزرو می‌کند و اگر پرداخت انجام نشود همانجا آزاد می‌کند. اگر لازم شد می‌توان از بخش Orders سفارش را باز کرد و به صورت دستی refund انجام داد.",
            ),
        },
    },
    "referrals": {
        "title": "سیستم ارجاع",
        "items": {
            "settings": (
                "تنظیمات کلی",
                "در Admin → Referrals می‌توان برنامه را فعال/غیرفعال کرد، حالت پاداش پیش‌فرض (Bonus یا Commission)، مقدار پاداش و فهرست reseller‌ها را تعیین نمود. دکمه‌های داشبورد به سرعت وضعیت لینک‌ها و کمیسیون‌های معوق را نشان می‌دهند.",
            ),
            "links": (
                "مدیریت لینک‌ها",
                "لیست Links امکان مشاهده جزئیات هر لینک، ویرایش مقدار پاداش یا حذف آن را می‌دهد. می‌توان پاداش‌های مرتبط را نیز دید و در صورت نیاز کمیسیون‌های معوق را دستی Paid کرد.",
            ),
        },
    },
}


@router.message(Command("help"))
async def handle_help_command(message: Message, session: AsyncSession, user_profile) -> None:
    await _render_help_menu(message, session, user_profile)


@router.callback_query(F.data == MainMenuCallback.HELP.value)
async def handle_help_menu(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
    await _render_help_menu(callback.message, session, user_profile)
    await callback.answer()


@router.callback_query(F.data == HelpCallback.MAIN_MENU.value)
async def handle_help_main(callback: CallbackQuery, session: AsyncSession, user_profile) -> None:
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
    cat_id = callback.data.split(":", 1)[1]
    content = USER_HELP_CONTENT.get(cat_id)
    if content is None:
        await callback.answer("Unknown section.", show_alert=True)
        return
    items = [(item_id, title) for item_id, (title, _) in content["items"].items()]
    text = f"<b>{content['title']}</b>\nیک گزینه را انتخاب کن تا توضیح آن نمایش داده شود."
    await callback.message.edit_text(
        text,
        reply_markup=help_items_keyboard(cat_id, items),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{HelpCallback.ITEM.value}:"))
async def handle_help_item(callback: CallbackQuery) -> None:
    _, cat_id, item_id = callback.data.split(":", 2)
    content = USER_HELP_CONTENT.get(cat_id)
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


@router.callback_query(F.data == HelpCallback.ADMIN_CATEGORY.value)
async def handle_admin_help_menu(callback: CallbackQuery, user_profile) -> None:
    if not _user_is_owner(callback.from_user.id):
        await callback.answer("This section is for administrators only.", show_alert=True)
        return
    categories = [(cat_id, block["title"]) for cat_id, block in ADMIN_HELP_CONTENT.items()]
    await callback.message.edit_text(
        "<b>Admin help</b>\nدسته مورد نظر را انتخاب کنید.",
        reply_markup=admin_help_categories_keyboard(categories),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{HelpCallback.ADMIN_CATEGORY.value}:"))
async def handle_admin_help_category(callback: CallbackQuery) -> None:
    if not _user_is_owner(callback.from_user.id):
        await callback.answer("This section is for administrators only.", show_alert=True)
        return
    _, cat_id = callback.data.split(":", 1)
    content = ADMIN_HELP_CONTENT.get(cat_id)
    if content is None:
        await callback.answer("Unknown section.", show_alert=True)
        return
    items = [(item_id, title) for item_id, (title, _) in content["items"].items()]
    await callback.message.edit_text(
        f"<b>{content['title']}</b>\nیکی از گزینه‌ها را انتخاب کنید.",
        reply_markup=admin_help_items_keyboard(cat_id, items),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{HelpCallback.ADMIN_ITEM.value}:"))
async def handle_admin_help_item(callback: CallbackQuery) -> None:
    if not _user_is_owner(callback.from_user.id):
        await callback.answer("This section is for administrators only.", show_alert=True)
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
    builder.button(text="Back", callback_data=f"{HelpCallback.ADMIN_CATEGORY.value}:{cat_id}")
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
    categories = [(cat_id, block["title"]) for cat_id, block in USER_HELP_CONTENT.items()]
    text = "<b>Help center</b>\nیک دسته را انتخاب کن تا توضیحات آن نمایش داده شود."
    keyboard = help_categories_keyboard(categories, include_admin=is_owner)
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
