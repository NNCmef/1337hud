let currentHost = "";
let currentProcesses = [];
let knownAlerts = new Set(); 

const themeSelect = document.getElementById('themeSelect');
const savedTheme = localStorage.getItem('1337-theme') || 'cyber';
document.body.dataset.theme = savedTheme;
if (themeSelect) {
    themeSelect.value = savedTheme;
    themeSelect.addEventListener('change', () => {
        document.body.dataset.theme = themeSelect.value;
        localStorage.setItem('1337-theme', themeSelect.value);
    });
}

const sysCtx = document.getElementById('sysChart').getContext('2d');
const netCtx = document.getElementById('netChart').getContext('2d');

const sysChart = new Chart(sysCtx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label: 'CPU (%)', borderColor: '#ef4444', backgroundColor: 'rgba(239, 68, 68, 0.1)', data: [], fill: true, tension: 0.2 },
            { label: 'RAM (%)', borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', data: [], fill: true, tension: 0.2 }
        ]
    },
    options: { scales: { y: { min: 0, max: 100 } }, animation: false, responsive: true, maintainAspectRatio: false }
});

const netChart = new Chart(netCtx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label: 'Вход (KB/s)', borderColor: '#10b981', data: [], tension: 0.2 },
            { label: 'Выход (KB/s)', borderColor: '#f59e0b', data: [], tension: 0.2 }
        ]
    },
    options: { animation: false, responsive: true, maintainAspectRatio: false }
});

// Переключение вкладок
document.querySelectorAll('.segmented-tabs .menu-item').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.segmented-tabs .menu-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        
        btn.classList.add('active');
        const tabId = 'tab-' + btn.getAttribute('data-tab');
        const activeTab = document.getElementById(tabId);
        if (activeTab) activeTab.classList.add('active');
    });
});

// ==========================================
// ЛОГИКА КАСТОМНОГО DROPDOWN ВЫБОРА ХОСТА
// ==========================================
const customTrigger = document.getElementById('customSelectTrigger');
const customOptionsContainer = document.getElementById('customSelectOptions');
const customValueText = document.getElementById('customSelectValue');

customTrigger.addEventListener('click', (e) => {
    e.stopPropagation();
    customOptionsContainer.classList.toggle('open');
});

document.addEventListener('click', () => {
    customOptionsContainer.classList.remove('open');
});

async function fetchHosts() {
    try {
        const res = await fetch('/api/v1/hosts');
        const data = await res.json();
        
        document.getElementById('totalHosts').innerText = data.hosts.length;
        if (data.hosts.length === 0) return;

        let selectedValid = data.hosts.some(h => h.host_id === currentHost);
        if (!selectedValid) {
            currentHost = data.hosts[0].host_id;
        }

        customOptionsContainer.innerHTML = '';
        
        data.hosts.forEach(h => {
            const opt = document.createElement('div');
            opt.className = 'custom-option' + (h.host_id === currentHost ? ' selected' : '');
            opt.innerText = `${h.host_id} (${h.status})`;
            
            if (h.host_id === currentHost) {
                customValueText.innerText = opt.innerText;
            }
            
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                currentHost = h.host_id;
                customValueText.innerText = opt.innerText;
                
                document.querySelectorAll('.custom-option').forEach(el => el.classList.remove('selected'));
                opt.classList.add('selected');
                
                customOptionsContainer.classList.remove('open');
                
                tick(); 
            });
            
            customOptionsContainer.appendChild(opt);
        });

        const activeHost = data.hosts.find(h => h.host_id === currentHost);
        if (activeHost) updateUI(activeHost);
    } catch (err) {
        console.error("Ошибка загрузки хостов:", err);
    }
}

