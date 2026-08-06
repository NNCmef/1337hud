import time
import platform
import psutil
import requests

# -------------------------------------------------------------
# НАСТРОЙКИ АГЕНТА
# -------------------------------------------------------------
SERVER_URL = "http://192.168.1.62:8000/api/v1/metrics"
HOST_ID = "my-local-pc"
INTERVAL = 3
# -------------------------------------------------------------

def get_uptime_str():
    try:
        boot_time = psutil.boot_time()
        uptime_sec = int(time.time() - boot_time)
        days, remainder = divmod(uptime_sec, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}д {hours}ч {minutes}м"
    except Exception:
        return "н/д"

def get_real_services():
    """Получение реальных системных служб ОС"""
    services = []
    if platform.system() == 'Windows':
        # Проверяем ключевые Windows-службы
        target_services = [
            ('Spooler', 'Диспетчер печати'),
            ('WinDefend', 'Защитник Windows'),
            ('EventLog', 'Журнал событий'),
            ('Dhcp', 'DHCP-клиент'),
            ('wuauserv', 'Центр обновления')
        ]
        for name, display in target_services:
            try:
                s = psutil.win_service_get(name)
                status = "running" if s.status() == "running" else "stopped"
                services.append({"name": f"{display} ({name})", "status": status})
            except Exception:
                pass
    else:
        # Для Linux / macOS проверяем запущенные демоны
        target_procs = ['sshd', 'dockerd', 'cron', 'systemd-journald']
        running_names = {p.info['name'] for p in psutil.process_iter(['name'])}
        for name in target_procs:
            status = "running" if any(name in (p or '') for p in running_names) else "stopped"
            services.append({"name": name, "status": status})
            
    return services

def check_http_targets():
    """Реальная проверка доступности веб-ресурсов и задержки"""
    targets = [
        {"name": "Cloudflare DNS", "url": "https://1.1.1.1"},
        {"name": "Google Web", "url": "https://www.google.com"},
        {"name": "GitHub API", "url": "https://api.github.com"}
    ]
    results = []
    for t in targets:
        try:
            start = time.perf_counter()
            resp = requests.get(t["url"], timeout=2)
            latency = int((time.perf_counter() - start) * 1000)
            results.append({
                "name": t["name"],
                "status": "UP" if resp.status_code < 400 else "DOWN",
                "code": resp.status_code,
                "latency_ms": latency
            })
        except Exception:
            results.append({
                "name": t["name"],
                "status": "DOWN",
                "code": 0,
                "latency_ms": 0
            })
    return results

def collect_metrics():
    num_cores = psutil.cpu_count(logical=True) or 1
    
    # Замер трафика и CPU
    net_before = psutil.net_io_counters()
    cpu_val = psutil.cpu_percent(interval=1)
    net_after = psutil.net_io_counters()
    
    net_recv_kbs = round((net_after.bytes_recv - net_before.bytes_recv) / 1024.0, 1)
    net_sent_kbs = round((net_after.bytes_sent - net_before.bytes_sent) / 1024.0, 1)

    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            pinfo = proc.info
            pid = pinfo['pid']
            name = pinfo['name'] or "unknown"
            
            # 🛑 Исключаем System Idle Process (PID 0) и процессы простоя
            if pid == 0 or name.lower() in ['system idle process', 'idle']:
                continue
                
            raw_cpu = pinfo['cpu_percent'] or 0.0
            # 🧮 Нормализуем процент CPU относительно числа ядер
            norm_cpu = round(raw_cpu / num_cores, 1)
            
            processes.append({
                "pid": pid,
                "name": name,
                "cpu": norm_cpu,
                "ram": round(pinfo['memory_percent'] or 0.0, 1)
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    # Сортируем процессы по нормализованному CPU
    top_processes = sorted(processes, key=lambda x: x['cpu'], reverse=True)[:15]
    disk_path = 'C:\\' if platform.system() == 'Windows' else '/'

    return {
        "host_id": HOST_ID,
        "cpu_usage": round(cpu_val, 1),
        "ram_usage": round(psutil.virtual_memory().percent, 1),
        "disk_usage": round(psutil.disk_usage(disk_path).percent, 1),
        "disk_read_mb": 0.0,
        "disk_write_mb": 0.0,
        "net_recv_kb": net_recv_kbs,
        "net_sent_kb": net_sent_kbs,
        "timestamp": int(time.time()),
        "sys_info": {
            "os": f"{platform.system()} {platform.release()}",
            "cpu_cores": num_cores,
            "ip_address": "127.0.0.1",
            "uptime": get_uptime_str()
        },
        "services": get_real_services(),
        "http_checks": check_http_targets(),
        "top_processes": top_processes
    }

def main():
    print(f"🚀 [1337 Agent] Узел '{HOST_ID}' запущен.")
    print(f"📡 Отправка на: {SERVER_URL}")
    
    while True:
        try:
            data = collect_metrics()
            res = requests.post(SERVER_URL, json=data, timeout=5)
            if res.status_code == 200:
                print(f"[{time.strftime('%H:%M:%S')}] ✅ Метрики и сервисы обновлены!")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Код ответа сервера: {res.status_code}")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ Ошибка связи с сервером: {e}")
        
        time.sleep(max(1, INTERVAL - 1))

if __name__ == "__main__":
    main()