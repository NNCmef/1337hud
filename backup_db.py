import os
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "metrics.db")))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(BASE_DIR / "backups")))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "14"))


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_DIR / f"metrics_{timestamp}.db"

    with sqlite3.connect(DATABASE_PATH) as source:
        with sqlite3.connect(destination) as target:
            source.backup(target)

    backups = sorted(BACKUP_DIR.glob("metrics_*.db"), key=lambda path: path.stat().st_mtime)
    for old_backup in backups[:-BACKUP_KEEP] if BACKUP_KEEP > 0 else []:
        old_backup.unlink()

    return destination


if __name__ == "__main__":
    result = create_backup()
    print(f"Backup created: {result}")
