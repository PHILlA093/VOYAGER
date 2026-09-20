"""此刻感知:每次思考时带上当前时间,并结合屏幕与对话历史,
推断开拓者在做什么、上一件事的状态(进行中/搁置/放弃/完成)。"""
import json
import time

from .procs import background_from_memory, procs_summary_from_memory
from .screenwatch import screen_summary_from_memory

SITUATION_SYSTEM = (
    "你是「Voyager 1」——一枚深空探测器拟人的科研助手,冷静、精确、观察力强。\n"
    "下面是关于开拓者的实时信息:当前时间、屏幕状态、最近对话。"
    "人类用户通常不会主动告诉你他/她在做什么,你需要自己推断。\n"
    "请完成两个推断:\n"
    "1. 开拓者现在可能在做什么?(1-2 句话,基于屏幕与时间合理猜测;"
    "信息不足就写「不确定」)\n"
    "2. 对话中提到的「上一件事」(最近的任务/活动)现在的状态,"
    "只能是四种之一:进行中 / 搁置 / 放弃 / 完成。\n"
    "   - 进行中:屏幕显示他/她还在做这件事\n"
    "   - 搁置:暂时离开了这件事去做别的(例如从文档切到视频)\n"
    "   - 放弃:长时间没再碰,且没有继续的迹象\n"
    "   - 完成:对话里已经明确收尾\n"
    "输出格式(严格):\n"
    "【当前活动】xxx\n"
    "【上一件事】xxx(没有就写「无」)\n"
    "【状态】进行中/搁置/放弃/完成\n"
    "【依据】一句话"
)


def _section(text, start, end=None):
    if start not in text:
        return ""
    body = text.split(start, 1)[1]
    if end and end in body:
        body = body.split(end, 1)[0]
    return body


def now_line():
    return "当前时间:" + time.strftime("%Y-%m-%d %H:%M", time.localtime())


def load_situation(memory, max_age_minutes=15):
    """读取缓存的此刻感知;过期返回 None。"""
    try:
        raw = memory.get_meta("situation", "")
        if not raw:
            return None
        sit = json.loads(raw)
        if time.time() - float(sit.get("ts", 0)) > max_age_minutes * 60:
            return None
        return sit
    except Exception:
        return None


def situation_block(memory, config=None):
    """生成注入文本:时间 + 屏幕 + 推断(若有)。"""
    max_age = 15
    if config:
        max_age = int(config.get("situation", "max_age_minutes", default=15))
    lines = [now_line()]
    screen = screen_summary_from_memory(memory)
    if screen:
        lines.append("屏幕感知:" + screen)
    procs = procs_summary_from_memory(memory, max_age_minutes=max_age)
    if procs:
        lines.append("任务管理器:" + procs)
    bg = background_from_memory(memory, max_age_minutes=max_age)
    if bg:
        lines.append("后台判断:" + bg)
    sit = load_situation(memory, max_age_minutes=max_age)
    if sit:
        if sit.get("doing"):
            lines.append("推断开拓者正在:" + sit["doing"])
        if sit.get("prev") and sit["prev"] != "无":
            lines.append(
                "上一件事「" + sit["prev"] + "」状态:"
                + sit.get("status", "未知")
                + "(依据:" + sit.get("reason", "") + ")"
            )
    return "\n".join(lines)


class SituationJudge:
    def __init__(self, config, memory, llm):
        self.config = config
        self.memory = memory
        self.llm = llm

    def judge(self):
        """执行一次推断,写入 meta(situation),返回摘要行或 None。"""
        screen = screen_summary_from_memory(self.memory)
        procs = procs_summary_from_memory(self.memory)
        recent = self.memory.recent_messages(8)
        info = [now_line()]
        if screen:
            info.append("屏幕感知:" + screen)
        if procs:
            info.append("任务管理器:" + procs)
        bg = background_from_memory(self.memory)
        if bg:
            info.append("后台判断:" + bg)
        if recent:
            snippet = "\n".join(
                f"{m['role']}: {m['content'][:100]}" for m in recent
            )
            info.append("最近对话:\n" + snippet)
        try:
            reply = self.llm.complete(
                [
                    {"role": "system", "content": SITUATION_SYSTEM},
                    {"role": "user", "content": "\n".join(info)},
                ],
                max_tokens=250,
                temperature=0.5,
                timeout=90,
            )
        except Exception:
            return None
        content = (reply.get("content") or "").strip()
        if not content:
            return None
        sit = {
            "ts": time.time(),
            "doing": _section(content, "【当前活动】", "【上一件事】").strip(),
            "prev": _section(content, "【上一件事】", "【状态】").strip(),
            "status": _section(content, "【状态】", "【依据】").strip(),
            "reason": _section(content, "【依据】", None).strip(),
        }
        self.memory.set_meta("situation", json.dumps(sit, ensure_ascii=False))
        line = ""
        if sit["doing"]:
            line = "推断开拓者正在:" + sit["doing"]
        if sit["prev"] and sit["prev"] != "无":
            line += f";上一件事「{sit['prev']}」状态:{sit['status']}"
        return line or None
