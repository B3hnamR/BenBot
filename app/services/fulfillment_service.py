from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.infrastructure.db.models import Order


@dataclass(slots=True)
class FulfillmentActionResult:
    action: str
    status: str
    detail: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class FulfillmentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._log = get_logger(__name__)

    async def execute(self, order: Order, bot: Bot) -> dict[str, Any]:
        plan = self._extract_plan(order)
        results: list[FulfillmentActionResult] = []
        if not plan:
            return {"actions": results, "context": {}, "success": True}

        context = self._build_context(order)
        success = True

        for index, raw_action in enumerate(plan, start=1):
            action_type = str(raw_action.get("action", "")).strip().lower()
            handler_name = f"_handle_{action_type}"

            if not action_type or not hasattr(self, handler_name):
                message = f"Unknown fulfillment action: {action_type or '?'}"
                self._log.warning(
                    "fulfillment_unknown_action",
                    order_id=order.id,
                    index=index,
                    action=action_type,
                )
                results.append(
                    FulfillmentActionResult(
                        action=action_type or "?",
                        status="skipped",
                        error=message,
                    )
                )
                success = False
                continue

            handler = getattr(self, handler_name)
            try:
                result = await handler(order, bot, raw_action, context)
                results.append(result)
                if result.status != "completed":
                    success = False
            except Exception as exc:  # noqa: BLE001
                self._log.exception(
                    "fulfillment_action_failed",
                    order_id=order.id,
                    action=action_type,
                    error=str(exc),
                )
                results.append(
                    FulfillmentActionResult(
                        action=action_type,
                        status="failed",
                        error=str(exc),
                    )
                )
                success = False

        return {
            "actions": [result.__dict__ for result in results],
            "context": context,
            "success": success,
        }

    @staticmethod
    def _extract_plan(order: Order) -> list[dict[str, Any]]:
        product = order.product
        if product is None:
            return []
        attrs = product.extra_attrs or {}
        plan = attrs.get("fulfillment_plan")
        if isinstance(plan, list):
            return [step for step in plan if isinstance(step, dict)]
        return []

    @staticmethod
    def _build_context(order: Order) -> dict[str, Any]:
        context: dict[str, Any] = {
            "order_id": order.id,
            "order_public_id": order.public_id,
            "user_id": order.user_id,
            "amount": float(order.total_amount),
            "currency": order.currency,
            "product_id": getattr(order.product, "id", None),
            "product_name": getattr(order.product, "name", ""),
        }
        return context

    async def _handle_generate_license(
        self,
        order: Order,
        _: Bot,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> FulfillmentActionResult:
        length = int(action.get("length") or 16)
        prefix = str(action.get("prefix") or "")
        charset = str(action.get("charset") or "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        code = prefix + "".join(secrets.choice(charset) for _ in range(length))

        context["license_code"] = code
        return FulfillmentActionResult(
            action="generate_license",
            status="completed",
            detail="License code generated.",
            metadata={"license_code": code},
        )

    async def _handle_send_text(
        self,
        order: Order,
        bot: Bot,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> FulfillmentActionResult:
        text_template = action.get("text")
        if not text_template:
            return FulfillmentActionResult(
                action="send_text",
                status="skipped",
                error="Missing 'text' in action.",
            )

        if order.user is None or order.user.telegram_id is None:
            return FulfillmentActionResult(
                action="send_text",
                status="failed",
                error="Missing user information for text delivery.",
            )

        text = self._render_template(str(text_template), context)
        await bot.send_message(order.user.telegram_id, text)
        return FulfillmentActionResult(
            action="send_text",
            status="completed",
            detail="Message sent to user.",
        )

    async def _handle_send_file(
        self,
        order: Order,
        bot: Bot,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> FulfillmentActionResult:
        file_id = action.get("file_id")
        file_path = action.get("file_path")
        caption = self._render_template(str(action.get("caption") or ""), context)

        if not file_id and not file_path:
            return FulfillmentActionResult(
                action="send_file",
                status="skipped",
                error="Either 'file_id' or 'file_path' must be provided.",
            )

        if order.user is None or order.user.telegram_id is None:
            return FulfillmentActionResult(
                action="send_file",
                status="failed",
                error="Missing user information for file delivery.",
            )

        if file_id:
            await bot.send_document(order.user.telegram_id, file_id, caption=caption or None)
            return FulfillmentActionResult(
                action="send_file",
                status="completed",
                detail="Document sent via file_id.",
            )

        resolved = Path(str(file_path)).expanduser()
        if not resolved.exists():
            return FulfillmentActionResult(
                action="send_file",
                status="failed",
                error=f"File not found: {resolved}",
            )

        await bot.send_document(order.user.telegram_id, resolved, caption=caption or None)
        return FulfillmentActionResult(
            action="send_file",
            status="completed",
            detail=f"Document sent from path {resolved}.",
        )

    async def _handle_webhook(
        self,
        order: Order,
        _: Bot,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> FulfillmentActionResult:
        url = action.get("url")
        if not url:
            return FulfillmentActionResult(
                action="webhook",
                status="skipped",
                error="Missing webhook URL.",
            )

        method = str(action.get("method") or "POST").upper()
        headers = action.get("headers") or {}
        payload_template = action.get("payload")
        payload = None
        if isinstance(payload_template, (dict, list, str, int, float, bool)):
            payload = self._render_structure(payload_template, context)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(method, url, json=payload, headers=headers or None)
            status = response.status_code

        if status >= 400:
            return FulfillmentActionResult(
                action="webhook",
                status="failed",
                error=f"Webhook responded with status {status}",
                metadata={"status_code": status},
            )

        return FulfillmentActionResult(
            action="webhook",
            status="completed",
            detail=f"Webhook executed ({status}).",
            metadata={"status_code": status},
        )

    @staticmethod
    def _render_template(template: str, context: dict[str, Any]) -> str:
        try:
            return template.format_map(_SafeDict(context))
        except Exception:
            return template

    def _render_structure(self, data: Any, context: dict[str, Any]) -> Any:
        if isinstance(data, str):
            return self._render_template(data, context)
        if isinstance(data, list):
            return [self._render_structure(item, context) for item in data]
        if isinstance(data, dict):
            return {key: self._render_structure(value, context) for key, value in data.items()}
        return data


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
