"""任务管理器(只读):枚举进程、CPU 与内存占用,供 Voyager 了解系统状态。

只读取信息,不提供任何操作进程的能力(不能结束、暂停或启动进程)。
"""
import ctypes
import json
import os
import time
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _filetime_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _process_list():
    """返回 [{pid, name, kernel, user, mem}] 列表。"""
    out = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (-1, 0xFFFFFFFFFFFFFFFF):
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return out
        while True:
            pid = entry.th32ProcessID
            name = entry.szExeFile
            k = u = mem = 0
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    c = wintypes.FILETIME()
                    e = wintypes.FILETIME()
                    kf = wintypes.FILETIME()
                    uf = wintypes.FILETIME()
                    if kernel32.GetProcessTimes(
                        handle, ctypes.byref(c), ctypes.byref(e),
                        ctypes.byref(kf), ctypes.byref(uf),
                    ):
                        k = _filetime_int(kf)
                        u = _filetime_int(uf)
                    pmc = PROCESS_MEMORY_COUNTERS()
                    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                    if psapi.GetProcessMemoryInfo(
                        handle, ctypes.byref(pmc), pmc.cb
                    ):
                        mem = pmc.WorkingSetSize
                finally:
                    kernel32.CloseHandle(handle)
            out.append(
                {"pid": pid, "name": name, "kernel": k, "user": u, "mem": mem}
            )
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return out


def read_task_manager():
    """读取一次任务管理器快照(两次采样算 CPU 占用)。
    返回 {ts, total, top_cpu, top_mem};失败返回 None。"""
    try:
        first = _process_list()
        if not first:
            return None
        t0 = time.time()
        time.sleep(0.8)
        elapsed = time.time() - t0
        second = _process_list()
        cores = max(1, os.cpu_count() or 1)
        by_pid = {p["pid"]: p for p in second}
        for p in first:
            q = by_pid.get(p["pid"])
            if q:
                wall = q["kernel"] + q["user"] - p["kernel"] - p["user"]
                p["cpu"] = wall / 10000000.0 / max(elapsed, 0.1) / cores * 100.0
                p["cpu"] = max(0.0, min(p["cpu"], 100.0))
            else:
                p["cpu"] = 0.0
        total = len(first)
        top_cpu = sorted(first, key=lambda p: p["cpu"], reverse=True)[:5]
        top_mem = sorted(first, key=lambda p: p["mem"], reverse=True)[:5]
        # 按程序名聚合(用于后台判断)
        by_name = {}
        for p in first:
            key = (p["name"] or "(unknown)").lower()
            e = by_name.setdefault(
                key,
                {"name": p["name"] or "(unknown)", "count": 0, "cpu": 0.0, "mem": 0},
            )
            e["count"] += 1
            e["cpu"] += p["cpu"]
            e["mem"] += p["mem"]
        agg = sorted(by_name.values(), key=lambda e: e["mem"], reverse=True)[:60]
        return {
            "ts": time.time(),
            "total": total,
            "top_cpu": [
                {"name": p["name"], "cpu": round(p["cpu"], 1), "pid": p["pid"]}
                for p in top_cpu
            ],
            "top_mem": [
                {"name": p["name"], "mem_mb": round(p["mem"] / 1048576.0, 1), "pid": p["pid"]}
                for p in top_mem
            ],
            "by_name": agg,
        }
    except Exception:
        return None


def summarize_procs(state):
    if not state:
        return ""
    lines = [f"进程总数 {state.get('total', 0)}"]
    cpu = state.get("top_cpu") or []
    if cpu:
        parts = ", ".join(f"{p['name']} {p['cpu']}%" for p in cpu[:3])
        lines.append(f"CPU 占用最高:{parts}")
    mem = state.get("top_mem") or []
    if mem:
        parts = ", ".join(f"{p['name']} {p['mem_mb']}MB" for p in mem[:3])
        lines.append(f"内存占用最高:{parts}")
    return "；".join(lines)


def procs_summary_from_memory(memory, max_age_minutes=15):
    """读取缓存的任务管理器摘要;过期返回空串。"""
    try:
        raw = memory.get_meta("procs_state", "")
        if not raw:
            return ""
        state = json.loads(raw)
        if time.time() - float(state.get("ts", 0)) > max_age_minutes * 60:
            return ""
        return summarize_procs(state)
    except Exception:
        return ""


# 系统级/无意义的进程,后台判断时忽略
NOISE_PROC = {
    "svchost.exe", "system", "registry", "memory compression", "dwm.exe",
    "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
    "smss.exe", "conhost.exe", "fontdrvhost.exe", "sihost.exe",
    "taskhostw.exe", "explorer.exe", "runtimebroker.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "searchhost.exe", "searchindexer.exe", "textinputhost.exe",
    "ctfmon.exe", "wudfhost.exe", "spoolsv.exe", "audiodg.exe",
    "python.exe", "pythonw.exe",
}


def _fg_app_from_memory(memory):
    """从屏幕感知里取当前前台程序名。"""
    try:
        raw = memory.get_meta("screen_state", "")
        if raw:
            return json.loads(raw).get("app") or ""
    except Exception:
        pass
    return ""


def background_summary(state, fg_app=""):
    """从快照中分辨后台程序(前台与系统进程除外);返回摘要文本。"""
    if not state:
        return ""
    fg = (fg_app or "").lower()
    items = []
    for e in state.get("by_name") or []:
        key = e["name"].lower()
        if key in NOISE_PROC or (fg and key == fg):
            continue
        items.append(e)
    if not items:
        return "后台很干净,没有明显的大程序在跑"
    parts = []
    for e in items[:8]:
        label = e["name"]
        if e["count"] > 1:
            label += f"(×{e['count']})"
        parts.append(label)
    return "后台程序:" + ",".join(parts)


def background_from_memory(memory, max_age_minutes=15):
    """读取缓存的后台判断摘要;过期返回空串。"""
    try:
        raw = memory.get_meta("procs_state", "")
        if not raw:
            return ""
        state = json.loads(raw)
        if time.time() - float(state.get("ts", 0)) > max_age_minutes * 60:
            return ""
        return background_summary(state, _fg_app_from_memory(memory))
    except Exception:
        return ""


class ProcsWatch:
    def __init__(self, config, memory):
        self.config = config
        self.memory = memory

    def snapshot(self):
        """读取并存储一次快照;返回 (最占内存进程是否变化, 摘要文本)。"""
        old = {}
        try:
            raw = self.memory.get_meta("procs_state", "")
            if raw:
                old = json.loads(raw)
        except Exception:
            old = {}
        state = read_task_manager()
        if state is None:
            return False, ""
        self.memory.set_meta("procs_state", json.dumps(state, ensure_ascii=False))
        self.memory.set_meta("last_procs", str(time.time()))
        changed = False
        try:
            if old.get("top_mem") and state.get("top_mem"):
                changed = (
                    state["top_mem"][0]["name"] != old["top_mem"][0]["name"]
                )
        except Exception:
            changed = False
        return changed, summarize_procs(state)
