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

# إعداد Supabase - استخدام المتغيرات البيئية من Render
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zmzotoutdeeizyfoikfw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_BqRz02wzKGRblUsM05DnOA_ovErV7U2")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres.zmzotoutdeeizyfoikfw:Alth3ka%40Drivers2024@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres")

# الاتصال بـ Supabase
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ تم الاتصال بـ Supabase بنجاح!")
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Supabase: {e}")
    supabase = None

# ============== دالة مساعدة للحصول على البيانات ==============
def get_all_data():
    """جلب جميع البيانات من Supabase (الطلبات والمندوبين)"""
    try:
        if not supabase:
            return []
        
        # جلب الطلبات
        orders_response = supabase.table('orders').select('*').execute()
        orders = orders_response.data if orders_response.data else []
        
        # جلب المندوبين
        agents_response = supabase.table('agents').select('*').execute()
        agents = agents_response.data if agents_response.data else []
        
        # دمج البيانات
        all_data = orders + agents
        return all_data
    except Exception as e:
        print(f"خطأ في جلب البيانات: {e}")
        return []

# ============== API ENDPOINTS ==============

@app.route('/api/data', methods=['GET'])
def get_data():
    """جلب جميع البيانات"""
    try:
        data = get_all_data()
        return jsonify(data)
    except Exception as e:
        print(f"API Error GET: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/data', methods=['POST'])
def add_data():
    """إضافة بيانات جديدة (طلب أو مندوب)"""
    try:
        new_item = request.json
        if not new_item:
            return jsonify({"isOk": False, "error": "No data provided"}), 400
        
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        # إضافة معرف فريد وتاريخ
        new_item['__backendId'] = str(int(datetime.now().timestamp() * 1000))
        new_item['created_at'] = datetime.now().isoformat()
        
        # تحديد الجدول المناسب
        if new_item.get('type') == 'agent':
            table_name = 'agents'
        else:
            table_name = 'orders'
            new_item['type'] = 'order'
        
        # إدراج البيانات في Supabase
        result = supabase.table(table_name).insert(new_item).execute()
        
        if result.data:
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        else:
            return jsonify({'isOk': False, 'error': 'Failed to save data'}), 500
            
    except Exception as e:
        print(f"API Error POST: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['PUT'])
def update_data(item_id):
    """تحديث بيانات موجودة (طلب أو مندوب)"""
    try:
        updated_item = request.json
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        # تحديد الجدول المناسب
        if updated_item.get('type') == 'agent':
            table_name = 'agents'
        else:
            table_name = 'orders'
        
        # تحديث البيانات في Supabase
        result = supabase.table(table_name).update(updated_item).eq('__backendId', item_id).execute()
        
        if result.data:
            return jsonify({'isOk': True, 'data': result.data[0]})
        else:
            # محاولة البحث في الجدول الآخر
            other_table = 'agents' if table_name == 'orders' else 'orders'
            result = supabase.table(other_table).update(updated_item).eq('__backendId', item_id).execute()
            if result.data:
                return jsonify({'isOk': True, 'data': result.data[0]})
            
            return jsonify({'isOk': False, 'error': 'Item not found'}), 404
            
    except Exception as e:
        print(f"API Error PUT: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['DELETE'])
def delete_data(item_id):
    """حذف بيانات (طلب أو مندوب)"""
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        # محاولة الحذف من جدول الطلبات أولاً
        result = supabase.table('orders').delete().eq('__backendId', item_id).execute()
        
        if not result.data:
            # محاولة الحذف من جدول المندوبين
            result = supabase.table('agents').delete().eq('__backendId', item_id).execute()
            
            if not result.data:
                return jsonify({'isOk': False, 'error': 'Item not found'}), 404
        
        return jsonify({'isOk': True})
        
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
    port = int(os.environ.get('PORT', 5000))
    print("🚀 تشغيل نظام الثقة - Altheka Drivers")
    print("☁️ استخدام قاعدة بيانات Supabase السحابية")
    print("🌐 افتح المتصفح على: http://localhost:" + str(port))
    app.run(debug=False, host='0.0.0.0', port=port)