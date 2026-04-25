import socket
import webbrowser
from contextlib import closing
from http.server import ThreadingHTTPServer

from .config_store import ConfigStore
from .database import Database
from .paths import ensure_directories
from .rules import RuleStore, ensure_rule_files
from .server import build_handler


def _find_available_port(preferred_port):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        if sock.connect_ex(("127.0.0.1", preferred_port)) != 0:
            return preferred_port

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(host="127.0.0.1", port=8765, open_browser=True):
    ensure_directories()
    ensure_rule_files()

    config_store = ConfigStore()
    database = Database()
    database.initialize()
    rules = RuleStore()

    services = {
        "config": config_store,
        "database": database,
        "rules": rules,
    }

    real_port = _find_available_port(port)
    handler = build_handler(services)
    httpd = ThreadingHTTPServer((host, real_port), handler)
    app_url = f"http://{host}:{real_port}"

    print(f"农场自动提醒已启动：{app_url}")
    if open_browser:
        webbrowser.open(app_url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("服务已停止。")
    finally:
        httpd.server_close()
