from flask import Flask, render_template, request, jsonify, session, make_response
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import time
import uuid
from functools import wraps
import threading
import gc
import signal
import sys
import atexit

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)
CORS(app)

# ============== إعداد الجلسات الآمنة ==============
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'trust-center-secret-key-change-this-2024')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400

# ============== تحسين إدارة الجلسات ==============
active_sessions_cache = {}
SESSION_CACHE_TTL = 300

def store_session_in_db(session_id, user_id, user_data):
    try:
        if supabase:
            expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
            supabase.table('active_sessions').upsert({
                'session_id': session_id,
                'user_id': user_id,
                'user_data': json.dumps(user_data),
                'created_at': datetime.now().isoformat(),
                'expires_at': expires_at,
                'last_accessed': datetime.now().isoformat()
            }, on_conflict='session_id').execute()
            return True
    except Exception as e:
        print(f"⚠️ خطأ في تخزين الجلسة: {e}")
    return False

def get_session_from_db(session_id):
    try:
        if supabase:
            result = supabase.table('active_sessions').select('*').eq('session_id', session_id).execute()
            if result.data:
                session_data = result.data[0]
                if datetime.fromisoformat(session_data['expires_at']) > datetime.now():
                    return session_data
                else:
                    supabase.table('active_sessions').delete().eq('session_id', session_id).execute()
    except Exception as e:
        print(f"⚠️ خطأ في استرجاع الجلسة: {e}")
    return None

def cleanup_expired_sessions():
    try:
        if supabase:
            result = supabase.table('active_sessions').delete().lt('expires_at', datetime.now().isoformat()).execute()
            if result.data:
                print(f"✅ تم تنظيف {len(result.data)} جلسة منتهية")
    except Exception as e:
        print(f"⚠️ خطأ في تنظيف الجلسات: {e}")

# ============== إعداد Supabase ==============
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zmzotoutdeeizyfoikfw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_BqRz02wzKGRblUsM05DnOA_ovErV7U2")

# ============== إعداد نظام الزعيم ==============
JENNI_API_URL = "https://jenni.alzaeemexp.com/api"
JENNI_USERNAME = os.getenv("JENNI_USERNAME", "07717798622")
JENNI_PASSWORD = os.getenv("JENNI_PASSWORD", "30007000")
JENNI_SYSTEM_CODE = os.getenv("JENNI_SYSTEM_CODE", "ECOMMERCE_STORE_01")
JENNI_WEBHOOK_TOKEN = os.getenv("JENNI_WEBHOOK_TOKEN", "TrustCenterSecretKey123")

jenni_jwt_token = None
jenni_token_expiry = None
jenni_token_lock = threading.Lock()

# ============== طابور الطلبات الفاشلة ==============
pending_orders_queue = []
pending_orders_lock = threading.Lock()

def add_to_pending_queue(order_data):
    with pending_orders_lock:
        pending_orders_queue.append({
            'order_data': order_data,
            'attempts': 0,
            'last_attempt': datetime.now().isoformat(),
            'created_at': datetime.now().isoformat()
        })
        print(f"📋 تم إضافة الطلب {order_data.get('__backendId')} إلى طابور الانتظار")

def process_pending_queue():
    print(f"🔄 [QUEUE] بدء معالجة طابور الانتظار - {len(pending_orders_queue)} طلب معلق")
    
    with pending_orders_lock:
        to_process = pending_orders_queue.copy()
    
    for pending in to_process:
        try:
            if pending['attempts'] >= 5:
                print(f"❌ تم تجاوز عدد المحاولات للطلب {pending['order_data'].get('__backendId')}")
                with pending_orders_lock:
                    if pending in pending_orders_queue:
                        pending_orders_queue.remove(pending)
                continue
            
            print(f"🔄 محاولة إعادة إرسال الطلب {pending['order_data'].get('__backendId')} (محاولة {pending['attempts'] + 1})")
            result = create_shipment_in_jenni(pending['order_data'])
            
            if result.get("success") and result.get("shipment_id"):
                if supabase:
                    supabase.table('orders').update({
                        "jenni_shipment_id": str(result["shipment_id"])
                    }).eq('__backendId', pending['order_data']['__backendId']).execute()
                
                with pending_orders_lock:
                    if pending in pending_orders_queue:
                        pending_orders_queue.remove(pending)
                print(f"✅ تم إرسال الطلب المعلق {pending['order_data'].get('__backendId')} بنجاح")
            else:
                with pending_orders_lock:
                    for p in pending_orders_queue:
                        if p['order_data']['__backendId'] == pending['order_data']['__backendId']:
                            p['attempts'] += 1
                            p['last_attempt'] = datetime.now().isoformat()
                            break
        except Exception as e:
            print(f"❌ خطأ في معالجة الطلب المعلق: {e}")
    
    print(f"✅ [QUEUE] انتهت معالجة الطابور - {len(pending_orders_queue)} طلب متبقي")

