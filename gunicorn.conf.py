# gunicorn.conf.py - لـ 2000 طلب يومياً
import multiprocessing
import os

port = int(os.environ.get('PORT', 5000))
bind = f"0.0.0.0:{port}"

# عدد العمال: (عدد المندوبين / 10) تقريباً
# 20 مندوب -> 3-4 عمال كافيين
workers = 3
threads = 4  # زيادة الخيوط لاستقبال أكثر

timeout = 90
graceful_timeout = 30

# زيادة هذا الرقم لأن لديك طلبات كثيرة
max_requests = 2000  # يعاد تشغيل العامل بعد 2000 طلب HTTP
max_requests_jitter = 200

reload = False
daemon = False
debug = False

accesslog = '-'
errorlog = '-'
loglevel = 'info'