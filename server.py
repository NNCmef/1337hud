import sqlite3
import json
import time
import subprocess
import platform
import socket
import hashlib
import secrets
import os
from pathlib import Path
from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

app = FastAPI(title="1337 Control Server v3.8")

# CORS для работы с мобильными клиентами
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent

def load_dotenv_file(path: Path):
    """Минимальный загрузчик .env без внешней зависимости."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

load_dotenv_file(BASE_DIR / ".env")
DB_NAME = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "metrics.db")))
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "change-me-local-agent-key")
MOBILE_API_KEY = os.getenv("MOBILE_API_KEY", "change-me-local-mobile-key")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

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
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    
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
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id TEXT,
            incident_key TEXT,
            level TEXT,
            message TEXT,
            status TEXT DEFAULT 'active',
            created_at INTEGER
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT,
            expires_at INTEGER
        )
    ''')

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_host_time ON metrics(host_id, timestamp DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_status_host ON incidents(status, host_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_terminal_host_time ON terminal_history(host_id, timestamp DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")
    
    conn.commit()
    conn.close()

init_db()

# =========================================================
# СИСТЕМА АВТОРИЗАЦИИ
# =========================================================

class AuthData(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
            )
            return secrets.compare_digest(candidate.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    # Совместимость со старыми аккаунтами; после входа хеш обновляется.
    legacy_hash = hashlib.sha256((password + "1337_salt_secret").encode()).hexdigest()
    return secrets.compare_digest(legacy_hash, stored_hash)

def check_auth(request: Request):
    api_key = request.headers.get("X-API-Key")
    if api_key and secrets.compare_digest(api_key, MOBILE_API_KEY):
        return "mobile_client"
        
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Не авторизован")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username, expires_at FROM sessions WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or row[1] < int(time.time()):
        raise HTTPException(status_code=401, detail="Сессия истекла")
    return row[0]

@app.post("/api/v1/auth/register")
def register(data: AuthData):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                       (data.username, hash_password(data.password)))
        conn.commit()
        return {"status": "ok", "message": "Профиль создан. Выполните вход."}
    except sqlite3.IntegrityError:
        return {"status": "error", "message": "Логин уже используется"}
    finally:
        conn.close()

@app.post("/api/v1/auth/login")
def login(data: AuthData):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (data.username,))
    row = cursor.fetchone()
    
    if not row or not verify_password(data.password, row[0]):
        conn.close()
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")

    if not row[0].startswith("pbkdf2_sha256$"):
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password(data.password), data.username)
        )
        
    token = secrets.token_hex(32)
    expires = int(time.time()) + (86400 * 7)
    
    cursor.execute("INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)", 
                   (token, data.username, expires))
    conn.commit()
    conn.close()
    
    response = JSONResponse(content={"status": "ok", "message": "Успешный вход"})
    response.set_cookie(
        key="session_token", value=token, httponly=True, samesite="lax",
        secure=COOKIE_SECURE, max_age=86400*7
    )
    return response

@app.post("/api/v1/auth/logout")
def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie("session_token")
    return response


# =========================================================
# МОДЕЛИ МЕТРИК И УТИЛИТЫ
# =========================================================

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
    sys_info: Dict[str, Any] = Field(default_factory=dict)
    services: List[Dict[str, Any]] = Field(default_factory=list)
    http_checks: List[Dict[str, Any]] = Field(default_factory=list)
    top_processes: List[Dict[str, Any]] = Field(default_factory=list)

class UniversalCommandPayload(BaseModel):
    host_id: Optional[str] = "my-local-pc"
    host: Optional[str] = "my-local-pc"
    command: Optional[str] = ""
    cmd: Optional[str] = ""
    text: Optional[str] = ""

def run_system_command(cmd_str: str) -> str:
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
    
    def handle_incident(incident_key: str, level: str, message: str):
        cursor.execute("SELECT id FROM incidents WHERE host_id = ? AND incident_key = ? AND status = 'active'", (data.host_id, incident_key))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO incidents (host_id, incident_key, level, message, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
                           (data.host_id, incident_key, level, message, data.timestamp))
    
    if data.cpu_usage > 85.0:
        handle_incident("cpu_high", "CRITICAL", f"Высокая загрузка CPU: {data.cpu_usage}%")
        
    for srv in data.services:
        if srv.get("status") == "stopped":
            handle_incident(f"srv_{srv.get('name')}", "WARNING", f"Служба {srv.get('name')} остановлена!")

    conn.commit()
    conn.close()

# ЭНДПОИНТ ДЛЯ АГЕНТА
@app.post("/api/v1/metrics")
def receive_metrics(data: MetricData, x_agent_token: str = Header(default="", alias="X-Agent-Token")):
    if not x_agent_token or not secrets.compare_digest(x_agent_token, AGENT_API_KEY):
        raise HTTPException(status_code=401, detail="Неверный токен агента")
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


# =========================================================
# ЗАЩИЩЕННЫЕ ЭНДПОИНТЫ API
# =========================================================

@app.get("/api/v1/hosts", dependencies=[Depends(check_auth)])
def get_hosts():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
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
        
        # Полностью прокидываем весь JSON на фронтенд без фильтрации!
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
            "sys_info": sys_info, # <-- ИСПРАВЛЕНИЕ ЗДЕСЬ
            "top_processes": top_procs,
            "services": services,
            "http_checks": http_checks,
            "disk_read": float(r[11] or 0.0),
            "disk_write": float(r[12] or 0.0)
        })
    return {"hosts": hosts}

@app.get("/api/v1/metrics/{host_id}", dependencies=[Depends(check_auth)])
def get_host_metrics(host_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT cpu_usage, ram_usage, net_recv_kb, net_sent_kb, timestamp FROM metrics WHERE host_id = ? ORDER BY id DESC LIMIT 20", (host_id,))
    rows = cursor.fetchall()
    conn.close()
    rows.reverse()
    return {"metrics": rows}

@app.get("/api/v1/alerts", dependencies=[Depends(check_auth)])
def get_alerts():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, host_id, level, message, created_at FROM incidents WHERE status = 'active' ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"alerts": [{"id": r[0], "host": r[1], "level": r[2], "message": r[3], "time": r[4]} for r in rows]}

@app.post("/api/v1/alerts/{alert_id}/resolve", dependencies=[Depends(check_auth)])
def resolve_alert(alert_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE incidents SET status = 'resolved' WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/v1/commands", dependencies=[Depends(check_auth)])
@app.post("/api/v1/commands/terminal", dependencies=[Depends(check_auth)])
@app.post("/api/v1/commands/terminal/{host_id}", dependencies=[Depends(check_auth)])
@app.post("/api/v1/terminal/exec", dependencies=[Depends(check_auth)])
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

@app.get("/api/v1/commands", dependencies=[Depends(check_auth)])
@app.get("/api/v1/commands/terminal", dependencies=[Depends(check_auth)])
@app.get("/api/v1/commands/terminal/{host_id}", dependencies=[Depends(check_auth)])
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

# =========================================================
# МАРШРУТЫ HTML-ИНТЕРФЕЙСА
# =========================================================

@app.get("/login", response_class=HTMLResponse)
def read_login():
    return FileResponse("frontend/login.html")

@app.get("/")
def read_index(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return RedirectResponse(url="/login", status_code=302)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username, expires_at FROM sessions WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or row[1] < int(time.time()):
        return RedirectResponse(url="/login", status_code=302)
        
    return FileResponse("frontend/index.html")

if __name__ == "__main__":
    import uvicorn
    local_ip = get_local_ip()
    print("=" * 60)
    print(f"🚀 Сервер v3.8 (Полный проброс железа) успешно запущен!")
    print(f"📱 Адрес для iOS: http://{local_ip}:8000")
    print(f"💻 Веб-панель: http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
