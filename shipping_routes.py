import os
import requests
from flask import Blueprint, request, jsonify
from firebase_admin import firestore
from config import db, limiter, app

shipping_bp = Blueprint('shipping', __name__)

def book_consignment_internal(order_id, order_data):
    """
    Helper function to book a shipping consignment on Shipsy/DTDC and save the AWB to Firestore.
    """
    shipsy_api_key = os.getenv('SHIPSY_API_KEY')
    shipsy_customer_code = os.getenv('SHIPSY_CUSTOMER_CODE')
    
    if not shipsy_api_key or shipsy_api_key == 'your_actual_key_here':
        raise Exception("Shipsy API Key not configured")
        
    payload = {
        "consignments": [
            {
                "customer_code": shipsy_customer_code,
                "service_type_id": order_data.get('service_type_id', 'B2C PRIORITY'),
                "load_type": order_data.get('load_type', 'NON-DOCUMENT'),
                "description": order_data.get('description', 'Jewelry Order'),
                "dimension_unit": "cm",
                "length": str(order_data.get('length', '10')),
                "width": str(order_data.get('width', '10')),
                "height": str(order_data.get('height', '5')),
                "weight_unit": "kg",
                "weight": str(order_data.get('weight', '0.5')),
                "declared_value": str(order_data.get('total')),
                "num_pieces": "1",
                "origin_details": {
                    "name": os.getenv('FIRM_NAME', 'SAGA'),
                    "phone": os.getenv('FIRM_PHONE', '0000000000'),
                    "address_line_1": os.getenv('FIRM_ADDRESS', 'SAGA Warehouse'),
                    "pincode": os.getenv('FIRM_PINCODE', '110001'),
                    "city": os.getenv('FIRM_CITY', 'New Delhi'),
                    "state": os.getenv('FIRM_STATE', 'Delhi')
                },
                "destination_details": {
                    "name": order_data.get('address', {}).get('name') or order_data.get('address', {}).get('fullName') or 'Customer',
                    "phone": order_data.get('address', {}).get('phone', '0000000000'),
                    "address_line_1": order_data.get('address', {}).get('addressLine1') or order_data.get('address', {}).get('addressLine') or '',
                    "address_line_2": order_data.get('address', {}).get('addressLine2') or order_data.get('address', {}).get('landmark') or '',
                    "pincode": order_data.get('address', {}).get('pincode', ''),
                    "city": order_data.get('address', {}).get('city', ''),
                    "state": order_data.get('address', {}).get('state', '')
                },
                "customer_reference_number": order_id,
                "commodity_id": "99",
                "is_risk_surcharge_applicable": False
            }
        ]
    }

    shipsy_url = os.getenv(
        'SHIPSY_API_URL', 
        "https://dtdcapi.shipsy.io/api/customer/integration/consignment/softdata"
    )
    headers = {
        "Content-Type": "application/json",
        "api-key": shipsy_api_key
    }

    response = requests.post(shipsy_url, json=payload, headers=headers)
    shipsy_response = response.json()

    if response.status_code == 200 and shipsy_response.get('status') == 'OK':
        consignment_data = shipsy_response.get('data', [{}])[0]
        if consignment_data.get('success'):
            awb = consignment_data.get('reference_number')
            # Save AWB to Firestore Order
            if db:
                db.collection('orders').document(order_id).update({
                    'awbNumber': awb,
                    'status': 'Shipped',
                    'updatedAt': firestore.SERVER_TIMESTAMP
                })
            else:
                raise Exception("Firebase Admin SDK is not initialized on the backend. Please configure the FIREBASE_SERVICE_ACCOUNT_PATH environment variable on Vercel.")
            return awb
        else:
            error_reason = consignment_data.get('message') or consignment_data.get('reason') or consignment_data.get('error_message') or 'Unknown Shipsy Error'
            raise Exception(f"Shipsy booking failed: {error_reason}")
    else:
        error_reason = shipsy_response.get('message') or shipsy_response.get('error_message') or shipsy_response
        raise Exception(f"Failed to communicate with DTDC: {error_reason}")

