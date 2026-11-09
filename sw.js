// YouVin service worker: keeps the app page available without internet.
const CACHE = 'youvin-shell-v1';
const SHELL = new URL('./index.html', self.registration.scope).href;

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll([SHELL, self.registration.scope]).catch(() => {})));
});

self.addEventListener('activate', e => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Only the app page itself. API, R2 audio and everything else go straight to the network.
  if (url.origin !== self.location.origin) return;
  if (req.mode !== 'navigate' && url.href !== SHELL && url.href !== self.registration.scope) return;
  e.respondWith(
    fetch(req)
      .then(res => {
        if (res.ok) caches.open(CACHE).then(c => c.put(SHELL, res.clone()));
        return res;
      })
      .catch(() => caches.match(SHELL).then(r => r || Response.error()))
  );
});
