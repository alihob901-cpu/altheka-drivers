from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
from dotenv import load_dotenv
import json
import requests
from functools import wraps

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)
CORS(app)

# ============== إعداد Supabase ==============
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zmzotoutdeeizyfoikfw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_BqRz02wzKGRblUsM05DnOA_ovErV7U2")

# ============== إعداد نظام الزعيم (Jenni Logistics) ==============
JENNI_API_URL = "https://jenni.alzaeemexp.com/api"
JENNI_USERNAME = os.getenv("JENNI_USERNAME", "07717798622")
JENNI_PASSWORD = os.getenv("JENNI_PASSWORD", "30007000")
JENNI_SYSTEM_CODE = os.getenv("JENNI_SYSTEM_CODE", "ECOMMERCE_STORE_01")
JENNI_WEBHOOK_TOKEN = os.getenv("JENNI_WEBHOOK_TOKEN", "TrustCenterSecretKey123")

# متغير لتخزين JWT token من الزعيم
jenni_jwt_token = None
jenni_token_expiry = None

# ============== إعداد Firebase Admin SDK ==============
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

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ تم الاتصال بـ Supabase بنجاح!")
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Supabase: {e}")
    supabase = None

# ============== دوال نظام الزعيم ==============
def jenni_login():
    """تسجيل الدخول إلى نظام الزعيم والحصول على JWT token"""
    global jenni_jwt_token, jenni_token_expiry
    import time
    
    print("🔑 محاولة تسجيل الدخول إلى نظام الزعيم...")
    try:
        response = requests.post(
            f"{JENNI_API_URL}/v2/auth/login",
            json={"username": JENNI_USERNAME, "password": JENNI_PASSWORD},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        print(f"📡 رد تسجيل الدخول: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            # تجربة الحصول على token من مفاتيح مختلفة
            jenni_jwt_token = data.get("token") or data.get("access_token") or data.get("jwt")
            expires_in = data.get("expires_in", 86400)
            jenni_token_expiry = time.time() + expires_in
            print(f"✅ تم تسجيل الدخول إلى نظام الزعيم بنجاح, token: {jenni_jwt_token[:30] if jenni_jwt_token else 'None'}...")
            return True
        else:
            print(f"❌ فشل تسجيل الدخول إلى الزعيم: {response.status_code} - {response.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ خطأ في تسجيل الدخول إلى الزعيم: {e}")
        return False

def jenni_get_token():
    """الحصول على JWT token صالح (مع إعادة تسجيل الدخول إذا انتهى)"""
    import time
    global jenni_jwt_token, jenni_token_expiry
    
    if not jenni_jwt_token or not jenni_token_expiry or time.time() > jenni_token_expiry - 300:
        print("⚠️ التوكن منتهي أو غير موجود، إعادة تسجيل الدخول...")
        if not jenni_login():
            return None
    return jenni_jwt_token

def create_shipment_in_jenni(order_data):
    """إرسال طلب جديد إلى نظام الزعيم مع تجربة طرق مصادقة متعددة"""
    print(f"📤 بدء إرسال الطلب {order_data.get('__backendId')} إلى نظام الزعيم...")
    
    token = jenni_get_token()
    if not token:
        print("❌ فشل الحصول على التوكن")
        return {"success": False, "error": "فشل المصادقة مع نظام الزعيم"}
    
    print(f"✅ تم الحصول على التوكن: {token[:30]}...")
    
    # تحويل بيانات الطلب إلى صيغة الزعيم - تبسيط للاختبار
    shipment_payload = {
        "system_code": JENNI_SYSTEM_CODE,
        "shipments": [{
            "shipment_number": order_data.get("__backendId", ""),
            "external_shipment_id": order_data.get("__backendId", ""),
            "receiver_name": order_data.get("customer_name", "")[:50],
            "receiver_phone_1": order_data.get("customer_phone", ""),
            "governorate_code": "BGD",
            "city": "بغداد",
            "address": order_data.get("customer_address", "")[:100],
            "amount_iqd": float(order_data.get("total", 0)),
            "quantity": order_data.get("quantity", 1),
        }]
    }
    
    print(f"📦 الحمولة المرسلة: {json.dumps(shipment_payload, ensure_ascii=False)[:500]}")
    
    # تجربة طرق مصادقة مختلفة
    auth_methods = [
        {"name": "Bearer Token", "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}},
        {"name": "Token Only", "headers": {"Content-Type": "application/json", "Authorization": token}},
        {"name": "API Key", "headers": {"Content-Type": "application/json", "apikey": token}},
        {"name": "X-API-Key", "headers": {"Content-Type": "application/json", "X-API-Key": token}},
        {"name": "JWT", "headers": {"Content-Type": "application/json", "JWT": token}},
    ]
    
    for method in auth_methods:
        print(f"📡 محاولة المصادقة بطريقة: {method['name']}")
        try:
            response = requests.post(
                f"{JENNI_API_URL}/v2/shipments/create",
                json=shipment_payload,
                headers=method['headers'],
                timeout=30
            )
            print(f"📡 رد الزعيم ({method['name']}): {response.status_code}")
            
            if response.status_code == 200 or response.status_code == 201:
                try:
                    result = response.json()
                    print(f"✅ نجحت المحاولة بطريقة {method['name']}!")
                    if result.get("accepted_shipments") and len(result["accepted_shipments"]) > 0:
                        shipment = result["accepted_shipments"][0]
                        return {
                            "success": True,
                            "shipment_id": shipment.get("shipment_id"),
                            "message": f"تم إرسال الطلب بنجاح عبر {method['name']}"
                        }
                except:
                    return {"success": True, "message": "تم الإرسال ولكن الاستجابة غير متوقعة"}
            elif response.status_code == 401:
                print(f"⚠️ فشل المصادقة بطريقة {method['name']}")
            else:
                print(f"⚠️ رد غير متوقع: {response.status_code}")
                
        except Exception as e:
            print(f"❌ خطأ في المحاولة {method['name']}: {e}")
    
    return {"success": False, "error": "فشلت جميع محاولات المصادقة مع نظام الزعيم"}

# ============== دوال الإشعارات ==============
def send_fcm_notification_via_admin(fcm_token, title, body, data=None):
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
    if not fcm_token or not FCM_SERVER_KEY:
        return False
    
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

def get_all_data():
    try:
        if not supabase:
            return []
        
        orders_response = supabase.table('orders').select('*').execute()
        orders = orders_response.data if orders_response.data else []
        for order in orders:
            order['type'] = 'order'
        
        agents_response = supabase.table('agents').select('*').execute()
        agents = agents_response.data if agents_response.data else []
        for agent in agents:
            agent['type'] = 'agent'
        
        return orders + agents
    except Exception as e:
        print(f"❌ خطأ في جلب البيانات: {e}")
        return []

# ============== API Routes ==============

@app.route('/api/data', methods=['GET'])
def get_data():
    try:
        data = get_all_data()
        return jsonify(data)
    except Exception as e:
        return jsonify([]), 500

@app.route('/api/data', methods=['POST'])
def add_data():
    try:
        new_item = request.json
        if not new_item or not supabase:
            return jsonify({"isOk": False, "error": "Invalid request"}), 400
        
        new_item['__backendId'] = str(int(datetime.now().timestamp() * 1000))
        new_item['created_at'] = datetime.now().isoformat()
        new_item['updated_at'] = datetime.now().isoformat()
        
        if new_item.get('type') == 'agent':
            table_name = 'agents'
        else:
            table_name = 'orders'
            new_item['type'] = 'order'
        
        print(f"📝 إضافة إلى جدول {table_name}: {new_item.get('customer_name', new_item.get('agent_name', 'غير معروف'))}")
        
        result = supabase.table(table_name).insert(new_item).execute()
        
        if result.data:
            returned_data = result.data[0]
            if 'type' not in returned_data:
                returned_data['type'] = table_name[:-1] if table_name != 'orders' else 'order'
            
            # ============== DEBUG ==============
            print(f"🔍 DEBUG: table_name={table_name}")
            print(f"🔍 DEBUG: status={new_item.get('status')}")
            print(f"🔍 DEBUG: will send to Jenni? {table_name == 'orders' and new_item.get('status') == 'جديد'}")
            # ===================================
            
            # ============== إرسال الطلب إلى نظام الزعيم ==============
            if table_name == 'orders' and new_item.get('status') == 'جديد':
                print("🚀 بدء إرسال الطلب إلى نظام الزعيم...")
                jenni_result = create_shipment_in_jenni(new_item)
                print(f"📊 نتيجة الإرسال إلى الزعيم: {jenni_result}")
                
                if jenni_result.get("success"):
                    print(f"📤 تم إرسال الطلب {new_item['__backendId']} إلى نظام الزعيم")
                    if jenni_result.get("shipment_id"):
                        supabase.table('orders').update({
                            "jenni_shipment_id": jenni_result["shipment_id"]
                        }).eq('__backendId', new_item['__backendId']).execute()
                else:
                    print(f"⚠️ فشل إرسال الطلب إلى الزعيم: {jenni_result.get('error')}")
            else:
                print("⏭️ تخطي إرسال إلى الزعيم (ليس طلب order أو الحالة ليست جديد)")
            
            return jsonify({'isOk': True, 'data': returned_data}), 201
        return jsonify({'isOk': False, 'error': 'Failed to save'}), 500
    except Exception as e:
        print(f"API Error POST: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['PUT'])
def update_data(item_id):
    try:
        updated_item = request.json
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        updated_item['updated_at'] = datetime.now().isoformat()
        
        table_name = 'agents' if updated_item.get('type') == 'agent' else 'orders'
        
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
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        result = supabase.table('orders').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        result = supabase.table('agents').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        return jsonify({'isOk': False, 'error': 'Item not found'}), 404
    except Exception as e:
        print(f"API Error DELETE: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

# ============== Webhook لاستقبال تحديثات الزعيم ==============
@app.route('/v2/push/update-status', methods=['POST'])
def jenni_webhook():
    """استقبال تحديثات الحالة من نظام الزعيم"""
    try:
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''
        
        if token != JENNI_WEBHOOK_TOKEN:
            print(f"⚠️ توكن غير صالح: {token}")
            return jsonify({"success": False, "message": "Invalid token"}), 401
        
        data = request.get_json()
        print(f"📬 استلام تحديث من نظام الزعيم: {json.dumps(data, ensure_ascii=False)[:500]}")
        
        system_code = data.get('system_code')
        updates = data.get('updates', [])
        
        if system_code != JENNI_SYSTEM_CODE:
            return jsonify({"success": False, "message": "Invalid system code"}), 401
        
        for update in updates:
            shipment_number = update.get('shipment_number')
            action_code = update.get('action_code')
            current_step = update.get('current_step')
            current_step_ar = update.get('current_step_ar')
            note = update.get('note')
            
            print(f"📦 تحديث للطلب {shipment_number}: {action_code} - {current_step_ar}")
            
            status_map = {
                'DELIVERED': 'واصل',
                'DELIVERED_PRICE_CHANGED': 'واصل',
                'PARTIALLY_DELIVERED': 'واصل',
                'OFD': 'قيد التوصيل',
                'POSTPONED': 'قيد التوصيل',
                'RTO_WH': 'راجع',
                'RTO_WITH_DA': 'راجع',
                'RTO_CONFIRMED': 'راجع'
            }
            
            new_status = status_map.get(current_step, None)
            
            if new_status and supabase:
                result = supabase.table('orders').update({
                    "status": new_status,
                    "admin_notes": note,
                    "updated_at": datetime.now().isoformat(),
                    "jenni_last_update": datetime.now().isoformat()
                }).eq('__backendId', shipment_number).execute()
                
                if result.data:
                    print(f"✅ تم تحديث حالة الطلب {shipment_number} إلى {new_status}")
                    
                    order = result.data[0]
                    agent_name = order.get('agent_name')
                    if agent_name:
                        send_notification_to_user(
                            agent_name,
                            f"تحديث حالة الطلب",
                            f"تم تغيير حالة طلب {order.get('customer_name', '')} إلى {new_status}",
                            shipment_number
                        )
        
        return jsonify({"success": True, "message": f"Processed {len(updates)} updates"}), 200
        
    except Exception as e:
        print(f"❌ خطأ في معالجة Webhook: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

# ============== باقي الـ Routes ==============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/_sdk/data_sdk.js')
def data_sdk():
    return render_template('data_sdk.js'), 200, {'Content-Type': 'application/javascript'}

@app.route('/_sdk/element_sdk.js')
def element_sdk():
    return render_template('element_sdk.js'), 200, {'Content-Type': 'application/javascript'}

@app.route('/firebase-messaging-sw.js')
def service_worker():
    return render_template('firebase-messaging-sw.js'), 200, {'Content-Type': 'application/javascript'}

@app.route('/api/fcm-token', methods=['POST'])
def save_fcm_token():
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

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    try:
        if not supabase:
            return jsonify([]), 500
        result = supabase.table('notifications').select('*').order('created_at', desc=True).execute()
        return jsonify(result.data if result.data else [])
    except Exception as e:
        return jsonify([]), 500

@app.route('/api/notifications', methods=['POST'])
def add_notification():
    try:
        new_item = request.json
        if not new_item or not supabase:
            return jsonify({"isOk": False, "error": "No data"}), 400
        
        new_item['_id'] = str(int(datetime.now().timestamp() * 1000))
        new_item['created_at'] = datetime.now().isoformat()
        new_item['read'] = new_item.get('read', False)
        
        result = supabase.table('notifications').insert(new_item).execute()
        
        if result.data:
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        return jsonify({'isOk': False, 'error': 'Failed to save'}), 500
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/notifications/<notification_id>/read', methods=['PUT'])
def mark_notification_read(notification_id):
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        result = supabase.table('notifications').update({'read': True}).eq('_id', notification_id).execute()
        
        if result.data:
            return jsonify({'isOk': True})
        return jsonify({'isOk': False, 'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/notifications', methods=['DELETE'])
def delete_all_notifications():
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        supabase.table('notifications').delete().neq('_id', '0').execute()
        return jsonify({'isOk': True})
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "supabase_connected": supabase is not None,
        "firebase_admin_initialized": firebase_initialized,
        "jenni_configured": True,
        "timestamp": datetime.now().isoformat()
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 تشغيل نظام الثقة - متكامل مع نظام الزعيم")
    print(f"🌐 المنفذ: {port}")
    print(f"🔗 رابط التطبيق: http://localhost:{port}")
    print("=" * 50)
    
    # محاولة تسجيل الدخول إلى الزعيم عند بدء التشغيل
    jenni_login()
    
    app.run(debug=False, host='0.0.0.0', port=port)