@shipping_bp.route('/track-order', methods=['POST'])
@limiter.limit("20 per minute")
def track_order():
    """
    Handles order tracking using the unified Shipsy API.
    """
    try:
        data = request.get_json()
        awb_number = data.get('awbNumber')
        
        if not awb_number:
            return jsonify({"error": "AWB number is required"}), 400

        shipsy_api_key = os.getenv('SHIPSY_API_KEY')
        if not shipsy_api_key:
            return jsonify({"error": "Shipsy API Key not configured"}), 500

        # Query Shipsy Tracking API directly using the API key
        base_url = os.getenv('SHIPSY_API_URL', "https://dtdcapi.shipsy.io/api/customer/integration/consignment/softdata")
        api_base = base_url.split('/api/')[0]
        tracking_url = f"{api_base}/api/customer/integration/consignment/track"
        
        headers = {
            'api-key': shipsy_api_key,
            'Content-Type': 'application/json'
        }
        params = {
            'reference_number': awb_number
        }
        
        response = requests.get(tracking_url, params=params, headers=headers)
        
        if response.status_code in [400, 404]:
            return jsonify({
                "error": "Tracking information is not yet available for this AWB."
            }), 404
            
        if response.status_code != 200:
            return jsonify({"error": f"Failed to get tracking: {response.text}"}), response.status_code

        res_data = response.json()
        if res_data.get('status') != 'OK' or not res_data.get('data'):
            return jsonify({"error": "No tracking data found for this AWB."}), 404
            
        consignment = res_data['data'][0]
        current_status = consignment.get('status', 'In Transit')
        current_location = consignment.get('current_hub', 'Processing Hub')
        delivery_date = consignment.get('expected_delivery_date', '4-5 Days')
        history = consignment.get('tracking_history', [])

        return jsonify({
            "status": current_status,
            "location": current_location,
            "eta": delivery_date,
            "awb": consignment.get('reference_number', awb_number),
            "origin": consignment.get('origin', ''),
            "destination": consignment.get('destination', ''),
            "history": [
                {
                    "status": h.get('status'),
                    "location": h.get('location'),
                    "time": h.get('activity_date'),
                    "remarks": h.get('remarks', '')
                } for h in history
            ]
        }), 200

    except Exception as e:
        app.logger.error(f"Tracking Error: {str(e)}")
        return jsonify({"error": "External Tracking Service currently unavailable"}), 500

