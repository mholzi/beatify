/**
 * Beatify Admin Page
 * Vanilla JS - no frameworks
 */

document.addEventListener('DOMContentLoaded', async () => {
    await loadStatus();
});

/**
 * Fetch and render current status from the API
 */
async function loadStatus() {
    try {
        const response = await fetch('/beatify/api/status');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const status = await response.json();

        renderMAStatus(status.ma_configured, status.ma_setup_url);
        renderMediaPlayers(status.media_players);
        renderPlaylists(status.playlists, status.playlist_dir);
    } catch (error) {
        console.error('Failed to load status:', error);
        document.getElementById('ma-status-content').innerHTML =
            '<span class="status-error">Failed to load status</span>';
    }
}

/**
 * Render Music Assistant status
 * @param {boolean} isConfigured
 * @param {string} setupUrl
 */
function renderMAStatus(isConfigured, setupUrl) {
    const container = document.getElementById('ma-status-content');

    if (isConfigured) {
        container.innerHTML = '<span class="status-connected">✓ Connected</span>';
    } else {
        container.innerHTML = `
            <span class="status-error">✗ Not configured</span>
            <p style="margin-top: 8px;">Music Assistant is required for Beatify to play songs.</p>
            <a href="${escapeHtml(setupUrl)}" target="_blank" rel="noopener" class="btn btn-secondary" style="margin-top: 12px;">
                Setup Guide
            </a>
        `;
    }
}

/**
 * Render media players list
 * @param {Array} players
 */
function renderMediaPlayers(players) {
    const container = document.getElementById('media-players-list');

    if (!players || players.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p>No media players found</p>
                <p style="font-size: 14px;">Add media players to Home Assistant to use with Beatify.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = players.map(player => `
        <div class="list-item">
            <span class="name">${escapeHtml(player.friendly_name)}</span>
            <span class="meta">${escapeHtml(player.state)}</span>
        </div>
    `).join('');
}

/**
 * Render playlists list
 * @param {Array} playlists
 * @param {string} playlistDir
 */
function renderPlaylists(playlists, playlistDir) {
    const container = document.getElementById('playlists-list');

    if (!playlists || playlists.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p>No playlists found</p>
                <p style="font-size: 14px;">Add .json playlist files to:<br><code>${escapeHtml(playlistDir)}</code></p>
            </div>
        `;
        return;
    }

    container.innerHTML = playlists.map(playlist => {
        const validClass = playlist.is_valid ? '' : 'is-invalid';
        const statusText = playlist.is_valid
            ? `${playlist.song_count} songs`
            : `Invalid: ${playlist.errors[0] || 'Unknown error'}`;

        return `
            <div class="list-item ${validClass}">
                <span class="name">${escapeHtml(playlist.name)}</span>
                <span class="meta">${escapeHtml(statusText)}</span>
            </div>
        `;
    }).join('');
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
    if (text === null || text === undefined) {
        return '';
    }
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}
