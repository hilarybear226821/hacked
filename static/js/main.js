document.addEventListener('DOMContentLoaded', () => {
    // --- State Management ---
    const state = {
        devices: new Map(),
        operations: new Map(),
        recordings: [],
        sdrStatus: 'offline',
        activeTab: 'discovery'
    };

    // --- DOM Elements ---
    const elements = {
        navLinks: document.querySelectorAll('.nav-links li'),
        tabPanels: document.querySelectorAll('.tab-panel'),
        deviceTable: document.querySelector('#device-table tbody'),
        recordingsTable: document.querySelector('#recordings-table tbody'),
        opList: document.getElementById('op-list'),
        systemLogs: document.getElementById('system-logs-container'),
        intelLogs: document.getElementById('intel-logs'),
        sdrStatusBadge: document.getElementById('sdr-status-badge'),
        clock: document.getElementById('clock'),
        statSubghz: document.querySelector('#stat-subghz .value'),
        statUptime: document.querySelector('#stat-uptime .value'),
        deviceCount: document.getElementById('device-count'),
        emergencyBtn: document.getElementById('btn-emergency-stop'),
        spectrumCanvas: document.getElementById('spectrum-canvas'),
        spectrumCtx: null
    };

    if (elements.spectrumCanvas) {
        elements.spectrumCtx = elements.spectrumCanvas.getContext('2d');
    }

    // --- Tab Switching ---
    elements.navLinks.forEach(link => {
        link.addEventListener('click', () => {
            const tabId = link.getAttribute('data-tab');

            // UI Update
            elements.navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');

            elements.tabPanels.forEach(p => p.classList.remove('active'));
            document.getElementById(`tab-${tabId}`).classList.add('active');

            state.activeTab = tabId;

            // Refresh logic if needed
            if (tabId === 'recordings') fetchRecordings();
            if (tabId === 'logs') fetchLogs();
        });
    });

    // --- WebSocket Connection ---
    let ws;
    function connectWS() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/events`;

        console.log(`Connecting to WebSocket: ${wsUrl}`);
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket Connected');
            elements.sdrStatusBadge.className = 'status-badge online';
            elements.sdrStatusBadge.querySelector('.text').textContent = 'SDR ONLINE';
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleWSMessage(data);
        };

        ws.onclose = () => {
            console.log('WebSocket Disconnected. Reconnecting...');
            elements.sdrStatusBadge.className = 'status-badge offline';
            elements.sdrStatusBadge.querySelector('.text').textContent = 'SDR OFFLINE';
            setTimeout(connectWS, 2000);
        };

        ws.onerror = (err) => {
            console.error('WebSocket Error:', err);
        };

        // Spectrum WS
        connectSpectrumWS();
    }

    function connectSpectrumWS() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/spectrum`;
        const ws = new WebSocket(wsUrl);

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'spectrum') {
                drawSpectrum(data);
            }
        };

        ws.onclose = () => setTimeout(connectSpectrumWS, 2000);
    }

    function drawSpectrum(data) {
        if (!elements.spectrumCtx) return;
        const ctx = elements.spectrumCtx;
        const width = ctx.canvas.width;
        const height = ctx.canvas.height;
        const bins = data.bins;

        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, width, height);

        // Draw Grid
        ctx.strokeStyle = '#333';
        ctx.beginPath();
        for (let i = 1; i < 4; i++) {
            const y = height * (i / 4);
            ctx.moveTo(0, y);
            ctx.lineTo(width, y);
        }
        ctx.stroke();

        // Draw FFT
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 2;
        ctx.beginPath();

        const binWidth = width / bins.length;

        // Scale dB to pixels (approx range -100 to 0)
        // dB = 20log10(amp)
        // typical noise floor ~ -70 to -80
        // max ~ 0 
        const minDb = -100;
        const maxDb = 0;
        const scale = height / (maxDb - minDb);

        bins.forEach((db, i) => {
            let val = db;
            if (val < minDb) val = minDb;
            if (val > maxDb) val = maxDb;

            const h = height - ((val - minDb) * scale);
            const x = i * binWidth;

            if (i === 0) ctx.moveTo(x, h);
            else ctx.lineTo(x, h);
        });

        ctx.stroke();

        // Labels
        ctx.fillStyle = '#fff';
        ctx.font = '10px monospace';
        ctx.fillText(`${(data.center_freq / 1e6).toFixed(2)} MHz`, width / 2 - 20, height - 10);
    }

    function handleWSMessage(msg) {
        if (msg.type === 'heartbeat') {
            updateHeartbeat(msg.data);
        } else if (msg.type === 'protocol_observed') {
            handleNewDevice(msg.data);
        } else if (msg.type === 'operation_update') {
            updateOperation(msg.data);
        }
    }

    // --- Data Handlers ---

    function handleNewDevice(dev) {
        const id = dev.device_id || dev.frame_id;
        state.devices.set(id, {
            ...dev,
            lastSeen: Date.now()
        });
        renderDevices();

        // Log to intel
        const logEntry = document.createElement('div');
        logEntry.className = 'log-item';
        logEntry.innerHTML = `<span class="time">${new Date().toLocaleTimeString()}</span> <span class="proto">${dev.protocol}</span> - ${id}`;
        elements.intelLogs.prepend(logEntry);
    }

    function renderDevices() {
        elements.deviceTable.innerHTML = '';
        const sorted = Array.from(state.devices.values())
            .sort((a, b) => b.lastSeen - a.lastSeen);

        sorted.forEach(dev => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><i class="fas fa-broadcast-tower"></i></td>
                <td><span class="badge">${dev.protocol}</span></td>
                <td>${dev.device_id || 'UNKNOWN'}</td>
                <td>${dev.confidence ? (dev.confidence * 100).toFixed(0) + '%' : 'N/A'}</td>
                <td>${new Date(dev.lastSeen).toLocaleTimeString()}</td>
                <td><button class="btn btn-secondary btn-sm">Inspect</button></td>
            `;
            elements.deviceTable.appendChild(row);
        });

        elements.deviceCount.textContent = `Devices: ${state.devices.size}`;
        elements.statSubghz.textContent = state.devices.size;
    }

    function updateHeartbeat(data) {
        // Uptime
        const uptime = Math.floor(data.backend_uptime_sec || 0);
        const h = Math.floor(uptime / 3600).toString().padStart(2, '0');
        const m = Math.floor((uptime % 3600) / 60).toString().padStart(2, '0');
        const s = (uptime % 60).toString().padStart(2, '0');
        elements.statUptime.textContent = `${h}:${m}:${s}`;

        // Operations
        renderOperations(data.operations || []);
    }

    function renderOperations(ops) {
        elements.opList.innerHTML = '';
        if (ops.length === 0) {
            elements.opList.innerHTML = '<p class="placeholder">No active operations.</p>';
            return;
        }

        ops.forEach(op => {
            const opEl = document.createElement('div');
            opEl.className = 'op-item';
            opEl.innerHTML = `
                <div class="op-info">
                    <span class="op-name">${op.name}</span>
                    <span class="op-state ${op.state}">${op.state}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${op.progress * 100}%"></div>
                </div>
                <div class="op-msg">${op.message || 'Processing...'}</div>
            `;
            elements.opList.appendChild(opEl);
        });
    }

    // --- API Interactions ---

    async function fetchRecordings() {
        try {
            const resp = await fetch('/api/recordings');
            const data = await resp.json();
            state.recordings = data.recordings || [];
            renderRecordings();
        } catch (err) {
            console.error('Failed to fetch recordings', err);
        }
    }

    function renderRecordings() {
        elements.recordingsTable.innerHTML = '';
        state.recordings.forEach(rec => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${rec.id.substring(0, 8)}</td>
                <td>${rec.name}</td>
                <td>${rec.freq_mhz} MHz</td>
                <td>${rec.timestamp_human || new Date(rec.timestamp * 1000).toLocaleString()}</td>
                <td>
                    <button class="btn btn-primary replay-btn" data-id="${rec.id}">Replay</button>
                    <button class="btn btn-danger delete-btn" data-id="${rec.id}">Del</button>
                </td>
            `;
            elements.recordingsTable.appendChild(row);
        });

        // Add listeners for dynamic buttons
        document.querySelectorAll('.replay-btn').forEach(btn => {
            btn.onclick = () => runAttack('replay', { id: btn.dataset.id });
        });
    }

    async function fetchLogs() {
        try {
            const resp = await fetch('/api/logs');
            const data = await resp.json();
            elements.systemLogs.innerHTML = data.reverse().map(log => `<div>${log}</div>`).join('');
            elements.systemLogs.scrollTop = elements.systemLogs.scrollHeight;
        } catch (err) {
            console.error('Failed to fetch logs', err);
        }
    }

    async function runAttack(type, params) {
        console.log(`Starting attack: ${type}`, params);
        // This is a stub - need to map type to real API endpoints defined in web_server.py
        let url = '';
        if (type === 'rolljam') url = '/api/subghz/auto/start';
        else if (type === 'camjam') url = '/api/attack/camera/start';
        else if (type === 'glassbreak') url = '/api/attack/glass/start';
        else if (type === 'bruteforce') url = '/api/attack/bruteforce/start';
        else if (type === 'replay') url = `/api/subghz/replay/${params.id}`;

        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            });
            const result = await resp.json();
            if (result.code === 'BUSY') {
                notify(result.message, 'error');
            } else {
                notify(`Operation started: ${type}`, 'success');
            }
        } catch (err) {
            notify(`Failed to start ${type}`, 'error');
        }
    }

    function notify(msg, type) {
        const area = document.getElementById('notification-area');
        const el = document.createElement('div');
        el.className = `notification ${type}`;
        el.textContent = msg;
        area.appendChild(el);
        setTimeout(() => el.remove(), 4000);
    }

    // --- Init ---
    connectWS();
    setInterval(fetchLogs, 5010); // Periodic log refresh

    // Attack button listeners
    document.querySelectorAll('.start-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const attack = btn.dataset.attack;
            let params = {};
            if (attack === 'rolljam') {
                const presetVal = document.getElementById('rolljam-preset').value;
                if (!presetVal) return;
                params.frequency_mhz = presetVal;
            }
            runAttack(attack, params);
        });
    });

    // Preset loading
    async function fetchPresets() {
        try {
            const resp = await fetch('/api/subghz/presets');
            const presets = await resp.json();
            const select = document.getElementById('rolljam-preset');
            presets.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.freq;
                opt.textContent = p.name;
                select.appendChild(opt);
            });

            select.onchange = () => {
                document.getElementById('btn-start-rolljam').disabled = !select.value;
            };
        } catch (err) {
            console.error('Failed to load presets', err);
        }
    }
    fetchPresets();

    elements.emergencyBtn.onclick = () => fetch('/api/stop_all', { method: 'POST' });

    // ==================== SCPE TAB ====================
    const scpeElements = {
        loopToggle: document.getElementById('btn-scpe-loop-toggle'),
        loopStatus: document.getElementById('scpe-loop-status'),
        statDevices: document.getElementById('scpe-stat-devices'),
        statTargets: document.getElementById('scpe-stat-targets'),
        statMode: document.getElementById('scpe-stat-mode'),
        statLoop: document.getElementById('scpe-stat-loop'),
        deviceTableBody: document.querySelector('#scpe-device-table tbody')
    };

    let scpeLoopActive = false;

    async function fetchSCPEStatus() {
        try {
            const resp = await fetch('/api/scpe/status');
            const status = await resp.json();

            // Update stats
            scpeElements.statDevices.textContent = status.total_devices || 0;
            scpeElements.statTargets.textContent = status.active_targets || 0;
            scpeElements.statMode.textContent = status.scheduler_mode || 'CROSSFADE';
            scpeElements.statLoop.textContent = status.loop_active ? 'Running' : 'Idle';

            scpeLoopActive = status.loop_active;
            scpeElements.loopToggle.textContent = scpeLoopActive ? 'Stop Loop' : 'Start Loop';
            scpeElements.loopStatus.textContent = scpeLoopActive ? 'Running' : 'Stopped';
            scpeElements.loopStatus.style.color = scpeLoopActive ? '#00ff00' : '#ff4444';

            // Render device table
            renderSCPEDevices(status.devices || []);
        } catch (err) {
            console.error('Failed to fetch SCPE status:', err);
        }
    }

    function renderSCPEDevices(devices) {
        scpeElements.deviceTableBody.innerHTML = '';

        devices.forEach(dev => {
            const row = document.createElement('tr');
            const isPrioritized = dev.priority > 0;

            row.innerHTML = `
                <td>${dev.id}</td>
                <td><span class="badge">${dev.protocol}</span></td>
                <td>${dev.freq_mhz.toFixed(2)}</td>
                <td>${dev.queue_size}</td>
                <td>${dev.jitter_pct.toFixed(1)}%</td>
                <td>
                    ${isPrioritized ?
                    `<input type="number" class="priority-slider" value="${dev.priority}" min="0" max="10" step="0.5" data-device="${dev.id}">` :
                    `<button class="btn btn-sm btn-primary add-target-btn" data-device="${dev.id}">Add</button>`
                }
                </td>
                <td>
                    ${isPrioritized ?
                    `<button class="btn btn-sm btn-danger remove-target-btn" data-device="${dev.id}">Remove</button>` : ''}
                    <button class="btn btn-sm btn-secondary replay-btn" data-device="${dev.id}">Replay</button>
                </td>
            `;
            scpeElements.deviceTableBody.appendChild(row);
        });

        // Add event listeners
        document.querySelectorAll('.add-target-btn').forEach(btn => {
            btn.onclick = () => addSCPETarget(btn.dataset.device, 1.0);
        });

        document.querySelectorAll('.remove-target-btn').forEach(btn => {
            btn.onclick = () => removeSCPETarget(btn.dataset.device);
        });

        document.querySelectorAll('.priority-slider').forEach(input => {
            input.onchange = () => updatePriority(input.dataset.device, parseFloat(input.value));
        });

        document.querySelectorAll('.replay-btn').forEach(btn => {
            btn.onclick = () => triggerSCPEReplay(btn.dataset.device);
        });
    }

    async function toggleSCPELoop() {
        const endpoint = scpeLoopActive ? '/api/scpe/loop/stop' : '/api/scpe/loop/start';
        try {
            await fetch(endpoint, { method: 'POST' });
            notify(scpeLoopActive ? 'SCPE Loop Stopped' : 'SCPE Loop Started', 'success');
            fetchSCPEStatus();
        } catch (err) {
            notify('Failed to toggle SCPE loop', 'error');
        }
    }

    async function addSCPETarget(deviceId, priority) {
        try {
            await fetch('/api/scpe/add_target', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: deviceId, priority })
            });
            notify(`Added ${deviceId} to SCPE targets`, 'success');
            fetchSCPEStatus();
        } catch (err) {
            notify('Failed to add target', 'error');
        }
    }

    async function removeSCPETarget(deviceId) {
        try {
            await fetch('/api/scpe/remove_target', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: deviceId })
            });
            notify(`Removed ${deviceId} from SCPE targets`, 'success');
            fetchSCPEStatus();
        } catch (err) {
            notify('Failed to remove target', 'error');
        }
    }

    async function updatePriority(deviceId, priority) {
        // Re-add with new priority
        await addSCPETarget(deviceId, priority);
    }

    async function triggerSCPEReplay(deviceId) {
        try {
            await fetch('/api/scpe/trigger_replay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: deviceId, mode: 'SCPE_THICK', duration: 2.0 })
            });
            notify(`Triggered SCPE replay on ${deviceId}`, 'success');
        } catch (err) {
            notify('Failed to trigger replay', 'error');
        }
    }

    // SCPE event listeners
    if (scpeElements.loopToggle) {
        scpeElements.loopToggle.onclick = toggleSCPELoop;
    }

    // Poll SCPE status when on SCPE tab
    setInterval(() => {
        if (state.activeTab === 'scpe') {
            fetchSCPEStatus();
        }
    }, 2000);

    // ==================================================

    // Clock
    setInterval(() => {
        elements.clock.textContent = new Date().toLocaleTimeString();
    }, 1000);
});
