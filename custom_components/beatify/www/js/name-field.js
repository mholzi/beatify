/**
 * Beatify — the name field's helpers (#3391): the rejected state, and the
 * last name offered again for a rematch.
 *
 * The rejected state is shared by the guest join form (player-core.js) and the
 * host's join modal (admin.js), which are the same field with the same job.
 * Import-free so it bundles into both player.bundle.min.js and admin.min.js.
 */

/**
 * The server refused this name. Mark the field, put the cursor back into it
 * and select the text, so the guest types over it instead of hunting for the
 * field and deleting first. The reason itself is the caller's to show, under
 * the field, where `aria-describedby` points.
 * @param {HTMLInputElement|null} input
 */
export function markNameRejected(input) {
    if (!input) return;
    input.setAttribute('aria-invalid', 'true');
    if (input.classList) input.classList.add('name-input--invalid');
    try {
        input.focus({ preventScroll: true });
        if (typeof input.select === 'function') input.select();
    } catch (e) { /* not focusable right now — the mark is still there */ }
}

/**
 * Undo markNameRejected() once the name is edited.
 * @param {HTMLInputElement|null} input
 */
export function clearNameRejected(input) {
    if (!input) return;
    input.removeAttribute('aria-invalid');
    if (input.classList) input.classList.remove('name-input--invalid');
}

// #3391: the last name this tab joined with, offered again in the join field
// for a rematch in the same party. sessionStorage on purpose: it ends with the
// tab, so a phone borrowed at the next party does not open with the previous
// guest's name. clearStoredPlayerName() in player-core leaves it alone, because
// the podium clears the stored name and the rematch is where this is wanted.
export var SESSION_KEY_LAST_NAME = 'beatify_last_name';

export function rememberLastName(name) {
    if (!name) return;
    try { sessionStorage.setItem(SESSION_KEY_LAST_NAME, name); } catch (e) { /* private mode */ }
}

export function getLastNameSuggestion() {
    try { return sessionStorage.getItem(SESSION_KEY_LAST_NAME) || null; } catch (e) { return null; }
}

/**
 * Put the remembered name into an empty join field. Only a suggestion: nothing
 * joins on its own, the guest still taps Join. A field that already holds text
 * (typed, or a rejected name being corrected) is never overwritten.
 * @param {HTMLInputElement|null} input
 * @returns {boolean} whether the field was filled
 */
export function prefillNameSuggestion(input) {
    if (!input || input.value) return false;
    var name = getLastNameSuggestion();
    if (!name) return false;
    input.value = name;
    return true;
}
