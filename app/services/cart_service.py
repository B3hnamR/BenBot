from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CartAdjustmentType, CartStatus
from app.infrastructure.db.models import CartAdjustment, CartItem, Product, ShoppingCart
from app.infrastructure.db.repositories import CartRepository, ProductRepository


@dataclass(slots=True)
class CartTotals:
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    shipping: Decimal
    total: Decimal


class CartService:
    """
    High-level cart orchestrator responsible for item management, pricing, and checkout preparation.

    The service keeps business logic separated from handlers so both bot flows and future APIs
    can rely on the same behaviour.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._carts = CartRepository(session)
        self._products = ProductRepository(session)

    async def get_cart_by_public_id(self, public_id: str) -> ShoppingCart | None:
        return await self._carts.get_by_public_id(public_id)

    async def get_active_cart(self, user_id: int, *, currency: str | None = None) -> ShoppingCart | None:
        cart = await self._carts.get_active_for_user(user_id)
        if cart and currency and cart.currency != currency:
            # Currency mismatch implies the cart must be rebuilt.
            await self.deactivate_cart(cart)
            return None
        return cart

    async def get_or_create_cart(
        self,
        *,
        user_id: int,
        currency: str,
        expires_at: datetime | None = None,
    ) -> ShoppingCart:
        cart = await self._carts.get_active_for_user(user_id)
        if cart:
            return cart
        cart = await self._carts.create_cart(
            user_id=user_id,
            currency=currency,
            expires_at=expires_at,
        )
        await self._session.flush()
        return cart

    async def add_product(
        self,
        cart: ShoppingCart,
        product: Product,
        *,
        quantity: int = 1,
        allow_increase: bool = True,
    ) -> CartItem:
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
        if not product.is_active:
            raise ValueError("Product is inactive.")
        unit_price = Decimal(product.price)
        currency = product.currency
        if cart.currency != currency:
            raise ValueError("Cart currency mismatch. Start a new cart before adding this product.")

        existing = await self._carts.get_item(cart, product.id)
        if existing:
            if not allow_increase:
                raise ValueError("Product already in cart.")
            new_quantity = existing.quantity + quantity
            self._ensure_quantity_allowed(product, new_quantity)
            total_amount = self._calc_line_total(unit_price, new_quantity)
            await self._carts.update_item(
                existing,
                quantity=new_quantity,
                total_amount=total_amount,
            )
            item = existing
        else:
            self._ensure_quantity_allowed(product, quantity)
            await self._session.refresh(cart, attribute_names=["items"])
            position = len(cart.items)
            total_amount = self._calc_line_total(unit_price, quantity)
            item = await self._carts.create_item(
                cart,
                product_id=product.id,
                quantity=quantity,
                unit_price=unit_price,
                currency=currency,
                total_amount=total_amount,
                position=position,
            )

        await self.refresh_totals(cart)
        await self._session.flush()
        return item

    async def update_quantity(self, cart: ShoppingCart, product: Product, quantity: int) -> CartItem | None:
        if quantity < 0:
            raise ValueError("Quantity cannot be negative.")
        item = await self._carts.get_item(cart, product.id)
        if item is None:
            return None
        if quantity == 0:
            await self._carts.remove_item(item)
            await self.refresh_totals(cart)
            await self._session.flush()
            return None
        self._ensure_quantity_allowed(product, quantity)
        total_amount = self._calc_line_total(item.unit_price, quantity)
        await self._carts.update_item(item, quantity=quantity, total_amount=total_amount)
        await self.refresh_totals(cart)
        await self._session.flush()
        return item

    async def remove_product(self, cart: ShoppingCart, product_id: int) -> None:
        item = await self._carts.get_item(cart, product_id)
        if item is None:
            return
        await self._carts.remove_item(item)
        await self.refresh_totals(cart)
        await self._session.flush()

    async def clear_cart(self, cart: ShoppingCart) -> None:
        await self._carts.clear_items(cart)
        await self._carts.clear_adjustments(cart)
        await self._carts.set_totals(
            cart,
            subtotal=Decimal("0.00"),
            discount=Decimal("0.00"),
            tax=Decimal("0.00"),
            shipping=Decimal("0.00"),
            total=Decimal("0.00"),
        )
        await self._session.flush()

    async def set_discount_code(self, cart: ShoppingCart, code: str | None) -> ShoppingCart:
        await self._carts.set_discount_code(cart, code)
        await self._session.flush()
        return cart

    async def refresh_totals(self, cart: ShoppingCart) -> CartTotals:
        await self._session.refresh(cart, attribute_names=["items", "adjustments"])
        subtotal = sum((item.total_amount for item in cart.items), start=Decimal("0.00"))
        discount = sum(
            (adj.amount for adj in cart.adjustments if adj.kind == CartAdjustmentType.PROMOTION),
            start=Decimal("0.00"),
        )
        tax = sum(
            (adj.amount for adj in cart.adjustments if adj.kind == CartAdjustmentType.TAX),
            start=Decimal("0.00"),
        )
        shipping = sum(
            (adj.amount for adj in cart.adjustments if adj.kind == CartAdjustmentType.SHIPPING),
            start=Decimal("0.00"),
        )
        total = (subtotal + tax + shipping) - discount
        totals = CartTotals(
            subtotal=self._quantize(subtotal),
            discount=self._quantize(discount),
            tax=self._quantize(tax),
            shipping=self._quantize(shipping),
            total=self._quantize(total),
        )
        await self._carts.set_totals(
            cart,
            subtotal=totals.subtotal,
            discount=totals.discount,
            tax=totals.tax,
            shipping=totals.shipping,
            total=totals.total,
        )
        return totals

    async def deactivate_cart(self, cart: ShoppingCart) -> ShoppingCart:
        await self._carts.set_status(cart, CartStatus.ABANDONED)
        await self._session.flush()
        return cart

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
        adjustment = await self._carts.add_adjustment(
            cart,
            kind=kind,
            amount=self._quantize(amount),
            code=code,
            title=title,
            meta=meta,
        )
        await self.refresh_totals(cart)
        await self._session.flush()
        return adjustment

    async def remove_adjustment(self, adjustment: CartAdjustment, cart: ShoppingCart) -> None:
        await self._carts.remove_adjustment(adjustment)
        await self.refresh_totals(cart)
        await self._session.flush()

    async def fetch_product(self, product_id: int) -> Product | None:
        return await self._products.get_by_id(product_id)

    @staticmethod
    def _calc_line_total(unit_price: Decimal, quantity: int) -> Decimal:
        return CartService._quantize(unit_price * quantity)

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _ensure_quantity_allowed(product: Product, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")

        max_per_order = getattr(product, "max_per_order", None)
        if max_per_order is not None and quantity > max_per_order:
            raise ValueError("Requested quantity exceeds per-order limit for this product.")

        inventory = getattr(product, "inventory", None)
        if inventory is not None and quantity > inventory:
            raise ValueError("Requested quantity exceeds available stock.")

        bundle_components = getattr(product, "bundle_components", None) or []
        if bundle_components:
            for component_link in bundle_components:
                component = getattr(component_link, "component", None)
                if component is None:
                    continue
                component_inventory = getattr(component, "inventory", None)
                component_quantity = getattr(component_link, "quantity", 1) or 1
                if component_inventory is None:
                    continue
                required = quantity * component_quantity
                if required > component_inventory:
                    raise ValueError(
                        "Not enough inventory for bundle components."
                    )
