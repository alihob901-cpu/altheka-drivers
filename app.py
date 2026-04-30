from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
from dotenv import load_dotenv
import json
import requests
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
import time

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

# ============== قائمة المحافظات ==============
GOVERNORATES_LIST = ['بغداد', 'البصرة', 'نينوى', 'أربيل', 'النجف', 'كركوك', 'الأنبار', 'كربلاء', 'ذي قار', 'ميسان', 'بابل', 'واسط', 'صلاح الدين', 'ديالى', 'المثنى', 'القادسية']

# ============== دالة تحويل المحافظات (مصححة حسب توثيق نظام الزعيم) ==============
def get_governorate_code(governorate_name):
    """تحويل اسم المحافظة إلى الكود المستخدم في نظام الزعيم"""
    governorate_map = {
        'بغداد': 'BGD',
        'البصرة': 'BAS',
        'نينوى': 'NIN',
        'أربيل': 'ARB',
        'النجف': 'NJF',
        'كركوك': 'KRK',
        'الأنبار': 'ANB',
        'كربلاء': 'KRB',
        'ذي قار': 'DHI',
        'ميسان': 'MYS',
        'بابل': 'BBL',
        'واسط': 'WST',
        'صلاح الدين': 'SAH',
        'ديالى': 'DYL',
        'المثنى': 'MTH',
        'القادسية': 'QAD'
    }
    code = governorate_map.get(governorate_name, 'BGD')
    print(f"🗺️ تحويل {governorate_name} -> {code}")
    return code

# ============== API لجلب قائمة المحافظات ==============
@app.route('/api/governorates', methods=['GET'])
def get_governorates():
    """إرجاع قائمة المحافظات للواجهة الأمامية"""
    return jsonify(GOVERNORATES_LIST)

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
            jenni_jwt_token = data.get("token") or data.get("access_token") or data.get("jwt")
            expires_in = data.get("expires_in", 86400)
            jenni_token_expiry = time.time() + expires_in
            print(f"✅ تم تسجيل الدخول إلى نظام الزعيم بنجاح")
            print(f"🔑 التوكن: {jenni_jwt_token[:50]}...")
            return True
        else:
            print(f"❌ فشل تسجيل الدخول إلى الزعيم: {response.status_code}")
            print(f"📄 الرد: {response.text}")
            return False
    except Exception as e:
        print(f"❌ خطأ في تسجيل الدخول إلى الزعيم: {e}")
        return False

def jenni_get_token():
    """الحصول على JWT token صالح (مع إعادة تسجيل الدخول إذا انتهى)"""
    import time
    global jenni_jwt_token, jenni_token_expiry
    
    if jenni_jwt_token and jenni_token_expiry and time.time() < jenni_token_expiry - 60:
        print(f"✅ التوكن صالح حتى: {datetime.fromtimestamp(jenni_token_expiry).strftime('%H:%M:%S')}")
        return jenni_jwt_token
    
    print("⚠️ التوكن منتهي أو غير موجود، إعادة تسجيل الدخول...")
    if jenni_login():
        return jenni_jwt_token
    return None

