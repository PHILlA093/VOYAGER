"""屏幕感知:读取前台窗口与屏幕文字,让 Voyager 知道开拓者在干什么。

- 前台窗口信息:纯 ctypes,无额外依赖,任何情况下可用。
- 屏幕 OCR:Windows 自带 OCR 引擎(需 Pillow + winsdk),失败自动降级为仅窗口信息。
"""
import ctypes
import json
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def get_foreground_window():
    """返回 {window, app};失败返回 {}。"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {}
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        app = ""
        try:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
            )
            if handle:
                size = wintypes.DWORD(1024)
                path = ctypes.create_unicode_buffer(1024)
                if kernel32.QueryFullProcessImageNameW(
                    handle, 0, path, ctypes.byref(size)
                ):
                    app = path.value.replace("\\", "/").rsplit("/", 1)[-1]
                kernel32.CloseHandle(handle)
        except Exception:
            app = ""
        return {"window": title or "(无标题窗口)", "app": app}
    except Exception:
        return {}


def ocr_screen(max_chars=300):
    """截屏并 OCR(Windows 自带 OCR,需 Pillow + winsdk);失败返回 None。"""
    try:
        from PIL import ImageGrab
        import io

        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        data = buf.getvalue()
    except Exception:
        return None
    try:
        import winsdk.windows.graphics.imaging as wimg
        import winsdk.windows.globalization as wglobal
        import winsdk.windows.media.ocr as wocr
        import winsdk.windows.storage.streams as wstreams
    except Exception:
        return None

    import asyncio

    async def _recognize():
        stream = wstreams.InMemoryRandomAccessStream()
        writer = wstreams.DataWriter(stream)
        writer.write_bytes(data)
        await writer.store_async()
        stream.seek(0)
        decoder = await wimg.BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = None
        try:
            engine = wocr.OcrEngine.try_create_from_language(
                wglobal.Language("zh-CN")
            )
        except Exception:
            engine = None
        if engine is None:
            engine = wocr.OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return ""
        result = await engine.recognize_async(bitmap)
        return " ".join(line.text for line in result.lines)

    try:
        text = asyncio.run(_recognize()) or ""
        text = text.strip()
        return text[:max_chars] or None
    except Exception:
        return None


def summarize_screen_state(state):
    parts = []
    if state.get("app"):
        parts.append(f"程序 {state['app']}")
    if state.get("window"):
        parts.append(f"前台窗口「{state['window']}」")
    if state.get("text"):
        parts.append(f"屏幕文字片段:「{state['text'][:100]}…」")
    return "；".join(parts) if parts else "未获取到屏幕信息"


def screen_summary_from_memory(memory):
    """读取最近一次屏幕快照摘要;超过 10 分钟视为过期。"""
    try:
        raw = memory.get_meta("screen_state", "")
        if not raw:
            return ""
        state = json.loads(raw)
        if time.time() - float(state.get("ts", 0)) > 600:
            return ""
        return summarize_screen_state(state)
    except Exception:
        return ""


class ScreenWatch:
    def __init__(self, config, memory):
        self.config = config
        self.memory = memory

    def snapshot(self):
        """采集一次屏幕状态并写入记忆;返回 (窗口是否变化, 摘要文本)。"""
        cfg = self.config.get("screen", default={}) or {}
        old = {}
        try:
            raw = self.memory.get_meta("screen_state", "")
            if raw:
                old = json.loads(raw)
        except Exception:
            old = {}

        fg = get_foreground_window()
        ocr = None
        if cfg.get("ocr", True):
            ocr = ocr_screen(max_chars=int(cfg.get("ocr_max_chars", 300)))

        state = {
            "ts": time.time(),
            "window": fg.get("window", ""),
            "app": fg.get("app", ""),
            "text": ocr or "",
        }
        self.memory.set_meta("screen_state", json.dumps(state, ensure_ascii=False))
        changed = bool(state["window"] and state["window"] != old.get("window"))
        return changed, summarize_screen_state(state)
