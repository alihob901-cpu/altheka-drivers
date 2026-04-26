# app.py - نسخة معدلة لتتوافق مع Flutter
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
from dotenv import load_dotenv
import json

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)
CORS(app)

# إعداد Supabase - استخدام نفس الإعدادات من Flutter
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zmzotoutdeeizyfoikfw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inptem90b3V0ZGVlaXp5Zm9pa2Z3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzcxMzI1NzksImV4cCI6MjA5MjcwODU3OX0.mfsGX5PC1kzBzRp832GiZ46oY60UWq_qKgREu6Rq-fM")

# إعداد Firebase Admin SDK
firebase_initialized = False
try:
    firebase_cred_json = os.getenv("FIREBASE_ADMIN_CRED_JSON")
    if firebase_cred_json:
        cred_dict = json.loads(firebase_cred_json)
        import firebase_admin
        from firebase_admin import credentials, messaging
        
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            firebase_initialized = True
            print("✅ Firebase Admin SDK initialized successfully!")
        else:
            firebase_initialized = True
            print("✅ Firebase Admin SDK already initialized")
    else:
        print("⚠️ FIREBASE_ADMIN_CRED_JSON not found")
except Exception as e:
    print(f"❌ خطأ في تهيئة Firebase: {e}")

FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")
FCM_SENDER_ID = os.getenv("FCM_SENDER_ID", "150648020047")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ تم الاتصال بـ Supabase بنجاح!")
    
    # التحقق من الجداول - استخدام نفس أسماء الجداول من Flutter
    tables_to_check = ['agents', 'orders', 'fcm_tokens', 'notifications']
    for table in tables_to_check:
        try:
            supabase.table(table).select('count').limit(1).execute()
            print(f"✅ جدول {table} موجود")
        except Exception as e:
            print(f"⚠️ جدول {table} غير موجود")
            
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Supabase: {e}")
    supabase = None

def get_all_data():
    """جلب جميع البيانات - متوافق مع Flutter"""
    try:
        if not supabase:
            print("⚠️ Supabase غير متصل")
            return []
        
        # جلب الطلبات من جدول orders (نفس هيكل Flutter)
        print("📥 جلب الطلبات...")
        orders_response = supabase.table('orders').select('*').execute()
        orders = orders_response.data if orders_response.data else []
        
        # جلب المندوبين من جدول agents (نفس هيكل Flutter)
        print("👥 جلب المندوبين...")
        agents_response = supabase.table('agents').select('*').execute()
        agents = agents_response.data if agents_response.data else []
        
        all_data = orders + agents
        print(f"✅ تم جلب {len(orders)} طلب و {len(agents)} مندوب")
        return all_data
    except Exception as e:
        print(f"❌ خطأ في جلب البيانات: {e}")
        return []

def send_fcm_notification_via_admin(fcm_token, title, body, data=None):
    """إرسال إشعار عبر Firebase Admin SDK"""
    if not firebase_initialized:
        return send_fcm_notification_via_legacy(fcm_token, title, body, data)
    
    try:
        from firebase_admin import messaging
        
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(sound="default")
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            )
        )
        
        response = messaging.send(message)
        print(f"✅ تم إرسال الإشعار: {response}")
        return True
    except Exception as e:
        print(f"❌ خطأ في الإشعار: {e}")
        return False

def send_fcm_notification_via_legacy(fcm_token, title, body, data=None):
    """إرسال إشعار عبر Legacy API"""
    if not fcm_token or not FCM_SERVER_KEY:
        return False
    
    import requests
    url = "https://fcm.googleapis.com/fcm/send"
    headers = {
        "Authorization": f"key={FCM_SERVER_KEY}",
        "Content-Type": "application/json"
    }
    
    notification_data = {
        "to": fcm_token,
        "notification": {"title": title, "body": body, "sound": "default"},
        "data": data or {}
    }
    
    try:
        response = requests.post(url, headers=headers, json=notification_data)
        result = response.json()
        if response.status_code == 200 and result.get("success", 0) > 0:
            print(f"✅ تم إرسال الإشعار: {title}")
            return True
        return False
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False

def send_notification_to_user(user_id, title, body, order_id=None):
    """إرسال إشعار إلى مستخدم"""
    try:
        if not supabase:
            return False
        
        result = supabase.table('fcm_tokens').select('fcm_token').eq('user_id', user_id).execute()
        if not result.data:
            print(f"⚠️ لا يوجد FCM Token للمستخدم: {user_id}")
            return False
        
        fcm_token = result.data[0]['fcm_token']
        data = {'order_id': str(order_id)} if order_id else {}
        return send_fcm_notification_via_admin(fcm_token, title, body, data)
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False

# ============== API Routes (متوافقة مع Flutter) ==============

