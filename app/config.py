"""Voyager 1 科研助手 - 配置加载与保存:config.json 位于应用根目录。"""
import json
import sys
import threading
from pathlib import Path

if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(sys.executable).resolve().parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config.json"
DATA_DIR = PROJECT_DIR / "data"

DEFAULTS = {
    "deepseek_api_key": "",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "temperature": 0.7,  # 学术严谨,不跳脱
    "max_tokens": 2048,
    "passphrases": {"layer1": "", "layer2": ""},
    "memory": {"recent_messages": 30, "max_facts": 8},
    "compact": {
        "auto_compact": True,
        "compact_window": 20,
        "min_messages": 8,
        "throttle_seconds": 60,
        "max_chars": 1600,
    },
    "search": {
        "enabled": True,
        "max_results": 5,
        "timeout": 8,
        "preferred_domains": [
            "arxiv.org",
            "pubmed.ncbi.nlm.nih.gov",
            "nature.com",
            "science.org",
            "cell.com",
            "thelancet.com",
            "sciencedirect.com",
            "scholar.google.com",
            "semanticscholar.org",
        ],
        "blocked_domains": ["zhihu.com", "baike.baidu.com"],
    },
    "rumination": {
        "enabled": True,
        "idle_minutes": 5,
        "max_searches": 2,
        "max_context": 40,
        "max_tokens": 800,
    },
    "curiosity": {
        "enabled": True,
        "interval_hours": 6,
        "max_topics": 2,
    },
    "initiative": {
        "enabled": True,
        "min_idle_minutes": 20,
        "min_gap_hours": 6,
        "chance": 0.6,
    },
    "screen": {
        "enabled": True,
        "interval_seconds": 60,
        "ocr": True,
        "ocr_max_chars": 300,
    },
    "situation": {
        "enabled": True,
        "judge_interval_minutes": 10,
        "max_age_minutes": 15,
    },
    "procs": {
        "enabled": True,
        "interval_seconds": 60,
    },
    "science": {
        "enabled": True,
        "max_results": 3,
        "keywords": [
            "科学", "物理", "医学", "生物", "化学", "天文", "航天", "神经",
            "基因", "量子", "研究", "论文", "期刊", "最新进展", "诺奖",
            "诺贝尔", "黑洞", "癌症", "疫苗", "临床", "药物", "粒子",
            "宇宙", "进化", "细胞", "nature", "science", "cell", "lancet",
            "pubmed", "arxiv", "doi", "physics", "biology", "medicine",
            "astronomy", "quantum", "genome", "cancer", "vaccine", "clinical",
            "论文", "文献", "综述", "预印本", "实验", "数据", "理论",
        ],
    },
    "ansys": {
        "enabled": True,
        "runwb_path": "",
        "timeout": 1800,
    },
    "ui": {
        "bubble_opacity": 0.9,
    },
}


class Config:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        merged = json.loads(json.dumps(DEFAULTS))
        if self.path.exists():
            try:
                user = json.loads(self.path.read_text(encoding="utf-8"))
                _deep_merge(merged, user)
            except Exception:
                pass
        return merged

    def get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, value, *keys):
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    def save(self):
        with self._lock:
            try:
                self.path.write_text(
                    json.dumps(self._data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass


def _deep_merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
