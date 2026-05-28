const CACHE = 'hekineitor-{{ version }}';
const STATIC = ['/', '/manifest.json', '/ads.txt', '/static/icon-192.png', '/static/icon-512.png', '/offline'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => Promise.all(STATIC.map(url => c.add(url).catch(() => null))))
  );
  // skipWaiting は page からの SKIP_WAITING メッセージで行う
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', e => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes('/api/') || url.pathname.includes('/admin')) return;
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => caches.match(e.request).then(cached => cached || Response.error()))
    );
    return;
  }
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok && !url.pathname.startsWith('/r')) {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return res;
    }).catch(() => caches.match(e.request).then(cached => cached || caches.match('/offline')))
  );
});