@app.route('/api/data', methods=['GET'])
def get_data():
    """جلب جميع البيانات"""
    try:
        data = get_all_data()
        return jsonify(data)
    except Exception as e:
        print(f"API Error GET: {e}")
        return jsonify([]), 500

@app.route('/api/data', methods=['POST'])
def add_data():
    """إضافة بيانات جديدة"""
    try:
        new_item = request.json
        if not new_item or not supabase:
            return jsonify({"isOk": False, "error": "Invalid request"}), 400
        
        # إنشاء __backendId بنفس طريقة Flutter
        new_item['__backendId'] = str(int(datetime.now().timestamp() * 1000))
        new_item['created_at'] = datetime.now().isoformat()
        new_item['updated_at'] = datetime.now().isoformat()
        
        # تحديد الجدول
        if new_item.get('type') == 'agent' or new_item.get('agent_code'):
            table_name = 'agents'
        else:
            table_name = 'orders'
            new_item['type'] = 'order'
        
        print(f"📝 إضافة إلى {table_name}: {new_item}")
        
        result = supabase.table(table_name).insert(new_item).execute()
        
        if result.data:
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        return jsonify({'isOk': False, 'error': 'Failed to save'}), 500
    except Exception as e:
        print(f"API Error POST: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['PUT'])
def update_data(item_id):
    """تحديث بيانات"""
    try:
        updated_item = request.json
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        updated_item['updated_at'] = datetime.now().isoformat()
        
        # تحديد الجدول
        table_name = 'agents' if updated_item.get('type') == 'agent' else 'orders'
        
        # جلب البيانات القديمة للإشعارات
        old_result = supabase.table('orders').select('*').eq('__backendId', item_id).execute()
        old_item = old_result.data[0] if old_result.data else None
        
        result = supabase.table(table_name).update(updated_item).eq('__backendId', item_id).execute()
        
        if result.data:
            # إرسال إشعار عند تغيير الحالة
            if old_item and old_item.get('status') != updated_item.get('status'):
                agent_name = old_item.get('agent_name')
                customer_name = old_item.get('customer_name', 'زبون')
                new_status = updated_item.get('status')
                
                if agent_name and agent_name not in ['admin', 'المدير العام']:
                    if new_status == 'واصل':
                        title = "✅ طلب واصل"
                        body = f"تم توصيل طلب {customer_name} بنجاح"
                    elif new_status == 'راجع':
                        title = "↩️ طلب مرتجع"
                        body = f"تم إرجاع طلب {customer_name}"
                    elif new_status == 'قيد التوصيل':
                        title = "🚚 طلب قيد التوصيل"
                        body = f"طلب {customer_name} قيد التوصيل الآن"
                    else:
                        title = "📋 تحديث حالة الطلب"
                        body = f"تم تغيير حالة طلب {customer_name} إلى {new_status}"
                    
                    send_notification_to_user(agent_name, title, body, item_id)
            
            return jsonify({'isOk': True, 'data': result.data[0]})
        
        return jsonify({'isOk': False, 'error': 'Item not found'}), 404
    except Exception as e:
        print(f"API Error PUT: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['DELETE'])
def delete_data(item_id):
    """حذف بيانات"""
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        # محاولة الحذف من orders أولاً
        result = supabase.table('orders').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        # ثم من agents
        result = supabase.table('agents').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        return jsonify({'isOk': False, 'error': 'Item not found'}), 404
    except Exception as e:
        print(f"API Error DELETE: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

# ============== FCM Tokens API ==============

@app.route('/api/fcm-token', methods=['POST'])
def save_fcm_token():
    """حفظ FCM Token"""
    try:
        data = request.json
        user_id = data.get('user_id')
        fcm_token = data.get('fcm_token')
        device_info = data.get('device_info', 'web')
        
        if not user_id or not fcm_token or not supabase:
            return jsonify({"isOk": False, "error": "Missing data"}), 400
        
        existing = supabase.table('fcm_tokens').select('*').eq('user_id', user_id).execute()
        
        if existing.data:
            result = supabase.table('fcm_tokens').update({
                'fcm_token': fcm_token,
                'device_info': device_info,
                'updated_at': datetime.now().isoformat()
            }).eq('user_id', user_id).execute()
        else:
            result = supabase.table('fcm_tokens').insert({
                'user_id': user_id,
                'fcm_token': fcm_token,
                'device_info': device_info,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }).execute()
        
        return jsonify({'isOk': bool(result.data)})
    except Exception as e:
        print(f"API Error: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """نقطة للتحقق من صحة الخادم"""
    return jsonify({
        "status": "healthy",
        "supabase_connected": supabase is not None,
        "firebase_admin_initialized": firebase_initialized,
        "timestamp": datetime.now().isoformat()
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 تشغيل الخادم (متوافق مع Flutter)")
    print(f"🌐 المنفذ: {port}")
    print("=" * 50)
    app.run(debug=False, host='0.0.0.0', port=port)