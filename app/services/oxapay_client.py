from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx


class OxapayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


@dataclass
class OxapayInvoice:
    track_id: str
    pay_link: str | None
    status: str | None
    amount: float | None
    currency: str | None
    expires_at: datetime | None
    data: dict[str, Any]


@dataclass
class OxapayPayment:
    track_id: str
    status: str
    amount: float | None
    currency: str | None
    expired_at: datetime | None
    mixed_payment: bool | None
    fee_paid_by_payer: float | None
    transactions: list[dict[str, Any]]
    data: dict[str, Any]


class OxapayClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.oxapay.com/v1",
        timeout: float = 15.0,
    ) -> None:
        if not api_key:
            raise ValueError("OxaPay API key is required.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def create_invoice(self, payload: dict[str, Any]) -> OxapayInvoice:
        response = await self._request("POST", "/payment/create", json=payload)
        data = response.get("data") or {}
        return self._parse_invoice(data)

    async def get_payment(self, track_id: str) -> OxapayPayment:
        response = await self._request("GET", f"/payment/{track_id}")
        data = response.get("data") or {}
        return self._parse_payment(data)

    async def get_accepted_currencies(self) -> list[str]:
        response = await self._request("GET", "/payment/accepted-currencies")
        data = response.get("data") or {}
        currencies: Iterable[str] = data.get("list") or []
        return [str(item).strip().upper() for item in currencies if str(item).strip()]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "merchant_api_key": self._api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        ) as client:
            response = await client.request(
                method=method,
                url=path,
                json=json,
                params=params,
                headers=headers,
            )
        content = self._safe_json(response)
        status = content.get("status")
        if response.status_code >= 400 or (status is not None and int(status) >= 400):
            message = content.get("message") or f"OxaPay request failed with status {response.status_code}"
            raise OxapayError(message, status_code=response.status_code, payload=content)
        return content

    @staticmethod
    def _parse_invoice(data: dict[str, Any]) -> OxapayInvoice:
        return OxapayInvoice(
            track_id=str(data.get("track_id")),
            pay_link=data.get("pay_link") or data.get("payment_url") or data.get("link"),
            status=data.get("status"),
            amount=_safe_float(data.get("amount")),
            currency=(data.get("currency") or "").upper() or None,
            expires_at=_parse_timestamp(data.get("expired_at")),
            data=data,
        )

    @staticmethod
    def _parse_payment(data: dict[str, Any]) -> OxapayPayment:
        return OxapayPayment(
            track_id=str(data.get("track_id")),
            status=str(data.get("status") or "unknown"),
            amount=_safe_float(data.get("amount")),
            currency=(data.get("currency") or "").upper() or None,
            expired_at=_parse_timestamp(data.get("expired_at")),
            mixed_payment=_safe_bool(data.get("mixed_payment")),
            fee_paid_by_payer=_safe_float(data.get("fee_paid_by_payer")),
            transactions=list(data.get("txs") or []),
            data=data,
        )

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            raise OxapayError("Invalid JSON response from OxaPay.", status_code=response.status_code) from exc


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str) and value.isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return None
