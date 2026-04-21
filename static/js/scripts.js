function generateKey(prefix, bytes) {
    const arr = new Uint8Array(bytes);
    window.crypto.getRandomValues(arr);
    return prefix + Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
}

const ACTIVE_STREAM_KEY = 'slspanel.activeStreamPublisher';
const PUSH_STATUS_POLL_MS = 2000;
const STATS_POLL_MS = 2000;

function getPublisherSelectorValue(publisher) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
        return window.CSS.escape(publisher);
    }
    return publisher.replace(/"/g, '\\"');
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
        return publisher;
    }
    const publishers = data.publishers;
    if (publishers && typeof publishers === 'object') {
        const entries = Object.values(publishers).filter(metrics => hasUsableStats(metrics));
        if (entries.length > 0) {
            entries.sort((a, b) => scoreMetrics(b) - scoreMetrics(a));
            return entries[0];
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

function loadStats(playerKey) {
    const statsContainer = document.getElementById(`stats-${playerKey}`);
    if (!statsContainer) {
        return;
    }

    fetch(`/sls-stats/${playerKey}/`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                statsContainer.innerHTML = `<p class="text-danger">${data.error}</p>`;
                return;
            }

            const publisher = pickActivePublisherMetrics(data);
            if (!publisher) {
                statsContainer.innerHTML = `<p class="opn-muted"><em>${window.translations.statsNotAvailable}</em></p>`;
                return;
            }

            const bitrate = numericValue(publisher.bitrate);
            const buffer = numericValue(publisher.buffer);
            const droppedPkts = numericValue(publisher.dropped_pkts);
            const latency = numericValue(publisher.latency);
            const rtt = numericValue(publisher.rtt).toFixed(2);
            const uptime = formatUptime(numericValue(publisher.uptime));
            const status = data.status || 'unknown';
            const statusClass = status === 'ok' ? 'text-success' : 'text-warning';
            statsContainer.dataset.loaded = '1';
            statsContainer.innerHTML = `
                <div class="mt-2 p-2 bg-dark bg-opacity-50 rounded">
                    <h6 class="mb-2">${window.translations.streamStatistics}</h6>
                    <div class="row g-2">
                        <div class="col-md-4 col-6"><p>${window.translations.bitrate}:</p><strong>${bitrate} kbps</strong></div>
                        <div class="col-md-4 col-6"><p>${window.translations.latency}:</p><strong>${latency} ms</strong></div>
                        <div class="col-md-4 col-6"><p>${window.translations.rtt}:</p><strong>${rtt} ms</strong></div>
                        <div class="col-md-4 col-6"><p>${window.translations.buffer}:</p><strong>${buffer} ms</strong></div>
                        <div class="col-md-4 col-6"><p>${window.translations.droppedPackets}:</p><strong class="${droppedPkts > 0 ? 'text-warning' : ''}">${droppedPkts}</strong></div>
                        <div class="col-md-4 col-6"><p>${window.translations.uptime}:</p><strong>${uptime}</strong></div>
                        <div class="col-12 mt-2"><p>${window.translations.status}:</p><span class="${statusClass} fw-bold">${status.toUpperCase()}</span></div>
                    </div>
                </div>
            `;
        })
        .catch(() => {
            if (!statsContainer.dataset.loaded) {
                statsContainer.innerHTML = `<p><em>${window.translations.statsNotAvailable}</em></p>`;
            }
        });
}

function visibleStatsContainers() {
    return document.querySelectorAll('.accordion-collapse.show [id^="stats-"]');
}

function loadVisibleStats() {
    visibleStatsContainers().forEach(container => {
        const playerKey = container.dataset.playerKey;
        if (playerKey) {
            loadStats(playerKey);
        }
    });
}

function initializeStats() {
    const statsContainers = document.querySelectorAll('[id^="stats-"]');
    if (statsContainers.length === 0) {
        return;
    }
    loadVisibleStats();
    setInterval(loadVisibleStats, STATS_POLL_MS);

    document.querySelectorAll('.accordion-collapse[data-stream-publisher]').forEach(collapseEl => {
        collapseEl.addEventListener('shown.bs.collapse', function () {
            collapseEl.querySelectorAll('[id^="stats-"]').forEach(container => {
                const playerKey = container.dataset.playerKey;
                if (playerKey) {
                    loadStats(playerKey);
                }
            });
        });
    });
}

function initializeAccordionState() {
    const accordion = document.getElementById('streamAccordion');
    if (!accordion || !window.bootstrap || !window.bootstrap.Collapse) {
        return;
    }

    const collapseEls = accordion.querySelectorAll('.accordion-collapse[data-stream-publisher]');
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

    accordion.querySelectorAll('form.stream-action-form').forEach(form => {
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
    if (!form) {
        return;
    }

    const badgeEl = form.querySelector('[data-push-runner-badge]');
    if (badgeEl) {
        const nextText = `Runner: ${route.runner_state || 'unknown'}`;
        if (badgeEl.textContent.trim() !== nextText) {
            badgeEl.textContent = nextText;
        }
        badgeEl.className = `badge text-bg-${route.runner_badge || 'warning'}`;
    }

    const errEl = form.querySelector('[data-push-last-error]');
    if (errEl) {
        const errorText = (route.last_error || '').trim();
        if (errorText) {
            if (errEl.textContent !== errorText) {
                errEl.textContent = errorText;
            }
            errEl.classList.remove('d-none');
        } else {
            errEl.textContent = '';
            errEl.classList.add('d-none');
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

document.addEventListener('DOMContentLoaded', function () {
    const publisherInput = document.getElementById('publisher');
    const playerInput = document.getElementById('player');
    if (publisherInput && !publisherInput.value) {
        publisherInput.value = generateKey('live_', 16);
    }
    if (playerInput && !playerInput.value) {
        playerInput.value = generateKey('play_', 16);
    }
    initializeAccordionState();
    initializeStats();
    initializePushStatusPolling();
});
