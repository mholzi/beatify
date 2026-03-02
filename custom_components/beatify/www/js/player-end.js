/**
 * Beatify Player - End Module
 * End screen: leaderboard, superlatives, rematch/new-game buttons, share tab, highlights tab
 */

import {
    state, escapeHtml, showConfirmModal,
    AnimationQueue, triggerConfetti, stopConfetti, showView
} from './player-utils.js';

var utils = window.BeatifyUtils || {};

// ============================================
// End View (Story 5.6)
// ============================================

/**
 * Update end view with final standings and stats
 * @param {Object} data - State data with leaderboard and game_stats
 */
export function updateEndView(data) {
    window.scrollTo(0, 0);
    var leaderboard = data.leaderboard || [];

    leaderboard.forEach(function(entry) {
        entry.is_current = (entry.name === state.playerName);
    });

    // Update podium (positions 1, 2, 3)
    [1, 2, 3].forEach(function(place) {
        var player = leaderboard.find(function(p) { return p.rank === place; });
        var nameEl = document.getElementById('podium-' + place + '-name');
        var scoreEl = document.getElementById('podium-' + place + '-score');
        if (nameEl) nameEl.textContent = player ? escapeHtml(player.name) : '---';
        if (scoreEl) scoreEl.textContent = player ? player.score : '0';
    });

    var currentPlayer = leaderboard.find(function(p) { return p.is_current; });

    var rankEl = document.getElementById('your-final-rank');
    var scoreEl = document.getElementById('your-final-score');
    var bestStreakEl = document.getElementById('stat-best-streak');
    var roundsEl = document.getElementById('stat-rounds');
    var betsEl = document.getElementById('stat-bets');

    if (currentPlayer) {
        if (rankEl) rankEl.textContent = '#' + currentPlayer.rank;
        if (scoreEl) scoreEl.textContent = currentPlayer.score + ' ' + utils.t('leaderboard.points');
        if (bestStreakEl) bestStreakEl.textContent = currentPlayer.best_streak || 0;
        if (roundsEl) roundsEl.textContent = currentPlayer.rounds_played || 0;
        if (betsEl) betsEl.textContent = currentPlayer.bets_won || 0;
    }

    // Update full leaderboard (Story 11.4: disconnected styling)
    var listEl = document.getElementById('final-leaderboard-list');
    if (listEl) {
        listEl.innerHTML = leaderboard.map(function(entry) {
            var currentClass = entry.is_current ? 'is-current' : '';
            var disconnectedClass = entry.connected === false ? 'final-entry--disconnected' : '';
            var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';
            return '<div class="final-entry ' + currentClass + ' ' + disconnectedClass + '">' +
                '<span class="final-rank">#' + entry.rank + '</span>' +
                '<span class="final-name">' + escapeHtml(entry.name) + awayBadge + '</span>' +
                '<span class="final-score">' + entry.score + '</span>' +
            '</div>';
        }).join('');
    }

    renderSuperlatives(data.superlatives);

    renderHighlights(data.highlights);

    renderShareTab(data.share_data);

    // Show admin or player controls
    var adminControls = document.getElementById('end-admin-controls');
    var playerMessage = document.getElementById('end-player-message');

    if (currentPlayer && currentPlayer.is_admin) {
        if (adminControls) adminControls.classList.remove('hidden');
        if (playerMessage) playerMessage.classList.add('hidden');
        var newGameBtn = document.getElementById('new-game-btn');
        if (newGameBtn) {
            newGameBtn.onclick = handleNewGame;
        }
        // Wire up rematch button (Issue #254)
        var rematchBtn = document.getElementById('player-rematch-btn');
        if (rematchBtn) {
            rematchBtn.onclick = function() {
                rematchBtn.disabled = true;
                var origText = rematchBtn.textContent;
                rematchBtn.textContent = '⏳';
                fetch('/beatify/api/rematch-game', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' }
                })
                    .then(function(resp) {
                        if (!resp.ok) return resp.json().then(function(e) { throw new Error(e.message || 'Rematch failed'); });
                        AnimationQueue.clear();
                        stopConfetti();
                        showView('lobby-view');
                        state.reconnectAttempts = 0;
                        state.connectWithSession();
                    })
                    .catch(function(err) {
                        console.error('[Player] Rematch failed:', err);
                        alert(err.message || 'Failed to start rematch');
                        rematchBtn.disabled = false;
                        rematchBtn.textContent = origText;
                    });
            };
        }
    } else {
        if (adminControls) adminControls.classList.add('hidden');
        if (playerMessage) playerMessage.classList.remove('hidden');
    }

    // Story 14.5: Trigger end-game celebrations (AC3, AC4)
    if (currentPlayer) {
        var totalRounds = data.total_rounds || 10;
        var bestStreak = currentPlayer.best_streak || 0;
        var isPerfectGame = bestStreak === totalRounds && totalRounds > 0;

        if (isPerfectGame) {
            triggerConfetti('perfect');
        } else if (currentPlayer.rank === 1) {
            triggerConfetti('winner');
        }
    }
}

