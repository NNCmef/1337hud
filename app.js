let currentHost = "";
let timerId = null;
let currentProcesses = [];

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

async function fetchHosts() {
    try {
        const res = await fetch('/api/v1/hosts');
        const data = await res.json();
        const select = document.getElementById('hostSelect');
        
        document.getElementById('totalHosts').innerText = data.hosts.length;
        if (data.hosts.length === 0) return;

        const currentSelected = select.value;
        select.innerHTML = '';
        
        data.hosts.forEach(h => {
            const opt = document.createElement('option');
            opt.value = h.host_id;
            opt.innerText = `${h.host_id} (${h.status})`;
            select.appendChild(opt);
        });

        if (currentSelected && data.hosts.some(h => h.host_id === currentSelected)) {
            select.value = currentSelected;
        } else {
            select.value = data.hosts[0].host_id;
        }

        currentHost = select.value;
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

async function fetchAlerts() {
    try {
        const res = await fetch('/api/v1/alerts');
        const data = await res.json();
        const alertLog = document.getElementById('alertLog');
        
        if (!data.alerts || data.alerts.length === 0) {
            alertLog.innerHTML = '<div class="empty-alert">Алертов пока нет</div>';
            return;
        }

        alertLog.innerHTML = data.alerts.map(a => `
            <div class="alert-item">
                <span><strong>[${a.host}]</strong> ${a.message}</span>
                <span style="color:#64748b">${new Date(a.time * 1000).toLocaleTimeString()}</span>
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

    // Отрисовка реальных служб
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

    // Отрисовка HTTP/Ping проверок
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

    // Процессы
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

// REAL Terminal Execution
document.getElementById('terminalForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('terminalInput');
    const cmd = input.value.trim();
    if (!cmd) return;

    const win = document.getElementById('terminalWindow');
    
    // Пишем введиную команду
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

function setupTimer() {
    if (timerId) clearInterval(timerId);
    const rate = parseInt(document.getElementById('refreshRate').value);
    if (rate > 0) timerId = setInterval(tick, rate);
}

document.getElementById('hostSelect').addEventListener('change', (e) => {
    currentHost = e.target.value;
    tick();
});

document.getElementById('refreshRate').addEventListener('change', setupTimer);

tick();
setupTimer();