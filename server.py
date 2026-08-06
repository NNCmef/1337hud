import sqlite3
import json
import time
import subprocess
import platform
import socket
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

app = FastAPI(title="1337 Control Server v3.6")

# CORS для работы с мобильным iOS приложением
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "metrics.db"

app.mount("/static", StaticFiles(directory="frontend"), name="static")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id TEXT,
            cpu_usage REAL,
            ram_usage REAL,
            disk_usage REAL,
            net_sent_kb REAL,
            net_recv_kb REAL,
            timestamp INTEGER,
            sys_info TEXT,
            top_processes TEXT
        )
    ''')
    
    new_cols = [
        "disk_read_mb REAL DEFAULT 0.0",
        "disk_write_mb REAL DEFAULT 0.0",
        "services TEXT DEFAULT '[]'",
        "http_checks TEXT DEFAULT '[]'"
    ]
    for col in new_cols:
        try:
            cursor.execute(f"ALTER TABLE metrics ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id TEXT,
            level TEXT,
            message TEXT,
            timestamp INTEGER
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS terminal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id TEXT,
            command TEXT,
            output TEXT,
            timestamp INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

class MetricData(BaseModel):
    host_id: str
    cpu_usage: float
    ram_usage: float
    disk_usage: float
    disk_read_mb: float = 0.0
    disk_write_mb: float = 0.0
    net_sent_kb: float
    net_recv_kb: float
    timestamp: int
    sys_info: Dict[str, Any] = {}
    services: List[Dict[str, Any]] = []
    http_checks: List[Dict[str, Any]] = []
    top_processes: List[Dict[str, Any]] = []

class UniversalCommandPayload(BaseModel):
    host_id: Optional[str] = "my-local-pc"
    host: Optional[str] = "my-local-pc"
    command: Optional[str] = ""
    cmd: Optional[str] = ""
    text: Optional[str] = ""

def run_system_command(cmd_str: str) -> str:
    """Безопасное исполнение команд с автоподбором кодировки Windows/Linux"""
    if not cmd_str or not cmd_str.strip():
        return "Пустая команда."
    try:
        res = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            timeout=8
        )
        raw_bytes = res.stdout if res.stdout else res.stderr
        if not raw_bytes:
            return "Команда выполнена (без вывода)."
        
        encodings = ['cp866', 'cp1251', 'utf-8'] if platform.system() == 'Windows' else ['utf-8', 'latin-1']
        for enc in encodings:
            try:
                out = raw_bytes.decode(enc)
                if out and len(out.strip()) > 0:
                    return out.strip()
            except Exception:
                continue
        return raw_bytes.decode('utf-8', errors='replace').strip()
    except subprocess.TimeoutExpired:
        return "❌ Ошибка: Превышен лимит времени выполнения (8 сек)."
    except Exception as e:
        return f"❌ Ошибка выполнения: {str(e)}"

def check_alerts(data: MetricData):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if data.cpu_usage > 85.0:
        cursor.execute("INSERT INTO alerts (host_id, level, message, timestamp) VALUES (?, ?, ?, ?)",
                       (data.host_id, "CRITICAL", f"Высокая загрузка CPU: {data.cpu_usage}%", data.timestamp))
        
    for srv in data.services:
        if srv.get("status") == "stopped":
            cursor.execute("INSERT INTO alerts (host_id, level, message, timestamp) VALUES (?, ?, ?, ?)",
                           (data.host_id, "WARNING", f"Служба {srv.get('name')} остановлена!", data.timestamp))

    conn.commit()
    conn.close()

@app.post("/api/v1/metrics")
def receive_metrics(data: MetricData):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO metrics (host_id, cpu_usage, ram_usage, disk_usage, disk_read_mb, disk_write_mb, net_sent_kb, net_recv_kb, timestamp, sys_info, services, http_checks, top_processes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.host_id, data.cpu_usage, data.ram_usage, data.disk_usage,
        data.disk_read_mb, data.disk_write_mb, data.net_sent_kb, data.net_recv_kb, data.timestamp,
        json.dumps(data.sys_info), json.dumps(data.services), json.dumps(data.http_checks), json.dumps(data.top_processes)
    ))
    conn.commit()
    conn.close()
    
    check_alerts(data)
    return {"status": "ok"}

@app.get("/api/v1/hosts")
def get_hosts():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 🎯 Берём строго СВЕЖАЙШУЮ запись (MAX id), чтобы статус не мигал
    cursor.execute('''
        SELECT host_id, cpu_usage, ram_usage, disk_usage, net_recv_kb, net_sent_kb, timestamp, sys_info, top_processes, services, http_checks, disk_read_mb, disk_write_mb
        FROM metrics
        WHERE id IN (SELECT MAX(id) FROM metrics GROUP BY host_id)
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    current_time = int(time.time())
    hosts = []
    
    for r in rows:
        last_seen = r[6] or 0
        is_online = (current_time - last_seen) < 30
        
        sys_info = json.loads(r[7]) if r[7] else {}
        top_procs = json.loads(r[8]) if r[8] else []
        services = json.loads(r[9]) if r[9] else []
        http_checks = json.loads(r[10]) if r[10] else []

        hosts.append({
            "host_id": r[0] or "unknown",
            "cpu": float(r[1] or 0.0),
            "ram": float(r[2] or 0.0),
            "disk": float(r[3] or 0.0),
            "net_recv": float(r[4] or 0.0),
            "net_sent": float(r[5] or 0.0),
            "last_seen": int(last_seen),
            "status": "ONLINE" if is_online else "OFFLINE",
            "sys_info": {
                "os": sys_info.get("os", "Unknown OS"),
                "cpu_cores": sys_info.get("cpu_cores", 1),
                "ip_address": sys_info.get("ip_address", "-"),
                "uptime": sys_info.get("uptime", "-")
            },
            "top_processes": top_procs,
            "services": services,
            "http_checks": http_checks,
            "disk_read": float(r[11] or 0.0),
            "disk_write": float(r[12] or 0.0)
        })
    return {"hosts": hosts}

