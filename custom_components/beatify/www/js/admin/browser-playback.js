/**
 * Play without a speaker: this phone as the speaker.
 *
 * When the host picks "This phone", the server sends each round's 30-second
 * preview to the host's admin page, which plays it through browser-audio.js
 * (window.BeatifyBrowserAudio). This module is the admin's half of that:
 *
 * - it registers the page as the "phone" playback client once the admin
 *   socket is authenticated (the server only lets the host's own page take
 *   that role), and again when the host picks "This phone" while connected
 *   or a game turns out to be playing on it;
 * - it hands `browser_audio` frames to the player;
 * - it wakes the audio inside the host's taps. A browser plays sound only
 *   after a touch, and the tap on "Start game" is one — so the phone needs no
 *   extra "Sound on" step.
 *
 * No DOM beyond the tap listener, so it is unit-tested with plain stubs.
 */

export const PHONE_TARGET = 'beatify_browser.phone';

/**
 * @param {object} opts
 * @param {(frame: object) => boolean} opts.send - send over the admin socket
 * @param {() => (string|null)} opts.getSelectedEntityId - the picked speaker
 * @param {object|null} opts.lib - window.BeatifyBrowserAudio
 */
export function createPhonePlayback({ send, getSelectedEntityId, lib }) {
    let audio = null;
    let gameRole = null;   // browser_playback of the running game
    let holds = false;     // the server plays on this page

    function wanted() {
        return gameRole === 'phone' || getSelectedEntityId() === PHONE_TARGET;
    }

    function ensureAudio() {
        if (!audio && lib && typeof lib.createBrowserAudio === 'function') {
            audio = lib.createBrowserAudio({ send });
        }
        return audio;
    }

    /** Ask to play for the phone target; false when not wanted or not sent. */
    function register() {
        if (!lib || !wanted()) return false;
        ensureAudio();
        // claim: this is the host's own page; another admin tab that held the
        // role (an older device) hands it over.
        return !!send({ type: 'playback_register', role: 'phone', claim: true });
    }

    /**
     * Take one admin-socket frame. Returns true when it was a playback frame
     * this module consumed; `state` frames are read but never consumed.
     */
    function handle(data) {
        if (!data || typeof data !== 'object') return false;
        switch (data.type) {
            case 'state': {
                const previous = gameRole;
                gameRole = data.browser_playback || null;
                if (gameRole === 'phone' && previous !== 'phone' && !holds) register();
                return false;
            }
            case 'browser_audio': {
                const player = ensureAudio();
                return player ? player.handle(data) : false;
            }
            case 'playback_registered':
                if (data.role === 'phone') holds = !!data.active;
                return data.role === 'phone';
            case 'playback_released':
                if (data.role !== 'phone') return false;
                holds = false;
                if (audio) audio.release();
                return true;
            default:
                return false;
        }
    }

    /** The admin socket is (re)authenticated: a new socket holds nothing yet. */
    function onConnected() {
        holds = false;
        return register();
    }

    /** The host picked a speaker; register when it is this phone. */
    function selectionChanged() {
        if (!holds) register();
    }

    /** Wake the audio inside the host's taps while this phone is the speaker. */
    function onTap() {
        if (!wanted()) return;
        const player = ensureAudio();
        if (player && !player.isUnlocked()) player.unlock();
    }

    function armUnlockOnTap(target) {
        if (!target || typeof target.addEventListener !== 'function') return;
        // click and keydown are user activations on every browser, iOS
        // included (pointerdown is not, on a touch screen). Capture phase, so
        // the tap on "Start game" wakes the audio before its handler runs.
        target.addEventListener('click', onTap, true);
        target.addEventListener('keydown', onTap, true);
    }

    return {
        handle,
        register,
        onConnected,
        selectionChanged,
        onTap,
        armUnlockOnTap,
        holdsRole: () => holds,
    };
}

/**
 * Poll `/beatify/api/browser-targets` while the "TV screen" row says the TV
 * page is not open, and call `onConnected` once it is. Used by the admin's
 * speaker list and the wizard's step 1, so the row turns "connected" the
 * moment the TV page loads. Stops by itself after `maxMs` (a host who never
 * opens the TV page does not keep a timer running all evening).
 *
 * @param {object} opts
 * @param {(url: string) => Promise<Response>} opts.fetchFn
 * @param {() => void} opts.onConnected
 * @param {() => boolean} [opts.isVisible] - skip ticks while hidden
 */
export function createTvConnectionWatch({
    fetchFn,
    onConnected,
    isVisible = () => true,
    intervalMs = 4000,
    maxMs = 10 * 60 * 1000,
    now = () => Date.now(),
    setIntervalFn = (fn, ms) => setInterval(fn, ms),
    clearIntervalFn = (t) => clearInterval(t),
}) {
    let timer = null;
    let startedAt = 0;

    function stop() {
        if (timer !== null) {
            clearIntervalFn(timer);
            timer = null;
        }
    }

    async function tick() {
        if (timer === null) return;
        if (now() - startedAt > maxMs) {
            stop();
            return;
        }
        if (!isVisible()) return;
        try {
            const res = await fetchFn('/beatify/api/browser-targets');
            if (!res || !res.ok) return;
            const data = await res.json();
            if (data && data.tv && timer !== null) {
                stop();
                onConnected();
            }
        } catch (e) { /* next tick */ }
    }

    function start() {
        stop();
        startedAt = now();
        timer = setIntervalFn(tick, intervalMs);
    }

    return { start, stop, tick, isRunning: () => timer !== null };
}
