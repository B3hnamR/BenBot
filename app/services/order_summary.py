from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.infrastructure.db.models import Order


@dataclass(slots=True)
class OrderSummary:
    label: str
    inline: str
    item_lines: list[str]
    totals_lines: list[str]
    has_cart_items: bool


def build_order_summary(order: Order) -> OrderSummary:
    extra = order.extra_attrs or {}
    items = _normalize_items(extra.get("cart_items"))
    totals = _normalize_totals(extra.get("cart_totals"))

    if items:
        inline = "; ".join(_format_inline_item(item) for item in items)
        item_lines = [
            _format_detailed_item(index, item, fallback_currency=order.currency)
            for index, item in enumerate(items, start=1)
        ]
        totals_lines = _format_totals(totals, currency=order.currency, fallback_total=str(order.total_amount))
        return OrderSummary(
            label=inline,
            inline=inline,
            item_lines=item_lines,
            totals_lines=totals_lines,
            has_cart_items=True,
        )

    product_name = getattr(order.product, "name", "product")
    totals_lines = [f"Total: {order.total_amount} {order.currency}"]
    return OrderSummary(
        label=product_name,
        inline=product_name,
        item_lines=[],
        totals_lines=totals_lines,
        has_cart_items=False,
    )


def _normalize_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, dict):
            items.append(entry)
    return items


def _normalize_totals(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        result[str(key)] = str(value)
    return result


def _format_inline_item(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "Item")
    quantity = item.get("quantity")
    if quantity is None:
        return name
    try:
        qty_value = int(quantity)
        return f"{name} x{qty_value}"
    except (TypeError, ValueError):
        return f"{name} x{quantity}"


def _format_detailed_item(
    index: int,
    item: dict[str, Any],
    *,
    fallback_currency: str,
) -> str:
    name = str(item.get("name") or "Item")
    quantity = item.get("quantity") or 1
    try:
        quantity_int = int(quantity)
    except (TypeError, ValueError):
        quantity_repr = str(quantity)
    else:
        quantity_repr = str(quantity_int)

    total_amount = item.get("total_amount")
    currency = str(item.get("currency") or fallback_currency)

    line = f"{index}. {name} x{quantity_repr}"
    if total_amount:
        line += f" - {total_amount} {currency}"
    return line


def _format_totals(
    totals: dict[str, str],
    *,
    currency: str,
    fallback_total: str,
) -> list[str]:
    if not totals:
        return [f"Total: {fallback_total} {currency}"]

    lines: list[str] = []
    subtotal = totals.get("subtotal")
    discount = totals.get("discount")
    tax = totals.get("tax")
    shipping = totals.get("shipping")
    total = totals.get("total")

    if subtotal:
        lines.append(f"Subtotal: {subtotal} {currency}")
    if discount and _is_nonzero(discount):
        lines.append(f"Discounts: -{discount} {currency}")
    if tax and _is_nonzero(tax):
        lines.append(f"Tax: {tax} {currency}")
    if shipping and _is_nonzero(shipping):
        lines.append(f"Shipping: {shipping} {currency}")

    if total:
        lines.append(f"Total: {total} {currency}")
    else:
        lines.append(f"Total: {fallback_total} {currency}")
    return lines


def _is_nonzero(value: str) -> bool:
    try:
        return Decimal(value) != 0
    except (InvalidOperation, TypeError, ValueError):
        return bool(value)
