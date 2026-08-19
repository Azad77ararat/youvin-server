// Service Worker — بيخزّن واجهة YouVin بشكل دائم عشان تفتح حتى بدون إنترنت أبداً
const CACHE_NAME = 'youvin-shell-v2';
const SHELL_FILES = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(SHELL_FILES.map((f) => new Request(f, { cache: 'reload' })))
    )
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter(n => n !== CACHE_NAME).map(n => caches.delete(n)))
    )
  );
  self.clients.claim();
});

// استراتيجية: جرّب الشبكة أول (عشان تاخدي آخر تحديث)، لو فشلت (ما فيه نت) استخدمي النسخة المخزّنة
// مهم: cache: 'no-store' يجبر تجاوز ذاكرة HTTP العادية للمتصفح، عشان دايماً نجيب آخر
// نسخة فعلية من GitHub Pages ومش نسخة قديمة محفوظة محلياً بالخطأ
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // بس لملفات الواجهة نفسها (مش لطلبات السيرفر تبع الأغاني عبر Tailscale)
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(event.request, { cache: 'no-store' })
      .then((res) => {
        const resClone = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
        return res;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match('./index.html')))
  );
});
