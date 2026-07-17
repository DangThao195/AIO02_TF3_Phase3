# tools/shipping_tool.py
from __future__ import annotations

import json
import requests
from langchain_core.tools import tool

from src.tools.service_config import SHIPPING_ADDR as SHIPPING_REST_ADDR


@tool
def get_shipping_quote_tool(
    address: str = "",
    destination: str = "",
    street: str = "",
    city: str = "",
    country: str = "",
    zip_code: str = "",
    state: str = "",
    product_id: str = "",
    quantity: int = 1,
) -> str:
    """
    Get a shipping estimate for a domestic delivery.
    Accepts either a free-form address or structured address fields.
    """
    if country and country.lower() != "vietnam":
        return "I am only authorized to estimate shipping costs for domestic deliveries within Vietnam."

    normalized_address = (address or destination or "").strip()
    if not normalized_address:
        structured = [street, city, state, zip_code, country]
        normalized_address = ", ".join(part.strip() for part in structured if part and part.strip())

    params = {
        "address": normalized_address,
        "street": street,
        "city": city,
        "state": state,
        "country": country,
        "zip_code": zip_code,
        "product_id": product_id,
        "quantity": quantity,
    }
    params = {
        key: value
        for key, value in params.items()
        if value not in ("", None, 0)
    }

    try:
        response = requests.get(
            f"{SHIPPING_REST_ADDR}/api/v1/shipping/quote",
            params=params,
            timeout=5,
        )
        response.raise_for_status()

        data = response.json()
        cost_info = data.get("cost_usd", {})
        units = cost_info.get("units", 0)
        nanos = cost_info.get("nanos", 0)
        currency_code = cost_info.get("currency_code", "USD")
        shipping_fee = float(units) + (float(nanos) / 1_000_000_000)

        payload = {
            "shipping_fee": round(shipping_fee, 2),
            "currency_code": currency_code,
            "address": normalized_address,
        }
        if "shipping_days" in data:
            payload["estimated_days"] = data.get("shipping_days")
        if "carrier" in data:
            payload["carrier"] = data.get("carrier")

        return json.dumps(payload, ensure_ascii=False)
    except requests.exceptions.RequestException as e:
        return f"System error when estimating shipping cost (REST Service on EKS): {str(e)}"
    except ValueError:
        return "Error: Received invalid JSON data from the REST shipping service on EKS Cluster."
