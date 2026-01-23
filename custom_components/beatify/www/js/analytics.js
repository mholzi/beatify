/**
 * Analytics Dashboard JavaScript (Story 19.2)
 *
 * Fetches analytics data from API and renders stat cards
 * with trend indicators and period filtering.
 */
(function() {
    'use strict';

    var API_URL = '/beatify/api/analytics';
    var SONG_STATS_API_URL = '/beatify/api/analytics/songs';
    var currentPeriod = '30d';
    var retryCount = 0;
    var maxRetries = 3;

    // Song statistics state (Story 19.7)
    var songStatsData = null;
    var modalPlaylistData = null;
    var modalCurrentPage = 1;
    var modalPageSize = 20;
    var modalSortField = 'play_count';
    var modalSortDir = 'desc';
    var modalSearchQuery = '';

    /**
     * Load analytics data from API
     * @param {string} period - Time period (7d, 30d, 90d, all)
     */
    async function loadAnalytics(period) {
        showLoading(true);
        hideError();

        try {
            var response = await fetch(API_URL + '?period=' + encodeURIComponent(period));
            if (!response.ok) {
                throw new Error('API returned ' + response.status);
            }
            var data = await response.json();
            renderStats(data);
            updateLastUpdated(data.generated_at);
            retryCount = 0;
            showLoading(false);
        } catch (err) {
            console.error('Analytics API error:', err);
            showLoading(false);

            if (retryCount < maxRetries) {
                retryCount++;
                setTimeout(function() {
                    loadAnalytics(period);
                }, 1000 * retryCount);
            } else {
                showError();
            }
        }
    }

    /**
     * Render stat cards with data
     * @param {Object} data - Analytics data from API
     */
    function renderStats(data) {
        updateStatCard('stat-total-games', data.total_games, data.trends.games);
        updateStatCard('stat-avg-players', data.avg_players_per_game.toFixed(1), data.trends.players);
        updateStatCard('stat-avg-score', data.avg_score.toFixed(1), data.trends.score);

        // Format error rate as percentage
        var errorPct = (data.error_rate * 100).toFixed(1) + '%';
        // For error rate, negative trend (fewer errors) is good
        updateStatCard('stat-error-rate', errorPct, data.trends.errors, true);

        // Render additional sections (Stories 19.4, 19.5, 19.6)
        if (data.playlists) {
            renderPlaylists(data.playlists);
        }
        if (data.chart_data) {
            renderChart(data.chart_data);
        }
        if (data.error_stats) {
            renderErrorStats(data.error_stats);
        }
    }

    /**
     * Render playlist section (Story 19.4)
     * @param {Array} playlists - Playlist stats array
     */
    function renderPlaylists(playlists) {
        var listEl = document.getElementById('playlist-list');
        var emptyEl = document.getElementById('playlist-empty');

        if (!playlists || playlists.length === 0) {
            listEl.innerHTML = '';
            emptyEl.classList.remove('hidden');
            return;
        }

        emptyEl.classList.add('hidden');
        var maxCount = playlists[0].play_count;

        listEl.innerHTML = playlists.map(function(p) {
            var barWidth = (p.play_count / maxCount * 100).toFixed(1);
            return '<div class="playlist-row">' +
                '<div class="playlist-info">' +
                    '<span class="playlist-name">' + escapeHtml(p.name) + '</span>' +
                    '<span class="playlist-stats">' + p.play_count + ' games (' + p.percentage + '%)</span>' +
                '</div>' +
                '<div class="playlist-bar-container">' +
                    '<div class="playlist-bar" style="width: ' + barWidth + '%;"></div>' +
                '</div>' +
            '</div>';
        }).join('');
    }

    /**
     * Render games chart (Story 19.5)
     * @param {Object} chartData - Chart data with labels and values
     */
    function renderChart(chartData) {
        var canvas = document.getElementById('games-chart');
        if (!canvas || !canvas.getContext) return;

        var ctx = canvas.getContext('2d');
        var container = canvas.parentElement;

        // Responsive canvas sizing
        canvas.width = container.offsetWidth;
        canvas.height = 300;

        var labels = chartData.labels || [];
        var values = chartData.values || [];

        if (labels.length === 0) {
            ctx.fillStyle = '#888';
            ctx.font = '14px system-ui';
            ctx.textAlign = 'center';
            ctx.fillText('No data available', canvas.width / 2, canvas.height / 2);
            return;
        }

        var maxValue = Math.max.apply(null, values.concat([1]));
        var padding = {top: 20, right: 20, bottom: 40, left: 50};
        var chartWidth = canvas.width - padding.left - padding.right;
        var chartHeight = canvas.height - padding.top - padding.bottom;
        var barWidth = chartWidth / labels.length * 0.7;
        var barGap = chartWidth / labels.length * 0.3;

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw gridlines
        ctx.strokeStyle = '#333';
        ctx.lineWidth = 1;
        for (var i = 0; i <= 5; i++) {
            var y = padding.top + (chartHeight / 5) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(canvas.width - padding.right, y);
            ctx.stroke();
        }

        // Draw bars with neon gradient
        var gradient = ctx.createLinearGradient(0, chartHeight, 0, 0);
        gradient.addColorStop(0, '#9d4edd');
        gradient.addColorStop(1, '#00f5ff');

        values.forEach(function(value, idx) {
            var barHeight = (value / maxValue) * chartHeight;
            var x = padding.left + idx * (barWidth + barGap) + barGap / 2;
            var y = padding.top + chartHeight - barHeight;

            ctx.fillStyle = gradient;
            ctx.shadowColor = '#00f5ff';
            ctx.shadowBlur = 10;
            ctx.fillRect(x, y, barWidth, barHeight);
            ctx.shadowBlur = 0;
        });

        // Draw x-axis labels
        ctx.fillStyle = '#888';
        ctx.font = '12px system-ui';
        ctx.textAlign = 'center';
        labels.forEach(function(label, idx) {
            var x = padding.left + idx * (barWidth + barGap) + barGap / 2 + barWidth / 2;
            ctx.fillText(label, x, canvas.height - 10);
        });

        // Draw y-axis labels
        ctx.textAlign = 'right';
        for (var j = 0; j <= 5; j++) {
            var yPos = padding.top + (chartHeight / 5) * j;
            var val = Math.round(maxValue - (maxValue / 5) * j);
            ctx.fillText(val, padding.left - 10, yPos + 4);
        }

        // Update accessible data table
        updateChartDataTable(labels, values);

        // Store for resize handling
        window.currentChartData = chartData;
    }

    /**
     * Update accessible data table for chart
     */
    function updateChartDataTable(labels, values) {
        var tbody = document.querySelector('#games-chart-data tbody');
        if (!tbody) return;
        tbody.innerHTML = labels.map(function(label, i) {
            return '<tr><td>' + label + '</td><td>' + values[i] + '</td></tr>';
        }).join('');
    }

    /**
     * Render error stats panel (Story 19.6)
     * @param {Object} errorStats - Error statistics
     */
    function renderErrorStats(errorStats) {
        var rateEl = document.getElementById('error-rate-value');
        var badgeEl = document.getElementById('health-badge');
        var expandBtn = document.getElementById('error-expand-btn');
        var listContainer = document.getElementById('error-list-container');
        var listEl = document.getElementById('error-list');
        var noErrorsMsg = document.getElementById('no-errors-msg');

        // Display error rate
        var ratePercent = (errorStats.error_rate * 100).toFixed(1) + '%';
        if (rateEl) rateEl.textContent = ratePercent;

        // Update health badge
        if (badgeEl) {
            badgeEl.className = 'health-badge ' + errorStats.status;
            var badgeText = {
                healthy: 'Healthy',
                warning: 'Warning',
                critical: 'Critical'
            };
            var badgeIcon = {
                healthy: '✓',
                warning: '⚠',
                critical: '✕'
            };
            var textEl = badgeEl.querySelector('.badge-text');
            var iconEl = badgeEl.querySelector('.badge-icon');
            if (textEl) textEl.textContent = badgeText[errorStats.status] || 'Healthy';
            if (iconEl) iconEl.textContent = badgeIcon[errorStats.status] || '✓';
        }

        // Handle error list
        if (errorStats.recent_errors && errorStats.recent_errors.length > 0) {
            if (noErrorsMsg) noErrorsMsg.classList.add('hidden');
            if (expandBtn) expandBtn.classList.remove('hidden');

            if (listEl) {
                listEl.innerHTML = errorStats.recent_errors.map(function(err) {
                    var timeAgo = formatRelativeTime(err.timestamp);
                    var icon = getErrorTypeIcon(err.type);
                    return '<li class="error-item">' +
                        '<span class="error-icon">' + icon + '</span>' +
                        '<div class="error-content">' +
                            '<span class="error-type">' + escapeHtml(err.type) + '</span>' +
                            '<span class="error-message">' + escapeHtml(err.message) + '</span>' +
                            '<span class="error-time">' + timeAgo + '</span>' +
                        '</div>' +
                    '</li>';
                }).join('');
            }
        } else {
            if (expandBtn) expandBtn.classList.add('hidden');
            if (listContainer) listContainer.classList.add('hidden');
            if (noErrorsMsg) noErrorsMsg.classList.remove('hidden');
        }
    }

    /**
     * Get icon for error type
     */
    function getErrorTypeIcon(type) {
        var icons = {
            'WEBSOCKET_DISCONNECT': '🔌',
            'MEDIA_PLAYER_ERROR': '🔇',
            'PLAYBACK_FAILURE': '⏸',
            'STATE_TRANSITION_ERROR': '⚙️'
        };
        return icons[type] || '❌';
    }

    // =====================================================
    // Song Statistics Functions (Story 19.7)
    // =====================================================

    /**
     * Load song statistics from API
     */
    async function loadSongStats() {
        try {
            var response = await fetch(SONG_STATS_API_URL);
            if (!response.ok) {
                throw new Error('Song stats API returned ' + response.status);
            }
            songStatsData = await response.json();
            renderSongStats(songStatsData);
        } catch (err) {
            console.error('Song stats API error:', err);
            showSongStatsEmpty();
        }
    }

    /**
     * Render song statistics (AC1, AC2)
     * @param {Object} data - Song stats from API
     */
    function renderSongStats(data) {
        var emptyEl = document.getElementById('song-stats-empty');
        var summaryEl = document.getElementById('song-summary-cards');
        var playlistEl = document.getElementById('playlist-song-stats');

        // Check if we have any data
        if (!data || (!data.most_played && !data.by_playlist.length)) {
            showSongStatsEmpty();
            return;
        }

        if (emptyEl) emptyEl.classList.add('hidden');
        if (summaryEl) summaryEl.classList.remove('hidden');

        // Render summary cards (AC1)
        renderSongSummaryCard('song-most-played', data.most_played, 'play_count');
        renderSongSummaryCard('song-hardest', data.hardest, 'accuracy');
        renderSongSummaryCard('song-easiest', data.easiest, 'accuracy');

        // Render playlist grid (AC2)
        renderPlaylistSongGrid(data.by_playlist);
    }

    /**
     * Render a single song summary card (AC1)
     * @param {string} cardId - Card element ID
     * @param {Object} song - Song data
     * @param {string} statType - Type of stat to display
     */
    function renderSongSummaryCard(cardId, song, statType) {
        var card = document.getElementById(cardId);
        if (!card) return;

        var titleEl = card.querySelector('.song-card-title');
        var artistEl = card.querySelector('.song-card-artist');
        var statEl = card.querySelector('.stat-number');

        if (!song) {
            if (titleEl) titleEl.textContent = '--';
            if (artistEl) artistEl.textContent = '--';
            if (statEl) statEl.textContent = '--';
            card.disabled = true;
            card.dataset.playlist = '';
            return;
        }

        card.disabled = false;
        card.dataset.playlist = song.playlist || '';
        card.dataset.songTitle = song.title || '';

        if (titleEl) titleEl.textContent = song.title || 'Unknown';
        if (artistEl) artistEl.textContent = song.artist || 'Unknown';

        if (statEl) {
            if (statType === 'play_count') {
                statEl.textContent = song.play_count || 0;
            } else if (statType === 'accuracy') {
                var accuracy = ((song.accuracy || 0) * 100).toFixed(0);
                statEl.textContent = accuracy + '%';

                // Apply color class (AC6)
                statEl.classList.remove('accuracy-high', 'accuracy-mid', 'accuracy-low');
                if (accuracy >= 70) statEl.classList.add('accuracy-high');
                else if (accuracy >= 40) statEl.classList.add('accuracy-mid');
                else statEl.classList.add('accuracy-low');
            }
        }
    }

    /**
     * Render playlist song statistics grid (AC2)
     * @param {Array} playlists - Playlist data array
     */
    function renderPlaylistSongGrid(playlists) {
        var container = document.getElementById('playlist-song-stats');
        if (!container) return;

        if (!playlists || playlists.length === 0) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = playlists.map(function(p) {
            var avgAccuracy = ((p.avg_accuracy || 0) * 100).toFixed(0);
            var accuracyClass = getAccuracyClass(avgAccuracy);

            return '<div class="playlist-song-card" data-playlist-id="' + escapeHtml(p.playlist_id) + '">' +
                '<div class="playlist-song-header">' +
                    '<h3 class="playlist-song-name">' + escapeHtml(p.playlist_name) + '</h3>' +
                    '<div class="playlist-song-summary">' +
                        '<span class="summary-stat">' +
                            '<span class="summary-value">' + p.unique_songs_played + '</span>' +
                            '<span class="summary-label" data-i18n="analyticsDashboard.songsPlayed">songs played</span>' +
                        '</span>' +
                        '<span class="summary-stat">' +
                            '<span class="summary-value ' + accuracyClass + '">' + avgAccuracy + '%</span>' +
                            '<span class="summary-label" data-i18n="analyticsDashboard.avgAccuracy">avg accuracy</span>' +
                        '</span>' +
                    '</div>' +
                '</div>' +
                '<button type="button" class="view-details-btn" data-playlist-id="' + escapeHtml(p.playlist_id) + '" ' +
                    'aria-label="View details for ' + escapeHtml(p.playlist_name) + '">' +
                    '<span data-i18n="analyticsDashboard.viewDetails">View Details</span>' +
                '</button>' +
            '</div>';
        }).join('');

        // Apply translations if available
        if (window.applyTranslations) {
            window.applyTranslations();
        }
    }

    /**
     * Show song stats empty state (AC7)
     */
    function showSongStatsEmpty() {
        var emptyEl = document.getElementById('song-stats-empty');
        var summaryEl = document.getElementById('song-summary-cards');
        var playlistEl = document.getElementById('playlist-song-stats');

        if (emptyEl) emptyEl.classList.remove('hidden');
        if (summaryEl) summaryEl.classList.add('hidden');
        if (playlistEl) playlistEl.innerHTML = '';
    }

    /**
     * Get CSS class for accuracy value (AC6)
     * @param {number} accuracy - Accuracy percentage
     * @returns {string} CSS class name
     */
    function getAccuracyClass(accuracy) {
        if (accuracy >= 70) return 'accuracy-high';
        if (accuracy >= 40) return 'accuracy-mid';
        return 'accuracy-low';
    }

    /**
     * Open playlist modal (AC4)
     * @param {string} playlistId - Playlist ID to display
     */
    function openPlaylistModal(playlistId) {
        if (!songStatsData || !songStatsData.by_playlist) return;

        var playlist = songStatsData.by_playlist.find(function(p) {
            return p.playlist_id === playlistId;
        });

        if (!playlist) return;

        modalPlaylistData = playlist;
        modalCurrentPage = 1;
        modalSearchQuery = '';
        modalSortField = 'play_count';
        modalSortDir = 'desc';

        var modal = document.getElementById('playlist-modal');
        var titleEl = document.getElementById('modal-title');
        var searchEl = document.getElementById('modal-search');
        var sortEl = document.getElementById('modal-sort-select');

        if (titleEl) titleEl.textContent = playlist.playlist_name;
        if (searchEl) searchEl.value = '';
        if (sortEl) sortEl.value = 'play_count';

        renderModalTable();

        if (modal && modal.showModal) {
            modal.showModal();
            // Focus trap (AC10)
            var firstFocusable = modal.querySelector('button, input, select');
            if (firstFocusable) firstFocusable.focus();
        }
    }

    /**
     * Close playlist modal
     */
    function closePlaylistModal() {
        var modal = document.getElementById('playlist-modal');
        if (modal && modal.close) {
            modal.close();
        }
        modalPlaylistData = null;
    }

    /**
     * Render modal table with current filters/sorting (AC4)
     */
    function renderModalTable() {
        if (!modalPlaylistData || !modalPlaylistData.songs) return;

        var songs = modalPlaylistData.songs.slice();

        // Apply search filter
        if (modalSearchQuery) {
            var query = modalSearchQuery.toLowerCase();
            songs = songs.filter(function(s) {
                return (s.title && s.title.toLowerCase().includes(query)) ||
                       (s.artist && s.artist.toLowerCase().includes(query));
            });
        }

        // Apply sorting
        songs.sort(function(a, b) {
            var aVal = a[modalSortField];
            var bVal = b[modalSortField];

            if (typeof aVal === 'string') {
                aVal = aVal.toLowerCase();
                bVal = (bVal || '').toLowerCase();
                return modalSortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
            }

            aVal = aVal || 0;
            bVal = bVal || 0;
            return modalSortDir === 'asc' ? aVal - bVal : bVal - aVal;
        });

        // Pagination
        var totalPages = Math.ceil(songs.length / modalPageSize) || 1;
        if (modalCurrentPage > totalPages) modalCurrentPage = totalPages;
        var startIdx = (modalCurrentPage - 1) * modalPageSize;
        var pageSongs = songs.slice(startIdx, startIdx + modalPageSize);

        // Render table body
        var tbody = document.getElementById('modal-song-tbody');
        if (tbody) {
            tbody.innerHTML = pageSongs.map(function(s) {
                var accuracy = ((s.accuracy || 0) * 100).toFixed(0);
                var accuracyClass = getAccuracyClass(accuracy);
                var playHeat = getPlayCountHeat(s.play_count);

                return '<tr>' +
                    '<td>' + escapeHtml(s.title || 'Unknown') + '</td>' +
                    '<td>' + escapeHtml(s.artist || 'Unknown') + '</td>' +
                    '<td>' + (s.year || '--') + '</td>' +
                    '<td><span class="' + playHeat + '">' + (s.play_count || 0) + '</span></td>' +
                    '<td><span class="' + accuracyClass + '">' + accuracy + '%</span></td>' +
                    '<td>' + (s.avg_year_diff || 0).toFixed(1) + '</td>' +
                '</tr>';
            }).join('');

            // Empty state for filtered results (AC7)
            if (pageSongs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">' +
                    '<span data-i18n="analyticsDashboard.noMatchingSongs">No matching songs found</span>' +
                '</td></tr>';
            }
        }

        // Update pagination
        updatePagination(songs.length, totalPages);
    }

    /**
     * Get CSS class for play count heat indicator (AC6)
     * @param {number} count - Play count
     * @returns {string} CSS class name
     */
    function getPlayCountHeat(count) {
        if (count >= 10) return 'heat-high';
        if (count >= 5) return 'heat-mid';
        return 'heat-low';
    }

    /**
     * Update pagination controls
     * @param {number} totalItems - Total items in filtered list
     * @param {number} totalPages - Total pages
     */
    function updatePagination(totalItems, totalPages) {
        var infoEl = document.getElementById('pagination-info');
        var prevBtn = document.getElementById('pagination-prev');
        var nextBtn = document.getElementById('pagination-next');

        if (infoEl) {
            infoEl.textContent = 'Page ' + modalCurrentPage + ' of ' + totalPages;
        }

        if (prevBtn) {
            prevBtn.disabled = modalCurrentPage <= 1;
        }

        if (nextBtn) {
            nextBtn.disabled = modalCurrentPage >= totalPages;
        }
    }

    /**
     * Handle modal search input
     * @param {Event} e - Input event
     */
    function handleModalSearch(e) {
        modalSearchQuery = e.target.value;
        modalCurrentPage = 1;
        renderModalTable();
    }

    /**
     * Handle modal sort change
     * @param {Event} e - Change event
     */
    function handleModalSort(e) {
        var newField = e.target.value;
        if (newField === modalSortField) {
            // Toggle direction
            modalSortDir = modalSortDir === 'asc' ? 'desc' : 'asc';
        } else {
            modalSortField = newField;
            // Default sort direction based on field type
            modalSortDir = (newField === 'title' || newField === 'artist') ? 'asc' : 'desc';
        }
        modalCurrentPage = 1;
        renderModalTable();
    }

    /**
     * Handle pagination button click
     * @param {number} direction - -1 for prev, 1 for next
     */
    function handlePagination(direction) {
        modalCurrentPage += direction;
        renderModalTable();
    }

    /**
     * Handle summary card click - scroll to song in playlist (AC1)
     * @param {Event} e - Click event
     */
    function handleSummaryCardClick(e) {
        var card = e.target.closest('.song-summary-card');
        if (!card || card.disabled) return;

        var playlistName = card.dataset.playlist;
        if (playlistName) {
            // Find and open the playlist
            var playlistId = playlistName.toLowerCase().replace(/ /g, '-');
            openPlaylistModal(playlistId);
        }
    }

    /**
     * Handle keyboard navigation in modal (AC10)
     * @param {KeyboardEvent} e - Keyboard event
     */
    function handleModalKeydown(e) {
        if (e.key === 'Escape') {
            closePlaylistModal();
        }
    }

    /**
     * Format timestamp as relative time
     */
    function formatRelativeTime(timestamp) {
        var now = Date.now() / 1000;
        var diff = now - timestamp;

        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
        if (diff < 86400) return Math.floor(diff / 3600) + ' hours ago';
        return Math.floor(diff / 86400) + ' days ago';
    }

    /**
     * Escape HTML special characters
     */
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /**
     * Update a single stat card
     * @param {string} id - Card element ID
     * @param {string|number} value - Display value
     * @param {number} trend - Trend percentage (-1 to 1)
     * @param {boolean} invertTrend - If true, negative is positive (for errors)
     */
    function updateStatCard(id, value, trend, invertTrend) {
        var card = document.getElementById(id);
        if (!card) return;

        card.classList.remove('loading');

        var valueEl = card.querySelector('.stat-value');
        var trendEl = card.querySelector('.stat-trend');

        if (valueEl) {
            valueEl.textContent = value;
        }

        if (trendEl) {
            if (trend === 0) {
                trendEl.textContent = '— 0%';
                trendEl.className = 'stat-trend neutral';
            } else {
                var isPositive = invertTrend ? trend < 0 : trend > 0;
                var arrow = trend > 0 ? '↑' : '↓';
                var pct = Math.abs(trend * 100).toFixed(0) + '%';
                trendEl.textContent = arrow + ' ' + pct;
                trendEl.className = 'stat-trend ' + (isPositive ? 'positive' : 'negative');
            }
        }
    }

    /**
     * Show/hide loading state
     * @param {boolean} show
     */
    function showLoading(show) {
        var loadingEl = document.getElementById('loading-state');
        var cardsEl = document.querySelector('.stat-cards');

        if (loadingEl) {
            loadingEl.classList.toggle('hidden', !show);
        }

        if (cardsEl) {
            cardsEl.classList.toggle('hidden', show);
        }

        // Add skeleton loading to cards
        document.querySelectorAll('.stat-card').forEach(function(card) {
            card.classList.toggle('loading', show);
        });
    }

    /**
     * Show error state
     */
    function showError() {
        var errorEl = document.getElementById('error-state');
        var cardsEl = document.querySelector('.stat-cards');

        if (errorEl) {
            errorEl.classList.remove('hidden');
        }

        if (cardsEl) {
            cardsEl.classList.add('hidden');
        }
    }

    /**
     * Hide error state
     */
    function hideError() {
        var errorEl = document.getElementById('error-state');
        if (errorEl) {
            errorEl.classList.add('hidden');
        }
    }

    /**
     * Update last updated timestamp
     * @param {number} timestamp - Unix timestamp
     */
    function updateLastUpdated(timestamp) {
        var el = document.getElementById('last-updated');
        if (!el) return;

        var date = new Date(timestamp * 1000);
        var timeStr = date.toLocaleTimeString(undefined, {
            hour: '2-digit',
            minute: '2-digit'
        });

        var t = window.t || function(key, fallback) { return fallback; };
        el.textContent = t('analyticsDashboard.lastUpdated', 'Updated') + ': ' + timeStr;
    }

    /**
     * Handle period button click
     * @param {Event} e
     */
    function handlePeriodClick(e) {
        var btn = e.target.closest('.period-btn');
        if (!btn) return;

        var period = btn.dataset.period;
        if (!period || period === currentPeriod) return;

        // Update active state
        document.querySelectorAll('.period-btn').forEach(function(b) {
            b.classList.remove('period-btn--active');
        });
        btn.classList.add('period-btn--active');

        currentPeriod = period;
        retryCount = 0;
        loadAnalytics(period);
    }

    /**
     * Handle refresh button click
     */
    function handleRefreshClick() {
        retryCount = 0;
        loadAnalytics(currentPeriod);
    }

    /**
     * Handle retry button click
     */
    function handleRetryClick() {
        retryCount = 0;
        hideError();
        loadAnalytics(currentPeriod);
    }

    /**
     * Initialize analytics dashboard
     */
    function init() {
        // Period selector
        var periodSelector = document.querySelector('.period-selector');
        if (periodSelector) {
            periodSelector.addEventListener('click', handlePeriodClick);
        }

        // Refresh button
        var refreshBtn = document.getElementById('refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', handleRefreshClick);
        }

        // Retry button
        var retryBtn = document.getElementById('retry-btn');
        if (retryBtn) {
            retryBtn.addEventListener('click', handleRetryClick);
        }

        // Error panel expand/collapse (Story 19.6)
        var errorExpandBtn = document.getElementById('error-expand-btn');
        if (errorExpandBtn) {
            errorExpandBtn.addEventListener('click', function() {
                var container = document.getElementById('error-list-container');
                var icon = this.querySelector('.expand-icon');
                if (container) {
                    container.classList.toggle('hidden');
                    if (icon) icon.textContent = container.classList.contains('hidden') ? '▼' : '▲';
                }
            });
        }

        // Window resize handler for chart (Story 19.5)
        var resizeTimeout;
        window.addEventListener('resize', function() {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(function() {
                if (window.currentChartData) {
                    renderChart(window.currentChartData);
                }
            }, 150);
        });

        // =====================================================
        // Song Statistics Event Listeners (Story 19.7)
        // =====================================================

        // Summary card clicks (AC1)
        var summaryCards = document.getElementById('song-summary-cards');
        if (summaryCards) {
            summaryCards.addEventListener('click', handleSummaryCardClick);
        }

        // Playlist card "View Details" button clicks (AC2)
        var playlistSongStats = document.getElementById('playlist-song-stats');
        if (playlistSongStats) {
            playlistSongStats.addEventListener('click', function(e) {
                var btn = e.target.closest('.view-details-btn');
                if (btn) {
                    var playlistId = btn.dataset.playlistId;
                    if (playlistId) openPlaylistModal(playlistId);
                }
            });
        }

        // Modal controls (AC4)
        var modal = document.getElementById('playlist-modal');
        if (modal) {
            // Close button
            var closeBtn = modal.querySelector('.modal-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', closePlaylistModal);
            }

            // Close on backdrop click
            modal.addEventListener('click', function(e) {
                if (e.target === modal) closePlaylistModal();
            });

            // Keyboard navigation (AC10)
            modal.addEventListener('keydown', handleModalKeydown);
        }

        // Modal search (AC4)
        var modalSearch = document.getElementById('modal-search');
        if (modalSearch) {
            // Debounced search
            var searchTimeout;
            modalSearch.addEventListener('input', function(e) {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(function() {
                    handleModalSearch(e);
                }, 150);
            });
        }

        // Modal sort (AC4)
        var modalSort = document.getElementById('modal-sort-select');
        if (modalSort) {
            modalSort.addEventListener('change', handleModalSort);
        }

        // Modal pagination (AC4)
        var prevBtn = document.getElementById('pagination-prev');
        var nextBtn = document.getElementById('pagination-next');
        if (prevBtn) {
            prevBtn.addEventListener('click', function() {
                handlePagination(-1);
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function() {
                handlePagination(1);
            });
        }

        // Initial load
        loadAnalytics(currentPeriod);
        loadSongStats(); // Story 19.7
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