def create_shipment_in_jenni(order_data):
    """إرسال طلب جديد إلى نظام الزعيم"""
    print(f"📤 بدء إرسال الطلب {order_data.get('__backendId')} إلى نظام الزعيم...")
    
    token = jenni_get_token()
    if not token:
        print("❌ فشل الحصول على التوكن")
        return {"success": False, "error": "فشل المصادقة مع نظام الزعيم", "skip": True}
    
    governorate_name = order_data.get("governorate", "بغداد")
    governorate_code = get_governorate_code(governorate_name)
    
    phone = order_data.get("customer_phone", "")
    phone = ''.join(filter(str.isdigit, phone))
    if not phone.startswith('07') or len(phone) != 11:
        phone = "07717798622"
        print(f"⚠️ تم تصحيح رقم الهاتف إلى: {phone}")
    
    # ✅ الحصول على المواد (product_info) أو المنتج العادي مع الكمية
    product_info = order_data.get("product_info", "") or order_data.get("product", "")
    quantity = int(order_data.get("quantity", 1))
    if quantity > 1 and not order_data.get("product_info"):
        product_info = f"{order_data.get('product', '')} ×{quantity}"
    
    shipment_payload = {
        "system_code": JENNI_SYSTEM_CODE,
        "shipments": [{
            "shipment_number": str(order_data.get("__backendId", "")),
            "external_shipment_id": str(order_data.get("__backendId", "")),
            "receiver_name": order_data.get("customer_name", "زبون")[:50],
            "receiver_phone_1": phone,
            "receiver_phone_2": "",
            "governorate_code": governorate_code,
            "city": governorate_name,
            "address": order_data.get("customer_address", "عنوان غير محدد")[:100],
            "landmark": order_data.get("landmark", "")[:100],  # ✅ إضافة معلم (landmark)
            "amount_iqd": float(order_data.get("total", 0)),
            "amount_collect_iqd": float(order_data.get("total", 0)),
            "quantity": quantity,
            "weight": 0.5,
            "content_type": "parcel",
            "product_info": product_info[:200],
            "note": order_data.get("admin_notes", "")[:200],
            "is_fragile": False,
            "is_express": False
        }]
    }
    
    print(f"📍 المحافظة المرسلة: {governorate_name} -> {governorate_code}")
    print(f"📦 الحمولة المرسلة: {json.dumps(shipment_payload, ensure_ascii=False)}")
    
    auth_methods = [token, f"Bearer {token}"]
    
    for auth_method in auth_methods:
        try:
            print(f"🔑 محاولة المصادقة بـ: {auth_method[:30]}...")
            response = requests.post(
                f"{JENNI_API_URL}/v2/shipments/create",
                json=shipment_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": auth_method
                },
                timeout=30
            )
            
            print(f"📡 رد الزعيم: {response.status_code}")
            print(f"📄 نص الرد: {response.text}")
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                if result.get("accepted_shipments") and len(result["accepted_shipments"]) > 0:
                    shipment = result["accepted_shipments"][0]
                    print(f"✅ تم قبول الطلب في الزعيم، ID: {shipment.get('shipment_id')}")
                    return {
                        "success": True,
                        "shipment_id": shipment.get("shipment_id"),
                        "message": "تم إرسال الطلب إلى نظام الزعيم بنجاح"
                    }
                else:
                    rejected = result.get("rejected_shipments", [])
                    reason = rejected[0].get("reason", "سبب غير معروف") if rejected else "الطلب مرفوض"
                    print(f"⚠️ سبب الرفض: {reason}")
                    return {"success": False, "error": f"مرفوض: {reason}", "skip": True}
            elif response.status_code == 401:
                print(f"⚠️ فشل المصادقة بالطريقة الحالية، جرب الطريقة التالية...")
                continue
            else:
                print(f"❌ فشل الإرسال: {response.status_code}")
                return {"success": False, "error": f"فشل الإرسال: {response.status_code}", "skip": True}
        except Exception as e:
            print(f"❌ استثناء في الإرسال: {e}")
            continue
    
    return {"success": False, "error": "فشل جميع محاولات المصادقة", "skip": True}

# ============== دالة حذف الطلب من نظام الزعيم ==============
def delete_shipment_from_jenni(shipment_number):
    """حذف شحنة من نظام الزعيم"""
    print(f"🗑️ محاولة حذف الطلب {shipment_number} من نظام الزعيم...")
    
    token = jenni_get_token()
    if not token:
        print("❌ فشل الحصول على التوكن")
        return {"success": False, "error": "فشل المصادقة مع نظام الزعيم"}
    
    auth_methods = [token, f"Bearer {token}"]
    
    for auth_method in auth_methods:
        try:
            delete_response = requests.delete(
                f"{JENNI_API_URL}/v2/orders/{shipment_number}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": auth_method
                },
                timeout=30
            )
            
            print(f"📡 رد الحذف: {delete_response.status_code}")
            
            if delete_response.status_code == 200:
                print(f"✅ تم حذف الطلب {shipment_number} من نظام الزعيم بنجاح")
                return {"success": True, "message": "تم حذف الطلب من نظام الزعيم"}
            elif delete_response.status_code == 404:
                print(f"⚠️ الطلب {shipment_number} غير موجود في نظام الزعيم")
                return {"success": True, "message": "الطلب غير موجود في نظام الزعيم"}
            elif delete_response.status_code == 401:
                print(f"⚠️ فشل المصادقة بالطريقة الحالية، جرب الطريقة التالية...")
                continue
            else:
                return {"success": False, "error": f"فشل الحذف: {delete_response.status_code}"}
        except Exception as e:
            print(f"❌ خطأ في حذف الزعيم: {e}")
            continue
    
    return {"success": False, "error": "فشل جميع محاولات المصادقة"}

