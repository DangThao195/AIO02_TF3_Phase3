# tools/shipping_tool.py
import requests
from langchain_core.tools import tool

# Endpoint for the REST service, mapped via port-forward 50051:50051
import os
SHIPPING_REST_ADDR = os.getenv("SHIPPING_ADDR", "http://shipping:50051")

@tool
def get_shipping_quote_tool(street: str, city: str, country: str, zip_code: str, state: str = "") -> str:
    """
    (Rest-based Intent - Extended)
    Use this REST tool (HTTP/1.1) to get estimated shipping costs based on the delivery address.
    Do not use as a gRPC tool. Required input: street, city, country, zip_code.
    """
    # 🛡️ Guardrail Check: Only authorized for deliveries within Vietnam
    if country.lower() != "vietnam":
        return "I am only authorized to estimate shipping costs for domestic deliveries within Vietnam."

    # 🛠️ REST GET parameters matching Member 2/3's structure
    # (Removed product_id as it's not defined in the provided proto context for this intent)
    params = {
        "street": street,
        "city": city,
        "state": state,
        "country": country,
        "zip_code": zip_code,
    }

    try:
        # Execute the REST GET Request to the local port-forwarded service
        response = requests.get(
            f"{SHIPPING_REST_ADDR}/api/v1/shipping/quote",
            params=params,
            timeout=5
        )
        
        # Check for HTTP errors (like 404, 500)
        response.raise_for_status() 
        
        # Parse the JSON response
        data = response.json()
        
        # Extract the Money object data (assuming it returns JSON matching demo.Money fields)
        cost_info = data.get("cost_usd", {})
        units = cost_info.get("units", "0")
        currency_code = cost_info.get("currency_code", "USD")
        
        return f"Estimated shipping cost for domestic delivery within Vietnam obtained from AWS Cloud: {units} {currency_code}."
        
    except requests.exceptions.RequestException as e:
        return f"System error when estimating shipping cost (REST Service on EKS): {str(e)}"
    except ValueError:
        return f"Error: Received invalid JSON data from the REST shipping service on EKS Cluster."