async function fetchMetrics() {
    if (!currentHost) return;
    try {
        const res = await fetch(`/api/v1/metrics/${currentHost}`);
        const data = await res.json();
        const metrics = data.metrics;

        const timeLabels = metrics.map(m => new Date(m[4] * 1000).toLocaleTimeString());
        
        sysChart.data.labels = timeLabels;
        sysChart.data.datasets[0].data = metrics.map(m => m[0]);
        sysChart.data.datasets[1].data = metrics.map(m => m[1]);
        sysChart.update();

        netChart.data.labels = timeLabels;
        netChart.data.datasets[0].data = metrics.map(m => m[2]);
        netChart.data.datasets[1].data = metrics.map(m => m[3]);
        netChart.update();

        document.getElementById('lastUpdate').innerText = new Date().toLocaleTimeString();
    } catch (err) {
        console.error("Ошибка метрик:", err);
    }
}

function playCyberAlertSound() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'square';
        osc.frequency.setValueAtTime(400, ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.15);
        gain.gain.setValueAtTime(0.1, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.3);
    } catch (e) {
        console.warn("Звук заблокирован браузером.");
    }
}

function showToastNotification(alertData) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast-alert';
    toast.innerHTML = `
        <div class="toast-title">⚠️ Инцидент: ${alertData.host}</div>
        <div class="toast-msg">${alertData.message}</div>
        <div style="font-size:10px; color:#64748b; margin-top:2px;">Кликните, чтобы открыть панель управления</div>
    `;
    
    toast.onclick = () => {
        const alertTabBtn = document.querySelector('.segmented-tabs .menu-item[data-tab="alerts"]');
        if (alertTabBtn) alertTabBtn.click();
        toast.remove();
    };

    container.appendChild(toast);
    setTimeout(() => { if (toast.parentNode) toast.remove(); }, 8000);
}

async function resolveAlert(alertId) {
    try {
        await fetch(`/api/v1/alerts/${alertId}/resolve`, { method: 'POST' });
        await fetchAlerts();
    } catch (err) {
        console.error("Ошибка при подтверждении алерта:", err);
    }
}

