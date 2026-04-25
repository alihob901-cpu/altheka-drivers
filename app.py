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
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres.zmzotoutdeeizyfoikfw:Alth3ka%40Drivers2024@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ تم الاتصال بـ Supabase بنجاح!")
    print(f"📡 Supabase URL: {SUPABASE_URL}")
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Supabase: {e}")
    supabase = None

def get_all_data():
    """جلب جميع البيانات من Supabase"""
    try:
        if not supabase:
            print("⚠️ Supabase غير متصل")
            return []
        
        print("📥 جلب الطلبات من Supabase...")
        orders_response = supabase.table('orders').select('*').execute()
        orders = orders_response.data if orders_response.data else []
        print(f"📦 تم جلب {len(orders)} طلب")
        
        print("👥 جلب المندوبين من Supabase...")
        agents_response = supabase.table('agents').select('*').execute()
        agents = agents_response.data if agents_response.data else []
        print(f"👤 تم جلب {len(agents)} مندوب")
        
        all_data = orders + agents
        return all_data
    except Exception as e:
        print(f"❌ خطأ في جلب البيانات: {e}")
        return []

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
        
        print(f"📝 إضافة إلى جدول {table_name}: {new_item.get('customer_name', new_item.get('agent_name', 'غير معروف'))}")
        
        # إدراج البيانات في Supabase
        result = supabase.table(table_name).insert(new_item).execute()
        
        if result.data:
            print(f"✅ تمت الإضافة بنجاح، ID: {result.data[0].get('__backendId')}")
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        else:
            print("❌ فشل في حفظ البيانات")
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
        
        print(f"✏️ تحديث في جدول {table_name}، ID: {item_id}")
        
        # تحديث البيانات في Supabase
        result = supabase.table(table_name).update(updated_item).eq('__backendId', item_id).execute()
        
        if result.data:
            print(f"✅ تم التحديث بنجاح")
            return jsonify({'isOk': True, 'data': result.data[0]})
        else:
            # محاولة البحث في الجدول الآخر
            other_table = 'agents' if table_name == 'orders' else 'orders'
            result = supabase.table(other_table).update(updated_item).eq('__backendId', item_id).execute()
            if result.data:
                print(f"✅ تم التحديث في جدول {other_table}")
                return jsonify({'isOk': True, 'data': result.data[0]})
            
            print(f"❌ العنصر غير موجود: {item_id}")
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
        
        print(f"🗑️ حذف عنصر ID: {item_id}")
        
        # محاولة الحذف من جدول الطلبات أولاً
        result = supabase.table('orders').delete().eq('__backendId', item_id).execute()
        
        if result.data:
            print(f"✅ تم الحذف من جدول orders")
            return jsonify({'isOk': True})
        
        # محاولة الحذف من جدول المندوبين
        result = supabase.table('agents').delete().eq('__backendId', item_id).execute()
        
        if result.data:
            print(f"✅ تم الحذف من جدول agents")
            return jsonify({'isOk': True})
        
        print(f"❌ العنصر غير موجود: {item_id}")
        return jsonify({'isOk': False, 'error': 'Item not found'}), 404
        
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

@app.route('/health', methods=['GET'])
def health_check():
    """نقطة للتحقق من صحة الخادم"""
    return jsonify({
        "status": "healthy",
        "supabase_connected": supabase is not None,
        "timestamp": datetime.now().isoformat()
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 تشغيل نظام الثقة - Altheka Drivers (Supabase)")
    print(f"🌐 المنفذ: {port}")
    print(f"🔗 رابط التطبيق: http://localhost:{port}")
    print(f"☁️ قاعدة البيانات: Supabase")
    print("=" * 50)
    app.run(debug=False, host='0.0.0.0', port=port)