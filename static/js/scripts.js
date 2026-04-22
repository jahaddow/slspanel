function generateKey(prefix, bytes) {
    const arr = new Uint8Array(bytes);
    window.crypto.getRandomValues(arr);
    return prefix + Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
}

const ACTIVE_STREAM_KEY = 'slspanel.activeStreamPublisher';
const GROUP_COLLAPSE_KEY = 'slspanel.collapsedGroups';
const PUSH_STATUS_POLL_MS = 2000;
const STATS_POLL_MS = 2000;
const LAYOUT_SAVE_DEBOUNCE_MS = 400;

function getPublisherSelectorValue(publisher) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
        return window.CSS.escape(publisher);
    }
    return publisher.replace(/"/g, '\\"');
}

function getCsrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (match && match[1]) {
        return decodeURIComponent(match[1]);
    }
    return '';
}

async function copyToClipboard(element) {
    const text = element.getAttribute('data-url');
    try {
        await navigator.clipboard.writeText(text);
        showCopyFeedback(element);
    } catch (_err) {
        copyToClipboardFallback(text, element);
    }
}

function copyToClipboardFallback(text, element) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.cssText = 'position:fixed;top:0;left:0;width:2em;height:2em;padding:0;border:none;outline:none;box-shadow:none;background:transparent;opacity:0;';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        const successful = document.execCommand('copy');
        if (successful) {
            showCopyFeedback(element);
        } else {
            showCopyError(element);
        }
    } catch (_err) {
        showCopyError(element);
    } finally {
        document.body.removeChild(textArea);
    }
}

function showCopyFeedback(element) {
    const feedback = element.nextElementSibling;
    if (feedback) {
        feedback.textContent = window.translations.copiedText;
        feedback.classList.add('visible');
        setTimeout(() => {
            feedback.textContent = '';
            feedback.classList.remove('visible');
        }, 2000);
    }
}

function showCopyError(element) {
    const feedback = element.nextElementSibling;
    if (feedback) {
        feedback.textContent = window.translations.copyError;
        feedback.classList.add('visible', 'text-danger');
        setTimeout(() => {
            feedback.textContent = '';
            feedback.classList.remove('visible', 'text-danger');
        }, 2000);
    }
}

function numericValue(value) {
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : 0;
    }
    if (typeof value === 'string' && value.trim() !== '') {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }
    return 0;
}

function scoreMetrics(metrics) {
    if (!metrics || typeof metrics !== 'object') {
        return 0;
    }
    return (
        numericValue(metrics.mbps_recv_rate) * 1000000 +
        numericValue(metrics.bitrate) * 1000 +
        numericValue(metrics.uptime)
    );
}

function hasUsableStats(metrics) {
    if (!metrics || typeof metrics !== 'object') {
        return false;
    }
    return (
        numericValue(metrics.bitrate) > 0 ||
        numericValue(metrics.mbps_recv_rate) > 0 ||
        numericValue(metrics.uptime) > 0
    );
}

function pickActivePublisherMetrics(data) {
    if (!data || typeof data !== 'object') {
        return null;
    }

    const publisher = data.publisher;
    if (publisher && typeof publisher === 'object' && hasUsableStats(publisher)) {
        return { metrics: publisher, source: 'publisher' };
    }

    const publishers = data.publishers;
    if (publishers && typeof publishers === 'object') {
        const entries = Object.values(publishers).filter(metrics => hasUsableStats(metrics));
        if (entries.length > 0) {
            entries.sort((a, b) => scoreMetrics(b) - scoreMetrics(a));
            return { metrics: entries[0], source: 'publishers' };
        }
    }
    return null;
}

function formatUptime(seconds) {
    if (!seconds) return '00:00:00';
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    const time = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    return days > 0 ? `${days}d ${time}` : time;
}

function formatSeconds(seconds) {
    const value = numericValue(seconds);
    if (value <= 0) {
        return '0s';
    }
    return `${Math.round(value)}s`;
}

function consumerHintKey(key) {
    return /(consumer|connection|client|subscriber|viewer|receiver|player)/i.test(key || '');
}

function normalizeEndpoint(raw) {
    if (typeof raw === 'string' && raw.trim()) {
        return raw.trim();
    }
    const endpoint = raw.endpoint || raw.address || raw.remote || raw.peer || raw.client;
    if (typeof endpoint === 'string' && endpoint.trim()) {
        return endpoint.trim();
    }
    const ip = raw.remote_ip || raw.peer_ip || raw.client_ip || raw.ip || raw.host;
    const port = raw.remote_port || raw.peer_port || raw.port;
    if (ip && port) {
        return `${ip}:${port}`;
    }
    if (ip) {
        return String(ip);
    }
    return '';
}

