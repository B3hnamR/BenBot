from aiogram import Dispatcher

from . import (
    admin,
    admin_coupons,
    admin_payments,
    admin_products,
    admin_referral,
    admin_support,
    admin_users,
    cart,
    common,
    products,
    referral,
    help,
    support,
)
from ..middlewares import OwnerAccessMiddleware


def register_handlers(dispatcher: Dispatcher, owner_middleware: OwnerAccessMiddleware) -> None:
    admin.router.message.outer_middleware(owner_middleware)
    admin.router.callback_query.outer_middleware(owner_middleware)
    admin_payments.router.message.outer_middleware(owner_middleware)
    admin_payments.router.callback_query.outer_middleware(owner_middleware)
    admin_coupons.router.message.outer_middleware(owner_middleware)
    admin_coupons.router.callback_query.outer_middleware(owner_middleware)
    admin_support.router.message.outer_middleware(owner_middleware)
    admin_support.router.callback_query.outer_middleware(owner_middleware)
    admin_products.router.message.outer_middleware(owner_middleware)
    admin_products.router.callback_query.outer_middleware(owner_middleware)
    admin_users.router.message.outer_middleware(owner_middleware)
    admin_users.router.callback_query.outer_middleware(owner_middleware)
    admin_referral.router.message.outer_middleware(owner_middleware)
    admin_referral.router.callback_query.outer_middleware(owner_middleware)

    dispatcher.include_router(support.router)
    dispatcher.include_router(common.router)
    dispatcher.include_router(cart.router)
    dispatcher.include_router(products.router)
    dispatcher.include_router(referral.router)
    dispatcher.include_router(help.router)
    dispatcher.include_router(admin_payments.router)
    dispatcher.include_router(admin_coupons.router)
    dispatcher.include_router(admin_support.router)
    dispatcher.include_router(admin_products.router)
    dispatcher.include_router(admin_users.router)
    dispatcher.include_router(admin_referral.router)
    dispatcher.include_router(admin.router)
