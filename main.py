"""Voyager 1 科研助手 - 启动入口。

运行方式(在项目根目录):
    python main.py
"""
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.config import DATA_DIR, Config
from app.core.backdoor import Backdoor
from app.core.memory import Memory
from app.core.search import Searcher
from app.llm import DeepSeekClient


def main():
    from app.config import PROJECT_DIR
    try:
        _main_impl()
    except Exception:
        import traceback
        try:
            (PROJECT_DIR / "error.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
        except Exception:
            pass
        raise


def _main_impl():
    config = Config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    memory = Memory(DATA_DIR / "voyager.db")
    llm = DeepSeekClient(config)
    searcher = Searcher(config)
    backdoor = Backdoor(config, memory)

    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow
    from app.ui.theme import QSS

    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow(config, memory, llm, searcher, backdoor)
    if not config.get("deepseek_api_key", default=""):
        win.status_label.setText("尚未配置 API Key,请在左侧「设置」页填写")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
