from aiogram import Router

from . import admin, common, drinks, tiers


def build_router() -> Router:
    router = Router()
    # common первым: /cancel должен срабатывать в любом состоянии.
    router.include_routers(common.router, admin.router, drinks.router, tiers.router)
    return router