@app.get("/api/v1/metrics/{host_id}")
def get_host_metrics(host_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT cpu_usage, ram_usage, net_recv_kb, net_sent_kb, timestamp FROM metrics WHERE host_id = ? ORDER BY id DESC LIMIT 20", (host_id,))
    rows = cursor.fetchall()
    conn.close()
    rows.reverse()
    return {"metrics": rows}

@app.get("/api/v1/alerts")
def get_alerts():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT host_id, level, message, timestamp FROM alerts ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    return {"alerts": [{"host": r[0], "level": r[1], "message": r[2], "time": r[3]} for r in rows]}

# 🛠️ МАРШРУТЫ ТЕРМИНАЛА (ОТДАЮТ ВСЕ ВОЗМОЖНЫЕ ПОЛЯ ДЛЯ SWIFT)
@app.post("/api/v1/commands")
@app.post("/api/v1/commands/terminal")
@app.post("/api/v1/commands/terminal/{host_id}")
@app.post("/api/v1/terminal/exec")
def handle_universal_command(payload: UniversalCommandPayload, host_id: Optional[str] = None):
    target_host = host_id or payload.host_id or payload.host or "my-local-pc"
    cmd_str = payload.command or payload.cmd or payload.text or ""
    
    now = int(time.time())
    if not cmd_str.strip():
        empty_res = {
            "id": 0, "host_id": target_host, "host": target_host,
            "command": "", "cmd": "", "output": "Пустая команда",
            "result": "Пустая команда", "response": "Пустая команда", "message": "Пустая команда",
            "status": "error", "timestamp": now
        }
        return {**empty_res, "logs": [empty_res], "history": [empty_res]}
    
    out_text = run_system_command(cmd_str)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO terminal_history (host_id, command, output, timestamp) VALUES (?, ?, ?, ?)",
        (target_host, cmd_str, out_text, now)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    item = {
        "id": new_id,
        "host_id": target_host,
        "host": target_host,
        "command": cmd_str,
        "cmd": cmd_str,
        "output": out_text,
        "result": out_text,
        "response": out_text,
        "message": out_text,
        "data": out_text,
        "status": "ok",
        "timestamp": now
    }
    
    return {
        **item,
        "logs": [item],
        "history": [item],
        "commands": [item]
    }

@app.get("/api/v1/commands")
@app.get("/api/v1/commands/terminal")
@app.get("/api/v1/commands/terminal/{host_id}")
def get_universal_history(host_id: Optional[str] = None):
    target_host = host_id or "my-local-pc"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, host_id, command, output, timestamp FROM terminal_history WHERE host_id = ? ORDER BY id ASC LIMIT 50",
        (target_host,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    now = int(time.time())
    if not rows:
        init_item = {
            "id": 1, "host_id": target_host, "host": target_host,
            "command": "system.init", "cmd": "system.init",
            "output": f"1337 Shell Ready [{target_host}]",
            "result": f"1337 Shell Ready [{target_host}]",
            "response": f"1337 Shell Ready [{target_host}]",
            "message": f"1337 Shell Ready [{target_host}]",
            "status": "ok", "timestamp": now
        }
        return [init_item]
        
    return [
        {
            "id": r[0], "host_id": r[1], "host": r[1],
            "command": r[2] or "", "cmd": r[2] or "",
            "output": r[3] or "", "result": r[3] or "",
            "response": r[3] or "", "message": r[3] or "",
            "status": "ok", "timestamp": r[4] or 0
        }
        for r in rows
    ]

@app.get("/")
def read_index():
    return FileResponse("frontend/index.html")

if __name__ == "__main__":
    import uvicorn
    local_ip = get_local_ip()
    print("=" * 60)
    print(f"🚀 Сервер v3.6 успешно запущен!")
    print(f"📱 Адрес для iOS: http://{local_ip}:8000")
    print(f"💻 Веб-панель: http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)