# ============== إعداد Firebase ==============
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

# ============== دوال الأمان ==============

def invalidate_all_sessions():
    try:
        if supabase:
            supabase.table('active_sessions').delete().neq('session_id', '0').execute()
        active_sessions_cache.clear()
        print("✅ تم إبطال جميع الجلسات النشطة")
    except Exception as e:
        print(f"⚠️ خطأ في إبطال الجلسات: {e}")

def session_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = request.cookies.get('session_id')
        if not session_id:
            return jsonify({"error": "غير مصرح به", "code": "UNAUTHORIZED"}), 401
        
        session_data = get_session_from_db(session_id)
        if not session_data:
            return jsonify({"error": "الجلسة منتهية أو غير صالحة", "code": "SESSION_EXPIRED"}), 401
        
        try:
            supabase.table('active_sessions').update({
                'last_accessed': datetime.now().isoformat()
            }).eq('session_id', session_id).execute()
        except:
            pass
        
        return f(*args, **kwargs)
    return decorated_function

def log_login_attempt(username, success, ip_address, user_agent):
    try:
        if supabase:
            try:
                supabase.table('login_logs').insert({
                    'username': username,
                    'success': success,
                    'ip_address': ip_address,
                    'user_agent': user_agent[:200] if user_agent else '',
                    'timestamp': datetime.now().isoformat()
                }).execute()
            except Exception as e:
                print(f"⚠️ لا يمكن تسجيل المحاولة: {e}")
    except Exception as e:
        print(f"خطأ في تسجيل محاولة الدخول: {e}")

# ============== API الأمان ==============