function looksLikeConsumerConnection(raw, hinted) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return false;
    }
    const keys = Object.keys(raw);
    if (keys.length === 0) {
        return false;
    }

    const identity = raw.connection_id || raw.socket_id || raw.client_id || raw.id || normalizeEndpoint(raw);
    const metricsPresent = (
        'latency' in raw ||
        'rtt' in raw ||
        'bitrate' in raw ||
        'mbps_recv_rate' in raw ||
        'buffer' in raw ||
        'dropped_pkts' in raw ||
        'uptime' in raw ||
        'status' in raw ||
        'state' in raw
    );

    if (identity && metricsPresent) {
        return true;
    }
    return Boolean(hinted && identity);
}

function normalizeConsumerConnection(raw, index) {
    if (typeof raw === 'string') {
        return {
            id: `conn-${index + 1}`,
            endpoint: normalizeEndpoint(raw) || 'unknown endpoint',
            latency: null,
            rtt: null,
            bitrate: null,
            recvRate: null,
            buffer: null,
            dropped: null,
            uptime: null,
            status: 'connected'
        };
    }

    const connectionId = raw.connection_id || raw.socket_id || raw.client_id || raw.id || `conn-${index + 1}`;
    const endpoint = normalizeEndpoint(raw);
    return {
        id: String(connectionId),
        endpoint: endpoint || 'unknown endpoint',
        latency: raw.latency,
        rtt: raw.rtt,
        bitrate: raw.bitrate,
        recvRate: raw.mbps_recv_rate ?? raw.recv_rate_mbps ?? raw.mbpsRecvRate,
        buffer: raw.buffer,
        dropped: raw.dropped_pkts,
        uptime: raw.uptime,
        status: raw.status || raw.state || 'connected'
    };
}

function formatConsumerRate(conn) {
    const kbps = numericValue(conn.bitrate);
    const mbps = numericValue(conn.recvRate);
    if (mbps > 0) {
        return `${kbps} kbps / ${mbps.toFixed(2)} Mbps`;
    }
    return `${kbps} kbps`;
}

function isInternalRelayConnection(conn) {
    const endpoint = String(conn.endpoint || '').toLowerCase();
    return endpoint.startsWith('127.0.0.1') || endpoint.startsWith('localhost') || endpoint.startsWith('::1');
}

function formatTimestamp(isoText) {
    if (!isoText) {
        return '-';
    }
    const date = new Date(isoText);
    if (Number.isNaN(date.getTime())) {
        return isoText;
    }
    return date.toLocaleString();
}

function extractConsumerConnections(data) {
    const found = [];
    let sawConsumerContainer = false;
    let hintedCount = null;
    const seen = new Set();

    function walk(node, path) {
        if (Array.isArray(node)) {
            node.forEach((item, idx) => walk(item, path.concat(String(idx))));
            return;
        }
        if (!node || typeof node !== 'object') {
            return;
        }

        const hinted = path.some(consumerHintKey);
        if (hinted) {
            sawConsumerContainer = true;
        }

        if (hinted && typeof node.connected === 'number' && Number.isFinite(node.connected)) {
            hintedCount = node.connected;
        }
        if (hinted && typeof node.count === 'number' && Number.isFinite(node.count)) {
            hintedCount = node.count;
        }

        if (looksLikeConsumerConnection(node, hinted)) {
            const signature = JSON.stringify(node);
            if (!seen.has(signature)) {
                seen.add(signature);
                found.push(node);
            }
        }

        Object.entries(node).forEach(([key, value]) => {
            if (consumerHintKey(key) && (Array.isArray(value) || (value && typeof value === 'object'))) {
                sawConsumerContainer = true;
            }
            if (consumerHintKey(key) && typeof value === 'number' && Number.isFinite(value) && /(count|connected|total|active)/i.test(key)) {
                hintedCount = value;
            }
            walk(value, path.concat(key));
        });
    }

    walk(data, []);
    return {
        connections: found.map((raw, idx) => normalizeConsumerConnection(raw, idx)),
        sawConsumerContainer,
        hintedCount
    };
}

