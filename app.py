from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)
CORS(app)

# إعداد Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zmzotoutdeeizyfoikfw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_BqRz02wzKGRblUsM05DnOA_ovErV7U2")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ تم الاتصال بـ Supabase بنجاح!")
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Supabase: {e}")
    supabase = None

def get_all_data():
    try:
        if not supabase:
            return []
        orders = supabase.table('orders').select('*').execute()
        agents = supabase.table('agents').select('*').execute()
        return (orders.data or []) + (agents.data or [])
    except Exception as e:
        print(f"خطأ في جلب البيانات: {e}")
        return []

@app.route('/api/data', methods=['GET'])
def get_data():
    try:
        data = get_all_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/data', methods=['POST'])
def add_data():
    try:
        new_item = request.json
        if not new_item:
            return jsonify({"isOk": False, "error": "No data provided"}), 400
        
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        new_item['__backendId'] = str(int(datetime.now().timestamp() * 1000))
        new_item['created_at'] = datetime.now().isoformat()
        
        table_name = 'orders' if new_item.get('type') == 'order' else 'agents'
        result = supabase.table(table_name).insert(new_item).execute()
        
        if result.data:
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        return jsonify({'isOk': False, 'error': 'Failed to save data'}), 500
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['PUT'])
def update_data(item_id):
    try:
        updated_item = request.json
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        table_name = 'orders' if updated_item.get('type') == 'order' else 'agents'
        result = supabase.table(table_name).update(updated_item).eq('__backendId', item_id).execute()
        
        if result.data:
            return jsonify({'isOk': True, 'data': result.data[0]})
        return jsonify({'isOk': False, 'error': 'Item not found'}), 404
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['DELETE'])
def delete_data(item_id):
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        result = supabase.table('orders').delete().eq('__backendId', item_id).execute()
        if not result.data:
            result = supabase.table('agents').delete().eq('__backendId', item_id).execute()
            if not result.data:
                return jsonify({'isOk': False, 'error': 'Item not found'}), 404
        
        return jsonify({'isOk': True})
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/_sdk/data_sdk.js')
def data_sdk():
    return render_template('data_sdk.js'), 200, {'Content-Type': 'application/javascript'}

@app.route('/_sdk/element_sdk.js')
def element_sdk():
    return render_template('element_sdk.js'), 200, {'Content-Type': 'application/javascript'}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("🚀 تشغيل نظام الثقة - Altheka Drivers (Supabase)")
    app.run(debug=False, host='0.0.0.0', port=port)
