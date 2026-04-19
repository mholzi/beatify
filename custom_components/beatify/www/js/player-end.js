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

    // Update podium (positions 1, 2, 3). Hide slots that have no player so
    // single- and two-player games don't show empty "---" placeholders.
    [1, 2, 3].forEach(function(place) {
        var player = leaderboard.find(function(p) { return p.rank === place; });
        var slotEl = document.querySelector('.podium-place.podium-' + place);
        if (slotEl) slotEl.classList.toggle('hidden', !player);
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

                // Issue #535: Prefer WebSocket for rematch (avoids admin token issue)
                if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                    state.ws.send(JSON.stringify({ type: 'admin', action: 'rematch_game' }));
                    return;
                }

                fetch('/beatify/api/rematch-game', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' }
                })
                    .then(function(resp) {
                        if (!resp.ok) return resp.json().then(function(e) { throw new Error(e.message || 'Rematch failed'); });
                        // Server will broadcast rematch_started to all clients (including admin).
                        // The rematch_started handler in player-core.js reconnects everyone via
                        // the existing WS — calling connectWithSession() here would race and
                        // cause a SESSION_TAKEOVER that corrupts state (admin loses isAdmin flag,
                        // connection-lost view flashes, End Game button becomes unresponsive).
                        rematchBtn.textContent = '⏳'; // keep spinner until rematch_started arrives
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
 * Generate visual card via Canvas API and download as PNG.
 * Vinyl-record design (DESIGN.md share-card Variant D): music-first identity
 * with the score on a pink→cyan gradient label inside a black vinyl disc.
 * Aligns with the brand palette — no more off-brand purple.
 *
 * @param {string} emojiGrid - The emoji grid text (source of truth for stats)
 * @param {string} playlistName - Name of the playlist
 * @param {Object} shareData - Optional share data with additional info
 */
function generateVisualCard(emojiGrid, playlistName, shareData) {
    var W = 800, H = 800;
    var canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    var ctx = canvas.getContext('2d');

    // ── Parse emojiGrid to extract stats, player name, and score ──
    var lines = emojiGrid.split('\n').filter(function(l) { return l.trim() !== ''; });
    var playerLine = '';
    var statsCorrect = '', statsStreak = '', statsExact = '', statsBets = '';
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        if (line.match(/👑/)) {
            playerLine = line;
        } else if (line.match(/correct/i)) {
            var correctMatch = line.match(/(\d+\/\d+)\s*correct/i);
            var streakMatch = line.match(/Streak:\s*(\d+)/i);
            if (correctMatch) statsCorrect = correctMatch[1];
            if (streakMatch) statsStreak = streakMatch[1];
        } else if (line.match(/exact/i)) {
            var exactMatch = line.match(/(\d+)\s*Exact/i);
            var betsMatch = line.match(/(\d+\/\d+)\s*Bets/i);
            if (exactMatch) statsExact = exactMatch[1];
            if (betsMatch) statsBets = betsMatch[1];
        }
    }

    // playerLine is "👑 jkjk: 10pts" (or without crown for non-winners)
    var playerName = '';
    var score = '0';
    var isWinner = false;
    if (playerLine) {
        isWinner = playerLine.indexOf('👑') !== -1;
        var m = playerLine.match(/(?:👑\s*)?([^:]+?):\s*(\d+)\s*pts?/i);
        if (m) {
            playerName = m[1].trim();
            score = m[2];
        }
    }
    if (!playerName) playerName = 'Beatify Player';

    // Wait for web fonts (Outfit + Inter) so the drawn text matches DESIGN.md
    var ready = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
    ready.then(drawCard);

    function drawCard() {
        // ── Background: navy with pink (top-left) + cyan (bottom-right) radial glows ──
        ctx.fillStyle = '#0a0a12';
        ctx.fillRect(0, 0, W, H);

        var pinkGlow = ctx.createRadialGradient(W * 0.3, H * 0.3, 0, W * 0.3, H * 0.3, W * 0.6);
        pinkGlow.addColorStop(0, 'rgba(255, 45, 106, 0.22)');
        pinkGlow.addColorStop(1, 'rgba(255, 45, 106, 0)');
        ctx.fillStyle = pinkGlow;
        ctx.fillRect(0, 0, W, H);

        var cyanGlow = ctx.createRadialGradient(W * 0.75, H * 0.75, 0, W * 0.75, H * 0.75, W * 0.55);
        cyanGlow.addColorStop(0, 'rgba(0, 245, 255, 0.14)');
        cyanGlow.addColorStop(1, 'rgba(0, 245, 255, 0)');
        ctx.fillStyle = cyanGlow;
        ctx.fillRect(0, 0, W, H);

        // ── Top row: Beatify wordmark (left) + optional Winner badge (right) ──
        var padX = 48;
        var topY = 68;

        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        ctx.font = '900 36px Outfit, system-ui, sans-serif';

        ctx.fillStyle = '#ffffff';
        ctx.fillText('Beat', padX, topY);
        var beatWidth = ctx.measureText('Beat').width;

        var ifyX = padX + beatWidth;
        var ifyWidth = ctx.measureText('ify').width;
        var ifyGrad = ctx.createLinearGradient(ifyX, 0, ifyX + ifyWidth, 0);
        ifyGrad.addColorStop(0, '#ff2d6a');
        ifyGrad.addColorStop(1, '#00f5ff');
        ctx.fillStyle = ifyGrad;
        ctx.fillText('ify', ifyX, topY);

        if (isWinner) {
            var badgeText = '🏆 WINNER';
            ctx.font = '800 13px Inter, system-ui, sans-serif';
            var bTextW = ctx.measureText(badgeText).width;
            var bW = bTextW + 28;
            var bH = 30;
            var bX = W - padX - bW;
            var bY = topY - bH / 2;

            var badgeGrad = ctx.createLinearGradient(bX, bY, bX + bW, bY);
            badgeGrad.addColorStop(0, '#ff2d6a');
            badgeGrad.addColorStop(1, '#7a1438');
            ctx.fillStyle = badgeGrad;
            ctx.beginPath();
            if (ctx.roundRect) {
                ctx.roundRect(bX, bY, bW, bH, 8);
            } else {
                ctx.rect(bX, bY, bW, bH);
            }
            ctx.fill();

            ctx.textAlign = 'center';
            ctx.fillStyle = '#ffffff';
            ctx.fillText(badgeText, bX + bW / 2, topY);
        }

        // ── Vinyl record: centerpiece ──
        var vinylCX = W / 2;
        var vinylCY = 380;
        var outerR = 180;
        var labelR = 72;

        // Drop shadow beneath vinyl
        ctx.save();
        ctx.shadowColor = 'rgba(0, 0, 0, 0.55)';
        ctx.shadowBlur = 36;
        ctx.shadowOffsetY = 10;
        ctx.fillStyle = '#0a0a12';
        ctx.beginPath();
        ctx.arc(vinylCX, vinylCY, outerR, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        // Vinyl base — subtle radial gradient from label-edge to outer edge
        var vinylGrad = ctx.createRadialGradient(vinylCX, vinylCY, labelR, vinylCX, vinylCY, outerR);
        vinylGrad.addColorStop(0, '#18181f');
        vinylGrad.addColorStop(0.35, '#13131c');
        vinylGrad.addColorStop(1, '#06060b');
        ctx.fillStyle = vinylGrad;
        ctx.beginPath();
        ctx.arc(vinylCX, vinylCY, outerR, 0, Math.PI * 2);
        ctx.fill();

        // Grooves — faint concentric rings every 5px
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
        ctx.lineWidth = 1;
        for (var r = labelR + 6; r < outerR - 2; r += 5) {
            ctx.beginPath();
            ctx.arc(vinylCX, vinylCY, r, 0, Math.PI * 2);
            ctx.stroke();
        }

        // Specular highlight (top-left glint) for the sheen
        var gloss = ctx.createRadialGradient(vinylCX - 50, vinylCY - 50, 0, vinylCX, vinylCY, outerR);
        gloss.addColorStop(0, 'rgba(255, 255, 255, 0.055)');
        gloss.addColorStop(0.45, 'rgba(255, 255, 255, 0)');
        ctx.fillStyle = gloss;
        ctx.beginPath();
        ctx.arc(vinylCX, vinylCY, outerR, 0, Math.PI * 2);
        ctx.fill();

        // Label — pink→cyan gradient with glow
        var labelGrad = ctx.createLinearGradient(
            vinylCX - labelR, vinylCY - labelR,
            vinylCX + labelR, vinylCY + labelR
        );
        labelGrad.addColorStop(0, '#ff2d6a');
        labelGrad.addColorStop(1, '#00f5ff');

        ctx.save();
        ctx.shadowColor = 'rgba(255, 45, 106, 0.5)';
        ctx.shadowBlur = 24;
        ctx.fillStyle = labelGrad;
        ctx.beginPath();
        ctx.arc(vinylCX, vinylCY, labelR, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        // Score on the label — big "10" + small "PTS"
        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = '900 48px Outfit, system-ui, sans-serif';
        ctx.fillText(score, vinylCX, vinylCY - 10);
        ctx.font = '800 14px Inter, system-ui, sans-serif';
        ctx.fillText('PTS', vinylCX, vinylCY + 26);

        // Spindle hole (tiny center dot)
        ctx.fillStyle = '#0a0a12';
        ctx.beginPath();
        ctx.arc(vinylCX, vinylCY, 6, 0, Math.PI * 2);
        ctx.fill();

        // ── Player name + correct count ──
        var nameLineY = 620;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#ffffff';
        ctx.font = '800 32px Outfit, system-ui, sans-serif';
        var nameText = playerName;
        if (statsCorrect) nameText += '  ·  ' + statsCorrect;
        ctx.fillText(nameText, vinylCX, nameLineY);

        // ── Playlist in italic ──
        ctx.font = 'italic 16px Inter, system-ui, sans-serif';
        ctx.fillStyle = '#b3b3c2';
        ctx.fillText('"' + (playlistName || 'Beatify') + '"', vinylCX, nameLineY + 32);

        // ── Stats footer: "N exact · 🔥N streak · beatify.fun" with number highlights ──
        var footerY = 720;
        var parts = [];
        if (statsExact && statsExact !== '0') {
            parts.push({ type: 'stat', num: statsExact, label: ' exact' });
        }
        if (statsStreak && statsStreak !== '0') {
            parts.push({ type: 'stat', num: '🔥' + statsStreak, label: ' streak' });
        }
        parts.push({ type: 'url', text: 'beatify.fun' });

        // Measure entire row so we can center it as a unit
        ctx.font = '600 15px Inter, system-ui, sans-serif';
        var sepW = ctx.measureText(' · ').width;
        var totalW = 0;
        parts.forEach(function(p, idx) {
            if (idx > 0) totalW += sepW;
            if (p.type === 'url') {
                ctx.font = '800 15px Outfit, system-ui, sans-serif';
                totalW += ctx.measureText(p.text).width;
            } else {
                ctx.font = '900 18px Outfit, system-ui, sans-serif';
                totalW += ctx.measureText(p.num).width;
                ctx.font = '600 15px Inter, system-ui, sans-serif';
                totalW += ctx.measureText(p.label).width;
            }
        });

        var curX = vinylCX - totalW / 2;
        ctx.textAlign = 'left';
        parts.forEach(function(p, idx) {
            if (idx > 0) {
                ctx.font = '600 15px Inter, system-ui, sans-serif';
                ctx.fillStyle = '#6b6b7a';
                ctx.fillText(' · ', curX, footerY);
                curX += sepW;
            }
            if (p.type === 'url') {
                ctx.font = '800 15px Outfit, system-ui, sans-serif';
                ctx.fillStyle = '#00f5ff';
                ctx.fillText(p.text, curX, footerY);
                curX += ctx.measureText(p.text).width;
            } else {
                ctx.font = '900 18px Outfit, system-ui, sans-serif';
                ctx.fillStyle = '#00f5ff';
                ctx.fillText(p.num, curX, footerY);
                curX += ctx.measureText(p.num).width;
                ctx.font = '600 15px Inter, system-ui, sans-serif';
                ctx.fillStyle = '#b3b3c2';
                ctx.fillText(p.label, curX, footerY);
                curX += ctx.measureText(p.label).width;
            }
        });

        // ── Export: native share → download fallback ──
        canvas.toBlob(function(blob) {
            if (!blob) return;
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
    }
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
