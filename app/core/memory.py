"""SQLite 长期记忆:会话、消息、事实、学习笔记、元数据、搜索日志。"""
import json
import sqlite3
import threading
import time
import urllib.parse
from collections import Counter
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created REAL NOT NULL,
  updated REAL NOT NULL,
  summary TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL UNIQUE,
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  content TEXT NOT NULL,
  sources TEXT DEFAULT '[]',
  kind TEXT DEFAULT 'learn',
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  url TEXT NOT NULL DEFAULT '',
  accepted INTEGER NOT NULL DEFAULT 1,
  ts REAL NOT NULL
);
"""


class Memory:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else None
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.db_path) if self.db_path else ":memory:",
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)
            # 老库迁移:notes 增加 kind 列(learn=对话学习 / curiosity=自我兴趣)
            try:
                self._conn.execute("ALTER TABLE notes ADD COLUMN kind TEXT DEFAULT 'learn'")
            except sqlite3.OperationalError:
                pass
            self._conn.commit()
        self.session_id = self.new_session()

    def _query(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def new_session(self):
        now = time.time()
        cur = self._exec(
            "INSERT INTO sessions(created, updated) VALUES(?,?)", (now, now)
        )
        return cur.lastrowid

    def add_message(self, role, content):
        now = time.time()
        self._exec(
            "INSERT INTO messages(session_id, role, content, ts) VALUES(?,?,?,?)",
            (self.session_id, role, content, now),
        )
        self._exec(
            "UPDATE sessions SET updated=? WHERE id=?", (now, self.session_id)
        )

    def recent_messages(self, limit=12):
        rows = self._query(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (self.session_id, limit),
        )
        return [
            {"role": r["role"], "content": r["content"]}
            for r in reversed(rows)
        ]

    def messages_since(self, ts, limit=200):
        rows = self._query(
            "SELECT role, content, ts FROM messages WHERE session_id=? AND ts>? ORDER BY id ASC LIMIT ?",
            (self.session_id, ts, limit),
        )
        return [
            {"role": r["role"], "content": r["content"], "ts": r["ts"]}
            for r in rows
        ]

    def append_summary(self, text):
        text = (text or "").strip()
        if text:
            self._exec(
                "UPDATE sessions SET summary = summary || ? WHERE id=?",
                ("\n" + text, self.session_id),
            )

    def add_fact(self, text):
        text = (text or "").strip()
        if not text or len(text) > 500:
            return
        try:
            self._exec(
                "INSERT INTO facts(text, ts) VALUES(?,?)", (text, time.time())
            )
        except sqlite3.IntegrityError:
            pass

    def get_facts(self, limit=5):
        rows = self._query(
            "SELECT text FROM facts ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [r["text"] for r in reversed(rows)]

    def list_facts(self, limit=200):
        """带 id 的事实列表(供记忆界面展示与删除)。"""
        rows = self._query(
            "SELECT id, text, ts FROM facts ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [{"id": r["id"], "text": r["text"], "ts": r["ts"]} for r in rows]

    def delete_fact(self, fact_id):
        self._exec("DELETE FROM facts WHERE id=?", (fact_id,))

    def clear_facts(self):
        self._exec("DELETE FROM facts")

    def add_note(self, topic, content, sources=None, kind="learn"):
        self._exec(
            "INSERT INTO notes(topic, content, sources, kind, ts) VALUES(?,?,?,?,?)",
            (
                topic,
                content,
                json.dumps(sources or [], ensure_ascii=False),
                kind,
                time.time(),
            ),
        )

    def latest_notes(self, limit=2):
        rows = self._query(
            "SELECT topic, content, sources, kind FROM notes ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        out = []
        for r in reversed(rows):
            try:
                srcs = json.loads(r["sources"])
            except Exception:
                srcs = []
            out.append(
                {
                    "topic": r["topic"],
                    "content": r["content"],
                    "sources": srcs,
                    "kind": r["kind"] or "learn",
                }
            )
        return out

    def list_notes(self, limit=200):
        """带 id 的笔记列表(供记忆界面展示与删除)。"""
        rows = self._query(
            "SELECT id, topic, content, kind, ts FROM notes ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {"id": r["id"], "topic": r["topic"], "content": r["content"],
             "kind": r["kind"] or "learn", "ts": r["ts"]}
            for r in rows
        ]

    def delete_note(self, note_id):
        self._exec("DELETE FROM notes WHERE id=?", (note_id,))

    def clear_notes(self):
        self._exec("DELETE FROM notes")

    def clear_conversation(self):
        """清空当前会话的对话记录(消息与摘要),保留会话骨架。"""
        self._exec("DELETE FROM messages WHERE session_id=?", (self.session_id,))
        self._exec("UPDATE sessions SET summary='' WHERE id=?", (self.session_id,))

    def get_summary(self, limit=800):
        """读取本会话累积摘要(取末尾 limit 字符)。"""
        rows = self._query(
            "SELECT summary FROM sessions WHERE id=?", (self.session_id,)
        )
        if not rows or not rows[0]["summary"]:
            return ""
        return rows[0]["summary"][-limit:]

    def overflow_messages(self, window=20, cap=200):
        """返回比「最新 window 条」更早的消息(按时间正序),用于滚动整理。"""
        rows = self._query(
            "SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 1 OFFSET ?",
            (self.session_id, max(0, window - 1)),
        )
        if not rows:
            return []
        cutoff = rows[0]["id"]
        return self._query(
            "SELECT id, role, content FROM messages WHERE session_id=? AND id<=? ORDER BY id ASC LIMIT ?",
            (self.session_id, cutoff, cap),
        )

    def get_meta(self, key, default=None):
        rows = self._query("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_meta(self, key, value):
        self._exec(
            "INSERT INTO meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def log_search(self, query, url, accepted=True):
        self._exec(
            "INSERT INTO search_log(query, url, accepted, ts) VALUES(?,?,?,?)",
            (query, url or "", 1 if accepted else 0, time.time()),
        )

    def accepted_domains(self, min_count=2):
        rows = self._query(
            "SELECT url FROM search_log WHERE accepted=1 AND url<>''"
        )
        cnt = Counter()
        for r in rows:
            try:
                host = urllib.parse.urlparse(r["url"]).netloc.lower()
                if host:
                    cnt[host] += 1
            except Exception:
                pass
        return [d for d, c in cnt.most_common(10) if c >= min_count]

    def reset(self):
        """清空全部记忆(消息/会话/事实/笔记/元数据/搜索日志),开启全新会话。"""
        with self._lock:
            for table in (
                "search_log", "meta", "notes", "facts", "messages", "sessions",
            ):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()
        self.session_id = self.new_session()

    def close(self):
        try:
            with self._lock:
                self._conn.close()
        except Exception:
            pass
