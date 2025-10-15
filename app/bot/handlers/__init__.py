from aiogram import Dispatcher

from . import admin, admin_products, admin_users, common, products
from ..middlewares import OwnerAccessMiddleware


def register_handlers(dispatcher: Dispatcher, owner_middleware: OwnerAccessMiddleware) -> None:
    admin.router.message.outer_middleware(owner_middleware)
    admin.router.callback_query.outer_middleware(owner_middleware)
    admin_products.router.message.outer_middleware(owner_middleware)
    admin_products.router.callback_query.outer_middleware(owner_middleware)
    admin_users.router.message.outer_middleware(owner_middleware)
    admin_users.router.callback_query.outer_middleware(owner_middleware)

    dispatcher.include_router(common.router)
    dispatcher.include_router(products.router)
    dispatcher.include_router(admin_products.router)
    dispatcher.include_router(admin_users.router)
    dispatcher.include_router(admin.router)
