import time
import platform
import psutil
import requests
import subprocess
import os
import socket

# -------------------------------------------------------------
# НАСТРОЙКИ АГЕНТА
# -------------------------------------------------------------
def load_dotenv_file(path):
    """Минимальный загрузчик .env без внешней зависимости."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_dotenv_file(os.path.join(os.path.dirname(__file__), ".env"))
SERVER_URL = os.getenv("SERVER_URL", "http://192.168.1.62:8000/api/v1/metrics")
HOST_ID = os.getenv("HOST_ID", platform.node() or "unknown-host")
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "change-me-local-agent-key")
INTERVAL = int(os.getenv("INTERVAL", "3"))
# -------------------------------------------------------------

HW_INFO = {
    "cpu_name": "Неизвестно",
    "gpu_name": "Неизвестно",
    "ram_total": "0 GB",
    "disk_total": "0 GB"
}

def init_hw_info():
    """Единоразовый сбор статического железа при запуске агента"""
    global HW_INFO
    
    # 1. ОЗУ (Всегда работает безотказно через psutil)
    ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    HW_INFO["ram_total"] = f"{ram_gb} GB"
    
    # 2. Диск
    disk_path = 'C:\\' if platform.system() == 'Windows' else '/'
    disk_gb = round(psutil.disk_usage(disk_path).total / (1024**3), 1)
    HW_INFO["disk_total"] = f"{disk_gb} GB"
    
    # 3. CPU и GPU (Современный метод через PowerShell для Windows 11)
    try:
        if platform.system() == 'Windows':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Собираем красивое имя CPU
            cpu_res = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"], 
                text=True, startupinfo=si
            )
            if cpu_res.strip():
                HW_INFO["cpu_name"] = cpu_res.strip()
                
            # Собираем имя GPU
            gpu_res = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"], 
                text=True, startupinfo=si
            )
            if gpu_res.strip():
                # Если видеокарт несколько (например, встройка + дискретка), склеиваем их красиво
                gpus = [g.strip() for g in gpu_res.strip().split('\n') if g.strip()]
                HW_INFO["gpu_name"] = " + ".join(gpus) if gpus else "Неизвестно"
        else:
            # Резервный метод для Linux
            HW_INFO["cpu_name"] = platform.processor() or "Неизвестный CPU"
            res = subprocess.check_output(["lspci"], text=True)
            vga_lines = [l for l in res.split('\n') if 'VGA' in l or '3D controller' in l]
            if vga_lines:
                HW_INFO["gpu_name"] = vga_lines[0].split(': ')[-1]
    except Exception:
        if HW_INFO["cpu_name"] == "Неизвестно":
            HW_INFO["cpu_name"] = platform.processor() or "Неизвестный CPU"

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

def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()

def get_real_services():
    services = []
    if platform.system() == 'Windows':
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
        target_procs = ['sshd', 'dockerd', 'cron', 'systemd-journald']
        running_names = {p.info['name'] for p in psutil.process_iter(['name'])}
        for name in target_procs:
            status = "running" if any(name in (p or '') for p in running_names) else "stopped"
            services.append({"name": name, "status": status})
            
    return services

def check_http_targets():
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
    
    net_before = psutil.net_io_counters()
    disk_before = psutil.disk_io_counters()
    cpu_val = psutil.cpu_percent(interval=1)
    net_after = psutil.net_io_counters()
    disk_after = psutil.disk_io_counters()
    
    net_recv_kbs = round((net_after.bytes_recv - net_before.bytes_recv) / 1024.0, 1)
    net_sent_kbs = round((net_after.bytes_sent - net_before.bytes_sent) / 1024.0, 1)
    disk_read_mb = 0.0
    disk_write_mb = 0.0
    if disk_before and disk_after:
        disk_read_mb = round((disk_after.read_bytes - disk_before.read_bytes) / (1024**2), 2)
        disk_write_mb = round((disk_after.write_bytes - disk_before.write_bytes) / (1024**2), 2)

    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            pinfo = proc.info
            pid = pinfo['pid']
            name = pinfo['name'] or "unknown"
            
            if pid == 0 or name.lower() in ['system idle process', 'idle']:
                continue
                
            raw_cpu = pinfo['cpu_percent'] or 0.0
            norm_cpu = round(raw_cpu / num_cores, 1)
            
            processes.append({
                "pid": pid,
                "name": name,
                "cpu": norm_cpu,
                "ram": round(pinfo['memory_percent'] or 0.0, 1)
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    top_processes = sorted(processes, key=lambda x: x['cpu'], reverse=True)[:15]
    disk_path = 'C:\\' if platform.system() == 'Windows' else '/'

    return {
        "host_id": HOST_ID,
        "cpu_usage": round(cpu_val, 1),
        "ram_usage": round(psutil.virtual_memory().percent, 1),
        "disk_usage": round(psutil.disk_usage(disk_path).percent, 1),
        "disk_read_mb": disk_read_mb,
        "disk_write_mb": disk_write_mb,
        "net_recv_kb": net_recv_kbs,
        "net_sent_kb": net_sent_kbs,
        "timestamp": int(time.time()),
        "sys_info": {
            "os": f"{platform.system()} {platform.release()}",
            "cpu_cores": num_cores,
            "ip_address": get_local_ip(),
            "uptime": get_uptime_str(),
            "cpu_name": HW_INFO["cpu_name"],
            "gpu_name": HW_INFO["gpu_name"],
            "ram_total": HW_INFO["ram_total"],
            "disk_total": HW_INFO["disk_total"]
        },
        "services": get_real_services(),
        "http_checks": check_http_targets(),
        "top_processes": top_processes
    }

def main():
    print(f"🚀 [1337 Agent] Инициализация узла '{HOST_ID}'...")
    init_hw_info()
    print(f"🖥️  CPU: {HW_INFO['cpu_name']}")
    print(f"🎮  GPU: {HW_INFO['gpu_name']}")
    print(f"📡 Отправка на: {SERVER_URL}")
    
    while True:
        try:
            data = collect_metrics()
            res = requests.post(
                SERVER_URL,
                json=data,
                headers={"X-Agent-Token": AGENT_API_KEY},
                timeout=5
            )
            if res.status_code == 200:
                print(f"[{time.strftime('%H:%M:%S')}] ✅ Метрики обновлены!")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Код ответа сервера: {res.status_code}")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ Ошибка связи с сервером: {e}")
        
        time.sleep(max(1, INTERVAL - 1))

if __name__ == "__main__":
    main()