// ============================================
// Superlatives (Story 15.2)
// ============================================

/**
 * Render superlatives / fun awards (Story 15.2)
 * @param {Array|null} superlatives - Array of award objects from state
 */
function renderSuperlatives(superlatives) {
    var container = document.getElementById('superlatives-container');
    if (!container) return;

    if (!superlatives || superlatives.length === 0) {
        container.classList.add('hidden');
        return;
    }

    var html = '';
    superlatives.forEach(function(award, index) {
        var valueText = '';
        switch (award.value_label) {
            case 'avg_time':
                valueText = award.value + 's ' + utils.t('superlatives.avgTime');
                break;
            case 'streak':
                valueText = award.value + ' ' + utils.t('superlatives.streak');
                break;
            case 'bets':
                valueText = award.value + ' ' + utils.t('superlatives.bets');
                break;
            case 'points':
                valueText = award.value + ' ' + utils.t('superlatives.points');
                break;
            case 'close_guesses':
                valueText = award.value + ' ' + utils.t('superlatives.closeGuesses');
                break;
            default:
                valueText = award.value;
        }

        html += '<div class="superlative-card superlative-card--' + award.id + '" style="animation-delay: ' + (index * 0.2) + 's">' +
            '<div class="superlative-emoji">' + award.emoji + '</div>' +
            '<div class="superlative-title">' + utils.t('superlatives.' + award.title) + '</div>' +
            '<div class="superlative-player">' + escapeHtml(award.player_name) + '</div>' +
            '<div class="superlative-value">' + valueText + '</div>' +
        '</div>';
    });

    container.innerHTML = html;
    container.classList.remove('hidden');
}

// ============================================
// Highlights (Issue #75)
// ============================================

/**
 * Render game highlights reel (Issue #75)
 * @param {Array|null} highlights - Array of highlight objects from state
 */
function renderHighlights(highlights) {
    var container = document.getElementById('highlights-container');
    if (!container) return;

    if (!highlights || highlights.length === 0) {
        container.classList.add('hidden');
        return;
    }

    var listEl = document.getElementById('highlights-list');
    if (!listEl) return;

    var html = '';
    highlights.forEach(function(h, index) {
        var text = utils.t('highlights.' + h.description, h.description_params) || h.description;
        if (text === h.description && h.description_params) {
            text = utils.t('highlights.' + h.description) || h.description;
            Object.keys(h.description_params).forEach(function(key) {
                text = text.replace('{' + key + '}', escapeHtml(h.description_params[key]));
            });
        }

        html += '<div class="highlight-card" style="animation-delay: ' + (index * 0.5) + 's">' +
            '<div class="highlight-emoji">' + (h.emoji || '✨') + '</div>' +
            '<div class="highlight-content">' +
                '<div class="highlight-text">' + text + '</div>' +
                '<div class="highlight-round">' + utils.t('highlights.roundLabel', {round: h.round}) + '</div>' +
            '</div>' +
        '</div>';
    });

    listEl.innerHTML = html;
    container.classList.remove('hidden');
}

// ============================================
// Share Tab (Issue #120, #216)
// ============================================

/**
 * Render shareable result card (Issue #120, #216)
 * @param {Object|null} shareData - Share data from state with emoji_grids, playlist_name, total_rounds
 */
