from __future__ import annotations

from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import SettingKey
from app.infrastructure.db.models import RequiredChannel
from app.infrastructure.db.repositories import (
    RequiredChannelRepository,
    SettingsRepository,
)


class ConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings_repo = SettingsRepository(session)
        self._channel_repo = RequiredChannelRepository(session)
        self._env_settings = get_settings()


    async def invoice_timeout_minutes(self) -> int:
        value = await self._settings_repo.get_value(
            SettingKey.INVOICE_TIMEOUT_MINUTES,
            default=self._env_settings.invoice_payment_timeout_minutes,
        )
        try:
            return int(value)
        except (TypeError, ValueError):
            return self._env_settings.invoice_payment_timeout_minutes

    async def payment_currency(self) -> str:
        value = await self._settings_repo.get_value(
            SettingKey.PAYMENT_CURRENCY,
            default=self._env_settings.payment_currency,
        )
        if isinstance(value, str) and value:
            return value.upper()
        return self._env_settings.payment_currency

    async def ensure_defaults(self) -> None:
        await self._settings_repo.upsert(
            SettingKey.SUBSCRIPTION_REQUIRED,
            await self._ensure_bool_default(
                SettingKey.SUBSCRIPTION_REQUIRED,
                self._env_settings.require_subscription_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.SUBSCRIPTION_CHANNELS,
            await self._ensure_channels_default(),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CURRENCY,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CURRENCY,
                self._env_settings.payment_currency,
            ),
        )
        if self._env_settings.payment_provider_token:
            await self._settings_repo.upsert(
                SettingKey.PAYMENT_PROVIDER_TOKEN,
                self._env_settings.payment_provider_token,
            )
        await self._settings_repo.upsert(
            SettingKey.INVOICE_TIMEOUT_MINUTES,
            await self._ensure_value_default(
                SettingKey.INVOICE_TIMEOUT_MINUTES,
                self._env_settings.invoice_payment_timeout_minutes,
            ),
        )

        if self._env_settings.required_channels_default:
            existing = await self._channel_repo.list_active()
            if not existing:
                for identifier in self._env_settings.required_channels_default:
                    channel = RequiredChannel(
                        channel_id=None,
                        username=identifier.lstrip("@"),
                        is_mandatory=True,
                    )
                    await self._channel_repo.upsert(channel)

    async def _ensure_bool_default(self, key: SettingKey, default: bool) -> bool:
        value = await self._settings_repo.get_value(key)
        if value is None:
            return default
        return bool(value)

    async def _ensure_value_default(self, key: SettingKey, default: int | str) -> int | str:
        value = await self._settings_repo.get_value(key)
        if value is None:
            return default
        return value

    async def _ensure_channels_default(self) -> list[str]:
        value = await self._settings_repo.get_value(SettingKey.SUBSCRIPTION_CHANNELS)
        if value is None:
            return self._env_settings.required_channels_default
        if isinstance(value, list):
            return value
        return self._env_settings.required_channels_default

    async def subscription_required(self) -> bool:
        value = await self._settings_repo.get_value(
            SettingKey.SUBSCRIPTION_REQUIRED,
            default=self._env_settings.require_subscription_default,
        )
        return bool(value)

    async def set_subscription_required(self, enabled: bool) -> bool:
        await self._settings_repo.upsert(SettingKey.SUBSCRIPTION_REQUIRED, enabled)
        return enabled

    async def get_required_channels(self) -> Sequence[RequiredChannel]:
        channels = await self._channel_repo.list_active()
        return channels

    async def update_required_channels(
        self,
        channel_entities: Sequence[RequiredChannel],
    ) -> None:
        existing = {channel.channel_id for channel in await self._channel_repo.list_active() if channel.channel_id}
        new_ids = {channel.channel_id for channel in channel_entities if channel.channel_id}
        remove_ids = existing - new_ids
        if remove_ids:
            await self._channel_repo.bulk_soft_delete(remove_ids)

        for channel in channel_entities:
            await self._channel_repo.upsert(channel)
