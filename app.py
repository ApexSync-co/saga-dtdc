import os
from flask import jsonify
from config import app
from shipping_routes import shipping_bp

# Register Blueprints
app.register_blueprint(shipping_bp)

@app.route('/', methods=['GET'])
def home():
    """
    Root status check.
    """
    return jsonify({"status": "Saga DTDC Backend is Running"}), 200

if __name__ == '__main__':
    # For local development only. Production servers use Gunicorn/Vercel.
    is_dev = os.getenv('FLASK_ENV') == 'development'
    app.run(debug=is_dev, port=5001)
