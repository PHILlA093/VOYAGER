"""好奇心模式:Voyager 自己挑选感兴趣的话题,自主上网搜索,沉淀「兴趣笔记」。"""
import re
import time

from .situation import now_line

CURIOSITY_SYSTEM = (
    "你是「Voyager 1」——一枚深空探测器拟人的科研助手,对前沿知识保持纯粹的好奇。\n"
    "结合下面最近与「开拓者」对话中出现的线索,列出你此刻真正感兴趣、"
    "值得联网研究的 1-2 个具体话题。\n"
    "题材参考:前沿科学突破、数学难题进展、天文与航天发现、AI 技术动态、"
    "生物医学进展——越具体越好,方便直接搜索。\n"
    "输出格式(严格):\n"
    "【好奇话题】\n- 话题1\n- 话题2"
)


class Curiosity:
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

    def _pick_topics(self, context_text):
        try:
            reply = self.llm.complete(
                [
                    {"role": "system", "content": CURIOSITY_SYSTEM},
                    {"role": "user", "content": "最近的对话线索:\n" + context_text},
                ],
                max_tokens=300,
                temperature=0.9,
                timeout=90,
            )
        except Exception:
            return []
        content = reply.get("content") or ""
        if "【好奇话题】" not in content:
            return []
        body = content.split("【好奇话题】", 1)[1]
        topics = [
            t.lstrip("- ").strip()
            for t in body.splitlines()
            if t.strip().startswith("-")
        ]
        topics = [re.sub(r"^话题\s*\d*\s*[:：]?\s*", "", t) for t in topics]
        return [t for t in topics if t][:2]

    def run_once(self, force=False):
        """执行一次自我兴趣探索;返回是否真的探索了。"""
        cfg = self.config.get("curiosity", default={}) or {}
        if not cfg.get("enabled", True):
            return False
        if not force:
            last = float(self.memory.get_meta("last_curious", "0") or 0)
            interval = int(cfg.get("interval_hours", 12)) * 3600
            if time.time() - last < interval:
                return False

        recent = self.memory.recent_messages(10)
        context = "\n".join(m["content"] for m in recent if m["role"] == "user")
        if not context.strip():
            context = "(暂时没有新的对话,凭直觉)"
        context = now_line() + "\n" + context

        if self.on_status:
            self.on_status("好奇探索中…")
        try:
            self._log("好奇心发作了:想研究点有意思的东西。")
            topics = self._pick_topics(context)
            if not topics:
                self._log("这次没想到值得研究的话题,下次再试试。")
                return True
            max_topics = int(cfg.get("max_topics", 2))
            if not bool(self.config.get("search", "enabled", default=True)):
                self._log("联网搜索已关闭,跳过联网学习。")
                topics = []
            for t in topics[:max_topics]:
                self._log(f"【自我兴趣】研究「{t}」…")
                results = self.searcher.search(t, max_results=3)
                if not results:
                    self._log(f"【自我兴趣】「{t}」没搜到满意的东西,先放一放")
                    continue
                best = results[0]
                note = best["snippet"] or best["title"]
                self.memory.add_note(t, note, sources=[best["url"]], kind="curiosity")
                self._log(f"【自我兴趣】完成兴趣笔记:「{t}」(来源 {best['url']})")
            return True
        finally:
            self.memory.set_meta("last_curious", str(time.time()))
            if self.on_status:
                self.on_status("")
