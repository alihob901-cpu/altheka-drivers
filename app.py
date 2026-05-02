from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import os
from datetime import datetime
from dotenv import load_dotenv
import json
import requests
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
GOVERNORATES_LIST = [
    'بغداد', 'البصرة', 'نينوى', 'أربيل', 'النجف', 'كركوك', 'الأنبار', 'كربلاء',
    'ذي قار', 'ميسان', 'بابل', 'واسط', 'صلاح الدين', 'ديالى', 'المثنى', 'القادسية',
    'السليمانية', 'دهوك'
]

# ============== دالة تحويل المحافظات ==============
def get_governorate_code(governorate_name):
    governorate_map = {
        'بغداد': 'BGD', 'البصرة': 'BAS', 'نينوى': 'NIN', 'أربيل': 'ARB',
        'النجف': 'NJF', 'كركوك': 'KRK', 'الأنبار': 'ANB', 'كربلاء': 'KRB',
        'ذي قار': 'DHI', 'ميسان': 'MYS', 'بابل': 'BBL', 'واسط': 'WST',
        'صلاح الدين': 'SAH', 'ديالى': 'DYL', 'المثنى': 'MTH', 'القادسية': 'QAD',
        'السليمانية': 'SMH', 'دهوك': 'DOH'
    }
    return governorate_map.get(governorate_name, 'BGD')

# ============== API لجلب قائمة المحافظات ==============
@app.route('/api/governorates', methods=['GET'])
def get_governorates():
    return jsonify(GOVERNORATES_LIST)

# ============== دوال نظام الزعيم ==============
def jenni_login():
    global jenni_jwt_token, jenni_token_expiry
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
            jenni_token_expiry = time.time() + data.get("expires_in", 86400)
            print("✅ تم تسجيل الدخول إلى نظام الزعيم")
            return True
        return False
    except Exception as e:
        print(f"❌ خطأ في تسجيل الدخول: {e}")
        return False

def jenni_get_token():
    global jenni_jwt_token, jenni_token_expiry
    if jenni_jwt_token and jenni_token_expiry and time.time() < jenni_token_expiry - 60:
        return jenni_jwt_token
    if jenni_login():
        return jenni_jwt_token
    return None

