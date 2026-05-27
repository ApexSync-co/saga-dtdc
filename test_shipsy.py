import os
import json
import requests
from dotenv import load_dotenv

# 1. Load environment variables from local .env
load_dotenv()

shipsy_api_key = os.getenv('SHIPSY_API_KEY')
shipsy_customer_code = os.getenv('SHIPSY_CUSTOMER_CODE')
shipsy_url = os.getenv('SHIPSY_API_URL', "https://dtdcapi.shipsy.io/api/customer/integration/consignment/softdata")

print("==================================================")
print("       DTDC / Shipsy Consignment Test API")
print("==================================================")
print(f"URL: {shipsy_url}")
print(f"Customer Code: {shipsy_customer_code}")
print(f"API Key: {shipsy_api_key[:6]}..." if shipsy_api_key else "API Key: MISSING!")
print("--------------------------------------------------")

if not shipsy_api_key or not shipsy_customer_code:
    print("ERROR: Please make sure SHIPSY_API_KEY and SHIPSY_CUSTOMER_CODE are configured in your .env file.")
    exit(1)

# 2. Construct the exact payload matching your warehouse details in .env
payload = {
    "consignments": [
        {
            "customer_code": shipsy_customer_code,
            "service_type_id": "B2C PRIORITY",
            "load_type": "NON-DOCUMENT",
            "description": "Jewelry Order Test",
            "dimension_unit": "cm",
            "length": "10",
            "width": "10",
            "height": "5",
            "weight_unit": "kg",
            "weight": "0.5",
            "declared_value": "1000",
            "num_pieces": "1",
            "origin_details": {
                "name": os.getenv('FIRM_NAME', 'SAGA'),
                "phone": os.getenv('FIRM_PHONE', '9847294800'),
                "address_line_1": os.getenv('FIRM_ADDRESS', 'Anugraha, Ponnezha P O, Thekkekara'),
                "pincode": os.getenv('FIRM_PINCODE', '690107'),
                "city": os.getenv('FIRM_CITY', 'PALLARIMANGALAM'),
                "state": os.getenv('FIRM_STATE', 'KERALA')
            },
            "destination_details": {
                "name": "Test Customer",
                "phone": "9876543210",
                "address_line_1": "123 Main Street",
                "pincode": "400001",
                "city": "Mumbai",
                "state": "Maharashtra"
            },
            "customer_reference_number": "TEST_ORDER_999",
            "commodity_id": "99",
            "is_risk_surcharge_applicable": False
        }
    ]
}

print("SENDING REQUEST PAYLOAD:")
print(json.dumps(payload, indent=2))
print("--------------------------------------------------")

headers = {
    "Content-Type": "application/json",
    "api-key": shipsy_api_key
}

# 3. Call the API and print raw response
try:
    print("Waiting for DTDC response...")
    response = requests.post(shipsy_url, json=payload, headers=headers, timeout=10)
    print(f"\nHTTP STATUS: {response.status_code}")
    print("RESPONSE BODY:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"\nRequest failed: {str(e)}")

print("==================================================")