function renderStreamStatsCard(collapseEl, payload) {
    const container = collapseEl.querySelector('[data-stream-stats]');
    if (!container) {
        return;
    }

    if (!payload || payload.error) {
        container.innerHTML = `<p class="opn-muted"><em>${window.translations.statsNotAvailable}</em></p>`;
        return;
    }

    const picked = pickActivePublisherMetrics(payload);
    if (!picked) {
        container.innerHTML = `<p class="opn-muted"><em>Publisher statistics not available for this stream.</em></p>`;
        return;
    }

    const publisher = picked.metrics;
    const bitrate = numericValue(publisher.bitrate);
    const latency = numericValue(publisher.latency);
    const rtt = numericValue(publisher.rtt).toFixed(2);
    const buffer = numericValue(publisher.buffer);
    const droppedPkts = numericValue(publisher.dropped_pkts);
    const uptime = formatUptime(numericValue(publisher.uptime));
    const status = (payload.status || 'unknown').toUpperCase();

    container.innerHTML = `
        <div class="row g-2">
            <div class="col-md-4 col-6"><p>Bitrate:</p><strong>${bitrate} kbps</strong></div>
            <div class="col-md-4 col-6"><p>Latency:</p><strong>${latency} ms</strong></div>
            <div class="col-md-4 col-6"><p>RTT:</p><strong>${rtt} ms</strong></div>
            <div class="col-md-4 col-6"><p>Buffer:</p><strong>${buffer} ms</strong></div>
            <div class="col-md-4 col-6"><p>Dropped:</p><strong>${droppedPkts}</strong></div>
            <div class="col-md-4 col-6"><p>Uptime:</p><strong>${uptime}</strong></div>
            <div class="col-md-6 col-6"><p>Status:</p><strong>${status}</strong></div>
            <div class="col-md-6 col-6"><p>Source:</p><strong>${picked.source}</strong></div>
        </div>
    `;
}

function updatePushSourceBitrate(collapseEl, payload) {
    const bitrateEl = collapseEl.querySelector('[data-push-source-bitrate]');
    if (!bitrateEl) {
        return;
    }

    const picked = pickActivePublisherMetrics(payload);
    if (!picked) {
        bitrateEl.textContent = '0 kbps';
        return;
    }

    const bitrate = numericValue(picked.metrics.bitrate);
    bitrateEl.textContent = `${bitrate} kbps`;
}

