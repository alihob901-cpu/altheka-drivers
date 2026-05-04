# app.py
from flask import Flask, render_template, request, jsonify, session, make_response
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
from dotenv import load_dotenv
import json
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import time
import uuid
from functools import wraps

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

# تخزين الجلسات النشطة
active_sessions = {}

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

# ============== دوال الأمان والجلسات ==============

def invalidate_all_sessions():
    global active_sessions
    active_sessions.clear()
    print("✅ تم إبطال جميع الجلسات النشطة")

def session_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = request.cookies.get('session_id')
        user_id = session.get('user_id')
        
        if not session_id or not user_id:
            return jsonify({"error": "غير مصرح به", "code": "UNAUTHORIZED"}), 401
        
        if user_id not in active_sessions or session_id not in active_sessions.get(user_id, []):
            return jsonify({"error": "تم تسجيل الخروج من جميع الأجهزة", "code": "SESSION_INVALIDATED"}), 401
        
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
        add_notification_to_db('🔐 أمان النظام', f'تم تسجيل الخروج من جميع الأجهزة', 'security')
        return jsonify({"success": True, "message": "تم تسجيل الخروج من جميع الأجهزة"}), 200
    except Exception as e:
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
            supabase.table('agents').update({"agent_password": new_password}).eq('agent_code', 'admin').execute()
            supabase.table('agents').update({"agent_password": new_password}).eq('agent_name', 'المدير العام').execute()
        
        invalidate_all_sessions()
        add_notification_to_db('🔐 تغيير كلمة المرور', 'تم تغيير كلمة مرور الأدمن بنجاح', 'security')
        return jsonify({"success": True, "message": "تم تغيير كلمة المرور وتسجيل الخروج من جميع الأجهزة"}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/active-sessions', methods=['GET'])
def get_active_sessions():
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header:
            return jsonify({"error": "غير مصرح به"}), 401
        
        session_count = sum(len(sessions) for sessions in active_sessions.values())
        return jsonify({"success": True, "active_sessions_count": session_count, "users": list(active_sessions.keys())}), 200
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
    print("🔑 محاولة تسجيل الدخول إلى نظام الزعيم...")
    try:
        response = requests.post(f"{JENNI_API_URL}/v2/auth/login", json={"username": JENNI_USERNAME, "password": JENNI_PASSWORD}, headers={"Content-Type": "application/json"}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            jenni_jwt_token = data.get("token") or data.get("access_token") or data.get("jwt")
            expires_in = data.get("expires_in", 86400)
            jenni_token_expiry = time.time() + expires_in
            print("✅ تم تسجيل الدخول إلى نظام الزعيم بنجاح")
            return True
        return False
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False

def jenni_get_token():
    global jenni_jwt_token, jenni_token_expiry
    if jenni_jwt_token and jenni_token_expiry and time.time() < jenni_token_expiry - 60:
        return jenni_jwt_token
    print("⚠️ التوكن منتهي، إعادة تسجيل الدخول...")
    return jenni_jwt_token if jenni_login() else None

def create_shipment_in_jenni(order_data):
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة", "skip": True}
    
    governorate_code = get_governorate_code(order_data.get("governorate", "بغداد"))
    phone = order_data.get("customer_phone", "")
    original_phone = phone
    phone = ''.join(filter(str.isdigit, phone))
    if not phone.startswith('07') or len(phone) not in [10, 11]:
        phone = original_phone
    
    quantity = int(order_data.get("quantity", 1))
    product_info = order_data.get("product_info", "") or order_data.get("product", "")
    if quantity > 1 and not order_data.get("product_info"):
        product_info = f"{order_data.get('product', '')} ×{quantity}"
    
    payload = {
        "system_code": JENNI_SYSTEM_CODE,
        "shipments": [{
            "shipment_number": str(order_data.get("__backendId", "")),
            "external_shipment_id": str(order_data.get("__backendId", "")),
            "receiver_name": order_data.get("customer_name", "زبون")[:50],
            "receiver_phone_1": phone,
            "governorate_code": governorate_code,
            "city": order_data.get("governorate", "بغداد"),
            "address": order_data.get("customer_address", "عنوان غير محدد")[:100],
            "landmark": order_data.get("landmark", "")[:100],
            "amount_iqd": float(order_data.get("total", 0)),
            "quantity": quantity,
            "product_info": product_info[:200],
            "note": order_data.get("admin_notes", "")[:200]
        }]
    }
    
    auth_headers = [{"Authorization": f"Bearer {token}"}, {"Authorization": token}, {"x-access-token": token}]
    for auth_header in auth_headers:
        try:
            response = requests.post(f"{JENNI_API_URL}/v2/shipments/create", json=payload, headers={"Content-Type": "application/json", **auth_header}, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("accepted_shipments"):
                    shipment = result["accepted_shipments"][0]
                    return {"success": True, "shipment_id": shipment.get("shipment_id")}
        except Exception:
            continue
    return {"success": False, "error": "فشل الإرسال", "skip": True}

def cancel_shipment_in_jenni(shipment_number, reason="تم إلغاء الطلب"):
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة"}
    
    payload = {"system_code": JENNI_SYSTEM_CODE, "updates": [{"shipment_number": str(shipment_number), "action_code": "RETURN_TO_STORE", "note": reason}]}
    auth_headers = [{"Authorization": f"Bearer {token}"}, {"Authorization": token}]
    for auth_header in auth_headers:
        try:
            response = requests.post(f"{JENNI_API_URL}/v2/push/update-status", json=payload, headers={"Content-Type": "application/json", **auth_header}, timeout=30)
            if response.status_code == 200:
                return {"success": True, "action": "cancelled", "message": "تم إلغاء الطلب"}
        except Exception:
            continue
    return {"success": False, "error": "فشل الإلغاء"}

def delete_shipment_by_id(shipment_id):
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة"}
    
    for auth_header in [{"Authorization": f"Bearer {token}"}, {"Authorization": token}]:
        try:
            response = requests.delete(f"{JENNI_API_URL}/v2/orders/{shipment_id}", headers={"Content-Type": "application/json", **auth_header}, timeout=30)
            if response.status_code == 200:
                return {"success": True, "action": "deleted"}
            elif response.status_code == 404:
                return {"success": True, "action": "not_found"}
        except Exception:
            continue
    return {"success": False, "error": "فشل الحذف"}

def delete_shipment_by_number(shipment_number):
    if not supabase:
        return {"success": False}
    try:
        order_result = supabase.table('orders').select('jenni_shipment_id').eq('__backendId', shipment_number).execute()
        if order_result.data and order_result.data[0].get('jenni_shipment_id'):
            return delete_shipment_by_id(order_result.data[0]['jenni_shipment_id'])
        else:
            return cancel_shipment_in_jenni(shipment_number)
    except Exception:
        return cancel_shipment_in_jenni(shipment_number)

def delete_or_cancel_shipment_in_jenni(shipment_number):
    result = delete_shipment_by_number(shipment_number)
    if result.get("success"):
        return result
    return {"success": False, "error": "فشل"}

@app.route('/api/cancel-in-jenni/<shipment_number>', methods=['POST'])
def api_cancel_in_jenni(shipment_number):
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'تم إلغاء الطلب')
        result = cancel_shipment_in_jenni(shipment_number, reason)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============== ✅ دوال تسديد أرباح المندوب (مع دعم البحث بالاسم والكود) ==============

def find_agent(agent_identifier):
    """البحث عن المندوب باستخدام __backendId أو agent_name أو agent_code"""
    if not supabase:
        return None
    
    # 1. البحث باستخدام __backendId (رقم)
    result = supabase.table('agents').select('*').eq('__backendId', agent_identifier).execute()
    if result.data:
        return result.data[0]
    
    # 2. البحث باستخدام agent_name (اسم)
    result = supabase.table('agents').select('*').eq('agent_name', agent_identifier).execute()
    if result.data:
        return result.data[0]
    
    # 3. البحث باستخدام agent_code (كود)
    result = supabase.table('agents').select('*').eq('agent_code', agent_identifier).execute()
    if result.data:
        return result.data[0]
    
    return None

def get_agent_total_profit(agent_name):
    """حساب إجمالي أرباح المندوب من الطلبات الواصلة"""
    if not supabase:
        return 0.0
    try:
        result = supabase.table('orders').select('profit').eq('agent_name', agent_name).eq('status', 'واصل').execute()
        total = sum(order.get('profit', 0) or 0 for order in (result.data or []))
        return float(total)
    except Exception as e:
        print(f"❌ خطأ في حساب أرباح المندوب: {e}")
        return 0.0

def get_agent_settlement(agent_id):
    """جلب بيانات التسديد للمندوب"""
    if not supabase:
        return {"total_paid": 0.0, "remaining_profit": 0.0}
    try:
        result = supabase.table('agent_settlements').select('*').eq('agent_id', agent_id).execute()
        if result.data:
            return result.data[0]
        else:
            return {"total_paid": 0.0, "remaining_profit": 0.0}
    except Exception as e:
        print(f"❌ خطأ في جلب بيانات التسديد: {e}")
        return {"total_paid": 0.0, "remaining_profit": 0.0}

def update_agent_settlement(agent_id, paid_amount):
    """تحديث تسديد أرباح المندوب (بدون حذف الطلبات)"""
    if not supabase:
        return False
    try:
        agent = find_agent(agent_id)
        if not agent:
            return False
        
        agent_name = agent.get('agent_name')
        real_agent_id = agent.get('__backendId')
        total_profit = get_agent_total_profit(agent_name)
        
        settlement = get_agent_settlement(real_agent_id)
        current_paid = float(settlement.get('total_paid', 0))
        new_total_paid = current_paid + paid_amount
        remaining_profit = total_profit - new_total_paid
        
        existing = supabase.table('agent_settlements').select('*').eq('agent_id', real_agent_id).execute()
        if existing.data:
            supabase.table('agent_settlements').update({
                'total_paid': new_total_paid,
                'remaining_profit': remaining_profit if remaining_profit > 0 else 0,
                'last_payment_date': datetime.now().isoformat(),
                'last_payment_amount': paid_amount,
                'updated_at': datetime.now().isoformat()
            }).eq('agent_id', real_agent_id).execute()
        else:
            supabase.table('agent_settlements').insert({
                'agent_id': real_agent_id,
                'total_paid': paid_amount,
                'remaining_profit': remaining_profit if remaining_profit > 0 else 0,
                'last_payment_date': datetime.now().isoformat(),
                'last_payment_amount': paid_amount,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }).execute()
        
        print(f"💰 سداد أرباح للمندوب {agent_name}: إجمالي={total_profit}, سبق دفعه={current_paid}, دفع الآن={paid_amount}, المتبقي={remaining_profit}")
        add_notification_to_db('💰 سداد أرباح جزئي', f'تم تسديد {paid_amount:,.0f} د.ع للمندوب {agent_name} - المتبقي: {remaining_profit:,.0f} د.ع', 'settlement')
        return True
    except Exception as e:
        print(f"❌ خطأ في تحديث التسديد: {e}")
        return False

@app.route('/api/settle-agent/<agent_identifier>', methods=['POST'])
def settle_agent(agent_identifier):
    """تسديد أرباح المندوب (يدعم __backendId, agent_name, agent_code)"""
    try:
        data = request.json
        paid_amount = float(data.get('paid_amount', 0))
        
        if paid_amount <= 0:
            return jsonify({"success": False, "error": "المبلغ غير صالح"}), 400
        
        if not supabase:
            return jsonify({"success": False, "error": "Supabase not connected"}), 500
        
        # البحث عن المندوب باستخدام أي معرف
        agent = find_agent(agent_identifier)
        if not agent:
            return jsonify({"success": False, "error": "المندوب غير موجود"}), 404
        
        agent_name = agent.get('agent_name')
        real_agent_id = agent.get('__backendId')
        
        total_profit = get_agent_total_profit(agent_name)
        settlement = get_agent_settlement(real_agent_id)
        current_paid = settlement.get('total_paid', 0)
        remaining_profit = total_profit - current_paid
        
        print(f"💰 محاولة تسديد للمندوب {agent_name}: إجمالي={total_profit}, سبق دفعه={current_paid}, المتبقي={remaining_profit}, المطلوب={paid_amount}")
        
        if total_profit <= 0:
            return jsonify({"success": False, "error": "لا توجد أرباح مستحقة لهذا المندوب"}), 400
        
        if paid_amount > remaining_profit:
            return jsonify({"success": False, "error": f"المبلغ المدخل ({paid_amount:,.0f}) أكبر من الربح المتبقي ({remaining_profit:,.0f})"}), 400
        
        success = update_agent_settlement(real_agent_id, paid_amount)
        
        if success:
            new_settlement = get_agent_settlement(real_agent_id)
            return jsonify({
                "success": True,
                "message": f"تم تسديد {paid_amount:,.0f} د.ع للمندوب {agent_name}",
                "total_profit": total_profit,
                "total_paid": new_settlement.get('total_paid', current_paid + paid_amount),
                "remaining_profit": new_settlement.get('remaining_profit', remaining_profit - paid_amount),
                "deleted_orders": 0
            })
        else:
            return jsonify({"success": False, "error": "حدث خطأ أثناء التسديد"}), 500
        
    except Exception as e:
        print(f"❌ خطأ في تسديد أرباح المندوب: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/agent-settlement/<agent_identifier>', methods=['GET'])
def get_agent_settlement_api(agent_identifier):
    """جلب بيانات تسديد المندوب (يدعم __backendId, agent_name, agent_code)"""
    try:
        if not supabase:
            return jsonify({"success": False, "error": "Supabase not connected"}), 500
        
        agent = find_agent(agent_identifier)
        if not agent:
            return jsonify({"success": False, "error": "المندوب غير موجود"}), 404
        
        agent_name = agent.get('agent_name')
        real_agent_id = agent.get('__backendId')
        
        settlement = get_agent_settlement(real_agent_id)
        total_profit = get_agent_total_profit(agent_name)
        total_paid = settlement.get('total_paid', 0)
        remaining = total_profit - total_paid
        
        return jsonify({
            "success": True,
            "agent_name": agent_name,
            "agent_id": real_agent_id,
            "total_profit": total_profit,
            "total_paid": total_paid,
            "remaining_profit": remaining if remaining > 0 else 0,
            "last_payment_date": settlement.get('last_payment_date'),
            "last_payment_amount": settlement.get('last_payment_amount', 0)
        })
    except Exception as e:
        print(f"❌ خطأ في جلب بيانات التسديد: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def delete_shipment_from_jenni(shipment_number):
    return delete_or_cancel_shipment_in_jenni(shipment_number)

def sync_deleted_shipments():
    print("🔄 بدء مزامنة الحذف...")
    if not supabase:
        return
    try:
        token = jenni_get_token()
        if not token:
            return
        deleted_count = 0
        local_orders = supabase.table('orders').select('__backendId, jenni_shipment_id').execute()
        for order in local_orders.data:
            if not order.get('jenni_shipment_id'):
                continue
            try:
                response = requests.post(f"{JENNI_API_URL}/v2/shipments/query", json={"shipment_ids": [int(order['jenni_shipment_id'])]}, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
                if response.status_code == 200 and not response.json().get('shipments'):
                    supabase.table('orders').delete().eq('__backendId', order['__backendId']).execute()
                    deleted_count += 1
            except Exception:
                pass
        if deleted_count > 0:
            add_notification_to_db('مزامنة مع الزعيم', f'تم حذف {deleted_count} طلب', 'status')
    except Exception as e:
        print(f"❌ خطأ: {e}")

def sync_cancelled_from_jenni():
    print("⚠️ ميزة مزامنة الطلبات الملغية معطلة مؤقتاً")
    return

@app.route('/api/sync-with-jenni', methods=['POST'])
def sync_with_jenni():
    try:
        sync_deleted_shipments()
        return jsonify({"success": True, "message": "تمت المزامنة بنجاح"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/sync-cancelled-from-jenni', methods=['POST'])
def api_sync_cancelled_from_jenni():
    return jsonify({"success": True, "message": "الميزة معطلة مؤقتاً", "updated_count": 0}), 200

# ============== دوال الإشعارات ==============
def send_fcm_notification_via_admin(fcm_token, title, body, data=None):
    if not firebase_initialized:
        return send_fcm_notification_via_legacy(fcm_token, title, body, data)
    try:
        from firebase_admin import messaging
        message = messaging.Message(notification=messaging.Notification(title=title, body=body), data=data or {}, token=fcm_token)
        messaging.send(message)
        return True
    except Exception as e:
        print(f"❌ خطأ في الإشعار: {e}")
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
    except Exception:
        return False

def send_notification_to_user(user_id, title, body, order_id=None):
    try:
        if not supabase:
            return False
        result = supabase.table('fcm_tokens').select('fcm_token').eq('user_id', user_id).execute()
        if not result.data:
            return False
        data = {'order_id': str(order_id)} if order_id else {}
        return send_fcm_notification_via_admin(result.data[0]['fcm_token'], title, body, data)
    except Exception:
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
    except Exception:
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
                jenni_result = create_shipment_in_jenni(new_item)
                if jenni_result.get("success") and jenni_result.get("shipment_id"):
                    supabase.table('orders').update({"jenni_shipment_id": str(jenni_result["shipment_id"])}).eq('__backendId', new_item['__backendId']).execute()
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        return jsonify({'isOk': False, 'error': 'Failed to save'}), 500
    except Exception as e:
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
                titles = {'واصل': '✅ طلب واصل', 'راجع': '↩️ طلب مرتجع', 'قيد التوصيل': '🚚 طلب قيد التوصيل', 'ملغي': '❌ طلب ملغي'}
                send_notification_to_user(agent_name, titles.get(new_status, '📋 تحديث حالة الطلب'), f"تم تغيير حالة طلب {customer_name} إلى {new_status}", item_id)
        
        return jsonify({'isOk': True, 'data': result.data[0]}) if result.data else jsonify({'isOk': False, 'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/data/<item_id>', methods=['DELETE'])
def delete_data(item_id):
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        order_result = supabase.table('orders').select('*').eq('__backendId', item_id).execute()
        if order_result.data:
            delete_or_cancel_shipment_in_jenni(item_id)
        
        result = supabase.table('orders').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        result = supabase.table('agents').delete().eq('__backendId', item_id).execute()
        if result.data:
            return jsonify({'isOk': True})
        
        return jsonify({'isOk': False, 'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({"isOk": False, "error": str(e)}), 500

def add_notification_to_db(title, message, type):
    try:
        if supabase:
            supabase.table('notifications').insert({'_id': str(int(datetime.now().timestamp() * 1000)), 'title': title, 'message': message, 'type': type, 'read': False, 'created_at': datetime.now().isoformat()}).execute()
    except Exception:
        pass

@app.route('/api/delete-from-jenni/<shipment_number>', methods=['DELETE'])
def api_delete_from_jenni(shipment_number):
    return jsonify(delete_or_cancel_shipment_in_jenni(shipment_number))

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
        
        status_map = {'DELIVERED': 'واصل', 'DELIVERED_PRICE_CHANGED': 'واصل', 'PARTIALLY_DELIVERED': 'واصل', 'OFD': 'قيد التوصيل', 'POSTPONED': 'قيد التوصيل', 'RTO_WH': 'راجع', 'RTO_WITH_DA': 'راجع', 'RTO_CONFIRMED': 'راجع', 'CANCELLED': 'ملغي'}
        updated_count = 0
        
        for update in data.get('updates', []):
            shipment_number = update.get('shipment_number')
            current_step = update.get('current_step')
            new_status = status_map.get(current_step)
            
            if new_status and supabase and shipment_number:
                result = supabase.table('orders').update({"status": new_status, "updated_at": datetime.now().isoformat()}).eq('__backendId', shipment_number).execute()
                if result.data:
                    updated_count += 1
                    print(f"✅ تم تحديث حالة الطلب {shipment_number} إلى {new_status}")
        
        return jsonify({"success": True, "message": f"Processed {updated_count} updates"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

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
            return jsonify({"isOk": False}), 400
        existing = supabase.table('fcm_tokens').select('*').eq('user_id', user_id).execute()
        if existing.data:
            supabase.table('fcm_tokens').update({'fcm_token': fcm_token, 'updated_at': datetime.now().isoformat()}).eq('user_id', user_id).execute()
        else:
            supabase.table('fcm_tokens').insert({'user_id': user_id, 'fcm_token': fcm_token, 'created_at': datetime.now().isoformat()}).execute()
        return jsonify({'isOk': True})
    except Exception:
        return jsonify({"isOk": False}), 500

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

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "supabase_connected": supabase is not None, "active_sessions": sum(len(s) for s in active_sessions.values()), "timestamp": datetime.now().isoformat()}), 200

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if username == 'admin' and password == '1234321ali123':
            session_id = str(uuid.uuid4())
            session['user_id'] = username
            session.permanent = True
            if username not in active_sessions:
                active_sessions[username] = []
            active_sessions[username].append(session_id)
            response = make_response(jsonify({"success": True, "user_type": "admin", "message": "تم تسجيل الدخول بنجاح"}))
            response.set_cookie('session_id', session_id, httponly=True, samesite='Lax', max_age=86400)
            return response
        
        if supabase:
            agent_result = supabase.table('agents').select('*').eq('agent_code', username).execute()
            if agent_result.data and agent_result.data[0].get('agent_password') == password:
                agent = agent_result.data[0]
                session_id = str(uuid.uuid4())
                session['user_id'] = agent.get('agent_code')
                session['agent_name'] = agent.get('agent_name')
                session.permanent = True
                if agent.get('agent_code') not in active_sessions:
                    active_sessions[agent.get('agent_code')] = []
                active_sessions[agent.get('agent_code')].append(session_id)
                response = make_response(jsonify({"success": True, "user_type": "agent", "agent_name": agent.get('agent_name'), "message": "تم تسجيل الدخول بنجاح"}))
                response.set_cookie('session_id', session_id, httponly=True, samesite='Lax', max_age=86400)
                return response
        
        return jsonify({"success": False, "error": "بيانات الدخول غير صحيحة"}), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    try:
        session_id = request.cookies.get('session_id')
        user_id = session.get('user_id')
        if user_id and session_id and user_id in active_sessions and session_id in active_sessions[user_id]:
            active_sessions[user_id].remove(session_id)
            if not active_sessions[user_id]:
                del active_sessions[user_id]
        session.clear()
        response = make_response(jsonify({"success": True, "message": "تم تسجيل الخروج"}))
        response.set_cookie('session_id', '', expires=0)
        return response
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============== تشغيل المهام المجدولة ==============
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=sync_deleted_shipments, trigger="interval", hours=1, id='sync_deleted')
    scheduler.start()
    print("✅ تم تشغيل المجدول")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 تشغيل نظام الثقة")
    print(f"🌐 المنفذ: {port}")
    print("=" * 50)
    jenni_login()
    start_scheduler()
    app.run(debug=False, host='0.0.0.0', port=port)