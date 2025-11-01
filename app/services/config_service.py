from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import ReferralRewardType, SettingKey
from app.infrastructure.db.models import RequiredChannel
from app.infrastructure.db.repositories import (
    RequiredChannelRepository,
    SettingsRepository,
)


class ConfigService:
    @dataclass
    class CryptoSettings:
        enabled: bool
        currencies: list[str]
        lifetime_minutes: int
        mixed_payment: bool
        fee_payer: str
        underpaid_coverage: float
        auto_withdrawal: bool
        to_currency: str | None
        return_url: str | None
        callback_url: str | None
        callback_secret: str | None

    @dataclass
    class AlertSettings:
        notify_payment: bool
        notify_cancellation: bool
        notify_expiration: bool

    @dataclass
    class SupportAntiSpamSettings:
        max_open_tickets: int
        max_tickets_per_window: int
        window_minutes: int
        min_reply_interval_seconds: int

    @dataclass
    class LoyaltySettings:
        enabled: bool
        points_per_currency: float
        redeem_ratio: float
        min_redeem_points: int
        auto_earn: bool
        auto_prompt: bool

    @dataclass
    class ReferralSettings:
        enabled: bool
        allow_public_links: bool
        default_reward_type: ReferralRewardType
        default_reward_value: Decimal
        auto_reward: bool
        reseller_user_ids: list[int]

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
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_ENABLED,
            await self._ensure_bool_default(
                SettingKey.PAYMENT_CRYPTO_ENABLED,
                bool(self._env_settings.oxapay_api_key),
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_ALLOWED_CURRENCIES,
            await self._ensure_list_default(
                SettingKey.PAYMENT_CRYPTO_ALLOWED_CURRENCIES,
                self._env_settings.oxapay_default_currencies,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_LIFETIME_MINUTES,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CRYPTO_LIFETIME_MINUTES,
                self._env_settings.oxapay_invoice_lifetime_minutes,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_MIXED_PAYMENT,
            await self._ensure_bool_default(
                SettingKey.PAYMENT_CRYPTO_MIXED_PAYMENT,
                self._env_settings.oxapay_mixed_payment,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_FEE_PAYER,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CRYPTO_FEE_PAYER,
                self._env_settings.oxapay_fee_payer,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_UNDERPAID_COVERAGE,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CRYPTO_UNDERPAID_COVERAGE,
                self._env_settings.oxapay_underpaid_coverage,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_AUTO_WITHDRAWAL,
            await self._ensure_bool_default(
                SettingKey.PAYMENT_CRYPTO_AUTO_WITHDRAWAL,
                self._env_settings.oxapay_auto_withdrawal,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_TO_CURRENCY,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CRYPTO_TO_CURRENCY,
                self._env_settings.oxapay_to_currency or "",
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_RETURN_URL,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CRYPTO_RETURN_URL,
                self._env_settings.oxapay_return_url or "",
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_CALLBACK_URL,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CRYPTO_CALLBACK_URL,
                self._env_settings.oxapay_callback_url or "",
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_CALLBACK_SECRET,
            await self._ensure_value_default(
                SettingKey.PAYMENT_CRYPTO_CALLBACK_SECRET,
                self._env_settings.oxapay_callback_secret or "",
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.ALERT_ORDER_PAYMENT,
            await self._ensure_bool_default(
                SettingKey.ALERT_ORDER_PAYMENT,
                True,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.ALERT_ORDER_CANCELLED,
            await self._ensure_bool_default(
                SettingKey.ALERT_ORDER_CANCELLED,
                True,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.ALERT_ORDER_EXPIRED,
            await self._ensure_bool_default(
                SettingKey.ALERT_ORDER_EXPIRED,
                True,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_MAX_OPEN_TICKETS,
            await self._ensure_value_default(
                SettingKey.SUPPORT_ANTISPAM_MAX_OPEN_TICKETS,
                self._env_settings.support_antispam_max_open_tickets,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_MAX_TICKETS_PER_WINDOW,
            await self._ensure_value_default(
                SettingKey.SUPPORT_ANTISPAM_MAX_TICKETS_PER_WINDOW,
                self._env_settings.support_antispam_max_tickets_per_window,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_WINDOW_MINUTES,
            await self._ensure_value_default(
                SettingKey.SUPPORT_ANTISPAM_WINDOW_MINUTES,
                self._env_settings.support_antispam_window_minutes,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_MIN_REPLY_INTERVAL_SECONDS,
            await self._ensure_value_default(
                SettingKey.SUPPORT_ANTISPAM_MIN_REPLY_INTERVAL_SECONDS,
                self._env_settings.support_antispam_min_reply_interval_seconds,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_ENABLED,
            await self._ensure_bool_default(
                SettingKey.LOYALTY_ENABLED,
                self._env_settings.loyalty_enabled_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_POINTS_PER_CURRENCY,
            await self._ensure_value_default(
                SettingKey.LOYALTY_POINTS_PER_CURRENCY,
                self._env_settings.loyalty_points_per_currency_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_REDEEM_RATIO,
            await self._ensure_value_default(
                SettingKey.LOYALTY_REDEEM_RATIO,
                self._env_settings.loyalty_redeem_ratio_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_MIN_REDEEM_POINTS,
            await self._ensure_value_default(
                SettingKey.LOYALTY_MIN_REDEEM_POINTS,
                self._env_settings.loyalty_min_redeem_points_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_AUTO_EARN,
            await self._ensure_bool_default(
                SettingKey.LOYALTY_AUTO_EARN,
                self._env_settings.loyalty_auto_earn_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_AUTO_PROMPT,
            await self._ensure_bool_default(
                SettingKey.LOYALTY_AUTO_PROMPT,
                self._env_settings.loyalty_auto_prompt_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_ENABLED,
            await self._ensure_bool_default(
                SettingKey.REFERRAL_ENABLED,
                self._env_settings.referral_enabled_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_DEFAULT_REWARD_TYPE,
            await self._ensure_value_default(
                SettingKey.REFERRAL_DEFAULT_REWARD_TYPE,
                self._env_settings.referral_reward_type_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_DEFAULT_REWARD_VALUE,
            await self._ensure_value_default(
                SettingKey.REFERRAL_DEFAULT_REWARD_VALUE,
                self._env_settings.referral_reward_value_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_AUTO_REWARD,
            await self._ensure_bool_default(
                SettingKey.REFERRAL_AUTO_REWARD,
                self._env_settings.referral_auto_reward_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_ALLOW_PUBLIC_LINKS,
            await self._ensure_bool_default(
                SettingKey.REFERRAL_ALLOW_PUBLIC_LINKS,
                self._env_settings.referral_allow_public_default,
            ),
        )
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_RESELLERS,
            await self._ensure_int_list_default(
                SettingKey.REFERRAL_RESELLERS,
                self._env_settings.referral_reseller_ids_default,
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
        return self._to_bool(value, default)

    async def _ensure_value_default(self, key: SettingKey, default: int | str) -> int | str:
        value = await self._settings_repo.get_value(key)
        if value is None:
            return default
        return value

    async def _ensure_list_default(
        self,
        key: SettingKey,
        default: Sequence[str],
    ) -> list[str]:
        value = await self._settings_repo.get_value(key)
        if value is None:
            return [item.upper() for item in default]
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip().upper() for item in value.split(",") if item.strip()]
        return [item.upper() for item in default]

    async def _ensure_int_list_default(
        self,
        key: SettingKey,
        default: Sequence[int],
    ) -> list[int]:
        value = await self._settings_repo.get_value(key)
        if value is None:
            return list(default)
        items: list[int] = []
        if isinstance(value, list):
            source = value
        elif isinstance(value, str):
            source = [item.strip() for item in value.split(",")]
        else:
            source = default
        for item in source:
            try:
                items.append(int(item))
            except (TypeError, ValueError):
                continue
        return items

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
        return self._to_bool(value, self._env_settings.require_subscription_default)

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

    async def get_alert_settings(self) -> "ConfigService.AlertSettings":
        payment = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.ALERT_ORDER_PAYMENT,
                default=True,
            ),
            True,
        )
        cancellation = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.ALERT_ORDER_CANCELLED,
                default=True,
            ),
            True,
        )
        expiration = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.ALERT_ORDER_EXPIRED,
                default=True,
            ),
            True,
        )
        return self.AlertSettings(
            notify_payment=payment,
            notify_cancellation=cancellation,
            notify_expiration=expiration,
        )

    async def save_alert_settings(
        self,
        config: "ConfigService.AlertSettings",
    ) -> "ConfigService.AlertSettings":
        await self._settings_repo.upsert(
            SettingKey.ALERT_ORDER_PAYMENT,
            bool(config.notify_payment),
        )
        await self._settings_repo.upsert(
            SettingKey.ALERT_ORDER_CANCELLED,
            bool(config.notify_cancellation),
        )
        await self._settings_repo.upsert(
            SettingKey.ALERT_ORDER_EXPIRED,
            bool(config.notify_expiration),
        )
        return await self.get_alert_settings()

    async def get_support_antispam_settings(self) -> "ConfigService.SupportAntiSpamSettings":
        max_open = self._safe_int(
            await self._settings_repo.get_value(
                SettingKey.SUPPORT_ANTISPAM_MAX_OPEN_TICKETS,
                default=self._env_settings.support_antispam_max_open_tickets,
            ),
            self._env_settings.support_antispam_max_open_tickets,
        )
        max_window = self._safe_int(
            await self._settings_repo.get_value(
                SettingKey.SUPPORT_ANTISPAM_MAX_TICKETS_PER_WINDOW,
                default=self._env_settings.support_antispam_max_tickets_per_window,
            ),
            self._env_settings.support_antispam_max_tickets_per_window,
        )
        window_minutes = self._safe_int(
            await self._settings_repo.get_value(
                SettingKey.SUPPORT_ANTISPAM_WINDOW_MINUTES,
                default=self._env_settings.support_antispam_window_minutes,
            ),
            self._env_settings.support_antispam_window_minutes,
        )
        min_interval = self._safe_int(
            await self._settings_repo.get_value(
                SettingKey.SUPPORT_ANTISPAM_MIN_REPLY_INTERVAL_SECONDS,
                default=self._env_settings.support_antispam_min_reply_interval_seconds,
            ),
            self._env_settings.support_antispam_min_reply_interval_seconds,
        )
        return self.SupportAntiSpamSettings(
            max_open_tickets=max(0, max_open),
            max_tickets_per_window=max(0, max_window),
            window_minutes=max(0, window_minutes),
            min_reply_interval_seconds=max(0, min_interval),
        )

    async def save_support_antispam_settings(
        self,
        config: "ConfigService.SupportAntiSpamSettings",
    ) -> "ConfigService.SupportAntiSpamSettings":
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_MAX_OPEN_TICKETS,
            max(0, int(config.max_open_tickets)),
        )
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_MAX_TICKETS_PER_WINDOW,
            max(0, int(config.max_tickets_per_window)),
        )
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_WINDOW_MINUTES,
            max(0, int(config.window_minutes)),
        )
        await self._settings_repo.upsert(
            SettingKey.SUPPORT_ANTISPAM_MIN_REPLY_INTERVAL_SECONDS,
            max(0, int(config.min_reply_interval_seconds)),
        )
        return await self.get_support_antispam_settings()

    async def get_crypto_settings(self) -> CryptoSettings:
        enabled = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.PAYMENT_CRYPTO_ENABLED,
                default=bool(self._env_settings.oxapay_api_key),
            ),
            bool(self._env_settings.oxapay_api_key),
        )
        currencies = await self._ensure_list_default(
            SettingKey.PAYMENT_CRYPTO_ALLOWED_CURRENCIES,
            self._env_settings.oxapay_default_currencies or [],
        )
        lifetime_raw = await self._settings_repo.get_value(
            SettingKey.PAYMENT_CRYPTO_LIFETIME_MINUTES,
            default=self._env_settings.oxapay_invoice_lifetime_minutes,
        )
        lifetime = self._safe_int(lifetime_raw, self._env_settings.oxapay_invoice_lifetime_minutes)
        mixed_payment = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.PAYMENT_CRYPTO_MIXED_PAYMENT,
                default=self._env_settings.oxapay_mixed_payment,
            ),
            self._env_settings.oxapay_mixed_payment,
        )
        fee_payer = str(
            await self._settings_repo.get_value(
                SettingKey.PAYMENT_CRYPTO_FEE_PAYER,
                default=self._env_settings.oxapay_fee_payer,
            )
            or self._env_settings.oxapay_fee_payer
        ).strip().lower()
        if fee_payer not in {"payer", "merchant"}:
            fee_payer = "merchant"

        underpaid_raw = await self._settings_repo.get_value(
            SettingKey.PAYMENT_CRYPTO_UNDERPAID_COVERAGE,
            default=self._env_settings.oxapay_underpaid_coverage,
        )
        underpaid_coverage = self._safe_float(underpaid_raw, self._env_settings.oxapay_underpaid_coverage)
        auto_withdrawal = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.PAYMENT_CRYPTO_AUTO_WITHDRAWAL,
                default=self._env_settings.oxapay_auto_withdrawal,
            ),
            self._env_settings.oxapay_auto_withdrawal,
        )
        to_currency_raw = await self._settings_repo.get_value(
            SettingKey.PAYMENT_CRYPTO_TO_CURRENCY,
            default=self._env_settings.oxapay_to_currency or "",
        )
        to_currency = str(to_currency_raw).strip().upper() or None
        return_url_raw = await self._settings_repo.get_value(
            SettingKey.PAYMENT_CRYPTO_RETURN_URL,
            default=self._env_settings.oxapay_return_url or "",
        )
        return_url = str(return_url_raw).strip() or None
        callback_url_raw = await self._settings_repo.get_value(
            SettingKey.PAYMENT_CRYPTO_CALLBACK_URL,
            default=self._env_settings.oxapay_callback_url or "",
        )
        callback_url = str(callback_url_raw).strip() or None
        callback_secret_raw = await self._settings_repo.get_value(
            SettingKey.PAYMENT_CRYPTO_CALLBACK_SECRET,
            default=self._env_settings.oxapay_callback_secret or "",
        )
        callback_secret = str(callback_secret_raw).strip() or None

        return self.CryptoSettings(
            enabled=enabled,
            currencies=currencies,
            lifetime_minutes=lifetime,
            mixed_payment=mixed_payment,
            fee_payer=fee_payer,
            underpaid_coverage=underpaid_coverage,
            auto_withdrawal=auto_withdrawal,
            to_currency=to_currency,
            return_url=return_url,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )

    async def save_crypto_settings(self, config: CryptoSettings) -> CryptoSettings:
        await self._settings_repo.upsert(SettingKey.PAYMENT_CRYPTO_ENABLED, bool(config.enabled))
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_ALLOWED_CURRENCIES,
            [currency.upper() for currency in config.currencies],
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_LIFETIME_MINUTES,
            int(config.lifetime_minutes),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_MIXED_PAYMENT,
            bool(config.mixed_payment),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_FEE_PAYER,
            config.fee_payer.strip().lower(),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_UNDERPAID_COVERAGE,
            float(config.underpaid_coverage),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_AUTO_WITHDRAWAL,
            bool(config.auto_withdrawal),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_TO_CURRENCY,
            (config.to_currency or "").upper(),
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_RETURN_URL,
            config.return_url or "",
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_CALLBACK_URL,
            config.callback_url or "",
        )
        await self._settings_repo.upsert(
            SettingKey.PAYMENT_CRYPTO_CALLBACK_SECRET,
            config.callback_secret or "",
        )
        return await self.get_crypto_settings()

    async def get_loyalty_settings(self) -> "ConfigService.LoyaltySettings":
        enabled = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.LOYALTY_ENABLED,
                default=self._env_settings.loyalty_enabled_default,
            ),
            self._env_settings.loyalty_enabled_default,
        )
        points_per_currency = self._safe_float(
            await self._settings_repo.get_value(
                SettingKey.LOYALTY_POINTS_PER_CURRENCY,
                default=self._env_settings.loyalty_points_per_currency_default,
            ),
            float(self._env_settings.loyalty_points_per_currency_default),
        )
        redeem_ratio = self._safe_float(
            await self._settings_repo.get_value(
                SettingKey.LOYALTY_REDEEM_RATIO,
                default=self._env_settings.loyalty_redeem_ratio_default,
            ),
            float(self._env_settings.loyalty_redeem_ratio_default),
        )
        min_redeem_points = self._safe_int(
            await self._settings_repo.get_value(
                SettingKey.LOYALTY_MIN_REDEEM_POINTS,
                default=self._env_settings.loyalty_min_redeem_points_default,
            ),
            self._env_settings.loyalty_min_redeem_points_default,
        )
        auto_earn = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.LOYALTY_AUTO_EARN,
                default=self._env_settings.loyalty_auto_earn_default,
            ),
            self._env_settings.loyalty_auto_earn_default,
        )
        auto_prompt = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.LOYALTY_AUTO_PROMPT,
                default=self._env_settings.loyalty_auto_prompt_default,
            ),
            self._env_settings.loyalty_auto_prompt_default,
        )
        return self.LoyaltySettings(
            enabled=enabled,
            points_per_currency=max(0.0, points_per_currency),
            redeem_ratio=max(0.0, redeem_ratio),
            min_redeem_points=max(0, min_redeem_points),
            auto_earn=auto_earn,
            auto_prompt=auto_prompt,
        )

    async def save_loyalty_settings(
        self,
        config: "ConfigService.LoyaltySettings",
    ) -> "ConfigService.LoyaltySettings":
        await self._settings_repo.upsert(SettingKey.LOYALTY_ENABLED, bool(config.enabled))
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_POINTS_PER_CURRENCY,
            float(config.points_per_currency),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_REDEEM_RATIO,
            float(config.redeem_ratio),
        )
        await self._settings_repo.upsert(
            SettingKey.LOYALTY_MIN_REDEEM_POINTS,
            max(0, int(config.min_redeem_points)),
        )
        await self._settings_repo.upsert(SettingKey.LOYALTY_AUTO_EARN, bool(config.auto_earn))
        await self._settings_repo.upsert(SettingKey.LOYALTY_AUTO_PROMPT, bool(config.auto_prompt))
        return await self.get_loyalty_settings()

    async def get_referral_settings(self) -> "ConfigService.ReferralSettings":
        enabled = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.REFERRAL_ENABLED,
                default=self._env_settings.referral_enabled_default,
            ),
            self._env_settings.referral_enabled_default,
        )
        allow_public = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.REFERRAL_ALLOW_PUBLIC_LINKS,
                default=self._env_settings.referral_allow_public_default,
            ),
            self._env_settings.referral_allow_public_default,
        )
        reward_type_raw = await self._settings_repo.get_value(
            SettingKey.REFERRAL_DEFAULT_REWARD_TYPE,
            default=self._env_settings.referral_reward_type_default,
        )
        try:
            reward_type = ReferralRewardType(str(reward_type_raw).strip().lower())
        except Exception:  # noqa: BLE001
            reward_type = ReferralRewardType(self._env_settings.referral_reward_type_default)
        reward_value_raw = await self._settings_repo.get_value(
            SettingKey.REFERRAL_DEFAULT_REWARD_VALUE,
            default=self._env_settings.referral_reward_value_default,
        )
        try:
            reward_value = Decimal(str(reward_value_raw))
        except Exception:  # noqa: BLE001
            reward_value = Decimal(str(self._env_settings.referral_reward_value_default))
        auto_reward = self._to_bool(
            await self._settings_repo.get_value(
                SettingKey.REFERRAL_AUTO_REWARD,
                default=self._env_settings.referral_auto_reward_default,
            ),
            self._env_settings.referral_auto_reward_default,
        )
        resellers_raw = await self._settings_repo.get_value(
            SettingKey.REFERRAL_RESELLERS,
            default=self._env_settings.referral_reseller_ids_default,
        )
        reseller_ids: set[int] = set()
        if isinstance(resellers_raw, list):
            for item in resellers_raw:
                try:
                    reseller_ids.add(int(item))
                except (TypeError, ValueError):
                    continue
        elif isinstance(resellers_raw, str):
            for item in resellers_raw.split(","):
                item = item.strip()
                if not item:
                    continue
                try:
                    reseller_ids.add(int(item))
                except ValueError:
                    continue
        else:
            reseller_ids.update(self._env_settings.referral_reseller_ids_default)

        return self.ReferralSettings(
            enabled=enabled,
            allow_public_links=allow_public,
            default_reward_type=reward_type,
            default_reward_value=reward_value,
            auto_reward=auto_reward,
            reseller_user_ids=sorted(reseller_ids),
        )

    async def save_referral_settings(
        self,
        config: "ConfigService.ReferralSettings",
    ) -> "ConfigService.ReferralSettings":
        await self._settings_repo.upsert(SettingKey.REFERRAL_ENABLED, bool(config.enabled))
        await self._settings_repo.upsert(SettingKey.REFERRAL_ALLOW_PUBLIC_LINKS, bool(config.allow_public_links))
        await self._settings_repo.upsert(SettingKey.REFERRAL_DEFAULT_REWARD_TYPE, config.default_reward_type.value)
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_DEFAULT_REWARD_VALUE,
            float(config.default_reward_value),
        )
        await self._settings_repo.upsert(SettingKey.REFERRAL_AUTO_REWARD, bool(config.auto_reward))
        await self._settings_repo.upsert(
            SettingKey.REFERRAL_RESELLERS,
            [int(user_id) for user_id in config.reseller_user_ids],
        )
        return await self.get_referral_settings()

    @staticmethod
    def _safe_int(value: int | str | None, default: int) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: float | str | None, default: float) -> float:
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value: object, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y", "on"}:
                return True
            if lowered in {"0", "false", "no", "n", "off"}:
                return False
        return bool(value)
