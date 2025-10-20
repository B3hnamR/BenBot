from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from app.core.enums import CartAdjustmentType, CartStatus
from app.infrastructure.db.models import CartAdjustment, CartItem, ShoppingCart

from .base import BaseRepository


class CartRepository(BaseRepository):
    async def create_cart(
        self,
        *,
        user_id: int | None,
        currency: str,
        expires_at: datetime | None = None,
        meta: dict | None = None,
    ) -> ShoppingCart:
        cart = ShoppingCart(
            public_id=str(uuid4()),
            user_id=user_id,
            status=CartStatus.ACTIVE,
            currency=currency,
            expires_at=expires_at,
            meta=meta,
        )
        await self.add(cart)
        return cart

    async def get_by_public_id(self, public_id: str, *, with_items: bool = True) -> ShoppingCart | None:
        stmt: Select[tuple[ShoppingCart]] = select(ShoppingCart).where(ShoppingCart.public_id == public_id)
        if with_items:
            stmt = stmt.options(
                selectinload(ShoppingCart.items).selectinload(CartItem.product),
                selectinload(ShoppingCart.adjustments),
            )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_active_for_user(self, user_id: int) -> ShoppingCart | None:
        result = await self.session.execute(
            select(ShoppingCart)
            .options(
                selectinload(ShoppingCart.items).selectinload(CartItem.product),
                selectinload(ShoppingCart.adjustments),
            )
            .where(
                ShoppingCart.user_id == user_id,
                ShoppingCart.status == CartStatus.ACTIVE,
            )
            .order_by(ShoppingCart.updated_at.desc())
            .limit(1)
        )
        return result.unique().scalar_one_or_none()

    async def list_items(self, cart: ShoppingCart) -> list[CartItem]:
        await self.session.refresh(cart, attribute_names=["items"])
        return list(cart.items)

    async def get_item(self, cart: ShoppingCart, product_id: int) -> CartItem | None:
        stmt = (
            select(CartItem)
            .where(CartItem.cart_id == cart.id, CartItem.product_id == product_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_item(
        self,
        cart: ShoppingCart,
        *,
        product_id: int,
        quantity: int,
        unit_price: Decimal,
        currency: str,
        total_amount: Decimal,
        position: int = 0,
        title_override: str | None = None,
        meta: dict | None = None,
    ) -> CartItem:
        item = CartItem(
            cart=cart,
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
            currency=currency,
            total_amount=total_amount,
            position=position,
            title_override=title_override,
            meta=meta,
        )
        await self.add(item)
        return item

    async def update_item(
        self,
        item: CartItem,
        *,
        quantity: int | None = None,
        unit_price: Decimal | None = None,
        total_amount: Decimal | None = None,
        meta: dict | None = None,
        position: int | None = None,
    ) -> CartItem:
        if quantity is not None:
            item.quantity = quantity
        if unit_price is not None:
            item.unit_price = unit_price
        if total_amount is not None:
            item.total_amount = total_amount
        if meta is not None:
            item.meta = meta
        if position is not None:
            item.position = position
        return item

    async def remove_item(self, item: CartItem) -> None:
        await self.session.delete(item)

    async def clear_items(self, cart: ShoppingCart) -> None:
        await self.session.refresh(cart, attribute_names=["items"])
        for item in list(cart.items):
            await self.session.delete(item)

    async def add_adjustment(
        self,
        cart: ShoppingCart,
        *,
        kind: CartAdjustmentType,
        amount: Decimal,
        code: str | None = None,
        title: str | None = None,
        meta: dict | None = None,
    ) -> CartAdjustment:
        adjustment = CartAdjustment(
            cart=cart,
            kind=kind,
            code=code,
            title=title,
            amount=amount,
            meta=meta,
        )
        await self.add(adjustment)
        return adjustment

    async def remove_adjustment(self, adjustment: CartAdjustment) -> None:
        await self.session.delete(adjustment)

    async def clear_adjustments(self, cart: ShoppingCart, *, of_kind: CartAdjustmentType | None = None) -> None:
        await self.session.refresh(cart, attribute_names=["adjustments"])
        for adjustment in list(cart.adjustments):
            if of_kind is None or adjustment.kind == of_kind:
                await self.session.delete(adjustment)

    async def set_totals(
        self,
        cart: ShoppingCart,
        *,
        subtotal: Decimal,
        discount: Decimal,
        tax: Decimal,
        shipping: Decimal,
        total: Decimal,
    ) -> ShoppingCart:
        cart.subtotal_amount = subtotal
        cart.discount_amount = discount
        cart.tax_amount = tax
        cart.shipping_amount = shipping
        cart.total_amount = total
        return cart

    async def set_status(self, cart: ShoppingCart, status: CartStatus) -> ShoppingCart:
        cart.status = status
        return cart

    async def set_discount_code(self, cart: ShoppingCart, code: str | None) -> ShoppingCart:
        cart.discount_code = code
        return cart