@shipping_bp.route('/create-consignment', methods=['POST'])
@limiter.limit("10 per minute")
def create_consignment():
    """
    Uploads order to DTDC via Shipsy Order Upload API manually.
    """
    try:
        data = request.get_json()
        order_id = data.get('orderId')
        
        if not order_id:
            return jsonify({"error": "Order ID is required"}), 400

        awb = book_consignment_internal(order_id, data)
        return jsonify({
            "status": "success",
            "awb": awb
        }), 200
        
    except Exception as e:
        app.logger.error(f"Consignment creation failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

@shipping_bp.route('/generate-label', methods=['GET'])
@limiter.limit("20 per minute")
def generate_label():
    """
    Generates a shipping label for a consignment via Shipsy API.
    """
    try:
        awb = request.args.get('awb')
        label_code = request.args.get('label_code', 'SHIP_LABEL_4X6')
        label_format = request.args.get('label_format', 'pdf')
        
        if not awb:
            return jsonify({"error": "AWB number is required"}), 400

        shipsy_api_key = os.getenv('SHIPSY_API_KEY')
        if not shipsy_api_key:
            return jsonify({"error": "Shipsy API Key not configured"}), 500

        # Shipsy Label API URL
        base_url = os.getenv('SHIPSY_API_URL', "https://dtdcapi.shipsy.io/api/customer/integration/consignment/softdata")
        api_base = base_url.split('/api/')[0]
        label_url = f"{api_base}/api/customer/integration/consignment/shippinglabel/stream"
        
        params = {
            'reference_number': awb,
            'label_code': label_code,
            'label_format': label_format
        }
        headers = {
            'api-key': shipsy_api_key
        }

        response = requests.get(label_url, params=params, headers=headers, stream=True)

        if response.status_code != 200:
            return jsonify({
                "error": "Failed to generate label from Shipsy",
                "details": response.text
            }), response.status_code

        # If it's a PDF, stream it back to the client
        if label_format == 'pdf':
            return (
                response.content,
                200,
                {
                    'Content-Type': 'application/pdf',
                    'Content-Disposition': f'attachment; filename=label_{awb}.pdf'
                }
            )
        
        # If it's base64, return as JSON
        return jsonify(response.json()), 200

    except Exception as e:
        app.logger.error(f"Label Generation Error: {str(e)}")
        return jsonify({"error": "Internal error during label generation"}), 500

@shipping_bp.route('/cancel-consignment', methods=['POST'])
@limiter.limit("10 per minute")
def cancel_consignment():
    """
    Cancels a consignment in the DTDC/Shipsy system.
    """
    try:
        data = request.get_json()
        awb = data.get('awb')
        
        if not awb:
            return jsonify({"error": "AWB number is required"}), 400

        shipsy_api_key = os.getenv('SHIPSY_API_KEY')
        shipsy_customer_code = os.getenv('SHIPSY_CUSTOMER_CODE')
        
        if not shipsy_api_key:
            return jsonify({"error": "Shipsy API Key not configured"}), 500

        # Shipsy Cancellation API URL
        base_url = os.getenv('SHIPSY_API_URL', "https://dtdcapi.shipsy.io/api/customer/integration/consignment/softdata")
        api_base = base_url.split('/api/')[0]
        cancel_url = f"{api_base}/api/customer/integration/consignment/cancel"
        
        payload = {
            "AWBNo": [str(awb)],
            "customerCode": shipsy_customer_code
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": shipsy_api_key
        }

        response = requests.post(cancel_url, json=payload, headers=headers)
        shipsy_response = response.json()

        if response.status_code == 200 and shipsy_response.get('status') == 'OK':
            # Check if the specific consignment was canceled
            consignments = shipsy_response.get('successConsignments', [])
            if consignments and consignments[0].get('success'):
                return jsonify({
                    "status": "success",
                    "message": "Consignment canceled successfully",
                    "details": shipsy_response
                }), 200
            else:
                return jsonify({
                    "status": "failure",
                    "error": "Shipsy failed to cancel consignment",
                    "details": shipsy_response
                }), 400
        
        return jsonify({
            "error": "Failed to cancel order with DTDC",
            "details": shipsy_response
        }), response.status_code

    except Exception as e:
        app.logger.error(f"Cancellation Error: {str(e)}")
        return jsonify({"error": "Internal error during cancellation"}), 500

def send_customer_notification(order_id, customer_email, customer_phone, status, awb):
    """
    Sends notification to customer via Email/SMS.
    Placeholder for actual Twilio/SendGrid integration.
    """
    print(f"NOTIFY: Order {order_id} is now {status}. AWB: {awb}")
    pass

@shipping_bp.route('/sync-order-statuses', methods=['GET'])
@limiter.limit("5 per hour")
def sync_order_statuses():
    """
    Background job to sync Firestore statuses with DTDC live tracking.
    Can be triggered by a Cron Job.
    """
    if not db:
        return jsonify({"error": "Firebase not initialized"}), 500

    try:
        # 1. Fetch orders that are Shipped or Out for Delivery
        orders_ref = db.collection('orders')
        query = orders_ref.where('status', 'in', ['Shipped', 'Out for Delivery']).stream()
        
        sync_results = []
        
        for doc in query:
            order_data = doc.to_dict()
            order_id = doc.id
            awb = order_data.get('awbNumber') or order_data.get('trackingId')
            
            if not awb:
                continue

            # 2. Get Live Tracking from DTDC
            try:
                shipsy_api_key = os.getenv('SHIPSY_API_KEY')
                base_url = os.getenv('SHIPSY_API_URL', "https://dtdcapi.shipsy.io/api/customer/integration/consignment/softdata")
                api_base = base_url.split('/api/')[0]
                tracking_url = f"{api_base}/api/customer/integration/consignment/track"
                
                params = {'reference_number': awb}
                headers = {'api-key': shipsy_api_key}
                
                response = requests.get(tracking_url, params=params, headers=headers)
                
                if response.status_code != 200:
                    continue

                res_data = response.json()
                if res_data.get('status') != 'OK' or not res_data.get('data'):
                    continue
                    
                consignment = res_data['data'][0]
                live_status = consignment.get('status', '').upper()
                
                # 3. Map DTDC status to internal status
                new_status = None
                if 'DELIVERED' in live_status:
                    new_status = 'Delivered'
                elif 'OUT FOR DELIVERY' in live_status:
                    new_status = 'Out for Delivery'
                elif 'TRANSIT' in live_status:
                    new_status = 'Shipped'

                # 4. Update Firestore if status changed
                if new_status and new_status != order_data.get('status'):
                    doc.reference.update({
                        'status': new_status,
                        'lastSync': firestore.SERVER_TIMESTAMP
                    })
                    
                    # 5. Send Notification
                    send_customer_notification(
                        order_id, 
                        order_data.get('customerEmail'), 
                        order_data.get('address', {}).get('phone'),
                        new_status,
                        awb
                    )
                    
                    sync_results.append({
                        "orderId": order_id,
                        "oldStatus": order_data.get('status'),
                        "newStatus": new_status
                    })

            except Exception as inner_e:
                app.logger.error(f"Error syncing order {order_id}: {str(inner_e)}")
                continue

        return jsonify({
            "status": "success",
            "synced_count": len(sync_results),
            "updates": sync_results
        }), 200

    except Exception as e:
        app.logger.error(f"Global Sync Error: {str(e)}")
        return jsonify({"error": "Failed to run status sync"}), 500
