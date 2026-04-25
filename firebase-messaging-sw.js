// firebase-messaging-sw.js
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-messaging-compat.js');

const firebaseConfig = {
  apiKey: "AIzaSyBBRW9XT2wdeBlKh9Fs50H68FUItv68Jbw",
  authDomain: "trust-center-notifications.firebaseapp.com",
  projectId: "trust-center-notifications",
  storageBucket: "trust-center-notifications.firebasestorage.app",
  messagingSenderId: "150648020047",
  appId: "1:150648020047:web:c5051941de6f2e81ee9e3a"
};

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  console.log('📨 إشعار خلفية:', payload);
  
  const notificationTitle = payload.notification?.title || 'مركز الثقة';
  const notificationOptions = {
    body: payload.notification?.body || 'لديك إشعار جديد',
    icon: '/favicon.ico',
    badge: '/favicon.ico',
    data: {
      url: payload.data?.url || '/',
      orderId: payload.data?.orderId || null
    },
    vibrate: [200, 100, 200],
    requireInteraction: true
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data?.url || '/')
  );
});