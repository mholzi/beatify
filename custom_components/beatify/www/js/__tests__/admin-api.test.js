/**
 * Unit tests for the pure helpers extracted into admin/api.js (#1279, Schritt 3/6).
 *
 * Step 3 moves the admin WebSocket hub (connect / message-dispatch / reconnect)
 * out of admin.js into admin/api.js. The live-socket lifecycle is not unit-
 * tested here (it needs a real WS + DOM + the injected admin callbacks — that's
 * covered by the mandatory manual device QA). What IS cleanly testable are the
 * two side-effect-free helpers the hub builds on:
 *
 *   - buildWsUrl(location)   — ws:/wss: URL builder from a location-like object
 *   - reconnectDelay(attempt) — exponential backoff (1-based), capped at 30s
 */
import { describe, it, expect } from 'vitest';
import { buildWsUrl, reconnectDelay } from '../admin/api.js';

describe('buildWsUrl', () => {
    it('uses wss: on an https location', () => {
        expect(buildWsUrl({ protocol: 'https:', host: 'example.com' }))
            .toBe('wss://example.com/beatify/ws');
    });

    it('uses ws: on an http location', () => {
        expect(buildWsUrl({ protocol: 'http:', host: 'example.com' }))
            .toBe('ws://example.com/beatify/ws');
    });

    it('uses ws: for any non-https protocol (e.g. file:)', () => {
        expect(buildWsUrl({ protocol: 'file:', host: 'localhost:8123' }))
            .toBe('ws://localhost:8123/beatify/ws');
    });

    it('preserves host:port', () => {
        expect(buildWsUrl({ protocol: 'https:', host: 'ha.local:8123' }))
            .toBe('wss://ha.local:8123/beatify/ws');
    });

    it('always targets the /beatify/ws path', () => {
        expect(buildWsUrl({ protocol: 'https:', host: 'x' })).toMatch(/\/beatify\/ws$/);
    });
});

describe('reconnectDelay', () => {
    it('returns 1000ms for the first attempt', () => {
        expect(reconnectDelay(1)).toBe(1000);
    });

    it('doubles each attempt (exponential backoff)', () => {
        expect(reconnectDelay(2)).toBe(2000);
        expect(reconnectDelay(3)).toBe(4000);
        expect(reconnectDelay(4)).toBe(8000);
        expect(reconnectDelay(5)).toBe(16000);
    });

    it('caps the delay at 30000ms', () => {
        // 2^5 * 1000 = 32000 > cap, and everything beyond stays at the cap
        expect(reconnectDelay(6)).toBe(30000);
        expect(reconnectDelay(10)).toBe(30000);
        expect(reconnectDelay(100)).toBe(30000);
    });
});