# ============== API لتصفير أرباح المندوب (سداد) ==============
@app.route('/api/settle-agent/<agent_id>', methods=['POST'])
def settle_agent(agent_id):
    """تصفير أرباح المندوب (حذف جميع الطلبات الواصلة)"""
    try:
        data = request.json
        paid_amount = data.get('paid_amount', 0)
        
        if not supabase:
            return jsonify({"success": False, "error": "Supabase not connected"}), 500
        
        # جلب المندوب
        agent_result = supabase.table('agents').select('*').eq('__backendId', agent_id).execute()
        if not agent_result.data:
            return jsonify({"success": False, "error": "المندوب غير موجود"}), 404
        
        agent = agent_result.data[0]
        agent_name = agent.get('agent_name')
        
        # جلب جميع الطلبات الواصلة للمندوب
        orders_result = supabase.table('orders').select('*').eq('agent_name', agent_name).eq('status', 'واصل').execute()
        orders = orders_result.data if orders_result.data else []
        
        deleted_count = 0
        for order in orders:
            # حذف من نظام الزعيم
            if order.get('__backendId'):
                delete_shipment_from_jenni(order.get('__backendId'))
            # حذف من قاعدة البيانات
            supabase.table('orders').delete().eq('__backendId', order.get('__backendId')).execute()
            deleted_count += 1
        
        # إضافة إشعار
        add_notification_to_db(
            'سداد أرباح',
            f'تم تسديد {paid_amount:,.0f} د.ع للمندوب {agent_name} وتم حذف {deleted_count} طلب',
            'settlement'
        )
        
        return jsonify({
            "success": True,
            "message": f"تم تسديد {paid_amount:,.0f} د.ع للمندوب {agent_name}",
            "deleted_orders": deleted_count
        })
        
    except Exception as e:
        print(f"❌ خطأ في تسديد أرباح المندوب: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============== مزامنة الحذف مع نظام الزعيم (Polling) ==============
def sync_deleted_shipments():
    """مزامنة الطلبات المحذوفة من نظام الزعيم (تحديد الطلبات التي تم حذفها من الزعيم وحذفها محلياً)"""
    print("🔄 [مزامنة] بدء مزامنة الحذف مع نظام الزعيم...")
    
    if not supabase:
        print("❌ Supabase غير متصل")
        return
    
    try:
        # جلب جميع الطلبات من قاعدة البيانات المحلية
        local_orders = supabase.table('orders').select('__backendId, jenni_shipment_id, customer_name').execute()
        
        if not local_orders.data:
            print("📭 لا توجد طلبات للمزامنة")
            return
        
        token = jenni_get_token()
        if not token:
            print("❌ فشل الحصول على التوكن")
            return
        
        deleted_count = 0
        checked_count = 0
        
        for order in local_orders.data:
            shipment_id = order.get('jenni_shipment_id')
            if not shipment_id:
                continue
                
            try:
                # الاستعلام عن الطلب في نظام الزعيم
                response = requests.post(
                    f"{JENNI_API_URL}/v2/shipments/query",
                    json={"shipment_ids": [int(shipment_id)]},
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                    timeout=30
                )
                
                checked_count += 1
                
                if response.status_code == 200:
                    result = response.json()
                    # إذا لم يتم العثور على الطلب في الزعيم، احذفه محلياً
                    if not result.get('shipments') or len(result['shipments']) == 0:
                        print(f"🗑️ [مزامنة] الطلب {order['__backendId']} (الزبون: {order.get('customer_name', 'غير معروف')}) غير موجود في الزعيم، يتم حذفه محلياً")
                        supabase.table('orders').delete().eq('__backendId', order['__backendId']).execute()
                        deleted_count += 1
                elif response.status_code == 401:
                    # توكن منتهي، حاول تسجيل الدخول مرة أخرى
                    print("⚠️ توكن منتهي، محاولة إعادة التسجيل...")
                    token = jenni_login()
                    if token:
                        continue
                else:
                    print(f"⚠️ فشل الاستعلام للطلب {order['__backendId']}: {response.status_code}")
                    
            except Exception as e:
                print(f"❌ خطأ في الاستعلام للطلب {order['__backendId']}: {e}")
                continue
        
        print(f"✅ [مزامنة] اكتملت المزامنة: تم فحص {checked_count} طلب، تم حذف {deleted_count} طلب محلياً")
        
        # إضافة إشعار في قاعدة البيانات
        if deleted_count > 0:
            add_notification_to_db(
                'مزامنة مع الزعيم',
                f'تم حذف {deleted_count} طلب تلقائياً (لم يتم العثور عليها في نظام الزعيم)',
                'status'
            )
        
    except Exception as e:
        print(f"❌ خطأ في مزامنة الحذف: {e}")

# ============== API للمزامنة اليدوية ==============
@app.route('/api/sync-with-jenni', methods=['POST'])
def sync_with_jenni():
    """مزامنة يدوية مع نظام الزعيم - حذف الطلبات التي تم حذفها من الزعيم"""
    try:
        print("🔄 بدء مزامنة يدوية مع نظام الزعيم...")
        sync_deleted_shipments()
        return jsonify({"success": True, "message": "تمت المزامنة بنجاح"})
    except Exception as e:
        print(f"❌ خطأ في المزامنة اليدوية: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

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
        
        # إزالة الحقول التي قد تسبب مشكلة (مع الاحتفاظ بـ product_info, landmark للإرسال إلى الزعيم)
        insert_item = {k: v for k, v in new_item.items() if k not in ['governorate', 'district', 'governorate_code', 'jenni_last_update']}
        
        result = supabase.table(table_name).insert(insert_item).execute()
        
        if result.data:
            returned_data = result.data[0]
            if 'type' not in returned_data:
                returned_data['type'] = table_name[:-1] if table_name != 'orders' else 'order'
            
            if table_name == 'orders' and new_item.get('status') == 'جديد':
                print("🚀 بدء إرسال الطلب إلى نظام الزعيم...")
                try:
                    jenni_result = create_shipment_in_jenni(new_item)
                    print(f"📊 نتيجة الإرسال إلى الزعيم: {jenni_result}")
                    
                    if jenni_result.get("success") and jenni_result.get("shipment_id"):
                        supabase.table('orders').update({
                            "jenni_shipment_id": str(jenni_result["shipment_id"])
                        }).eq('__backendId', new_item['__backendId']).execute()
                        print(f"📤 تم إرسال الطلب إلى نظام الزعيم بنجاح")
                    else:
                        print(f"⚠️ فشل إرسال الطلب إلى الزعيم (تم حفظه محلياً فقط)")
                except Exception as e:
                    print(f"❌ خطأ في إرسال الزعيم: {e}")
            
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
        
        order_result = supabase.table('orders').select('*').eq('__backendId', item_id).execute()
        
        if order_result.data:
            order = order_result.data[0]
            print(f"🗑️ حذف الطلب {item_id} من نظام الزعيم...")
            delete_result = delete_shipment_from_jenni(item_id)
            if delete_result.get("success"):
                print("✅ تم حذف الطلب من نظام الزعيم")
            else:
                print(f"⚠️ فشل حذف الطلب من الزعيم: {delete_result.get('error')}")
        
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

def add_notification_to_db(title, message, type):
    """إضافة إشعار إلى قاعدة البيانات"""
    try:
        if supabase:
            supabase.table('notifications').insert({
                '_id': str(int(datetime.now().timestamp() * 1000)),
                'title': title,
                'message': message,
                'type': type,
                'read': False,
                'created_at': datetime.now().isoformat()
            }).execute()
    except Exception as e:
        print(f"خطأ في إضافة الإشعار: {e}")

# ============== الحذف من الزعيم عبر API ==============
@app.route('/api/delete-from-jenni/<shipment_number>', methods=['DELETE'])
def api_delete_from_jenni(shipment_number):
    """API لحذف شحنة من نظام الزعيم"""
    result = delete_shipment_from_jenni(shipment_number)
    return jsonify(result)

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
        print(f"📬 استلام تحديث من نظام الزعيم: {data}")
        
        system_code = data.get('system_code')
        updates = data.get('updates', [])
        
        if system_code != JENNI_SYSTEM_CODE:
            return jsonify({"success": False, "message": "Invalid system code"}), 401
        
        for update in updates:
            shipment_number = update.get('shipment_number')
            current_step = update.get('current_step')
            current_step_ar = update.get('current_step_ar')
            note = update.get('note')
            
            print(f"📦 تحديث للطلب {shipment_number}: {current_step} - {current_step_ar}")
            
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

# ============== تشغيل المهام المجدولة ==============
def start_scheduler():
    """تشغيل المجدول للمهام الخلفية"""
    scheduler = BackgroundScheduler()
    # تشغيل مزامنة الحذف كل ساعة
    scheduler.add_job(func=sync_deleted_shipments, trigger="interval", hours=1, id='sync_deleted_job')
    scheduler.start()
    print("✅ تم تشغيل المجدول - سيتم مزامنة الحذف مع الزعيم كل ساعة")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 تشغيل نظام الثقة - متكامل مع نظام الزعيم")
    print(f"🌐 المنفذ: {port}")
    print(f"🔗 رابط التطبيق: http://localhost:{port}")
    print("=" * 50)
    
    jenni_login()
    
    # تشغيل المجدول
    start_scheduler()
    
    app.run(debug=False, host='0.0.0.0', port=port)