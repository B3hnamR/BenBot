from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(..., alias="BOT_TOKEN")
    owner_user_ids: List[int] = Field(default_factory=list, alias="BOT_OWNER_USER_IDS")

    db_host: str = Field("mariadb", alias="DB_HOST")
    db_port: int = Field(3306, alias="DB_PORT")
    db_user: str = Field("ben", alias="DB_USER")
    db_password: str = Field("ben", alias="DB_PASSWORD")
    db_name: str = Field("ben_bot", alias="DB_NAME")

    log_level: str = Field("INFO", alias="LOG_LEVEL")

    require_subscription_default: bool = Field(
        False,
        alias="REQUIRE_SUBSCRIPTION_DEFAULT",
        description="Toggle enforcing channel membership for new users.",
    )
    required_channels_default: List[str] = Field(
        default_factory=list,
        alias="REQUIRED_CHANNELS_DEFAULT",
        description="List of Telegram usernames/IDs required for subscription.",
    )

    membership_cache_ttl: int = Field(
        300,
        alias="MEMBERSHIP_CACHE_TTL",
        description="Number of seconds to cache membership status to reduce API calls.",
    )
    support_antispam_max_open_tickets: int = Field(
        5,
        alias="SUPPORT_ANTISPAM_MAX_OPEN_TICKETS",
        description="Maximum number of open support tickets per user (0 disables the check).",
    )
    support_antispam_max_tickets_per_window: int = Field(
        3,
        alias="SUPPORT_ANTISPAM_MAX_TICKETS_PER_WINDOW",
        description="Maximum number of tickets a user may create within the configured window (0 disables the check).",
    )
    support_antispam_window_minutes: int = Field(
        60,
        alias="SUPPORT_ANTISPAM_WINDOW_MINUTES",
        description="Time window in minutes for evaluating new ticket limits.",
    )
    support_antispam_min_reply_interval_seconds: int = Field(
        10,
        alias="SUPPORT_ANTISPAM_MIN_REPLY_INTERVAL_SECONDS",
        description="Minimum number of seconds between support messages from the same user (0 disables the check).",
    )

    payment_provider_token: str | None = Field(
        None,
        alias="PAYMENT_PROVIDER_TOKEN",
        description="Telegram payment provider token obtained from BotFather.",
    )
    payment_currency: str = Field(
        "USD",
        alias="PAYMENT_CURRENCY",
        description="Default ISO 4217 currency code for invoices.",
    )
    invoice_payment_timeout_minutes: int = Field(
        30,
        alias="INVOICE_PAYMENT_TIMEOUT_MINUTES",
        description="How long an invoice stays valid before expiring.",
    )
    oxapay_api_key: str | None = Field(
        None,
        alias="OXAPAY_API_KEY",
        description="Merchant API key for OxaPay.",
    )
    oxapay_base_url: str = Field(
        "https://api.oxapay.com/v1",
        alias="OXAPAY_BASE_URL",
        description="Base URL for OxaPay API calls.",
    )
    oxapay_checkout_base_url: str = Field(
        "https://pay.oxapay.com",
        alias="OXAPAY_CHECKOUT_BASE_URL",
        description="Base URL for constructing public OxaPay checkout links.",
    )
    oxapay_sandbox: bool = Field(
        False,
        alias="OXAPAY_SANDBOX",
        description="Run OxaPay requests in sandbox mode.",
    )
    oxapay_default_currencies: List[str] = Field(
        default_factory=list,
        alias="OXAPAY_DEFAULT_CURRENCIES",
        description="Comma separated list of crypto currencies enabled by default.",
    )
    oxapay_invoice_lifetime_minutes: int = Field(
        60,
        alias="OXAPAY_INVOICE_LIFETIME_MINUTES",
        description="Default expiration time for OxaPay invoices (minutes).",
    )
    oxapay_mixed_payment: bool = Field(
        True,
        alias="OXAPAY_MIXED_PAYMENT",
        description="Allow buyers to complete payment with multiple currencies.",
    )
    oxapay_fee_payer: str = Field(
        "payer",
        alias="OXAPAY_FEE_PAYER",
        description="Who covers OxaPay fee: 'payer' or 'merchant'.",
    )
    oxapay_underpaid_coverage: float = Field(
        0,
        alias="OXAPAY_UNDERPAID_COVERAGE",
        description="Accepted underpaid coverage percentage.",
    )
    oxapay_auto_withdrawal: bool = Field(
        False,
        alias="OXAPAY_AUTO_WITHDRAWAL",
        description="Enable automatic withdrawal for settled funds.",
    )
    oxapay_to_currency: str | None = Field(
        None,
        alias="OXAPAY_TO_CURRENCY",
        description="Destination currency to auto-convert payments to (e.g., USDT).",
    )
    oxapay_return_url: str | None = Field(
        None,
        alias="OXAPAY_RETURN_URL",
        description="Default URL for redirecting users after successful payment.",
    )
    oxapay_callback_url: str | None = Field(
        None,
        alias="OXAPAY_CALLBACK_URL",
        description="Default webhook URL for OxaPay callbacks.",
    )
    oxapay_callback_secret: str | None = Field(
        None,
        alias="OXAPAY_CALLBACK_SECRET",
        description="Secret used to validate OxaPay webhook signatures.",
    )

    @field_validator("owner_user_ids", mode="before")
    @classmethod
    def split_owner_ids(cls, value: str | List[int]) -> List[int]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        items = [item.strip() for item in str(value).split(",") if item.strip()]
        return [int(item) for item in items]

    @field_validator("required_channels_default", mode="before")
    @classmethod
    def split_required_channels(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @field_validator("oxapay_default_currencies", mode="before")
    @classmethod
    def split_oxapay_currencies(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        return [item.strip().upper() for item in str(value).split(",") if item.strip()]

    @field_validator("oxapay_fee_payer")
    @classmethod
    def normalise_fee_payer(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if value not in {"payer", "merchant"}:
            return "merchant"
        return value

    @property
    def db_async_url(self) -> str:
        return (
            f"mysql+asyncmy://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def db_sync_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