async function fetchAlerts() {
    try {
        const res = await fetch('/api/v1/alerts');
        const data = await res.json();
        const alertLog = document.getElementById('alertLog');
        
        if (!data.alerts || data.alerts.length === 0) {
            alertLog.innerHTML = '<div class="empty-alert">✅ Активных инцидентов нет. Системы в норме.</div>';
            knownAlerts.clear();
            return;
        }

        let newAlertsDetected = false;
        const currentAlertIds = new Set(data.alerts.map(a => a.id));
        
        data.alerts.forEach(a => {
            if (!knownAlerts.has(a.id)) {
                newAlertsDetected = true;
                showToastNotification(a);
            }
        });
        
        knownAlerts = currentAlertIds;

        if (newAlertsDetected) {
            playCyberAlertSound();
        }

        alertLog.innerHTML = data.alerts.map(a => `
            <div class="alert-item" style="align-items: center;">
                <div style="flex: 1;">
                    <div style="margin-bottom: 4px;">
                        <strong>[${a.host}]</strong> <span class="tag-down">${a.level}</span>
                    </div>
                    <div style="color: var(--text-main); font-size: 13px;">${a.message}</div>
                    <div style="color: var(--text-muted); font-size: 10px; margin-top: 6px;">
                        ${new Date(a.time * 1000).toLocaleString()}
                    </div>
                </div>
                <div>
                    <button class="alert-action-btn" onclick="resolveAlert(${a.id})">🛠️ Работает</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error("Ошибка алертов:", err);
    }
}

function updateUI(host) {
    const badge = document.getElementById('globalStatus');
    const statusText = document.getElementById('statusText');
    if (statusText) statusText.innerText = host.status;
    badge.className = 'status-pill ' + (host.status === 'ONLINE' ? 'status-online' : 'status-offline');

    if (host.sys_info) {
        document.getElementById('infoOS').innerText = host.sys_info.os || '-';
        document.getElementById('infoCores').innerText = host.sys_info.cpu_cores || '-';
        document.getElementById('infoIP').innerText = host.sys_info.ip_address || '-';
        document.getElementById('infoUptime').innerText = host.sys_info.uptime || '-';
        
        // Встраиваем данные о железе в новую вкладку
        document.getElementById('hwCpu').innerText = host.sys_info.cpu_name || 'Неизвестно';
        document.getElementById('hwGpu').innerText = host.sys_info.gpu_name || 'Неизвестно';
        document.getElementById('hwRam').innerText = host.sys_info.ram_total || '-';
        document.getElementById('hwDisk').innerText = host.sys_info.disk_total || '-';
    }

    document.getElementById('cpuVal').innerText = host.cpu + '%';
    document.getElementById('cpuBar').style.width = host.cpu + '%';
    document.getElementById('ramVal').innerText = host.ram + '%';
    document.getElementById('ramBar').style.width = host.ram + '%';
    document.getElementById('diskVal').innerText = host.disk + '%';
    document.getElementById('diskBar').style.width = host.disk + '%';
    document.getElementById('diskSpeedVal').innerText = `R: ${host.disk_read} MB/s | W: ${host.disk_write} MB/s`;
    document.getElementById('netVal').innerText = `↓ ${host.net_recv} KB/s | ↑ ${host.net_sent} KB/s`;

    const termLabel = document.getElementById('terminalHostLabel');
    if (termLabel) termLabel.innerText = host.host_id;

    const srvList = document.getElementById('servicesList');
    if (host.services && host.services.length > 0) {
        srvList.innerHTML = host.services.map(s => `
            <li>
                <span>${s.name}</span>
                <span class="tag-${s.status}">${s.status.toUpperCase()}</span>
            </li>
        `).join('');
    } else {
        srvList.innerHTML = '<li>Службы не найдены</li>';
    }

    const httpList = document.getElementById('httpList');
    if (host.http_checks && host.http_checks.length > 0) {
        httpList.innerHTML = host.http_checks.map(h => `
            <li>
                <span>${h.name} (${h.latency_ms}ms)</span>
                <span class="tag-${h.status.toLowerCase()}">${h.status} [${h.code}]</span>
            </li>
        `).join('');
    } else {
        httpList.innerHTML = '<li>Проверки недоступны</li>';
    }

    currentProcesses = host.top_processes || [];
    renderProcesses();
}

function renderProcesses() {
    const searchVal = document.getElementById('processSearch').value.toLowerCase();
    const procTable = document.getElementById('processTable');
    
    const filtered = currentProcesses.filter(p => 
        p.name.toLowerCase().includes(searchVal) || String(p.pid).includes(searchVal)
    );

    document.getElementById('processCount').innerText = filtered.length;

    if (filtered.length > 0) {
        procTable.innerHTML = filtered.map(p => `
            <tr>
                <td><code>${p.pid}</code></td>
                <td><strong>${p.name}</strong></td>
                <td style="color:#ef4444">${p.cpu}%</td>
                <td style="color:#3b82f6">${p.ram}%</td>
            </tr>
        `).join('');
    } else {
        procTable.innerHTML = '<tr><td colspan="4">Процессы не найдены</td></tr>';
    }
}

document.getElementById('processSearch').addEventListener('input', renderProcesses);

document.getElementById('terminalForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('terminalInput');
    const cmd = input.value.trim();
    if (!cmd) return;

    const win = document.getElementById('terminalWindow');
    
    const cmdLine = document.createElement('div');
    cmdLine.className = 'term-line';
    cmdLine.innerText = `❯ ${cmd}`;
    win.appendChild(cmdLine);
    
    input.value = '';

    try {
        const res = await fetch('/api/v1/terminal/exec', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();
        
        const outLine = document.createElement('div');
        outLine.className = 'term-line sys';
        outLine.innerText = data.output;
        win.appendChild(outLine);
    } catch (err) {
        const errLine = document.createElement('div');
        errLine.className = 'term-line err';
        errLine.innerText = `❌ Ошибка выполнения: ${err.message}`;
        win.appendChild(errLine);
    }

    win.scrollTop = win.scrollHeight;
});

document.getElementById('clearTermBtn').addEventListener('click', () => {
    document.getElementById('terminalWindow').innerHTML = '<div class="term-line sys">Консоль очищена.</div>';
});

async function tick() {
    await fetchHosts();
    await fetchMetrics();
    await fetchAlerts();
}

tick();
setInterval(tick, 3000);
