from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.enums import SettingKey
from app.infrastructure.db.models import AppSetting

from .base import BaseRepository


class SettingsRepository(BaseRepository):
    async def get(self, key: SettingKey) -> AppSetting | None:
        result = await self.session.execute(
            select(AppSetting).where(AppSetting.key == key.value)
        )
        return result.scalar_one_or_none()

    async def get_value(self, key: SettingKey, default: Any = None) -> Any:
        setting = await self.get(key)
        if setting is None:
            return default
        return setting.value

    async def upsert(self, key: SettingKey, value: Any) -> AppSetting:
        setting = await self.get(key)
        if setting is None:
            setting = AppSetting(key=key.value, value=value)
            await self.add(setting)
        else:
            setting.value = value
        return setting
