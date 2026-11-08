/**
 * Beatify browser audio: play without a speaker.
 *
 * When the host picks "TV screen" or "This phone" as the speaker, the server
 * sends the round's 30-second preview URL to that one page, and this player
 * plays it in an <audio> element. Shared by the TV page (dashboard.js) and the
 * admin page (admin.js), so the two speak one protocol:
 *
 *   server -> page  {type: 'browser_audio', action: 'play', url, id}
 *                   {type: 'browser_audio', action: 'stop' | 'resume'}
 *                   {type: 'browser_audio', action: 'volume', level}
 *                   {type: 'browser_audio', action: 'announce', url}
 *   page -> server  {type: 'playback_report', state, id}
 *                   state: playing | blocked | error | ended | paused
 *
 * Browsers refuse to play sound before the page has been touched once. The TV
 * shows a one-time "Sound on" button for that, the phone gets it with the tap
 * on "Start game": both call unlock() inside that tap, which starts both audio
 * elements once so later play() calls are allowed. A clip that arrives before
 * the tap is reported "blocked" and starts with the tap.
 *
 * The clip is streamed from its source and never stored (Deezer's terms):
 * nothing here fetches, caches or copies the audio.
 *
 * Classic script (no module): dashboard.js is an IIFE and reads it from
 * window.BeatifyBrowserAudio; admin.js does the same.
 */
(function(root) {
    'use strict';

    // 44-byte WAV with no samples: what unlock() plays to wake an element.
    var SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';
    // Music level while an announcement speaks over it.
    var DUCK_FACTOR = 0.25;

    function clampLevel(level) {
        var n = Number(level);
        if (!isFinite(n)) return 1;
        return Math.max(0, Math.min(1, n));
    }

    /**
     * @param {object} opts
     * @param {(msg: object) => void} opts.send - deliver a frame to the server
     * @param {(needed: boolean) => void} [opts.onNeedsTap] - show or hide the
     *   "Sound on" prompt: true when a clip waits for a tap
     * @param {() => HTMLAudioElement} [opts.createAudio] - test seam
     * @param {number} [opts.volume] - starting level, 0..1
     */
    function createBrowserAudio(opts) {
        var send = opts.send;
        var onNeedsTap = opts.onNeedsTap || function() {};
        var createAudio = opts.createAudio || function() { return new Audio(); };

        var music = createAudio();
        var voice = createAudio();
        music.preload = 'auto';
        voice.preload = 'auto';

        var unlocked = false;
        var waiting = null;      // {url, id} of a clip blocked until the tap
        var currentUrl = null;   // the clip in `music`, for resume
        var level = clampLevel(opts.volume == null ? 0.8 : opts.volume);
        var ducked = false;
        var needsTap = false;

        function report(state, id) {
            var frame = { type: 'playback_report', state: state };
            if (typeof id === 'number') frame.id = id;
            try { send(frame); } catch (e) { /* socket gone: the server notices */ }
        }

        function setNeedsTap(value) {
            if (needsTap === value) return;
            needsTap = value;
            onNeedsTap(value);
        }

        function applyVolume() {
            music.volume = ducked ? level * DUCK_FACTOR : level;
            voice.volume = level;
        }

        function start(element, id) {
            var result;
            try {
                result = element.play();
            } catch (err) {
                report('error', id);
                return;
            }
            if (!result || typeof result.then !== 'function') {
                report('playing', id);
                return;
            }
            result.then(function() {
                waiting = null;
                setNeedsTap(false);
                report('playing', id);
            }, function(err) {
                if (err && err.name === 'NotAllowedError') {
                    waiting = { url: currentUrl, id: id };
                    setNeedsTap(true);
                    report('blocked', id);
                } else if (err && err.name === 'AbortError') {
                    // A newer play() or a stop() replaced this one; not a failure.
                } else {
                    report('error', id);
                }
            });
        }

        music.onended = function() {
            if (music.src && music.src !== SILENT_WAV && currentUrl) report('ended');
        };
        voice.onended = function() {
            ducked = false;
            applyVolume();
        };
        voice.onerror = voice.onended;

        function play(url, id) {
            if (typeof url !== 'string' || url.indexOf('https://') !== 0) {
                report('error', id);
                return;
            }
            currentUrl = url;
            music.src = url;
            applyVolume();
            start(music, id);
        }

        function stop() {
            waiting = null;
            try { music.pause(); } catch (e) { /* not started */ }
            report('paused');
        }

        function resume() {
            if (!currentUrl) return;
            start(music);
        }

        function announce(url) {
            if (typeof url !== 'string' || !url) return;
            voice.src = url;
            ducked = !!currentUrl;
            applyVolume();
            var result;
            try { result = voice.play(); } catch (e) { result = null; }
            if (result && typeof result.catch === 'function') {
                result.catch(function() { ducked = false; applyVolume(); });
            }
        }

        /** Wake both elements inside a tap; starts a clip that was waiting. */
        function unlock() {
            unlocked = true;
            setNeedsTap(false);
            if (!voice.src || voice.src === SILENT_WAV) {
                voice.src = SILENT_WAV;
                try {
                    var v = voice.play();
                    if (v && typeof v.catch === 'function') v.catch(function() {});
                } catch (e) { /* nothing to wake */ }
            }
            if (waiting) {
                var w = waiting;
                waiting = null;
                start(music, w.id);
                return;
            }
            if (!currentUrl) {
                music.src = SILENT_WAV;
                try {
                    var m = music.play();
                    if (m && typeof m.catch === 'function') m.catch(function() {});
                } catch (e) { /* nothing to wake */ }
            }
        }

        /** This page no longer plays (another page claimed the role). */
        function release() {
            waiting = null;
            currentUrl = null;
            try { music.pause(); } catch (e) { /* idle */ }
            try { voice.pause(); } catch (e) { /* idle */ }
            setNeedsTap(false);
        }

        function handle(msg) {
            if (!msg || msg.type !== 'browser_audio') return false;
            switch (msg.action) {
                case 'play': play(msg.url, msg.id); break;
                case 'stop': stop(); break;
                case 'resume': resume(); break;
                case 'volume': level = clampLevel(msg.level); applyVolume(); break;
                case 'announce': announce(msg.url); break;
                default: return false;
            }
            return true;
        }

        return {
            handle: handle,
            unlock: unlock,
            release: release,
            isUnlocked: function() { return unlocked; },
            needsTap: function() { return needsTap; },
            getVolume: function() { return level; },
        };
    }

    root.BeatifyBrowserAudio = {
        createBrowserAudio: createBrowserAudio,
        SILENT_WAV: SILENT_WAV,
        DUCK_FACTOR: DUCK_FACTOR,
        TV_TARGET: 'beatify_browser.tv',
        PHONE_TARGET: 'beatify_browser.phone',
        isBrowserTarget: function(entityId) {
            return entityId === 'beatify_browser.tv' || entityId === 'beatify_browser.phone';
        },
    };
})(typeof window !== 'undefined' ? window : globalThis);