@app.route('/api/logout-all', methods=['POST'])
def logout_all_devices():
    try:
        data = request.get_json() or {}
        admin_password = data.get('admin_password')
        
        if admin_password != '1234321ali123':
            return jsonify({"success": False, "error": "كلمة المرور غير صحيحة"}), 401
        
        invalidate_all_sessions()
        
        add_notification_to_db(
            '🔐 أمان النظام',
            f'تم تسجيل الخروج من جميع الأجهزة - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            'security'
        )
        
        return jsonify({"success": True, "message": "تم تسجيل الخروج من جميع الأجهزة"}), 200
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/change-admin-password', methods=['POST'])
def change_admin_password():
    try:
        data = request.get_json()
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        
        if old_password != '1234321ali123':
            return jsonify({"success": False, "error": "كلمة المرور الحالية غير صحيحة"}), 401
        
        if len(new_password) < 8:
            return jsonify({"success": False, "error": "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل"}), 400
        
        if supabase:
            supabase.table('agents').update({
                "agent_password": new_password
            }).eq('agent_code', 'admin').execute()
            
            supabase.table('agents').update({
                "agent_password": new_password
            }).eq('agent_name', 'المدير العام').execute()
        
        invalidate_all_sessions()
        
        add_notification_to_db(
            '🔐 تغيير كلمة المرور',
            'تم تغيير كلمة مرور الأدمن بنجاح',
            'security'
        )
        
        return jsonify({"success": True, "message": "تم تغيير كلمة المرور وتسجيل الخروج من جميع الأجهزة"}), 200
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/active-sessions', methods=['GET'])
def get_active_sessions():
    try:
        session_count = 0
        if supabase:
            result = supabase.table('active_sessions').select('*', count='exact').execute()
            session_count = result.count if hasattr(result, 'count') else 0
        
        return jsonify({
            "success": True,
            "active_sessions_count": session_count,
            "users": []
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============== قائمة المحافظات ==============
GOVERNORATES_LIST = [
    'بغداد', 'البصرة', 'نينوى', 'أربيل', 'النجف', 'كركوك', 'الأنبار', 'كربلاء',
    'ذي قار', 'ميسان', 'بابل', 'واسط', 'صلاح الدين', 'ديالى', 'المثنى', 'القادسية',
    'السليمانية', 'دهوك'
]

def get_governorate_code(governorate_name):
    governorate_map = {
        'بغداد': 'BGD', 'البصرة': 'BAS', 'نينوى': 'NIN', 'أربيل': 'ARB',
        'النجف': 'NJF', 'كركوك': 'KRK', 'الأنبار': 'ANB', 'كربلاء': 'KRB',
        'ذي قار': 'DHI', 'ميسان': 'MYS', 'بابل': 'BBL', 'واسط': 'WST',
        'صلاح الدين': 'SAH', 'ديالى': 'DYL', 'المثنى': 'MTH', 'القادسية': 'QAD',
        'السليمانية': 'SMH', 'دهوك': 'DOH'
    }
    return governorate_map.get(governorate_name, 'BGD')

@app.route('/api/governorates', methods=['GET'])
def get_governorates():
    return jsonify(GOVERNORATES_LIST)

# ============== دوال نظام الزعيم ==============
def jenni_login():
    global jenni_jwt_token, jenni_token_expiry
    
    with jenni_token_lock:
        print("🔑 محاولة تسجيل الدخول إلى نظام الزعيم...")
        try:
            response = requests.post(
                f"{JENNI_API_URL}/v2/auth/login",
                json={"username": JENNI_USERNAME, "password": JENNI_PASSWORD},
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                jenni_jwt_token = data.get("token") or data.get("access_token") or data.get("jwt")
                expires_in = data.get("expires_in", 86400)
                jenni_token_expiry = time.time() + expires_in
                print(f"✅ تم تسجيل الدخول إلى نظام الزعيم بنجاح")
                return True
            else:
                print(f"❌ فشل تسجيل الدخول: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ خطأ في تسجيل الدخول: {e}")
            return False

def jenni_get_token():
    global jenni_jwt_token, jenni_token_expiry
    
    with jenni_token_lock:
        if jenni_jwt_token and jenni_token_expiry and time.time() < jenni_token_expiry - 60:
            return jenni_jwt_token
    
    print("⚠️ التوكن منتهي أو غير موجود، إعادة تسجيل الدخول...")
    if jenni_login():
        return jenni_jwt_token
    return None

def arabic_to_english_numbers(text):
    arabic_numerals = {'٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
                       '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'}
    if not text:
        return text
    text = str(text)
    for arabic, english in arabic_numerals.items():
        text = text.replace(arabic, english)
    return text

def create_shipment_in_jenni(order_data):
    print(f"📤 بدء إرسال الطلب {order_data.get('__backendId')} إلى نظام الزعيم...")
    
    token = jenni_get_token()
    if not token:
        print("❌ فشل الحصول على التوكن")
        return {"success": False, "error": "فشل المصادقة مع نظام الزعيم", "skip": True}
    
    governorate_name = order_data.get("governorate", "بغداد")
    governorate_code = get_governorate_code(governorate_name)
    
    phone = order_data.get("customer_phone", "")
    original_phone = phone
    
    phone = ''.join(filter(lambda x: x.isdigit() or x in '٠١٢٣٤٥٦٧٨٩', phone))
    phone = arabic_to_english_numbers(phone)
    
    if phone.startswith('7') and len(phone) == 9:
        phone = '0' + phone
    
    if not phone.startswith('07') or len(phone) not in [10, 11]:
        phone = ''.join(filter(str.isdigit, original_phone))
        phone = arabic_to_english_numbers(phone)
    
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
            "landmark": order_data.get("landmark", "")[:100],
            "amount_iqd": float(order_data.get("total", 0)),
            "quantity": quantity,
            "weight": 0.5,
            "content_type": "parcel",
            "product_info": product_info[:200],
            "note": order_data.get("admin_notes", "")[:200],
            "is_fragile": False,
            "is_express": False
        }]
    }
    
    auth_headers = [
        {"Authorization": f"Bearer {token}"},
        {"Authorization": token},
        {"x-access-token": token},
        {"api-key": token}
    ]
    
    for idx, auth_header in enumerate(auth_headers):
        try:
            response = requests.post(
                f"{JENNI_API_URL}/v2/shipments/create",
                json=shipment_payload,
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            
            if response.status_code in [200, 201]:
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
                    return {"success": False, "error": f"مرفوض: {reason}", "skip": True}
            elif response.status_code == 401:
                continue
            else:
                return {"success": False, "error": f"فشل الإرسال: {response.status_code}", "skip": True}
        except Exception as e:
            print(f"❌ استثناء: {e}")
            continue
    
    return {"success": False, "error": "فشل جميع محاولات المصادقة", "skip": True}

def cancel_shipment_in_jenni(shipment_number, reason="تم إلغاء الطلب"):
    print(f"📝 محاولة إلغاء الطلب {shipment_number}...")
    
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة"}
    
    update_payload = {
        "system_code": JENNI_SYSTEM_CODE,
        "updates": [{
            "shipment_number": str(shipment_number),
            "action_code": "RETURN_TO_STORE",
            "note": f"{reason} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }]
    }
    
    auth_headers = [
        {"Authorization": f"Bearer {token}"},
        {"Authorization": token}
    ]
    
    for idx, auth_header in enumerate(auth_headers):
        try:
            response = requests.post(
                f"{JENNI_API_URL}/v2/push/update-status",
                json=update_payload,
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"✅ تم إلغاء الطلب {shipment_number}")
                return {"success": True, "action": "cancelled"}
            elif response.status_code == 401:
                continue
            else:
                return {"success": False, "error": f"فشل الإلغاء: {response.status_code}"}
        except Exception as e:
            continue
    
    return {"success": False, "error": "فشل جميع محاولات الإلغاء"}

def delete_shipment_by_id(shipment_id):
    print(f"🗑️ محاولة حذف الطلب بالـ ID: {shipment_id}...")
    
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة"}
    
    auth_headers = [
        {"Authorization": f"Bearer {token}"},
        {"Authorization": token}
    ]
    
    for idx, auth_header in enumerate(auth_headers):
        try:
            response = requests.delete(
                f"{JENNI_API_URL}/v2/orders/{shipment_id}",
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"✅ تم حذف الطلب (ID: {shipment_id})")
                return {"success": True, "action": "deleted"}
            elif response.status_code == 404:
                return {"success": True, "action": "not_found"}
            elif response.status_code == 401:
                continue
            else:
                return {"success": False, "error": f"فشل الحذف: {response.status_code}"}
        except Exception as e:
            continue
    
    return {"success": False, "error": "فشل جميع محاولات المصادقة"}

def delete_or_cancel_shipment_in_jenni(shipment_number):
    if not supabase:
        return {"success": False, "error": "Supabase not connected"}
    
    try:
        order_result = supabase.table('orders').select('jenni_shipment_id').eq('__backendId', shipment_number).execute()
        if order_result.data and order_result.data[0].get('jenni_shipment_id'):
            return delete_shipment_by_id(order_result.data[0]['jenni_shipment_id'])
    except Exception as e:
        print(f"❌ خطأ: {e}")
    
    return cancel_shipment_in_jenni(shipment_number)

@app.route('/api/settle-agent/<agent_id>', methods=['POST'])
def settle_agent(agent_id):
    try:
        data = request.json
        paid_amount = data.get('paid_amount', 0)
        
        if not supabase:
            return jsonify({"success": False, "error": "Supabase not connected"}), 500
        
        agent_result = supabase.table('agents').select('*').eq('__backendId', agent_id).execute()
        if not agent_result.data:
            return jsonify({"success": False, "error": "المندوب غير موجود"}), 404
        
        agent = agent_result.data[0]
        agent_name = agent.get('agent_name')
        
        orders_result = supabase.table('orders').select('*').eq('agent_name', agent_name).eq('status', 'واصل').execute()
        orders = orders_result.data if orders_result.data else []
        
        if not orders:
            return jsonify({"success": False, "error": "لا توجد أرباح مستحقة"}), 400
        
        total_profit = sum(order.get('profit', 0) for order in orders)
        
        if paid_amount <= 0:
            return jsonify({"success": False, "error": "الرجاء إدخال مبلغ السداد"}), 400
        
        if paid_amount > total_profit:
            return jsonify({"success": False, "error": f"المبلغ أكبر من إجمالي الأرباح ({total_profit:,.0f} د.ع)"}), 400
        
        for order in orders:
            supabase.table('orders').update({
                "profit": 0,
                "updated_at": datetime.now().isoformat()
            }).eq('__backendId', order['__backendId']).execute()
        
        add_notification_to_db(
            'سداد أرباح',
            f'تم تسديد {paid_amount:,.0f} د.ع للمندوب {agent_name} (تم تصفير أرباح {len(orders)} طلب)',
            'settlement'
        )
        
        return jsonify({
            "success": True,
            "message": f"تم تسديد {paid_amount:,.0f} د.ع للمندوب {agent_name}",
            "orders_cleared": len(orders)
        })
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============== وظائف المزامنة (بدون حدود) ==============
def sync_deleted_shipments():
    """مزامنة الحذف مع نظام الزعيم - بدون حدود للطلبات"""
    print(f"🔄 [SYNC] بدء مزامنة الحذف - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not supabase:
        return
    
    try:
        token = jenni_get_token()
        if not token:
            return
        
        deleted_count = 0
        # ✅ بدون حد - جلب جميع الطلبات
        local_orders = supabase.table('orders').select('__backendId, jenni_shipment_id').execute()
        
        # إذا كان هناك أكثر من 1000 طلب، استخدم pagination للحصول على الكل
        if len(local_orders.data) > 500:
            print(f"📊 عدد الطلبات كبير ({len(local_orders.data)}), استخدام pagination...")
            page_size = 500
            offset = 0
            all_orders = []
            while True:
                batch = supabase.table('orders')\
                    .select('__backendId, jenni_shipment_id')\
                    .range(offset, offset + page_size - 1)\
                    .execute()
                if not batch.data:
                    break
                all_orders.extend(batch.data)
                offset += page_size
            local_orders.data = all_orders
        
        print(f"📋 جاري فحص {len(local_orders.data)} طلب...")
        
        for order in local_orders.data:
            if not order.get('jenni_shipment_id'):
                continue
            
            try:
                response = requests.post(
                    f"{JENNI_API_URL}/v2/shipments/query",
                    json={"shipment_ids": [int(order['jenni_shipment_id'])]},
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if not result.get('shipments'):
                        supabase.table('orders').delete().eq('__backendId', order['__backendId']).execute()
                        deleted_count += 1
                        print(f"🗑️ تم حذف الطلب {order['__backendId']}")
            except Exception as e:
                print(f"❌ خطأ في استعلام الشحنة: {e}")
                continue
        
        if deleted_count > 0:
            add_notification_to_db('مزامنة مع الزعيم', f'تم حذف {deleted_count} طلب', 'status')
            
    except Exception as e:
        print(f"❌ خطأ في مزامنة الحذف: {e}")

def sync_active_orders_from_jenni():
    """جلب تحديثات الطلبات النشطة من نظام الزعيم (Polling) - بدون حدود"""
    print(f"🔄 [POLLING] بدء جلب تحديثات الطلبات - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not supabase:
        return
    
    token = jenni_get_token()
    if not token:
        return
    
    active_statuses = ['جديد', 'قيد التوصيل', 'راجع', 'مؤجل']
    active_orders = []
    
    try:
        for status in active_statuses:
            # ✅ بدون حد - جلب جميع الطلبات النشطة
            result = supabase.table('orders').select('__backendId, jenni_shipment_id, customer_name, status').eq('status', status).execute()
            if result.data:
                active_orders.extend(result.data)
        
        active_orders = [o for o in active_orders if o.get('jenni_shipment_id')]
        
        if not active_orders:
            print("📭 لا توجد طلبات نشطة")
            return
        
        print(f"📋 تم العثور على {len(active_orders)} طلب نشط")
        
        status_map = {
            'DELIVERED': 'واصل', 'DELIVERED_PRICE_CHANGED': 'واصل',
            'PARTIALLY_DELIVERED': 'واصل', 'FORCE_DELIVERY': 'واصل',
            'OFD': 'قيد التوصيل', 'POSTPONED': 'مؤجل',
            'DELIVERY_REATTEMPT': 'قيد التوصيل', 'TRANSIT': 'قيد التوصيل',
            'RTO_WH': 'راجع', 'RTO_WITH_DA': 'راجع', 'RTO_CONFIRMED': 'راجع',
            'CANCELLED': 'ملغي', 'REJECTED_PRICE_CHANGE': 'ملغي'
        }
        
        updated_count = 0
        
        for order in active_orders:
            try:
                response = requests.post(
                    f"{JENNI_API_URL}/v2/shipments/query",
                    json={"shipment_ids": [int(order['jenni_shipment_id'])]},
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    for shipment in result.get('shipments', []):
                        current_step = shipment.get('current_step')
                        new_status = status_map.get(current_step)
                        
                        if new_status and order.get('status') != new_status:
                            supabase.table('orders').update({
                                "status": new_status,
                                "updated_at": datetime.now().isoformat(),
                                "jenni_last_update": datetime.now().isoformat()
                            }).eq('__backendId', order['__backendId']).execute()
                            
                            updated_count += 1
                            print(f"✅ تم تحديث الطلب {order['__backendId']} إلى {new_status}")
                            
            except Exception as e:
                continue
        
        if updated_count > 0:
            print(f"✅ تم تحديث {updated_count} طلب")
            
    except Exception as e:
        print(f"❌ خطأ في المزامنة: {e}")

@app.route('/api/sync-with-jenni', methods=['POST'])
def sync_with_jenni():
    try:
        sync_deleted_shipments()
        return jsonify({"success": True, "message": "تمت المزامنة بنجاح"})
    except Exception as e:
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
            android=messaging.AndroidConfig(priority="high"),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(aps=messaging.Aps(sound="default", badge=1))
            )
        )
        messaging.send(message)
        return True
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False

def send_fcm_notification_via_legacy(fcm_token, title, body, data=None):
    if not fcm_token or not FCM_SERVER_KEY:
        return False
    
    url = "https://fcm.googleapis.com/fcm/send"
    headers = {"Authorization": f"key={FCM_SERVER_KEY}", "Content-Type": "application/json"}
    notification_data = {"to": fcm_token, "notification": {"title": title, "body": body}, "data": data or {}}
    
    try:
        response = requests.post(url, headers=headers, json=notification_data)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False

def send_notification_to_user(user_id, title, body, order_id=None):
    try:
        if not supabase:
            return False
        result = supabase.table('fcm_tokens').select('fcm_token').eq('user_id', user_id).execute()
        if not result.data:
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
        orders = supabase.table('orders').select('*').execute()
        agents = supabase.table('agents').select('*').execute()
        
        for o in (orders.data or []):
            o['type'] = 'order'
        for a in (agents.data or []):
            a['type'] = 'agent'
        
        return (orders.data or []) + (agents.data or [])
    except Exception as e:
        print(f"❌ خطأ في جلب البيانات: {e}")
        return []

# ============== API Routes ==============

@app.route('/api/data', methods=['GET'])
def get_data():
    try:
        return jsonify(get_all_data())
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
        
        table_name = 'agents' if new_item.get('type') == 'agent' else 'orders'
        
        insert_item = {k: v for k, v in new_item.items() if k not in ['governorate', 'district', 'governorate_code']}
        
        result = supabase.table(table_name).insert(insert_item).execute()
        
        if result.data:
            if table_name == 'orders' and new_item.get('status') == 'جديد':
                print("🚀 بدء إرسال الطلب إلى نظام الزعيم...")
                try:
                    jenni_result = create_shipment_in_jenni(new_item)
                    if jenni_result.get("success") and jenni_result.get("shipment_id"):
                        supabase.table('orders').update({
                            "jenni_shipment_id": str(jenni_result["shipment_id"])
                        }).eq('__backendId', new_item['__backendId']).execute()
                        print(f"✅ تم إرسال الطلب إلى نظام الزعيم بنجاح")
                    else:
                        print(f"⚠️ فشل إرسال الطلب إلى الزعيم: {jenni_result.get('error')}")
                        add_to_pending_queue(new_item)
                except Exception as e:
                    print(f"❌ خطأ في إرسال الطلب للزعيم: {e}")
                    add_to_pending_queue(new_item)
            
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        
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
        
        old_result = supabase.table(table_name).select('*').eq('__backendId', item_id).execute()
        old_item = old_result.data[0] if old_result.data else None
        
        result = supabase.table(table_name).update(updated_item).eq('__backendId', item_id).execute()
        
        if result.data and old_item and old_item.get('status') != updated_item.get('status'):
            agent_name = old_item.get('agent_name')
            if agent_name and agent_name not in ['admin', 'المدير العام']:
                customer_name = old_item.get('customer_name', 'زبون')
                new_status = updated_item.get('status')
                titles = {
                    'واصل': '✅ طلب واصل',
                    'راجع': '↩️ طلب مرتجع',
                    'قيد التوصيل': '🚚 طلب قيد التوصيل',
                    'ملغي': '❌ طلب ملغي',
                    'مؤجل': '📅 طلب مؤجل'
                }
                title = titles.get(new_status, '📋 تحديث حالة الطلب')
                body = f"تم تغيير حالة طلب {customer_name} إلى {new_status}"
                send_notification_to_user(agent_name, title, body, item_id)
        
        return jsonify({'isOk': True, 'data': result.data[0]}) if result.data else jsonify({'isOk': False, 'error': 'Not found'}), 404
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
            print(f"🗑️ حذف الطلب {item_id} من نظام الزعيم...")
            delete_or_cancel_shipment_in_jenni(item_id)
        
        result = supabase.table('orders').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        result = supabase.table('agents').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        return jsonify({'isOk': False, 'error': 'Not found'}), 404
    except Exception as e:
        print(f"API Error DELETE: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

def add_notification_to_db(title, message, type):
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

@app.route('/api/delete-from-jenni/<shipment_number>', methods=['DELETE'])
def api_delete_from_jenni(shipment_number):
    result = delete_or_cancel_shipment_in_jenni(shipment_number)
    return jsonify(result)

@app.route('/api/cancel-in-jenni/<shipment_number>', methods=['POST'])
def api_cancel_in_jenni(shipment_number):
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'تم إلغاء الطلب')
        result = cancel_shipment_in_jenni(shipment_number, reason)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/v2/push/update-status', methods=['POST'])
def jenni_webhook():
    try:
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''
        
        if token != JENNI_WEBHOOK_TOKEN:
            return jsonify({"success": False, "message": "Invalid token"}), 401
        
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "message": "No data"}), 400
        
        system_code = data.get('system_code')
        updates = data.get('updates', [])
        
        if system_code != JENNI_SYSTEM_CODE:
            return jsonify({"success": False, "message": "Invalid system code"}), 401
        
        status_map = {
            'DELIVERED': 'واصل', 'DELIVERED_PRICE_CHANGED': 'واصل',
            'PARTIALLY_DELIVERED': 'واصل', 'FORCE_DELIVERY': 'واصل',
            'OFD': 'قيد التوصيل', 'POSTPONED': 'مؤجل',
            'DELIVERY_REATTEMPT': 'قيد التوصيل', 'TRANSIT': 'قيد التوصيل',
            'RTO_WH': 'راجع', 'RTO_WITH_DA': 'راجع', 'RTO_CONFIRMED': 'راجع',
            'CANCELLED': 'ملغي', 'REJECTED_PRICE_CHANGE': 'ملغي'
        }
        
        updated_count = 0
        
        for update in updates:
            shipment_number = update.get('shipment_number')
            current_step = update.get('current_step')
            note = update.get('note')
            
            new_status = status_map.get(current_step)
            
            if new_status and supabase and shipment_number:
                result = supabase.table('orders').update({
                    "status": new_status,
                    "admin_notes": note if note else None,
                    "updated_at": datetime.now().isoformat(),
                    "jenni_last_update": datetime.now().isoformat()
                }).eq('__backendId', shipment_number).execute()
                
                if result.data:
                    updated_count += 1
                    print(f"✅ تم تحديث الطلب {shipment_number} إلى {new_status}")
        
        return jsonify({"success": True, "message": f"Processed {updated_count} updates"}), 200
        
    except Exception as e:
        print(f"❌ خطأ في معالجة Webhook: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

# ============== Routes للواجهة ==============
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
        
        if not user_id or not fcm_token or not supabase:
            return jsonify({"isOk": False, "error": "Missing data"}), 400
        
        existing = supabase.table('fcm_tokens').select('*').eq('user_id', user_id).execute()
        if existing.data:
            supabase.table('fcm_tokens').update({'fcm_token': fcm_token, 'updated_at': datetime.now().isoformat()}).eq('user_id', user_id).execute()
        else:
            supabase.table('fcm_tokens').insert({'user_id': user_id, 'fcm_token': fcm_token, 'created_at': datetime.now().isoformat()}).execute()
        
        return jsonify({'isOk': True})
    except Exception as e:
        print(f"API Error: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    try:
        if not supabase:
            return jsonify([]), 500
        result = supabase.table('notifications').select('*').order('created_at', desc=True).execute()
        return jsonify(result.data or [])
    except Exception:
        return jsonify([]), 500

@app.route('/api/notifications', methods=['POST'])
def add_notification():
    try:
        item = request.json
        if not item or not supabase:
            return jsonify({"isOk": False}), 400
        item['_id'] = str(int(datetime.now().timestamp() * 1000))
        item['created_at'] = datetime.now().isoformat()
        result = supabase.table('notifications').insert(item).execute()
        return jsonify({'isOk': True, 'data': result.data[0]}) if result.data else jsonify({'isOk': False}), 201
    except Exception:
        return jsonify({"isOk": False}), 500

@app.route('/api/notifications/<notification_id>/read', methods=['PUT'])
def mark_notification_read(notification_id):
    try:
        if not supabase:
            return jsonify({"isOk": False}), 500
        supabase.table('notifications').update({'read': True}).eq('_id', notification_id).execute()
        return jsonify({'isOk': True})
    except Exception:
        return jsonify({"isOk": False}), 500

@app.route('/api/notifications', methods=['DELETE'])
def delete_all_notifications():
    try:
        if supabase:
            supabase.table('notifications').delete().neq('_id', '0').execute()
        return jsonify({'isOk': True})
    except Exception:
        return jsonify({"isOk": False}), 500

@app.route('/api/pending-queue-status', methods=['GET'])
def get_pending_queue_status():
    with pending_orders_lock:
        return jsonify({
            "queue_size": len(pending_orders_queue),
            "pending_orders": [
                {
                    "order_id": p['order_data'].get('__backendId'),
                    "attempts": p['attempts'],
                    "last_attempt": p['last_attempt']
                } for p in pending_orders_queue
            ]
        })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "supabase_connected": supabase is not None,
        "timestamp": datetime.now().isoformat(),
        "pending_queue_size": len(pending_orders_queue),
        "memory_usage": gc.get_count()
    }), 200

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', '')
        
        if username == 'admin' and password == '1234321ali123':
            log_login_attempt(username, True, ip_address, user_agent)
            
            session_id = str(uuid.uuid4())
            session['user_id'] = username
            session['user_type'] = 'admin'
            session.permanent = True
            
            store_session_in_db(session_id, username, {'user_type': 'admin'})
            
            response = make_response(jsonify({
                "success": True,
                "user_type": "admin",
                "message": "تم تسجيل الدخول بنجاح"
            }))
            response.set_cookie('session_id', session_id, httponly=True, samesite='Lax', max_age=86400)
            return response
        
        if supabase:
            agent_result = supabase.table('agents').select('*').eq('agent_code', username).execute()
            if agent_result.data:
                agent = agent_result.data[0]
                if agent.get('agent_password') == password:
                    log_login_attempt(username, True, ip_address, user_agent)
                    
                    session_id = str(uuid.uuid4())
                    session['user_id'] = agent.get('agent_code')
                    session['user_type'] = 'agent'
                    session['agent_name'] = agent.get('agent_name')
                    session.permanent = True
                    
                    store_session_in_db(session_id, agent.get('agent_code'), {
                        'user_type': 'agent',
                        'agent_name': agent.get('agent_name')
                    })
                    
                    response = make_response(jsonify({
                        "success": True,
                        "user_type": "agent",
                        "agent_name": agent.get('agent_name'),
                        "message": "تم تسجيل الدخول بنجاح"
                    }))
                    response.set_cookie('session_id', session_id, httponly=True, samesite='Lax', max_age=86400)
                    return response
        
        log_login_attempt(username, False, ip_address, user_agent)
        return jsonify({"success": False, "error": "بيانات الدخول غير صحيحة"}), 401
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    try:
        session_id = request.cookies.get('session_id')
        
        if session_id and supabase:
            supabase.table('active_sessions').delete().eq('session_id', session_id).execute()
        
        session.clear()
        
        response = make_response(jsonify({"success": True, "message": "تم تسجيل الخروج"}))
        response.set_cookie('session_id', '', expires=0)
        return response
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============== إدارة المهام المجدولة ==============
_scheduler = None

def start_scheduler():
    global _scheduler
    
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("🔄 إيقاف المجدول القديم...")
    
    _scheduler = BackgroundScheduler()
    
    _scheduler.add_job(
        func=sync_deleted_shipments, 
        trigger=IntervalTrigger(hours=1),
        id='sync_deleted',
        replace_existing=True
    )
    
    _scheduler.add_job(
        func=sync_active_orders_from_jenni,
        trigger=IntervalTrigger(minutes=30),
        id='polling_active_orders',
        replace_existing=True
    )
    
    _scheduler.add_job(
        func=process_pending_queue,
        trigger=IntervalTrigger(minutes=5),
        id='process_queue',
        replace_existing=True
    )
    
    _scheduler.add_job(
        func=cleanup_expired_sessions,
        trigger=IntervalTrigger(hours=6),
        id='cleanup_sessions',
        replace_existing=True
    )
    
    _scheduler.add_job(
        func=lambda: gc.collect(),
        trigger=IntervalTrigger(hours=1),
        id='gc_collect',
        replace_existing=True
    )
    
    _scheduler.start()
    print("✅ تم تشغيل المجدول مع جميع المهام")

def shutdown_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        print("🛑 تم إيقاف المجدول")

atexit.register(shutdown_scheduler)

def signal_handler(signum, frame):
    print(f"\n🛑 استلام إشارة {signum}, جاري الإيقاف...")
    shutdown_scheduler()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 تشغيل نظام الثقة - النسخة المحسنة")
    print(f"🌐 المنفذ: {port}")
    print("=" * 50)
    
    jenni_login()
    start_scheduler()
    
    app.run(debug=False, host='0.0.0.0', port=port)