function renderConsumerList(container, payload) {
    if (!container) {
        return;
    }

    if (!payload || payload.error) {
        container.innerHTML = '<p class="opn-muted"><em>Consumer stats unavailable right now.</em></p>';
        return;
    }

    let connections = [];
    let extracted = null;
    if (Array.isArray(payload.consumers)) {
        connections = payload.consumers.map((raw, idx) => normalizeConsumerConnection(raw, idx));
    } else {
        extracted = extractConsumerConnections(payload);
        connections = extracted.connections;
    }

    const visibleConnections = connections.filter(conn => !isInternalRelayConnection(conn));

    if (visibleConnections.length === 0) {
        if (typeof payload.consumer_count === 'number') {
            if (payload.consumer_count > 0) {
                container.innerHTML = '<p class="opn-muted"><em>No external consumers currently connected.</em></p>';
            } else {
                container.innerHTML = '<p class="opn-muted"><em>No consumers currently connected.</em></p>';
            }
        } else {
            if (extracted && extracted.sawConsumerContainer) {
                if (typeof extracted.hintedCount === 'number' && extracted.hintedCount > 0) {
                    container.innerHTML = '<p class="opn-muted"><em>Consumer count is reported, but per-connection details are unavailable in this payload.</em></p>';
                } else {
                    container.innerHTML = '<p class="opn-muted"><em>No consumers currently connected.</em></p>';
                }
            } else {
                container.innerHTML = '<p class="opn-muted"><em>This stats response does not include consumer connection details.</em></p>';
            }
        }
        return;
    }

    const rows = visibleConnections.map(conn => `
        <tr>
            <td>${conn.id}</td>
            <td>${conn.endpoint}</td>
            <td>${numericValue(conn.latency)} ms</td>
            <td>${numericValue(conn.rtt).toFixed(2)} ms</td>
            <td>${formatConsumerRate(conn)}</td>
            <td>${numericValue(conn.buffer)} ms</td>
            <td>${numericValue(conn.dropped)}</td>
            <td>${formatUptime(numericValue(conn.uptime))}</td>
            <td>${String(conn.status).toUpperCase()}</td>
        </tr>
    `).join('');

    container.innerHTML = `
        <div class="table-responsive">
            <table class="table table-sm table-dark table-striped align-middle mb-0 consumer-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Endpoint</th>
                        <th>Latency</th>
                        <th>RTT</th>
                        <th>Rate</th>
                        <th>Buffer</th>
                        <th>Dropped</th>
                        <th>Uptime</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function fetchPublisherStats(publisherKey) {
    return fetch(`/sls-stats/publisher/${encodeURIComponent(publisherKey)}/`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return response.json();
        })
        .catch(() => ({ error: true }));
}

function fetchConsumerStats(playerKey) {
    return fetch(`/sls-stats/consumers/${encodeURIComponent(playerKey)}/`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return response.json();
        })
        .catch(() => ({ error: true }));
}

function updateStatsForCollapse(collapseEl) {
    const playerContainers = Array.from(collapseEl.querySelectorAll('[data-player-consumers][data-player-key]'));
    const playerKeys = Array.from(new Set(playerContainers.map(el => el.dataset.playerKey).filter(Boolean)));
    const streamPublisher = collapseEl.dataset.streamPublisher || '';
    if (!streamPublisher && playerKeys.length === 0) {
        return;
    }

    const tasks = [];
    if (streamPublisher) {
        tasks.push(fetchPublisherStats(streamPublisher).then(payload => ({ type: 'publisher', payload })));
    }
    playerKeys.forEach(key => {
        tasks.push(fetchConsumerStats(key).then(payload => ({ type: 'consumer', key, payload })));
    });

    Promise.all(tasks).then(results => {
        const consumerMap = new Map();
        let publisherPayload = null;

        results.forEach(item => {
            if (item.type === 'publisher') {
                publisherPayload = item.payload;
            } else if (item.type === 'consumer') {
                consumerMap.set(item.key, item.payload);
            }
        });

        renderStreamStatsCard(collapseEl, publisherPayload);
        updatePushSourceBitrate(collapseEl, publisherPayload);
        playerContainers.forEach(container => {
            const key = container.dataset.playerKey;
            renderConsumerList(container, consumerMap.get(key));
        });
    });
}

function visibleStatCollapses() {
    return document.querySelectorAll('.accordion-collapse.show[data-stream-publisher]');
}

function initializeStats() {
    const collapses = document.querySelectorAll('.accordion-collapse[data-stream-publisher]');
    if (collapses.length === 0) {
        return;
    }

    function refreshVisible() {
        visibleStatCollapses().forEach(updateStatsForCollapse);
    }

    refreshVisible();
    setInterval(refreshVisible, STATS_POLL_MS);

    collapses.forEach(collapseEl => {
        collapseEl.addEventListener('shown.bs.collapse', function () {
            updateStatsForCollapse(collapseEl);
        });
    });
}

function initializeAccordionState() {
    const accordions = document.querySelectorAll('[data-group-accordion]');
    if (accordions.length === 0 || !window.bootstrap || !window.bootstrap.Collapse) {
        return;
    }

    const collapseEls = document.querySelectorAll('.accordion-collapse[data-stream-publisher]');
    if (collapseEls.length === 0) {
        return;
    }

    const byPublisher = {};
    collapseEls.forEach(el => {
        const publisher = el.dataset.streamPublisher;
        if (publisher) {
            byPublisher[publisher] = el;
        }
        el.addEventListener('shown.bs.collapse', function () {
            if (publisher) {
                localStorage.setItem(ACTIVE_STREAM_KEY, publisher);
            }
        });
        el.addEventListener('hidden.bs.collapse', function () {
            if (publisher && localStorage.getItem(ACTIVE_STREAM_KEY) === publisher) {
                localStorage.removeItem(ACTIVE_STREAM_KEY);
            }
        });
    });

    const savedPublisher = localStorage.getItem(ACTIVE_STREAM_KEY);
    const savedCollapse = savedPublisher ? byPublisher[savedPublisher] : null;
    if (savedCollapse) {
        window.bootstrap.Collapse.getOrCreateInstance(savedCollapse, { toggle: false }).show();
    } else if (savedPublisher) {
        localStorage.removeItem(ACTIVE_STREAM_KEY);
    }

    document.querySelectorAll('form.stream-action-form').forEach(form => {
        form.addEventListener('submit', function () {
            const collapse = form.closest('.accordion-collapse[data-stream-publisher]');
            if (!collapse) {
                return;
            }
            const publisher = collapse.dataset.streamPublisher;
            if (publisher) {
                localStorage.setItem(ACTIVE_STREAM_KEY, publisher);
            }
        });
    });
}

function visiblePushForms() {
    return Array.from(document.querySelectorAll('.accordion-collapse.show form[data-push-publisher]'));
}

function updatePushRouteCard(route) {
    if (!route || !route.publisher) {
        return;
    }

    const selectorValue = getPublisherSelectorValue(route.publisher);
    const form = document.querySelector(`form[data-push-publisher="${selectorValue}"]`);
    const statusCard = document.querySelector(`[data-push-status-card][data-publisher="${selectorValue}"]`);
    if (!form || !statusCard) {
        return;
    }

    const badgeEl = statusCard.querySelector('[data-push-runner-badge]');
    if (badgeEl) {
        const nextText = `Runner: ${route.runner_state || 'unknown'}`;
        if (badgeEl.textContent.trim() !== nextText) {
            badgeEl.textContent = nextText;
        }
        badgeEl.className = `badge text-bg-${route.runner_badge || 'warning'}`;
    }

    const errEl = statusCard.querySelector('[data-push-last-error]');
    if (errEl) {
        const errorText = (route.last_error || '').trim();
        const displayText = errorText || 'status unavailable';
        if (errEl.textContent !== displayText) {
            errEl.textContent = displayText;
        }
        errEl.classList.remove('alert-danger', 'alert-secondary', 'alert-success');
        if (route.runner_state === 'error' || route.runner_state === 'retrying') {
            errEl.classList.add('alert-danger');
        } else if (route.runner_state === 'running') {
            errEl.classList.add('alert-success');
        } else {
            errEl.classList.add('alert-secondary');
        }
    }

    const toggleBtn = form.querySelector('[data-push-toggle-btn]');
    if (toggleBtn) {
        const enabled = !!route.enabled;
        const nextLabel = enabled ? 'Disable push' : 'Enable push';
        if (toggleBtn.textContent.trim() !== nextLabel) {
            toggleBtn.textContent = nextLabel;
        }
        toggleBtn.classList.remove('btn-warning', 'btn-opn-primary', 'btn-primary');
        toggleBtn.classList.add(enabled ? 'btn-warning' : 'btn-opn-primary');
    }

    const enabledEl = statusCard.querySelector('[data-push-enabled]');
    if (enabledEl) {
        enabledEl.textContent = route.enabled ? 'Yes' : 'No';
    }

    const sourceEl = statusCard.querySelector('[data-push-source-key]');
    if (sourceEl) {
        sourceEl.textContent = (route.source_player_key || '-').trim() || '-';
    }

    const destinationEl = statusCard.querySelector('[data-push-destination]');
    if (destinationEl) {
        destinationEl.textContent = (route.destination_url || '-').trim() || '-';
    }

    const updatedEl = statusCard.querySelector('[data-push-updated]');
    if (updatedEl) {
        updatedEl.textContent = formatTimestamp(route.runner_updated_at);
    }

    const relayRateEl = statusCard.querySelector('[data-push-relay-bitrate]');
    if (relayRateEl) {
        relayRateEl.textContent = `${numericValue(route.relay_bitrate_kbps)} kbps`;
    }

    const uptimeEl = statusCard.querySelector('[data-push-relay-uptime]');
    if (uptimeEl) {
        uptimeEl.textContent = formatSeconds(route.relay_uptime_seconds);
    }

    const retryEl = statusCard.querySelector('[data-push-retry]');
    if (retryEl) {
        retryEl.textContent = formatSeconds(route.retry_in_seconds);
    }

    const exitEl = statusCard.querySelector('[data-push-exit]');
    if (exitEl) {
        exitEl.textContent = route.last_exit_code === null || route.last_exit_code === undefined ? '-' : String(route.last_exit_code);
    }
}

function pollPushRouteStatus() {
    const activePublishers = new Set(visiblePushForms().map(form => form.dataset.pushPublisher));
    if (activePublishers.size === 0) {
        return;
    }

    fetch('/api/push/routes-status/')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (!data || data.status !== 'success' || !Array.isArray(data.routes)) {
                return;
            }
            data.routes.forEach(route => {
                if (activePublishers.has(route.publisher)) {
                    updatePushRouteCard(route);
                }
            });
        })
        .catch(() => {
            // Keep current UI state and retry on the next poll.
        });
}

function initializePushStatusPolling() {
    const forms = document.querySelectorAll('form[data-push-publisher]');
    if (forms.length === 0) {
        return;
    }
    pollPushRouteStatus();
    setInterval(pollPushRouteStatus, PUSH_STATUS_POLL_MS);
}

function initializeGroupCollapseState() {
    const groups = Array.from(document.querySelectorAll('[data-group-collapse][data-group-key]'));
    if (groups.length === 0 || !window.bootstrap || !window.bootstrap.Collapse) {
        return;
    }

    let collapsedKeys = {};
    try {
        collapsedKeys = JSON.parse(localStorage.getItem(GROUP_COLLAPSE_KEY) || '{}') || {};
    } catch (_err) {
        collapsedKeys = {};
    }

    groups.forEach(groupEl => {
        const key = groupEl.dataset.groupKey || '__ungrouped__';
        const shouldCollapse = !!collapsedKeys[key];
        const collapse = window.bootstrap.Collapse.getOrCreateInstance(groupEl, { toggle: false });
        if (shouldCollapse) {
            collapse.hide();
        } else {
            collapse.show();
        }

        groupEl.addEventListener('shown.bs.collapse', () => {
            collapsedKeys[key] = false;
            localStorage.setItem(GROUP_COLLAPSE_KEY, JSON.stringify(collapsedKeys));
        });
        groupEl.addEventListener('hidden.bs.collapse', () => {
            collapsedKeys[key] = true;
            localStorage.setItem(GROUP_COLLAPSE_KEY, JSON.stringify(collapsedKeys));
        });
    });
}

function readLayoutPayload() {
    const groups = Array.from(document.querySelectorAll('.opn-group[data-group-name]'));
    const layout = [];
    let sortOrder = 0;
    groups.forEach(group => {
        const groupName = group.dataset.groupName || '';
        group.querySelectorAll('[data-stream-item][data-stream-publisher]').forEach(item => {
            layout.push({
                publisher: item.dataset.streamPublisher,
                group_name: groupName,
                sort_order: sortOrder,
            });
            sortOrder += 1;
        });
    });
    return layout;
}

function initializeStreamLayoutDnD() {
    const root = document.getElementById('streamLayoutRoot');
    if (!root) {
        return;
    }

    const endpoint = root.dataset.layoutEndpoint;
    const csrfToken = root.dataset.csrfToken || getCsrfToken();
    const groups = root.querySelectorAll('.opn-group');
    if (!endpoint || groups.length === 0) {
        return;
    }

    let draggedItem = null;
    let saveTimer = null;

    const scheduleSave = () => {
        if (saveTimer) {
            clearTimeout(saveTimer);
        }
        saveTimer = setTimeout(() => {
            fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({ layout: readLayoutPayload() }),
            }).catch(() => {
                // Keep local layout and retry on next drag.
            });
        }, LAYOUT_SAVE_DEBOUNCE_MS);
    };

    root.querySelectorAll('[data-stream-item][draggable="true"]').forEach(item => {
        item.addEventListener('dragstart', event => {
            draggedItem = item;
            item.classList.add('opn-dragging');
            event.dataTransfer.effectAllowed = 'move';
        });

        item.addEventListener('dragend', () => {
            item.classList.remove('opn-dragging');
            draggedItem = null;
        });
    });

    groups.forEach(group => {
        const accordion = group.querySelector('[data-group-accordion]');
        if (!accordion) {
            return;
        }

        accordion.addEventListener('dragover', event => {
            if (!draggedItem) {
                return;
            }
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            const siblings = Array.from(accordion.querySelectorAll('[data-stream-item]:not(.opn-dragging)'));
            const next = siblings.find(candidate => {
                const rect = candidate.getBoundingClientRect();
                return event.clientY < rect.top + (rect.height / 2);
            });
            if (next) {
                accordion.insertBefore(draggedItem, next);
            } else {
                accordion.appendChild(draggedItem);
            }
        });

        accordion.addEventListener('drop', event => {
            if (!draggedItem) {
                return;
            }
            event.preventDefault();
            scheduleSave();
        });
    });
}

document.addEventListener('DOMContentLoaded', function () {
    const publisherInput = document.getElementById('publisher');
    const playerInput = document.getElementById('player');
    if (publisherInput && !publisherInput.value) {
        publisherInput.value = generateKey('live_', 16);
    }
    if (playerInput && !playerInput.value) {
        playerInput.value = generateKey('play_', 16);
    }
    initializeGroupCollapseState();
    initializeAccordionState();
    initializeStats();
    initializePushStatusPolling();
    initializeStreamLayoutDnD();
});
