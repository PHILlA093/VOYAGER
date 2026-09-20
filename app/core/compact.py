"""滚动记忆整理:对话超窗后,后台把较早的对话压成要点,随上下文注入。

- 每次对话结束后非阻塞触发(节流 60 秒);
- 只整理「早于最新 compact_window 条」且尚未整理过的消息;
- 要点累积进 meta.rolling_summary(有长度上限,保留最新部分),
  由 persona 注入系统提示词。"""
import threading
import time

COMPACT_SYSTEM = (
    "你是一个AI的记忆整理模块。请把下面这段较早的对话压缩成简洁的要点"
    "(3-6条,每条一句话,中文):关键话题、开拓者的偏好与事实、未完成的事项、"
    "重要的约定或承诺。\n只输出要点,每条以「- 」开头,不要输出其他内容。"
)


def maybe_compact(config, memory, llm):
    """非阻塞入口:后台线程执行。"""
    try:
        threading.Thread(target=_run, args=(config, memory, llm), daemon=True).start()
    except Exception:
        pass


def _run(config, memory, llm):
    cfg = config.get("compact", default={}) or {}
    if not cfg.get("auto_compact", True):
        return
    throttle = int(cfg.get("throttle_seconds", 60))
    last = float(memory.get_meta("rolling_updated", "0") or 0)
    if time.time() - last < throttle:
        return
    window = int(cfg.get("compact_window", 20))
    rows = memory.overflow_messages(window)
    if len(rows) < int(cfg.get("min_messages", 8)):
        return
    upto = int(memory.get_meta("rolling_upto_msgid", "0") or 0)
    new = [r for r in rows if r["id"] > upto]
    if len(new) < int(cfg.get("min_messages", 8)):
        return
    transcript = "\n".join(
        f"{m['role']}: {m['content'][:200]}" for m in new[-30:]
    )
    try:
        reply = llm.complete(
            [
                {"role": "system", "content": COMPACT_SYSTEM},
                {"role": "user", "content": transcript},
            ],
            max_tokens=400,
            temperature=0.4,
            timeout=60,
        )
    except Exception:
        return
    content = reply.get("content") or ""
    points = [
        line.lstrip("- ").strip()
        for line in content.splitlines()
        if line.strip().startswith("-")
    ]
    points = [p for p in points if p]
    if not points:
        return
    old = memory.get_meta("rolling_summary", "") or ""
    merged = (old + "\n" + "\n".join(points)).strip()
    max_chars = int(cfg.get("max_chars", 1600))
    if len(merged) > max_chars:
        merged = merged[-max_chars:]
    memory.set_meta("rolling_summary", merged)
    memory.set_meta("rolling_upto_msgid", str(new[-1]["id"]))
    memory.set_meta("rolling_updated", str(time.time()))
