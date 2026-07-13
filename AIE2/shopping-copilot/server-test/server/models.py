from dataclasses import dataclass


@dataclass
class ProductReview:
    id: int
    product_id: str
    username: str
    description: str
    score: float


@dataclass
class Product:
    id: str
    name: str
    description: str
    picture: str
    price_currency_code: str
    price_units: int
    price_nanos: int
    categories: str


@dataclass
class Order:
    order_id: str


@dataclass
class OrderItem:
    product_id: str
    quantity: int
    cost_currency_code: str
    cost_units: int
    cost_nanos: int
    order_id: str


@dataclass
class Shipping:
    shipping_tracking_id: str
    shipping_cost_currency_code: str
    shipping_cost_units: int
    shipping_cost_nanos: int
    street_address: str
    city: str
    state: str
    country: str
    zip_code: str
    order_id: str