def create_shipment_in_jenni(order_data):
    print(f"📤 بدء إرسال الطلب {order_data.get('__backendId')} إلى نظام الزعيم...")
    
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة مع نظام الزعيم", "skip": True}
    
    governorate_name = order_data.get("governorate", "بغداد")
    governorate_code = get_governorate_code(governorate_name)
    
    # معالجة رقم الهاتف
    phone = order_data.get("customer_phone", "")
    original_phone = phone
    phone = ''.join(filter(str.isdigit, phone))
    if not phone.startswith('07') or len(phone) not in [10, 11]:
        phone = original_phone
        print(f"⚠️ تحذير: رقم الهاتف غير قياسي ({original_phone})، سيتم إرساله كما هو")
    
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
        {"x-access-token": token}
    ]
    
    for auth_header in auth_headers:
        try:
            response = requests.post(
                f"{JENNI_API_URL}/v2/shipments/create",
                json=shipment_payload,
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            if response.status_code in [200, 201]:
                result = response.json()
                if result.get("accepted_shipments"):
                    shipment = result["accepted_shipments"][0]
                    return {"success": True, "shipment_id": shipment.get("shipment_id")}
            elif response.status_code == 401:
                continue
            else:
                return {"success": False, "error": f"فشل الإرسال: {response.status_code}", "skip": True}
        except Exception as e:
            continue
    return {"success": False, "error": "فشل جميع محاولات المصادقة", "skip": True}

# ============== ✅ دالة تعديل الطلب في نظام الزعيم (شاملة جميع الحقول) ==============
def edit_shipment_in_jenni(shipment_number, updated_data):
    """تعديل شحنة في نظام الزعيم - شامل جميع الحقول"""
    print(f"✏️ محاولة تعديل الطلب {shipment_number} في نظام الزعيم...")
    
    # البحث عن shipment_id من قاعدة البيانات
    if not supabase:
        return {"success": False, "error": "Supabase not connected"}
    
    try:
        order_result = supabase.table('orders').select('jenni_shipment_id').eq('__backendId', shipment_number).execute()
        if not order_result.data or not order_result.data[0].get('jenni_shipment_id'):
            print(f"⚠️ لم يتم العثور على shipment_id للطلب {shipment_number}")
            return {"success": False, "error": "Shipment ID not found"}
        
        shipment_id = order_result.data[0]['jenni_shipment_id']
        print(f"✅ تم العثور على shipment_id: {shipment_id}")
    except Exception as e:
        return {"success": False, "error": str(e)}
    
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة مع نظام الزعيم"}
    
    # معالجة البيانات
    customer_name = updated_data.get("customer_name", "")
    customer_phone = updated_data.get("customer_phone", "")
    governorate_name = updated_data.get("governorate", "بغداد")
    governorate_code = get_governorate_code(governorate_name)
    district = updated_data.get("district", "")
    landmark = updated_data.get("landmark", "")
    address = updated_data.get("customer_address", "")
    
    # بناء العنوان الكامل إذا لم يكن موجوداً
    if not address and (governorate_name or district or landmark):
        address_parts = []
        if governorate_name: address_parts.append(governorate_name)
        if district: address_parts.append(district)
        if landmark: address_parts.append(f"(قرب: {landmark})")
        address = " - ".join(address_parts)
    
    # معالجة المنتج والكمية
    product = updated_data.get("product", "")
    quantity = int(updated_data.get("quantity", 1))
    product_info = updated_data.get("product_info", "")
    if not product_info:
        product_info = f"{product} ×{quantity}" if quantity > 1 else product
    
    # معالجة الأسعار
    price = float(updated_data.get("price", 0))
    total = float(updated_data.get("total", price * quantity))
    profit = float(updated_data.get("profit", 0))
    admin_notes = updated_data.get("admin_notes", "")
    
    # معالجة رقم الهاتف
    phone = ''.join(filter(str.isdigit, customer_phone))
    if not phone.startswith('07') or len(phone) not in [10, 11]:
        phone = customer_phone
    
    # بناء payload التعديل (جميع الحقول)
    edit_payload = {
        "shipment_id": shipment_id,
        "receiver_name": customer_name[:50],
        "receiver_phone_1": phone,
        "governorate_code": governorate_code,
        "city": governorate_name,
        "address": address[:100],
        "landmark": landmark[:100],
        "amount_iqd": total,
        "quantity": quantity,
        "product_info": product_info[:200],
        "note": admin_notes[:200]
    }
    
    # إزالة الحقول الفارغة
    edit_payload = {k: v for k, v in edit_payload.items() if v}
    
    print(f"📦 Payload التعديل: {edit_payload}")
    
    auth_headers = [
        {"Authorization": f"Bearer {token}"},
        {"Authorization": token}
    ]
    
    for auth_header in auth_headers:
        try:
            response = requests.put(
                f"{JENNI_API_URL}/v2/shipments/edit",
                json=edit_payload,
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            
            print(f"📡 رد التعديل: {response.status_code}")
            if response.text:
                print(f"📄 رد: {response.text[:500]}")
            
            if response.status_code == 200:
                print(f"✅ تم تعديل الطلب {shipment_number} في نظام الزعيم بنجاح")
                return {"success": True, "message": "تم تعديل الطلب"}
            elif response.status_code == 401:
                print("⚠️ انتهت صلاحية التوكن، محاولة تجديد...")
                continue
            else:
                print(f"⚠️ فشل التعديل: {response.status_code}")
                return {"success": False, "error": f"فشل التعديل: {response.status_code}"}
        except Exception as e:
            print(f"❌ خطأ: {e}")
            continue
    
    return {"success": False, "error": "فشل تعديل الطلب بعد جميع المحاولات"}

# ============== دوال الحذف والإلغاء ==============
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
    
    for auth_header in auth_headers:
        try:
            response = requests.post(
                f"{JENNI_API_URL}/v2/push/update-status",
                json=update_payload,
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            if response.status_code == 200:
                return {"success": True, "action": "cancelled"}
            elif response.status_code == 401:
                continue
        except Exception:
            continue
    return {"success": False, "error": "فشل الإلغاء"}

def delete_shipment_by_id(shipment_id):
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة"}
    
    auth_headers = [
        {"Authorization": f"Bearer {token}"},
        {"Authorization": token}
    ]
    
    for auth_header in auth_headers:
        try:
            response = requests.delete(
                f"{JENNI_API_URL}/v2/orders/{shipment_id}",
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            if response.status_code == 200:
                return {"success": True, "action": "deleted"}
            elif response.status_code == 404:
                return {"success": True, "action": "not_found"}
            elif response.status_code == 401:
                continue
        except Exception:
            continue
    return {"success": False, "error": "فشل الحذف"}

def delete_shipment_by_number(shipment_number):
    if not supabase:
        return {"success": False, "error": "Supabase not connected"}
    
    try:
        order_result = supabase.table('orders').select('jenni_shipment_id').eq('__backendId', shipment_number).execute()
        if order_result.data and order_result.data[0].get('jenni_shipment_id'):
            return delete_shipment_by_id(order_result.data[0]['jenni_shipment_id'])
        else:
            return cancel_shipment_in_jenni(shipment_number, "تم حذف/إلغاء الطلب")
    except Exception as e:
        return {"success": False, "error": str(e)}

def delete_or_cancel_shipment_in_jenni(shipment_number, order_data=None):
    result = delete_shipment_by_number(shipment_number)
    if result.get("success"):
        return result
    
    token = jenni_get_token()
    if not token:
        return {"success": False, "error": "فشل المصادقة"}
    
    auth_headers = [
        {"Authorization": f"Bearer {token}"},
        {"Authorization": token}
    ]
    
    for auth_header in auth_headers:
        try:
            response = requests.delete(
                f"{JENNI_API_URL}/v2/orders/{shipment_number}",
                headers={"Content-Type": "application/json", **auth_header},
                timeout=30
            )
            if response.status_code == 200:
                return {"success": True, "action": "deleted"}
            elif response.status_code == 404:
                return {"success": True, "action": "not_found"}
            elif response.status_code == 401:
                continue
        except Exception:
            continue
    return {"success": False, "error": "فشل حذف الطلب"}

# ============== API Routes ==============

@app.route('/api/data', methods=['GET'])
def get_data():
    try:
        orders = supabase.table('orders').select('*').execute() if supabase else []
        agents = supabase.table('agents').select('*').execute() if supabase else []
        result = []
        for o in (orders.data or []):
            o['type'] = 'order'
            result.append(o)
        for a in (agents.data or []):
            a['type'] = 'agent'
            result.append(a)
        return jsonify(result)
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
                jenni_result = create_shipment_in_jenni(new_item)
                if jenni_result.get("success") and jenni_result.get("shipment_id"):
                    supabase.table('orders').update({
                        "jenni_shipment_id": str(jenni_result["shipment_id"])
                    }).eq('__backendId', new_item['__backendId']).execute()
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
        
        if result.data:
            # ✅ تعديل الطلب في نظام الزعيم إذا كان جدول orders
            if table_name == 'orders':
                print(f"✏️ محاولة تعديل الطلب {item_id} في نظام الزعيم...")
                edit_result = edit_shipment_in_jenni(item_id, updated_item)
                if edit_result.get("success"):
                    print(f"✅ تم تعديل الطلب في نظام الزعيم بنجاح")
                else:
                    print(f"⚠️ فشل تعديل الطلب في الزعيم: {edit_result.get('error')}")
            
            if old_item and old_item.get('status') != updated_item.get('status'):
                agent_name = old_item.get('agent_name')
                if agent_name and agent_name not in ['admin', 'المدير العام']:
                    customer_name = old_item.get('customer_name', 'زبون')
                    new_status = updated_item.get('status')
                    titles = {'واصل': '✅ طلب واصل', 'راجع': '↩️ طلب مرتجع', 
                              'قيد التوصيل': '🚚 طلب قيد التوصيل', 'ملغي': '❌ طلب ملغي'}
                    title = titles.get(new_status, '📋 تحديث حالة الطلب')
                    send_notification_to_user(agent_name, title, f"تم تغيير حالة طلب {customer_name} إلى {new_status}", item_id)
            
            return jsonify({'isOk': True, 'data': result.data[0]})
        return jsonify({'isOk': False, 'error': 'Not found'}), 404
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
        
        for order in orders:
            if order.get('__backendId'):
                delete_or_cancel_shipment_in_jenni(order.get('__backendId'))
            supabase.table('orders').delete().eq('__backendId', order.get('__backendId')).execute()
        
        add_notification_to_db('سداد أرباح', f'تم تسديد {paid_amount:,.0f} د.ع للمندوب {agent_name}', 'settlement')
        return jsonify({"success": True, "message": f"تم تسديد {paid_amount:,.0f} د.ع", "deleted_orders": len(orders)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def delete_shipment_from_jenni(shipment_number):
    return delete_or_cancel_shipment_in_jenni(shipment_number)

def sync_deleted_shipments():
    if not supabase:
        return
    try:
        token = jenni_get_token()
        if not token:
            return
        local_orders = supabase.table('orders').select('__backendId, jenni_shipment_id').execute()
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
            except Exception:
                continue
    except Exception as e:
        print(f"❌ خطأ في مزامنة الحذف: {e}")

@app.route('/api/sync-with-jenni', methods=['POST'])
def sync_with_jenni():
    try:
        sync_deleted_shipments()
        return jsonify({"success": True, "message": "تمت المزامنة بنجاح"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/cancel-in-jenni/<shipment_number>', methods=['POST'])
def api_cancel_in_jenni(shipment_number):
    try:
        data = request.get_json() or {}
        result = cancel_shipment_in_jenni(shipment_number, data.get('reason', 'تم إلغاء الطلب'))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/delete-from-jenni/<shipment_number>', methods=['DELETE'])
def api_delete_from_jenni(shipment_number):
    return jsonify(delete_or_cancel_shipment_in_jenni(shipment_number))

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
            apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound="default", badge=1)))
        )
        messaging.send(message)
        return True
    except Exception as e:
        return False

def send_fcm_notification_via_legacy(fcm_token, title, body, data=None):
    if not fcm_token or not FCM_SERVER_KEY:
        return False
    try:
        response = requests.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={"Authorization": f"key={FCM_SERVER_KEY}", "Content-Type": "application/json"},
            json={"to": fcm_token, "notification": {"title": title, "body": body}, "data": data or {}}
        )
        return response.status_code == 200
    except Exception:
        return False

def send_notification_to_user(user_id, title, body, order_id=None):
    if not supabase:
        return False
    try:
        result = supabase.table('fcm_tokens').select('fcm_token').eq('user_id', user_id).execute()
        if not result.data:
            return False
        data = {'order_id': str(order_id)} if order_id else {}
        return send_fcm_notification_via_admin(result.data[0]['fcm_token'], title, body, data)
    except Exception:
        return False

def add_notification_to_db(title, message, type):
    try:
        if supabase:
            supabase.table('notifications').insert({
                '_id': str(int(datetime.now().timestamp() * 1000)),
                'title': title, 'message': message, 'type': type,
                'read': False, 'created_at': datetime.now().isoformat()
            }).execute()
    except Exception as e:
        print(f"خطأ في إضافة الإشعار: {e}")

# ============== Webhook ==============
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
        
        if data.get('system_code') != JENNI_SYSTEM_CODE:
            return jsonify({"success": False, "message": "Invalid system code"}), 401
        
        status_map = {
            'DELIVERED': 'واصل', 'DELIVERED_PRICE_CHANGED': 'واصل', 'PARTIALLY_DELIVERED': 'واصل',
            'OFD': 'قيد التوصيل', 'POSTPONED': 'قيد التوصيل',
            'RTO_WH': 'راجع', 'RTO_WITH_DA': 'راجع', 'RTO_CONFIRMED': 'راجع',
            'CANCELLED': 'ملغي'
        }
        
        updated_count = 0
        for update in data.get('updates', []):
            shipment_number = update.get('shipment_number')
            current_step = update.get('current_step')
            new_status = status_map.get(current_step)
            
            if new_status and supabase and shipment_number:
                result = supabase.table('orders').update({
                    "status": new_status,
                    "admin_notes": update.get('note'),
                    "updated_at": datetime.now().isoformat(),
                    "jenni_last_update": datetime.now().isoformat()
                }).eq('__backendId', shipment_number).execute()
                
                if result.data:
                    updated_count += 1
                    order = result.data[0]
                    agent_name = order.get('agent_name')
                    if agent_name and agent_name not in ['admin', 'المدير العام']:
                        send_notification_to_user(agent_name, "تحديث حالة الطلب",
                            f"تم تغيير حالة طلب {order.get('customer_name', '')} إلى {new_status}", shipment_number)
        
        return jsonify({"success": True, "message": f"Processed {updated_count} updates"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ============== Routes ==============
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
        if supabase:
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
    return jsonify({
        "status": "healthy",
        "supabase_connected": supabase is not None,
        "timestamp": datetime.now().isoformat()
    }), 200

# ============== تشغيل المهام المجدولة ==============
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=sync_deleted_shipments, trigger="interval", hours=1, id='sync_deleted')
    scheduler.start()
    print("✅ تم تشغيل المجدول")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("🚀 تشغيل نظام الثقة")
    jenni_login()
    start_scheduler()
    app.run(debug=False, host='0.0.0.0', port=port)