function renderShareTab(shareData) {
    var container = document.getElementById('share-container');
    if (!container) return;

    if (!shareData || !shareData.emoji_grids) {
        container.classList.add('hidden');
        return;
    }

    var myGrid = shareData.emoji_grids[state.playerName];
    if (!myGrid) {
        var keys = Object.keys(shareData.emoji_grids);
        if (keys.length === 1) {
            myGrid = shareData.emoji_grids[keys[0]];
        }
    }
    if (!myGrid) {
        container.classList.add('hidden');
        return;
    }

    var gridEl = document.getElementById('share-emoji-grid');
    if (gridEl) {
        var lines = myGrid.split('\n').map(function(line) {
            return '<div class="emoji-grid-line">' + utils.escapeHtml(line) + '</div>';
        }).join('');
        gridEl.innerHTML = lines;
        gridEl.dataset.rawText = myGrid;
    }

    var copyBtn = document.getElementById('share-copy-btn');
    if (copyBtn) {
        copyBtn.onclick = function() {
            navigator.clipboard.writeText(myGrid).then(function() {
                var toast = document.getElementById('share-toast');
                if (toast) {
                    toast.classList.remove('hidden');
                    setTimeout(function() { toast.classList.add('hidden'); }, 2000);
                }
            });
        };
    }

    var saveBtn = document.getElementById('share-save-btn');
    if (saveBtn) {
        saveBtn.onclick = function() {
            generateVisualCard(myGrid, shareData.playlist_name, shareData);
        };
    }

    container.classList.remove('hidden');
}

/**
 * Generate visual card via Canvas API and download as PNG (Issue #120, #216)
 * @param {string} emojiGrid - The emoji grid text
 * @param {string} playlistName - Name of the playlist
 * @param {Object} shareData - Optional share data with additional info
 */
function generateVisualCard(emojiGrid, playlistName, shareData) {
    var canvas = document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 800;
    var ctx = canvas.getContext('2d');

    var bgGrad = ctx.createLinearGradient(0, 0, 0, 800);
    bgGrad.addColorStop(0, '#0f0c29');
    bgGrad.addColorStop(0.5, '#302b63');
    bgGrad.addColorStop(1, '#24243e');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, 800, 800);

    var accentGrad = ctx.createLinearGradient(0, 0, 800, 0);
    accentGrad.addColorStop(0, '#e94560');
    accentGrad.addColorStop(1, '#0f3460');
    ctx.fillStyle = accentGrad;
    ctx.fillRect(0, 0, 800, 4);

    var logoImg = new Image();
    logoImg.src = '/beatify/static/img/icon-256.png';
    logoImg.onerror = function() { drawCardContent(null); };
    logoImg.onload = function() { drawCardContent(logoImg); };

    function drawCardContent(logo) {
        // ── Header ──────────────────────────────────────────────
        if (logo) {
            ctx.drawImage(logo, 28, 20, 64, 64);
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 28px system-ui, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText('Beatify', 104, 60);
        } else {
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 28px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('🎵 Beatify', 400, 55);
        }

        // Playlist chip
        ctx.textAlign = 'center';
        var playlist = (playlistName || '').toUpperCase();
        ctx.font = 'bold 13px system-ui, sans-serif';
        var chipW = ctx.measureText(playlist).width + 32;
        var chipX = 400 - chipW / 2;
        ctx.fillStyle = 'rgba(233,69,96,0.18)';
        ctx.beginPath();
        ctx.roundRect(chipX, 96, chipW, 30, 15);
        ctx.fill();
        ctx.strokeStyle = '#e94560';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.fillStyle = '#e94560';
        ctx.fillText(playlist, 400, 116);

        // ── Parse emojiGrid ──────────────────────────────────────
        var lines = emojiGrid.split('\n').filter(function(l) { return l.trim() !== ''; });
        var playerLine = '', emojiRows = [], statsLines = [];
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (line.match(/[🟣🟢🟡🔴⬜🟠]/)) {
                emojiRows.push(line);
            } else if (line.match(/👑/)) {
                playerLine = line;
            } else if (line.match(/correct|streak|exact|bet/i)) {
                statsLines.push(line);
            }
        }

        // ── Player name ──────────────────────────────────────────
        if (playerLine) {
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 26px system-ui, sans-serif';
            ctx.fillText(playerLine, 400, 180);
        }

        // ── Emoji grid with bordered box ─────────────────────────
        var emojiBoxY = 210;
        var emojiBoxH = Math.max(80, emojiRows.length * 48 + 32);
        ctx.fillStyle = 'rgba(255,255,255,0.05)';
        ctx.beginPath();
        ctx.roundRect(80, emojiBoxY, 640, emojiBoxH, 16);
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.12)';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.font = '38px system-ui, sans-serif';
        ctx.fillStyle = '#ffffff';
        var emojiStartY = emojiBoxY + 24 + (emojiRows.length === 1 ? 10 : 0);
        emojiRows.forEach(function(row, idx) {
            ctx.fillText(row, 400, emojiStartY + idx * 48);
        });

        // ── Stats 3-column grid ──────────────────────────────────
        var statsY = emojiBoxY + emojiBoxH + 32;
        if (statsLines.length > 0) {
            var statParsed = [];
            statsLines.forEach(function(s) {
                var m = s.match(/(\d+)\s*[\/\|]\s*(\d+)/);
                if (m) {
                    statParsed.push({ val: m[1] + '/' + m[2], label: s.replace(/[\d\/\|🔥✅🎯💰]/g, '').trim().slice(0, 12) });
                } else {
                    var num = s.match(/\d+/);
                    statParsed.push({ val: num ? num[0] : '—', label: s.replace(/[\d🔥✅🎯💰]/g, '').trim().slice(0, 12) });
                }
            });
            var cols = Math.min(statParsed.length, 3);
            var colW = 200;
            var startX = 400 - ((cols - 1) * colW) / 2;
            statParsed.slice(0, cols).forEach(function(stat, idx) {
                var cx = startX + idx * colW;
                // Value
                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 32px system-ui, sans-serif';
                ctx.fillText(stat.val, cx, statsY + 36);
                // Label
                ctx.fillStyle = '#8888aa';
                ctx.font = '13px system-ui, sans-serif';
                ctx.fillText(stat.label, cx, statsY + 58);
            });
        }

        // ── Divider ──────────────────────────────────────────────
        var divY = 720;
        var divGrad = ctx.createLinearGradient(80, 0, 720, 0);
        divGrad.addColorStop(0, 'rgba(233,69,96,0)');
        divGrad.addColorStop(0.5, 'rgba(233,69,96,0.5)');
        divGrad.addColorStop(1, 'rgba(233,69,96,0)');
        ctx.strokeStyle = divGrad;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(80, divY);
        ctx.lineTo(720, divY);
        ctx.stroke();

        // ── Footer: URL + Tagline ────────────────────────────────
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 15px system-ui, sans-serif';
        ctx.fillText('beatify.fun', 400, 748);
        ctx.fillStyle = '#8888aa';
        ctx.font = '13px system-ui, sans-serif';
        ctx.fillText('The music quiz for your living room.', 400, 768);

    canvas.toBlob(function(blob) {
        if (navigator.share && navigator.canShare) {
            var file = new File([blob], 'beatify-results.png', { type: 'image/png' });
            var nativeShareData = { files: [file], title: 'My Beatify Results' };
            if (navigator.canShare(nativeShareData)) {
                navigator.share(nativeShareData).catch(function() {
                    downloadBlob(blob);
                });
                return;
            }
        }
        downloadBlob(blob);
    }, 'image/png');
    } // end drawCardContent
}

