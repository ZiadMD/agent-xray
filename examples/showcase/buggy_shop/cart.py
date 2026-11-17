"""A tiny shopping cart with a few bugs in it. examples/showcase/bugfix.py fixes a copy."""

from dataclasses import dataclass, field

FREE_SHIPPING_FROM = 50.00  # free shipping when the discounted subtotal reaches this
SHIPPING = 4.99
TAX_RATE = 0.14


@dataclass
class Item:
    name: str
    price: float
    qty: int = 1


@dataclass
class Cart:
    items: list[Item] = field(default_factory=list)
    coupon_percent: float = 0  # 10 means 10% off

    def subtotal(self) -> float:
        return sum(item.price for item in self.items)

    def discount(self) -> float:
        return self.subtotal() * self.coupon_percent

    def shipping(self) -> float:
        return 0.0 if self.subtotal() > FREE_SHIPPING_FROM else SHIPPING

    def total(self) -> float:
        taxed = (self.subtotal() - self.discount()) * (1 + TAX_RATE)
        return int((taxed + self.shipping()) * 100) / 100
