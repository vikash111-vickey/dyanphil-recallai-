// Dyanphil Service Worker - Network-First for HTML & Shell Updates
const CACHE_NAME = 'dyanphil-v3';

self.addEventListener('install', (event) => {
  // Force new service worker to activate immediately without waiting
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    // Delete all older caches immediately
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[SW] Purging old cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Exclude API requests
  const isApi = (
    url.pathname.startsWith('/api') ||
    url.pathname.startsWith('/ask') ||
    url.pathname.startsWith('/vault') ||
    url.pathname.startsWith('/settings') ||
    url.pathname.startsWith('/index') ||
    url.pathname.startsWith('/ocr') ||
    url.pathname.startsWith('/gmail') ||
    url.pathname.startsWith('/privacy') ||
    url.pathname.startsWith('/health') ||
    url.pathname.startsWith('/open')
  );

  if (event.request.method !== 'GET' || isApi) {
    return;
  }

  // Network-First for HTML documents (ensures user always gets the latest deployed code)
  if (event.request.mode === 'navigate' || url.pathname === '/' || url.pathname === '/index.html') {
    event.respondWith(
      fetch(event.request)
        .then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const copy = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return networkRes;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Cache-First for versioned static assets (hashed .js, .css, .woff2)
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const copy = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return networkRes;
        });
      })
    );
    return;
  }

  // Default: Network with cache fallback
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
