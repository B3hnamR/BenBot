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
