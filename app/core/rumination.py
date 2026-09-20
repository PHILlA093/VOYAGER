"""沉思模式:后台回顾对话、提炼记忆、联网学习 + 自我兴趣探索。"""
import re
import time

from .curiosity import Curiosity
from .situation import now_line

RUMINATE_SYSTEM = (
    "你是一个AI的沉思模块,负责回顾她与「开拓者」的对话。"
    "请用中文输出三部分,严格使用以下格式:\n"
    "【对话摘要】\n(2-4句话概括这段对话:话题、开拓者的状态与需求)\n"
    "【可记忆事实】\n- 事实1\n- 事实2\n(列出关于开拓者的、值得长期记住的事实,"
    "最多5条,没有就写「无」)\n"
    "【值得学习的话题】\n- 话题1\n- 话题2\n"
    "(这段对话里值得联网了解的话题,最多2个,没有就写「无」)"
)


class Rumination:
    def __init__(self, config, memory, llm, searcher, on_status=None, on_log=None):
        self.config = config
        self.memory = memory
        self.llm = llm
        self.searcher = searcher
        self.on_status = on_status
        self.on_log = on_log

    def _log(self, msg):
        if self.on_log:
            self.on_log(msg)

    @staticmethod
    def _section(text, start, end):
        if start not in text:
            return ""
        body = text.split(start, 1)[1]
        if end and end in body:
            body = body.split(end, 1)[0]
        return body

    def _analyze(self, transcript):
        try:
            reply = self.llm.complete(
                [
                    {"role": "system", "content": RUMINATE_SYSTEM},
                    {"role": "user", "content": now_line() + "\n" + transcript},
                ],
                max_tokens=self.config.get("rumination", "max_tokens", default=800),
                temperature=0.6,
                timeout=90,
            )
        except Exception:
            return "", [], []
        content = reply.get("content") or ""
        summary = self._section(content, "【对话摘要】", "【可记忆事实】")
        facts_raw = self._section(content, "【可记忆事实】", "【值得学习的话题】")
        topics_raw = self._section(content, "【值得学习的话题】", None)
        facts = [
            f.lstrip("- ").strip()
            for f in facts_raw.splitlines()
            if f.strip().startswith("-")
        ]
        facts = [f for f in facts if f and f != "无"]
        topics = [
            t.lstrip("- ").strip()
            for t in topics_raw.splitlines()
            if t.strip().startswith("-")
        ]
        topics = [re.sub(r"^话题\s*\d*\s*[:：]?\s*", "", t) for t in topics]
        topics = [t for t in topics if t and t != "无"]
        return summary.strip(), facts[:5], topics[:2]

    def run_once(self, force_curiosity=False):
        """执行一次沉思(对话回顾 + 自我兴趣探索)。应在后台线程调用。"""
        cfg = self.config.get("rumination", default={}) or {}
        if not cfg.get("enabled", True):
            return
        since = float(self.memory.get_meta("last_ruminated", "0") or 0)
        msgs = self.memory.messages_since(since, limit=cfg.get("max_context", 40))

        acted = False

        # 1) 对话回顾与学习
        if len(msgs) >= 4:
            acted = True
            if self.on_status:
                self.on_status("沉思中…")
            self._log("开始沉思…")
            try:
                transcript = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
                summary, facts, topics = self._analyze(transcript)

                if summary:
                    self.memory.append_summary(summary)
                    self._log(f"整理对话摘要:{summary[:60]}…")
                for f in facts:
                    self.memory.add_fact(f)
                if facts:
                    self._log(f"记住了 {len(facts)} 条关于开拓者的事实")

                searches = 0
                if not bool(self.config.get("search", "enabled", default=True)):
                    self._log("联网搜索已关闭,跳过话题联网学习。")
                    topics = []
                for topic in topics:
                    if searches >= int(cfg.get("max_searches", 2)):
                        break
                    self._log(f"学习中:{topic}")
                    results = self.searcher.search(topic, max_results=2)
                    if not results:
                        self._log(f"「{topic}」没搜到合适内容,跳过")
                        continue
                    searches += 1
                    best = results[0]
                    note = best["snippet"] or best["title"]
                    self.memory.add_note(
                        topic, note, sources=[best["url"]], kind="learn"
                    )
                    self._log(f"完成学习笔记:「{topic}」(来源 {best['url']})")

                self.memory.set_meta("last_ruminated", str(time.time()))
                self._log("对话回顾完毕。")
            except Exception as e:
                self._log(f"沉思中断:{e}")
            finally:
                if self.on_status:
                    self.on_status("")

        # 2) 自我兴趣探索(好奇心模式)
        try:
            cur = Curiosity(
                self.config,
                self.memory,
                self.llm,
                self.searcher,
                on_status=self.on_status,
                on_log=self.on_log,
            )
            if cur.run_once(force=force_curiosity):
                acted = True
        except Exception as e:
            self._log(f"好奇心探索中断:{e}")

        if not acted and self.on_status:
            self.on_status("")
