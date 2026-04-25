from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "farm_reminder"
DATA_DIR = ROOT_DIR / "data"
RULES_DIR = DATA_DIR / "rules"
ASSETS_DIR = DATA_DIR / "assets"
AVATAR_DIR = ASSETS_DIR / "avatar"
CROP_ASSET_DIR = ASSETS_DIR / "crops"
BACKUP_DIR = DATA_DIR / "backup"
WEB_DIR = ROOT_DIR / "web"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "app.db"
SOURCE_MARKDOWN_PATH = ROOT_DIR / "农场信息.md"


def ensure_directories():
    for directory in (
        DATA_DIR,
        RULES_DIR,
        ASSETS_DIR,
        AVATAR_DIR,
        CROP_ASSET_DIR,
        BACKUP_DIR,
        WEB_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
