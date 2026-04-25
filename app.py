from flask import Flask, render_template, request, jsonify
import json
import os
from datetime import datetime

app = Flask(__name__)

# مسار ملف قاعدة البيانات
DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'database.json')

# التأكد من وجود مجلد data
os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)

# التأكد من وجود ملف البيانات
def init_data_file():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)

# قراءة البيانات
def load_data():
    try:
        init_data_file()
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"خطأ في قراءة البيانات: {e}")
        return []

# حفظ البيانات
def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"خطأ في حفظ البيانات: {e}")
        return False

@app.route('/api/data', methods=['GET'])
def get_data():
    try:
        data = load_data()
        return jsonify(data)
    except Exception as e:
        print(f"API Error GET: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/data', methods=['POST'])
def add_data():
    try:
        new_item = request.json
        if not new_item:
            return jsonify({"isOk": False, "error": "No data provided"}), 400
        
        data = load_data()
        
        # إضافة معرف فريد وتاريخ
        new_item['__backendId'] = str(int(datetime.now().timestamp() * 1000))
        new_item['created_at'] = datetime.now().isoformat()
        
        data.append(new_item)
        
        if save_data(data):
            return jsonify({'isOk': True, 'data': new_item}), 201
        else:
            return jsonify({'isOk': False, 'error': 'Failed to save data'}), 500
    except Exception as e:
        print(f"API Error POST: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['PUT'])
def update_data(item_id):
    try:
        updated_item = request.json
        data = load_data()
        
        for i, item in enumerate(data):
            if item.get('__backendId') == item_id:
                updated_item['__backendId'] = item_id
                data[i] = updated_item
                if save_data(data):
                    return jsonify({'isOk': True, 'data': updated_item})
                else:
                    return jsonify({'isOk': False, 'error': 'Failed to save data'}), 500
        
        return jsonify({'isOk': False, 'error': 'Item not found'}), 404
    except Exception as e:
        print(f"API Error PUT: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['DELETE'])
def delete_data(item_id):
    try:
        data = load_data()
        original_length = len(data)
        data = [item for item in data if item.get('__backendId') != item_id]
        
        if len(data) == original_length:
            return jsonify({'isOk': False, 'error': 'Item not found'}), 404
        
        if save_data(data):
            return jsonify({'isOk': True})
        else:
            return jsonify({'isOk': False, 'error': 'Failed to save data'}), 500
    except Exception as e:
        print(f"API Error DELETE: {e}")
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
    print("🚀 تشغيل نظام الثقة - Altheka Drivers")
    print("📁 مسار قاعدة البيانات:", DATA_FILE)
    print("🌐 افتح المتصفح على: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)