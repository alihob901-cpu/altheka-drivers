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

# إعداد Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zmzotoutdeeizyfoikfw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_BqRz02wzKGRblUsM05DnOA_ovErV7U2")

# ============== إعداد Firebase Admin SDK ==============
firebase_initialized = False
try:
    # قراءة JSON من متغير البيئة
    firebase_cred_json = os.getenv("FIREBASE_ADMIN_CRED_JSON")
    if firebase_cred_json:
        cred_dict = json.loads(firebase_cred_json)
        import firebase_admin
        from firebase_admin import credentials, messaging
        
        # التحقق من عدم وجود تهيئة سابقة
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            firebase_initialized = True
            print("✅ Firebase Admin SDK initialized successfully!")
        else:
            firebase_initialized = True
            print("✅ Firebase Admin SDK already initialized")
    else:
        print("⚠️ FIREBASE_ADMIN_CRED_JSON not found in environment variables")
        print("📝 الإشعارات لن تعمل حتى يتم إضافة المفتاح")
except Exception as e:
    print(f"❌ خطأ في تهيئة Firebase Admin SDK: {e}")
    print("📝 الإشعارات لن تعمل حتى يتم إصلاح المشكلة")

# إعداد FCM Server Key (الطريقة البديلة)
FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")
FCM_SENDER_ID = os.getenv("FCM_SENDER_ID", "150648020047")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ تم الاتصال بـ Supabase بنجاح!")
    print(f"📡 Supabase URL: {SUPABASE_URL}")
    
    # التحقق من وجود جدول fcm_tokens وإنشاؤه إذا لم يكن موجوداً
    try:
        # محاولة الاستعلام من الجدول للتحقق من وجوده
        supabase.table('fcm_tokens').select('count').limit(1).execute()
        print("✅ جدول fcm_tokens موجود")
    except Exception as e:
        print("⚠️ جدول fcm_tokens غير موجود، يرجى إنشاؤه يدوياً في Supabase")
        print("📝 SQL لإنشاء الجدول:")
        print("""
        CREATE TABLE fcm_tokens (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL UNIQUE,
            fcm_token TEXT NOT NULL,
            device_info TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Supabase: {e}")
    supabase = None

def get_all_data():
    """جلب جميع البيانات من Supabase مع ضمان وجود حقل type"""
    try:
        if not supabase:
            print("⚠️ Supabase غير متصل")
            return []
        
        print("📥 جلب الطلبات من Supabase...")
        orders_response = supabase.table('orders').select('*').execute()
        orders = orders_response.data if orders_response.data else []
        
        # إضافة حقل type للطلبات
        for order in orders:
            order['type'] = 'order'
        print(f"📦 تم جلب {len(orders)} طلب")
        
        print("👥 جلب المندوبين من Supabase...")
        agents_response = supabase.table('agents').select('*').execute()
        agents = agents_response.data if agents_response.data else []
        
        # إضافة حقل type للمندوبين
        for agent in agents:
            agent['type'] = 'agent'
        print(f"👤 تم جلب {len(agents)} مندوب")
        
        all_data = orders + agents
        print(f"✅ إجمالي البيانات: {len(all_data)} عنصر")
        return all_data
    except Exception as e:
        print(f"❌ خطأ في جلب البيانات: {e}")
        return []

def send_fcm_notification_via_admin(fcm_token, title, body, data=None):
    """إرسال إشعار عبر Firebase Admin SDK (الطريقة الحديثة)"""
    if not firebase_initialized:
        print("⚠️ Firebase Admin SDK not initialized, trying legacy method")
        return send_fcm_notification_via_legacy(fcm_token, title, body, data)
    
    try:
        from firebase_admin import messaging
        
        # بناء رسالة الإشعار
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    click_action="FLUTTER_NOTIFICATION_CLICK"
                )
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound="default",
                        badge=1
                    )
                )
            )
        )
        
        # إرسال الإشعار
        response = messaging.send(message)
        print(f"✅ تم إرسال الإشعار بنجاح عبر Admin SDK: {response}")
        return True
        
    except Exception as e:
        print(f"❌ خطأ في إرسال الإشعار عبر Admin SDK: {e}")
        return False

def send_fcm_notification_via_legacy(fcm_token, title, body, data=None):
    """إرسال إشعار عبر FCM Legacy API (طريقة احتياطية)"""
    if not fcm_token:
        print("⚠️ لا يوجد FCM Token للإرسال")
        return False
    
    if not FCM_SERVER_KEY:
        print("⚠️ لم يتم تعيين FCM_SERVER_KEY في متغيرات البيئة")
        return False
    
    import requests
    
    url = "https://fcm.googleapis.com/fcm/send"
    headers = {
        "Authorization": f"key={FCM_SERVER_KEY}",
        "Content-Type": "application/json"
    }
    
    notification_data = {
        "to": fcm_token,
        "notification": {
            "title": title,
            "body": body,
            "icon": "/favicon.ico",
            "click_action": "https://altheka-drivers.onrender.com"
        },
        "data": data or {
            "click_action": "FLUTTER_NOTIFICATION_CLICK",
            "sound": "default"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(notification_data))
        result = response.json()
        if response.status_code == 200 and result.get("success", 0) > 0:
            print(f"✅ تم إرسال الإشعار بنجاح عبر Legacy API: {title}")
            return True
        else:
            print(f"❌ فشل إرسال الإشعار: {result}")
            return False
    except Exception as e:
        print(f"❌ خطأ في إرسال الإشعار: {e}")
        return False

def send_fcm_notification(fcm_token, title, body, data=None):
    """إرسال إشعار عبر FCM (تحاول Admin SDK أولاً ثم Legacy)"""
    # محاولة إرسال عبر Admin SDK أولاً
    if send_fcm_notification_via_admin(fcm_token, title, body, data):
        return True
    
    # إذا فشلت، جرب Legacy API
    return send_fcm_notification_via_legacy(fcm_token, title, body, data)

def send_notification_to_user(user_id, title, body, order_id=None):
    """إرسال إشعار إلى مستخدم محدد (مندوب أو مدير) باستخدام FCM Token المخزن"""
    try:
        if not supabase:
            print("⚠️ Supabase غير متصل")
            return False
        
        # البحث عن FCM Token للمستخدم
        result = supabase.table('fcm_tokens').select('fcm_token').eq('user_id', user_id).execute()
        
        if not result.data:
            print(f"⚠️ لا يوجد FCM Token للمستخدم: {user_id}")
            return False
        
        fcm_token = result.data[0]['fcm_token']
        
        # تحضير البيانات الإضافية
        data = {}
        if order_id:
            data['order_id'] = str(order_id)
        
        # إرسال الإشعار
        return send_fcm_notification(fcm_token, title, body, data)
        
    except Exception as e:
        print(f"❌ خطأ في إرسال الإشعار للمستخدم {user_id}: {e}")
        return False

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
        
        # تحديد الجدول المناسب والتأكد من وجود type
        if new_item.get('type') == 'agent':
            table_name = 'agents'
        else:
            table_name = 'orders'
            new_item['type'] = 'order'
        
        print(f"📝 إضافة إلى جدول {table_name}: {new_item.get('customer_name', new_item.get('agent_name', 'غير معروف'))}")
        print(f"📋 البيانات المرسلة: {new_item}")
        
        # إدراج البيانات في Supabase
        result = supabase.table(table_name).insert(new_item).execute()
        
        if result.data:
            print(f"✅ تمت الإضافة بنجاح، ID: {result.data[0].get('__backendId')}")
            # تأكد من أن البيانات المرجعة تحتوي على حقل type
            returned_data = result.data[0]
            if 'type' not in returned_data:
                returned_data['type'] = table_name[:-1] if table_name != 'orders' else 'order'
            return jsonify({'isOk': True, 'data': returned_data}), 201
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
        
        # تخزين البيانات القديمة لإرسال الإشعارات
        old_item = None
        
        # تحديد الجدول المناسب
        if updated_item.get('type') == 'agent':
            table_name = 'agents'
        else:
            table_name = 'orders'
            # جلب البيانات القديمة للطلب (لإرسال إشعار عند تغيير الحالة)
            old_result = supabase.table('orders').select('*').eq('__backendId', item_id).execute()
            if old_result.data:
                old_item = old_result.data[0]
        
        print(f"✏️ تحديث في جدول {table_name}، ID: {item_id}")
        
        # تحديث البيانات في Supabase
        result = supabase.table(table_name).update(updated_item).eq('__backendId', item_id).execute()
        
        if result.data:
            print(f"✅ تم التحديث بنجاح")
            returned_data = result.data[0]
            if 'type' not in returned_data:
                returned_data['type'] = table_name[:-1] if table_name != 'orders' else 'order'
            
            # إذا كان تحديث حالة طلب، أرسل إشعاراً للمندوب والمدير
            if (old_item and old_item.get('status') != updated_item.get('status') and 
                updated_item.get('status') and old_item.get('agent_name')):
                
                agent_name = old_item.get('agent_name')
                customer_name = old_item.get('customer_name', 'زبون')
                old_status = old_item.get('status', 'غير معروف')
                new_status = updated_item.get('status')
                
                if agent_name:
                    title = f"تغيير حالة الطلب"
                    body = f"طلب {customer_name}: تغير من {old_status} إلى {new_status}"
                    
                    # إرسال إشعار للمندوب
                    send_notification_to_user(agent_name, title, body, item_id)
                    
                    # إرسال إشعار للمدير
                    send_notification_to_user('admin', title, body, item_id)
                    
                    print(f"📨 تم إرسال إشعار للمندوب {agent_name} والمدير")
            
            return jsonify({'isOk': True, 'data': returned_data})
        else:
            # محاولة البحث في الجدول الآخر
            other_table = 'agents' if table_name == 'orders' else 'orders'
            result = supabase.table(other_table).update(updated_item).eq('__backendId', item_id).execute()
            if result.data:
                print(f"✅ تم التحديث في جدول {other_table}")
                returned_data = result.data[0]
                returned_data['type'] = other_table[:-1] if other_table != 'orders' else 'order'
                return jsonify({'isOk': True, 'data': returned_data})
            
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

# ============== مسار Service Worker للإشعارات ==============
@app.route('/firebase-messaging-sw.js')
def service_worker():
    """تقديم ملف Service Worker الخاص بـ Firebase"""
    return render_template('firebase-messaging-sw.js'), 200, {'Content-Type': 'application/javascript'}

# ============== API FCM Tokens ==============

@app.route('/api/fcm-token', methods=['POST'])
def save_fcm_token():
    """حفظ FCM Token للمستخدم الحالي"""
    try:
        data = request.json
        user_id = data.get('user_id')
        fcm_token = data.get('fcm_token')
        device_info = data.get('device_info', 'web')
        
        if not user_id or not fcm_token:
            return jsonify({"isOk": False, "error": "Missing user_id or fcm_token"}), 400
        
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        # التحقق من وجود المستخدم
        existing = supabase.table('fcm_tokens').select('*').eq('user_id', user_id).execute()
        
        if existing.data:
            # تحديث token الموجود
            result = supabase.table('fcm_tokens').update({
                'fcm_token': fcm_token,
                'device_info': device_info,
                'updated_at': datetime.now().isoformat()
            }).eq('user_id', user_id).execute()
        else:
            # إضافة token جديد
            result = supabase.table('fcm_tokens').insert({
                'user_id': user_id,
                'fcm_token': fcm_token,
                'device_info': device_info,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }).execute()
        
        if result.data:
            print(f"✅ تم حفظ FCM Token للمستخدم: {user_id}")
            return jsonify({'isOk': True})
        else:
            return jsonify({'isOk': False, 'error': 'Failed to save token'}), 500
            
    except Exception as e:
        print(f"API Error POST FCM Token: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/send-notification', methods=['POST'])
def send_notification():
    """إرسال إشعار إلى مستخدم محدد"""
    try:
        data = request.json
        user_id = data.get('user_id')
        title = data.get('title')
        body = data.get('body')
        order_id = data.get('order_id')
        
        if not user_id or not title or not body:
            return jsonify({"isOk": False, "error": "Missing required fields"}), 400
        
        result = send_notification_to_user(user_id, title, body, order_id)
        return jsonify({'isOk': result})
        
    except Exception as e:
        print(f"API Error Send Notification: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/fcm-tokens', methods=['GET'])
def get_fcm_tokens():
    """جلب جميع FCM Tokens (للمدير فقط)"""
    try:
        if not supabase:
            return jsonify([]), 500
        
        result = supabase.table('fcm_tokens').select('user_id, device_info, updated_at').execute()
        return jsonify(result.data if result.data else [])
        
    except Exception as e:
        print(f"API Error GET FCM Tokens: {e}")
        return jsonify([]), 500

@app.route('/health', methods=['GET'])
def health_check():
    """نقطة للتحقق من صحة الخادم"""
    return jsonify({
        "status": "healthy",
        "supabase_connected": supabase is not None,
        "firebase_admin_initialized": firebase_initialized,
        "fcm_configured": bool(FCM_SERVER_KEY),
        "timestamp": datetime.now().isoformat()
    }), 200


# ============== API الإشعارات (محلية للتخزين) ==============

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    """جلب جميع الإشعارات"""
    try:
        if not supabase:
            return jsonify([]), 500
        result = supabase.table('notifications').select('*').order('created_at', desc=True).execute()
        return jsonify(result.data if result.data else [])
    except Exception as e:
        print(f"API Error GET Notifications: {e}")
        return jsonify([]), 500

@app.route('/api/notifications', methods=['POST'])
def add_notification():
    """إضافة إشعار جديد"""
    try:
        new_item = request.json
        if not new_item:
            return jsonify({"isOk": False, "error": "No data"}), 400
        
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        # إضافة معرف فريد وتاريخ للإشعار
        new_item['_id'] = str(int(datetime.now().timestamp() * 1000))
        new_item['created_at'] = datetime.now().isoformat()
        new_item['read'] = new_item.get('read', False)
        
        result = supabase.table('notifications').insert(new_item).execute()
        
        if result.data:
            return jsonify({'isOk': True, 'data': result.data[0]}), 201
        return jsonify({'isOk': False, 'error': 'Failed to save'}), 500
    except Exception as e:
        print(f"API Error POST Notification: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/notifications/<notification_id>/read', methods=['PUT'])
def mark_notification_read(notification_id):
    """تحديث إشعار كمقروء"""
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        result = supabase.table('notifications').update({'read': True}).eq('_id', notification_id).execute()
        
        if result.data:
            return jsonify({'isOk': True})
        return jsonify({'isOk': False, 'error': 'Not found'}), 404
    except Exception as e:
        print(f"API Error Mark Read: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500

@app.route('/api/notifications', methods=['DELETE'])
def delete_all_notifications():
    """حذف جميع الإشعارات"""
    try:
        if not supabase:
            return jsonify({"isOk": False, "error": "Supabase not connected"}), 500
        
        supabase.table('notifications').delete().neq('_id', '0').execute()
        return jsonify({'isOk': True})
    except Exception as e:
        print(f"API Error Delete Notifications: {e}")
        return jsonify({"isOk": False, "error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 تشغيل نظام الثقة - Altheka Drivers (Supabase + FCM)")
    print(f"🌐 المنفذ: {port}")
    print(f"🔗 رابط التطبيق: http://localhost:{port}")
    print(f"☁️ قاعدة البيانات: Supabase")
    if firebase_initialized:
        print(f"✅ Firebase Admin SDK: مفعل")
    else:
        print(f"⚠️ Firebase Admin SDK: غير مفعل - يرجى إضافة FIREBASE_ADMIN_CRED_JSON")
    if FCM_SERVER_KEY:
        print(f"✅ FCM Legacy API: مفعل")
    else:
        print(f"⚠️ FCM Legacy API: غير مفعل")
    print("=" * 50)
    app.run(debug=False, host='0.0.0.0', port=port)