from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SettingKey
from app.infrastructure.db.repositories import SettingsRepository


@dataclass(slots=True)
class TimelineStatusDefinition:
    key: str
    label: str
    notify_user: bool = False
    user_message: str | None = None
    show_in_menu: bool = True
    show_in_filters: bool = True
    locked: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "notify_user": bool(self.notify_user),
            "user_message": self.user_message,
            "show_in_menu": bool(self.show_in_menu),
            "show_in_filters": bool(self.show_in_filters),
            "locked": bool(self.locked),
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TimelineStatusDefinition":
        return cls(
            key=str(data.get("key") or "").strip(),
            label=str(data.get("label") or "").strip() or "Update",
            notify_user=bool(data.get("notify_user", False)),
            user_message=data.get("user_message"),
            show_in_menu=bool(data.get("show_in_menu", True)),
            show_in_filters=bool(data.get("show_in_filters", True)),
            locked=bool(data.get("locked", False)),
        )


def _default_statuses() -> list[TimelineStatusDefinition]:
    return [
        TimelineStatusDefinition(
            key="processing",
            label="Processing",
            notify_user=True,
            user_message=(
                "Order <code>{order_id}</code> is now being processed.\n"
                "We'll let you know as soon as it ships."
            ),
            show_in_menu=True,
            show_in_filters=True,
            locked=True,
        ),
        TimelineStatusDefinition(
            key="shipping",
            label="Shipping",
            notify_user=True,
            user_message=(
                "Great news! Order <code>{order_id}</code> is on its way.\n"
                "We'll notify you once it has been delivered."
            ),
            show_in_menu=True,
            show_in_filters=True,
            locked=True,
        ),
        TimelineStatusDefinition(
            key="delivered",
            label="Delivered",
            notify_user=True,
            user_message=(
                "Order <code>{order_id}</code> has been delivered.\n"
                "If you need anything else, just let us know."
            ),
            show_in_menu=True,
            show_in_filters=True,
            locked=True,
        ),
        TimelineStatusDefinition(
            key="cancelled",
            label="Cancelled",
            notify_user=False,
            user_message=None,
            show_in_menu=True,
            show_in_filters=True,
            locked=True,
        ),
    ]


class TimelineStatusRegistry:
    _statuses: list[TimelineStatusDefinition] = []
    _index: dict[str, TimelineStatusDefinition] = {}

    @classmethod
    def set_statuses(cls, statuses: Sequence[TimelineStatusDefinition]) -> None:
        cls._statuses = list(statuses)
        cls._index = {status.key: status for status in cls._statuses}

    @classmethod
    def ensure_defaults(cls) -> None:
        if cls._statuses:
            return
        cls.set_statuses(_default_statuses())

    @classmethod
    def all(cls) -> list[TimelineStatusDefinition]:
        if not cls._statuses:
            cls.ensure_defaults()
        return list(cls._statuses)

    @classmethod
    def get(cls, key: str | None) -> TimelineStatusDefinition | None:
        if not key:
            return None
        if not cls._statuses:
            cls.ensure_defaults()
        return cls._index.get(key)

    @classmethod
    def show_in_menu(cls) -> list[TimelineStatusDefinition]:
        return [status for status in cls.all() if status.show_in_menu]

    @classmethod
    def show_in_filters(cls) -> list[TimelineStatusDefinition]:
        return [status for status in cls.all() if status.show_in_filters]

    @classmethod
    def label(cls, key: str | None) -> str | None:
        status = cls.get(key)
        return status.label if status else None

    @classmethod
    def notify_enabled(cls, key: str | None) -> bool:
        status = cls.get(key)
        return bool(status and status.notify_user)


class TimelineStatusService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = SettingsRepository(session)

    async def ensure_defaults(self) -> list[TimelineStatusDefinition]:
        statuses = await self._load_from_store()
        if not statuses:
            statuses = _default_statuses()
            await self._persist(statuses)
        else:
            TimelineStatusRegistry.set_statuses(statuses)
        return statuses

    async def list_statuses(self) -> list[TimelineStatusDefinition]:
        statuses = await self._load_from_store()
        if not statuses:
            return await self.ensure_defaults()
        TimelineStatusRegistry.set_statuses(statuses)
        return statuses

    async def add_status(
        self,
        key: str,
        *,
        label: str,
        notify_user: bool = False,
        show_in_menu: bool = True,
        show_in_filters: bool = True,
        user_message: str | None = None,
    ) -> TimelineStatusDefinition:
        key_normalized = self._normalize_key(key)
        if not key_normalized:
            raise ValueError("Status key is required.")
        statuses = await self.list_statuses()
        if any(status.key == key_normalized for status in statuses):
            raise ValueError("Status key already exists.")
        definition = TimelineStatusDefinition(
            key=key_normalized,
            label=label.strip() or key_normalized.replace("_", " ").title(),
            notify_user=notify_user,
            show_in_menu=show_in_menu,
            show_in_filters=show_in_filters,
            user_message=user_message,
        )
        statuses.append(definition)
        await self._persist(statuses)
        return definition

    async def update_status(self, key: str, **fields: Any) -> TimelineStatusDefinition:
        key_normalized = self._normalize_key(key)
        statuses = await self.list_statuses()
        updated = None
        for idx, status in enumerate(statuses):
            if status.key != key_normalized:
                continue
            data = status.to_mapping()
            data.update(fields)
            if status.locked:
                data["locked"] = True
            updated = TimelineStatusDefinition.from_mapping(data)
            statuses[idx] = updated
            break
        if updated is None:
            raise ValueError("Status not found.")
        await self._persist(statuses)
        return updated

    async def delete_status(self, key: str) -> bool:
        key_normalized = self._normalize_key(key)
        statuses = await self.list_statuses()
        filtered: list[TimelineStatusDefinition] = []
        removed = False
        for status in statuses:
            if status.key != key_normalized:
                filtered.append(status)
                continue
            if status.locked:
                raise ValueError("This status cannot be removed.")
            removed = True
        if not removed:
            raise ValueError("Status not found.")
        await self._persist(filtered)
        return True

    async def reset_defaults(self) -> list[TimelineStatusDefinition]:
        statuses = _default_statuses()
        await self._persist(statuses)
        return statuses

    async def _load_from_store(self) -> list[TimelineStatusDefinition]:
        raw = await self._settings.get_value(SettingKey.ORDER_TIMELINE_STATUSES)
        return self._parse_payload(raw)

    async def _persist(self, statuses: Sequence[TimelineStatusDefinition]) -> None:
        payload = [status.to_mapping() for status in statuses]
        await self._settings.upsert(SettingKey.ORDER_TIMELINE_STATUSES, payload)
        TimelineStatusRegistry.set_statuses(statuses)

    @staticmethod
    def _parse_payload(raw: Any) -> list[TimelineStatusDefinition]:
        if not isinstance(raw, Iterable):
            return []
        statuses: list[TimelineStatusDefinition] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            definition = TimelineStatusDefinition.from_mapping(item)
            if not definition.key:
                continue
            statuses.append(definition)
        return statuses

    @staticmethod
    def _normalize_key(value: str) -> str:
        normalized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.strip().lower())
        normalized = normalized.strip("_")
        return normalized
