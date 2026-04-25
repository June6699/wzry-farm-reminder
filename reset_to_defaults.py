from pathlib import Path
import shutil
import subprocess
import sqlite3

from farm_reminder.config_store import ConfigStore, DEFAULT_CONFIG
from farm_reminder.database import Database
from farm_reminder.paths import AVATAR_DIR, BACKUP_DIR, CONFIG_PATH, DB_PATH, ensure_directories
from farm_reminder.rules import ensure_rule_files


def remove_path(path: Path):
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def stop_local_server():
    command = """
    Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue };
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        ($_.Name -eq 'python.exe' -or $_.Name -eq 'py.exe') -and
        $_.CommandLine -like '*main.py*'
      } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode == 0


def reset_database():
    db = Database()
    db.initialize()
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.executescript(
            """
            DELETE FROM slot_states;
            DELETE FROM wallet_ledger;
            DELETE FROM activity_logs;
            DELETE FROM raid_logs;
            DELETE FROM theft_logs;
            DELETE FROM sqlite_sequence;
            """
        )
        connection.commit()
    finally:
        connection.close()


def main():
    ensure_directories()
    stop_local_server()

    if CONFIG_PATH.exists():
        remove_path(CONFIG_PATH)

    if AVATAR_DIR.exists():
        for child in AVATAR_DIR.iterdir():
            remove_path(child)
    if BACKUP_DIR.exists():
        for child in BACKUP_DIR.iterdir():
            remove_path(child)

    ensure_rule_files()
    reset_database()
    ConfigStore().save(DEFAULT_CONFIG)
    print("已恢复默认设置和空白日志数据。")


if __name__ == "__main__":
    main()
