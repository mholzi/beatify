/**
 * Beatify Admin — the "join once the socket is open" wait (#3059).
 *
 * When the host taps Join while the admin WebSocket is reconnecting,
 * handleAdminJoin() polls until the socket opens and then sends the join. The
 * poll used to live in a local `setInterval` nothing could reach, so Cancel,
 * the backdrop and Escape (closeAdminJoinModal) left it running: the join still
 * went out when the socket opened, and re-opening the modal armed a second one.
 *
 * The interval id now lives here. `startJoinWait` clears any earlier wait
 * first; `cancelJoinWait` is called by closeAdminJoinModal(); and the tick
 * bails out on its own if the modal is no longer visible.
 */

const POLL_MS = 100;
const TIMEOUT_MS = 20000;

let pollId = null;

/** Stop a pending wait, if any. Safe to call at any time. */
export function cancelJoinWait() {
    if (pollId !== null) {
        clearInterval(pollId);
        pollId = null;
    }
}

/**
 * Wait for the socket, then run `onReady`; run `onTimeout` after 20 s.
 * `isOpen` — socket is open; `isModalVisible` — the join modal is still shown.
 */
export function startJoinWait({ isOpen, isModalVisible, onReady, onTimeout }) {
    cancelJoinWait();
    const startedAt = Date.now();
    const id = setInterval(() => {
        if (pollId !== id) return;
        if (!isModalVisible()) {
            cancelJoinWait();
            return;
        }
        if (isOpen()) {
            cancelJoinWait();
            onReady();
        } else if (Date.now() - startedAt > TIMEOUT_MS) {
            cancelJoinWait();
            onTimeout();
        }
    }, POLL_MS);
    pollId = id;
}