/**
 * Helper to download a blob as a file
 */
function downloadBlob(blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'beatify-results.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ============================================
// Paused View (Story 7-1)
// ============================================

/**
 * Update paused view based on pause reason
 * @param {Object} data - State data with pause_reason
 */
export function updatePausedView(data) {
    var messageEl = document.getElementById('pause-message');
    if (messageEl) {
        if (data.pause_reason === 'admin_disconnected') {
            messageEl.textContent = utils.t('player.waitingForHostReconnect');
        } else if (data.pause_reason === 'media_player_error') {
            messageEl.textContent = utils.t('player.speakerUnavailable');
        } else {
            messageEl.textContent = utils.t('player.gamePaused');
        }
    }
}

// ============================================
// New Game (Story 6.6)
// ============================================

/**
 * Handle new game button click (Story 6.6)
 */
export async function handleNewGame() {
    var confirmed = await showConfirmModal(
        utils.t('admin.newGameTitle') || 'New Game?',
        utils.t('admin.newGameConfirm') || 'Start a new game?',
        utils.t('admin.newGame') || 'New Game',
        utils.t('common.cancel')
    );
    if (!confirmed) {
        return;
    }

    var btn = document.getElementById('new-game-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = utils.t('player.redirecting');
    }

    try {
        sessionStorage.removeItem('beatify_admin_name');
        sessionStorage.removeItem('beatify_is_admin');
    } catch (e) {
        // Ignore storage errors
    }

    window.location.href = '/beatify/admin';
}
