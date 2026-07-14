"""Tool registry + safety gates for the Shopping Copilot (AIE2-TF3).

Verified against pb/demo.proto — every RPC the agent may call actually exists. The registry
is an ALLOWLIST: any tool not listed here is denied at execution time (excessive-agency guard).
Write actions (cart) require an explicit human confirmation token (Confirmation Gate).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ToolKind(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    rpc: str
    kind: ToolKind
    description: str


ALLOWED_TOOLS: dict[str, ToolSpec] = {
    "search_products": ToolSpec(
        "search_products", "ProductCatalogService.SearchProducts", ToolKind.READ,
        "Tìm sản phẩm theo từ khóa. LƯU Ý: RPC không lọc giá — lọc giá ở tầng agent."),
    "get_product": ToolSpec(
        "get_product", "ProductCatalogService.GetProduct", ToolKind.READ,
        "Lấy chi tiết 1 sản phẩm."),
    "get_reviews": ToolSpec(
        "get_reviews", "ProductReviewService.GetProductReviews", ToolKind.READ,
        "Lấy review thật của sản phẩm (nguồn sự thật cho Q&A)."),
    "ask_ai_assistant": ToolSpec(
        "ask_ai_assistant", "ProductReviewService.AskProductAIAssistant", ToolKind.READ,
        "Hỏi-đáp grounded trên review (đi qua AI gateway + guardrail)."),
    "get_recommendations": ToolSpec(
        "get_recommendations", "RecommendationService.ListRecommendations", ToolKind.READ,
        "Gợi ý sản phẩm liên quan."),
    "add_to_cart": ToolSpec(
        "add_to_cart", "CartService.AddItem", ToolKind.WRITE,
        "Thêm sản phẩm vào giỏ. BẮT BUỘC confirmation gate."),
    "get_cart": ToolSpec(
        "get_cart", "CartService.GetCart", ToolKind.READ,
        "Xem giỏ hàng hiện tại."),
}


FORBIDDEN_RPCS = frozenset({
    "CheckoutService.PlaceOrder",
    "PaymentService.Charge",
    "CartService.EmptyCart",
    "FeatureFlagService.UpdateFlag",
    "FeatureFlagService.CreateFlag",
    "FeatureFlagService.DeleteFlag",
})


class ToolDenied(Exception):
    """Raised when the agent attempts a tool outside the allowlist or without confirmation."""


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    confirmed: bool = False


def authorize(call: ToolCall) -> ToolSpec:
    """Gatekeeper. Returns the ToolSpec if allowed, else raises ToolDenied.

    Enforces: (1) allowlist membership, (2) never a forbidden RPC, (3) confirmation for writes.
    """
    spec = ALLOWED_TOOLS.get(call.name)
    if spec is None:
        raise ToolDenied(f"tool '{call.name}' is not in the allowlist")
    if spec.rpc in FORBIDDEN_RPCS:
        raise ToolDenied(f"rpc '{spec.rpc}' is hard-blocked (excessive agency / flagd)")
    if spec.kind is ToolKind.WRITE and not call.confirmed:
        raise ToolDenied(f"write action '{call.name}' requires human confirmation (gate)")
    return spec


def confirmation_prompt(call: ToolCall) -> str:
    """The message the UI shows on the Confirmation Gate before a write action executes."""
    if call.name == "add_to_cart":
        qty = call.args.get("quantity", 1)
        pid = call.args.get("product_id", "?")
        return f"Bạn có muốn thêm {qty} × sản phẩm {pid} vào giỏ? [Xác nhận] [Hủy]"
    return f"Xác nhận hành động '{call.name}'? [Xác nhận] [Hủy]"
