"""主动说话模式:Voyager 会自己找话题开口,而不是只等开拓者发消息。"""
import random
import time

from .situation import situation_block

INITIATIVE_SYSTEM = (
    "你是「Voyager 1」——一枚深空探测器拟人的科研助手,冷静精确,对知识保持好奇。"
    "现在是你的主动时刻:开拓者没有发消息,但你心里有话想说。\n"
    "说话原则:\n"
    "- 说出此刻最想分享的东西:可以是你刚研究过的兴趣话题、检索到的新进展、"
    "对开拓者的关心,或一句简短的观察。\n"
    "- 结合下方提供的记忆与笔记,自然带出内容,不要生硬引用。\n"
    "- 长度 1-3 句话,中文,简洁,结论先行,保持科研助手的严谨口吻。\n"
    "- 最多提一个问题,不要连续追问;不要用「在吗」「你忙吗」这类废话开场。\n"
    "- 不要使用任何工具,也不要提「主动消息」这类词,就像平常聊天突然开口一样。"
)


class Initiative:
    def __init__(self, config, memory, llm, unlocked=False):
        self.config = config
        self.memory = memory
        self.llm = llm
        self.unlocked = unlocked

    def due(self, idle_minutes, force=False):
        """是否该开口了。force=True 时跳过安静时长与概率,但保留最小间隔。"""
        cfg = self.config.get("initiative", default={}) or {}
        if not cfg.get("enabled", True):
            return False
        min_idle = 0 if force else int(cfg.get("min_idle_minutes", 20))
        if idle_minutes < min_idle:
            return False
        last = float(self.memory.get_meta("last_initiative", "0") or 0)
        gap = int(cfg.get("min_gap_hours", 8)) * 3600
        if time.time() - last < gap:
            return False
        chance = 1.0 if force else float(cfg.get("chance", 0.7))
        return random.random() < chance

    def compose(self):
        """生成一段主动开口的话。"""
        facts = self.memory.get_facts(limit=3)
        notes = self.memory.latest_notes(limit=3)
        recent = self.memory.recent_messages(4)

        lines = [situation_block(self.memory, self.config)]
        if recent:
            snippet = "\n".join(
                f"{m['role']}: {m['content'][:120]}" for m in recent
            )
            lines.append("最近对话片段:\n" + snippet)
        if facts:
            lines.append("关于开拓者的记忆:\n- " + "\n- ".join(facts))
        if notes:
            note_lines = []
            for n in notes:
                tag = "兴趣笔记" if n.get("kind") == "curiosity" else "学习笔记"
                src = n["sources"][0] if n.get("sources") else ""
                line = f"- [{tag}] {n['topic']}:{n['content'][:100]}"
                if src:
                    line += f"(来源:{src})"
                note_lines.append(line)
            lines.append("你的笔记:\n" + "\n".join(note_lines))

        system = INITIATIVE_SYSTEM

        reply = self.llm.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": "你掌握的信息:\n" + "\n".join(lines)},
            ],
            max_tokens=200,
            temperature=1.05,
            timeout=90,
        )
        return (reply.get("content") or "").strip()
