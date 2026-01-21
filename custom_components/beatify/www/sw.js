/**
 * Beatify Service Worker (Story 18.5)
 *
 * Caches static assets for faster subsequent loads.
 * Uses Cache-First for static assets, Network-First for HTML.
 */
'use strict';

var CACHE_VERSION = 'beatify-v1';
var MAX_CACHE_ITEMS = 50;

// Critical assets to precache on install (minified versions only - fallback handled by HTML)
var PRECACHE_ASSETS = [
    '/beatify/static/css/styles.min.css',
    '/beatify/static/css/dashboard.min.css',
    '/beatify/static/js/player.min.js',
    '/beatify/static/js/admin.min.js',
    '/beatify/static/js/dashboard.min.js',
    '/beatify/static/js/i18n.min.js',
    '/beatify/static/js/vendor/qrcode.min.js',
    '/beatify/static/img/no-artwork.svg'
];

/**
 * Install event: Precache critical assets
 */
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_VERSION)
            .then(function(cache) {
                // Try to cache each asset, but don't fail if some are missing
                return Promise.all(
                    PRECACHE_ASSETS.map(function(url) {
                        return cache.add(url).catch(function(err) {
                            console.warn('[SW] Failed to cache:', url, err);
                        });
                    })
                );
            })
            .then(function() {
                // Activate immediately without waiting for other tabs to close
                return self.skipWaiting();
            })
    );
});

/**
 * Activate event: Clean up old caches
 */
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys()
            .then(function(cacheNames) {
                return Promise.all(
                    cacheNames
                        .filter(function(name) {
                            // Delete old Beatify caches
                            return name.startsWith('beatify-') && name !== CACHE_VERSION;
                        })
                        .map(function(name) {
                            console.log('[SW] Deleting old cache:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(function() {
                // Take control of all clients immediately
                return self.clients.claim();
            })
    );
});

/**
 * Fetch event: Handle requests with appropriate caching strategy
 */
self.addEventListener('fetch', function(event) {
    var url = new URL(event.request.url);

    // Skip WebSocket connections (AC: #2 - only WebSocket requires network)
    if (url.pathname.includes('/beatify/ws') || url.protocol === 'ws:' || url.protocol === 'wss:') {
        return;
    }

    // Skip API calls (AC: #2 - dynamic game state)
    if (url.pathname.includes('/beatify/api/')) {
        return;
    }

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // Google Fonts: Cache-First (rarely changes) - check before origin check
    if (url.hostname.includes('googleapis.com') || url.hostname.includes('gstatic.com')) {
        event.respondWith(cacheFirst(event.request));
        return;
    }

    // Skip requests to other origins (except Google Fonts handled above)
    if (url.origin !== location.origin) {
        return;
    }

    // HTML pages: Network-First (always try to get fresh)
    var accept = event.request.headers.get('accept') || '';
    if (accept.includes('text/html') || url.pathname.endsWith('.html')) {
        event.respondWith(networkFirst(event.request));
        return;
    }

    // Static assets: Cache-First
    if (url.pathname.startsWith('/beatify/static/')) {
        event.respondWith(cacheFirst(event.request));
        return;
    }
});

/**
 * Cache-First strategy: Return cached response if available, else fetch
 */
function cacheFirst(request) {
    return caches.match(request)
        .then(function(cached) {
            if (cached) {
                return cached;
            }
            return fetch(request)
                .then(function(response) {
                    // Only cache successful responses
                    if (response && response.ok) {
                        var clone = response.clone();
                        caches.open(CACHE_VERSION)
                            .then(function(cache) {
                                cache.put(request, clone);
                                pruneCache();
                            })
                            .catch(function(err) {
                                console.warn('[SW] Cache put failed:', err);
                            });
                    }
                    return response;
                });
        });
}

/**
 * Network-First strategy: Try network first, fall back to cache
 */
function networkFirst(request) {
    return fetch(request)
        .then(function(response) {
            // Cache successful responses
            if (response && response.ok) {
                var clone = response.clone();
                caches.open(CACHE_VERSION)
                    .then(function(cache) {
                        cache.put(request, clone);
                    })
                    .catch(function(err) {
                        console.warn('[SW] Cache put failed:', err);
                    });
            }
            return response;
        })
        .catch(function() {
            // Network failed, try cache
            return caches.match(request);
        });
}

/**
 * Prune cache to stay under size limit (AC: #4)
 */
function pruneCache() {
    caches.open(CACHE_VERSION)
        .then(function(cache) {
            cache.keys().then(function(keys) {
                if (keys.length > MAX_CACHE_ITEMS) {
                    // Delete oldest entries (FIFO)
                    var toDelete = keys.slice(0, keys.length - MAX_CACHE_ITEMS);
                    Promise.all(
                        toDelete.map(function(key) {
                            return cache.delete(key);
                        })
                    );
                }
            });
        })
        .catch(function(err) {
            console.warn('[SW] Prune cache failed:', err);
        });
}
