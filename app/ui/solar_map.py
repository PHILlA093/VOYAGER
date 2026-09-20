"""太阳系实时背景地图(斜视角)。

- 灰色球体代表天体(太阳/行星),略深一点的灰色线表示轨道
- 小行星带用灰色小块显示
- 实时监测旅行者一号/二号:优先从 JPL Horizons API 拉取真实日心坐标,
  离线时回退到近似模型(距离线性外推 + 固定方向)
- 每帧按当前时间计算行星位置(平均黄经近似),旅行者数据每 6 小时刷新
"""
import math
import threading
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygon, QRadialGradient
from PySide6.QtWidgets import QWidget

try:
    from ..core.net import request as _net_request
except Exception:  # 独立运行时无 app 包
    _net_request = None

# 行星: (名称, 轨道半径 AU, 平均运动 度/天, 2000-01-01 黄经 度)
_PLANETS = [
    ("水星", 0.387, 4.0923, 252.25),
    ("金星", 0.723, 1.6021, 181.98),
    ("地球", 1.000, 0.9856, 100.47),
    ("火星", 1.524, 0.5240, 355.43),
    ("木星", 5.203, 0.0831, 34.35),
    ("土星", 9.537, 0.0335, 50.08),
    ("天王星", 19.19, 0.0117, 314.06),
    ("海王星", 30.07, 0.0060, 304.35),
]
_J2000 = 2451545.0  # 儒略日(2000-01-01)
_R_POW = 0.6        # 径向幂律指数:内圈展开、外圈压缩,让太阳与水星轨道可见

# 旅行者近似方向(黄经度)与纬度,以及 2026-08 的近似日心距离(AU)
_V1_APPROX = {"lon": 255.0, "lat": 34.0, "r": 165.0}
_V2_APPROX = {"lon": 300.0, "lat": -45.0, "r": 138.0}

# 旅行者历史轨迹近似关键点 (r AU, 黄经 度, 黄纬 度)
# V1: 1977 发射 -> 木星 1979 -> 土星 1980 -> 向蛇夫座方向飞出
_V1_HISTORY = [
    (1.0, 245.0, 0.0), (2.0, 248.0, 1.0), (3.4, 250.0, 1.5), (4.6, 251.0, 2.0),
    (5.2, 252.0, 2.5),  # 木星 1979
    (7.0, 254.0, 5.0), (8.5, 255.0, 8.0), (9.5, 256.0, 10.0),  # 土星 1980
    (12.0, 254.0, 13.0), (16.0, 252.0, 17.0), (22.0, 250.0, 21.0),
    (30.0, 249.0, 25.0), (40.0, 248.0, 27.0), (55.0, 250.0, 29.0),
    (75.0, 252.0, 31.0), (100.0, 253.0, 32.0), (130.0, 254.0, 33.0),
    (165.0, 255.0, 34.0),  # 2026 当前
]
# V2: 1977 发射 -> 木星 1979 -> 土星 1981 -> 天王星 1986 -> 海王星 1989 -> 向南飞出
_V2_HISTORY = [
    (1.0, 205.0, 0.0), (2.0, 207.0, 1.0), (3.5, 208.0, 1.5), (4.6, 209.0, 2.0),
    (5.2, 210.0, 2.0),  # 木星 1979
    (7.0, 212.0, 3.0), (8.5, 213.0, 4.0), (9.5, 215.0, 5.0),  # 土星 1981
    (12.0, 218.0, 2.0), (15.0, 221.0, -2.0), (19.2, 224.0, -10.0),  # 天王星 1986
    (24.0, 228.0, -20.0), (30.1, 234.0, -32.0),  # 海王星 1989
    (45.0, 250.0, -38.0), (65.0, 268.0, -41.0), (90.0, 282.0, -43.0),
    (115.0, 293.0, -44.0), (138.0, 300.0, -45.0),  # 2026 当前
]

# Horizons 缓存(当前位置 + 历史轨迹)
_HZ_CACHE = {"ts": 0.0, "data": None}
_HISTORY_CACHE = {"ts": 0.0, "data": None}


def _jd_now():
    return time.time() / 86400.0 + 2440587.5


def _interp_history(points, per_seg=3):
    """在近似关键点之间线性插值,让轨迹平滑。"""
    out = []
    for i in range(len(points) - 1):
        (r1, lo1, la1), (r2, lo2, la2) = points[i], points[i + 1]
        for k in range(per_seg):
            t = k / per_seg
            out.append((r1 + (r2 - r1) * t, lo1 + (lo2 - lo1) * t, la1 + (la2 - la1) * t))
    out.append(points[-1])
    return out


def planet_longitude(name, jd):
    """平均黄经近似(度),视觉精度足够。"""
    for n, _r, rate, l0 in _PLANETS:
        if n == name:
            return (l0 + rate * (jd - _J2000)) % 360.0
    return 0.0


def _horizons_vectors(spk):
    """从 JPL Horizons API 获取日心黄道坐标(AU)。返回 (x, y, z) 或 None。"""
    if _net_request is None:
        return None
    from datetime import datetime, timedelta

    today = datetime.utcnow().strftime("%Y-%m-%d")
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "format": "json",
        "COMMAND": f"'{spk}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'VECTORS'",
        "CENTER": "'500@10'",
        "START_TIME": f"'{today}'",
        "STOP_TIME": f"'{tomorrow}'",
        "STEP_SIZE": "'1d'",
        "VEC_TABLE": "'2'",
        "REF_PLANE": "'ECLIPTIC'",
    }
    try:
        resp = _net_request("get", "https://ssd.jpl.nasa.gov/api/horizons.api",
                            params=params, timeout=10)
        text = resp.text or ""
        body = text.split("$$SOE", 1)[-1]
        body = body.split("$$EOE", 1)[0]
        for line in body.splitlines():
            parts = line.split()
            if len(parts) >= 5:
                try:
                    return (float(parts[2]), float(parts[3]), float(parts[4]))
                except ValueError:
                    continue
    except Exception:
        return None
    return None


def voyager_positions():
    """返回旅行者当前位置:只读缓存/近似值,**不发网络请求**(绘制线程安全)。
    真实星历由 refresh_voyager_data() 在后台线程拉取。"""
    hz = _HZ_CACHE["data"]
    if hz:
        try:
            return {"v1": _from_hz(hz["v1"]), "v2": _from_hz(hz["v2"])}
        except Exception:
            pass
    return _approx_positions()


def _from_hz(vec):
    x, y, z = vec
    r = math.sqrt(x * x + y * y + z * z)
    lon = math.degrees(math.atan2(y, x)) % 360.0
    lat = math.degrees(math.asin(z / r)) if r > 0 else 0.0
    return {"r": r, "lon": lon, "lat": lat}


def _approx_positions():
    """近似回退:距离按 ~3.6/3.3 AU 每年外推。"""
    years = (time.time() / 86400.0 + 2440587.5 - _J2000) / 365.25
    v1 = dict(_V1_APPROX)
    v1["r"] = 165.0 + (years - 26.62) * 3.6
    v2 = dict(_V2_APPROX)
    v2["r"] = 138.0 + (years - 26.62) * 3.3
    return {"v1": v1, "v2": v2}


def voyager_history():
    """旅行者历史轨迹:只读缓存,无缓存时用内置近似关键点插值(不发网络请求)。"""
    hz = _HISTORY_CACHE["data"]
    if hz:
        return hz
    return {"v1": _interp_history(_V1_HISTORY), "v2": _interp_history(_V2_HISTORY)}


def refresh_voyager_data():
    """联网拉取旅行者位置与历史轨迹并写入缓存(仅应在后台线程调用)。"""
    now = time.time()
    if now - _HZ_CACHE["ts"] > 6 * 3600:
        v1 = _horizons_vectors(-31)   # Voyager 1
        v2 = _horizons_vectors(-32)   # Voyager 2
        if v1 and v2:
            _HZ_CACHE["data"] = {"v1": v1, "v2": v2}
        _HZ_CACHE["ts"] = now
    if now - _HISTORY_CACHE["ts"] > 6 * 3600:
        h1 = _horizons_history(-31)
        h2 = _horizons_history(-32)
        if h1 and h2:
            _HISTORY_CACHE["data"] = {"v1": h1, "v2": h2}
        _HISTORY_CACHE["ts"] = now


def _horizons_history(spk):
    """从 JPL Horizons 拉取 1977-2026 每年一个点的历史日心黄道坐标(AU)。"""
    if _net_request is None:
        return None
    params = {
        "format": "json",
        "COMMAND": f"'{spk}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'VECTORS'",
        "CENTER": "'500@10'",
        "START_TIME": "'1977-01-01'",
        "STOP_TIME": "'2026-01-01'",
        "STEP_SIZE": "'1y'",
        "VEC_TABLE": "'2'",
        "REF_PLANE": "'ECLIPTIC'",
    }
    try:
        resp = _net_request("get", "https://ssd.jpl.nasa.gov/api/horizons.api",
                            params=params, timeout=15)
        text = resp.text or ""
        body = text.split("$$SOE", 1)[-1]
        body = body.split("$$EOE", 1)[0]
        out = []
        for line in body.splitlines():
            parts = line.split()
            if len(parts) >= 5:
                try:
                    x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
                except ValueError:
                    continue
                r = math.sqrt(x * x + y * y + z * z)
                if r > 1e-6:
                    out.append((r, math.degrees(math.atan2(y, x)) % 360.0,
                                math.degrees(math.asin(z / r))))
        return out if out else None
    except Exception:
        return None


class SolarMapWidget(QWidget):
    """斜视角太阳系实时地图背景。右键拖动:水平绕太阳南北极旋转,垂直调整倾斜角。"""

    data_ready = Signal()  # 后台星历拉取完成

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMouseTracking(True)
        self._rot = 0.0       # 绕太阳南北极(黄道经度)旋转角(度)
        self._tilt = 0.52     # 斜视角(rad)
        self._zoom = 1.0      # 缩放倍率(Ctrl+滚轮)
        self._drag = None     # 右键拖拽起点
        self._fetch_started = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(60_000)  # 每分钟重绘(位置随当前时间实时计算)
        self.data_ready.connect(self.update)
        # 首帧用近似值立即绘制,网络星历延后到后台线程(避免启动卡顿)
        QTimer.singleShot(600, self._start_fetch)

    def _start_fetch(self):
        if self._fetch_started:
            return
        self._fetch_started = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            refresh_voyager_data()
        except Exception:
            pass
        try:
            self.data_ready.emit()
        except Exception:
            pass

    # ---------- 交互 ----------

    def rotate_by(self, dx, dy):
        """右键拖动:水平旋转整个太阳系(可见的转动),垂直调整倾斜角;均无限制。"""
        self._rot = self._rot - dx * 0.4
        self._tilt = self._tilt + dy * 0.004
        self.update()

    def zoom_by(self, delta):
        """滚轮缩放(Ctrl+滚轮):delta 为 angleDelta().y()。"""
        self._zoom = max(0.2, min(10.0, self._zoom * (1.0 + delta / 1200.0)))
        self.update()

    # ---------- 鼠标右键拖动旋转(独立 widget 场景) ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._drag = (event.position().x(), event.position().y())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.RightButton:
            x0, y0 = self._drag
            p = event.position()
            self.rotate_by(p.x() - x0, p.y() - y0)
            self._drag = (p.x(), p.y())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self._drag = None
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # 最下层:纯白底
        p.fillRect(self.rect(), QColor(0xFF, 0xFF, 0xFF))

        cx, cy = w * 0.5, h * 0.46
        max_r_au = 32.0
        px = min(w, h * 1.6) * 0.38 / max_r_au * self._zoom  # 每 AU 像素(含缩放)
        sin_t = math.sin(self._tilt)
        cos_t = math.cos(self._tilt)
        jd = _jd_now()
        rot_deg = self._rot  # 绕太阳系垂直轴(黄道法线)的旋转角 = 黄道经度平移

        def proj(r_px, lon_rad, lat_rad=0.0):
            """标准正交投影(斜视角)。
            绕太阳系垂直轴旋转 = 所有天体的黄道经度整体平移 rot_deg,
            因此轨道椭圆形状不变,天体沿轨道移动(严格的轴向旋转)。
            """
            lon = lon_rad + math.radians(rot_deg)
            x = r_px * math.cos(lon)
            y = r_px * math.sin(lon) * sin_t - r_px * math.sin(lat_rad) * cos_t
            return (cx + x, cy + y)

        def clip_to_view(x, y, margin=16):
            """视野外的目标:沿视线方向裁到画面边缘(用于旅行者指示)。"""
            dx, dy = x - cx, y - cy
            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                return cx, cy, False
            tx = (w * 0.5 - margin) / abs(dx) if abs(dx) > 1e-9 else float("inf")
            ty = (h * 0.5 - margin) / abs(dy) if abs(dy) > 1e-9 else float("inf")
            t = min(tx, ty, 1.0)
            inside = t >= 1.0
            return cx + dx * t, cy + dy * t, inside

        # ---- 轨道(略深一点的灰,斜视角压扁;绕垂直轴旋转时形状不变) ----
        pen = p.pen()
        pen.setColor(QColor(0xC5, 0xCB, 0xD4))
        pen.setWidth(2)
        p.setPen(pen)
        for _n, r_au, _rate, _l0 in _PLANETS:
            rp = r_au * px
            pts = []
            for k in range(73):
                th = 2.0 * math.pi * k / 72.0
                x, y = proj(rp, th)
                pts.append(QPoint(int(x), int(y)))
            p.drawPolyline(QPolygon(pts))

        # ---- 小行星带(灰色小块,主带 2.2-3.2 AU;随垂直轴旋转) ----
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0xB9, 0xC0, 0xCA))
        seed = 20260824
        base = (jd - _J2000) * 0.05  # 整体缓慢旋转
        for i in range(90):
            a = math.radians((seed + i * 137.5) % 360.0 + base)
            rr = 2.2 + ((seed * 31 + i * 17) % 100) / 100.0 * 1.0
            xx, yy = proj(rr * px, a)
            p.drawEllipse(int(xx) - 1, int(yy) - 1, 3, 3)

        # ---- 天体(灰色球体) ----
        sizes = {"太阳": 9.0, "水星": 2.0, "金星": 3.0, "地球": 3.2,
                 "火星": 2.6, "木星": 6.0, "土星": 5.2, "天王星": 3.6, "海王星": 3.5}
        # 太阳(在旋转中心;大小取水星轨道的 0.8 倍,始终位于水星轨道以内)
        sun_r = max(1.5, 0.387 * px * 0.8)
        self._draw_sphere(p, cx, cy, sun_r, QColor(0x8E, 0x95, 0xA3))
        # 行星(随垂直轴旋转:经度平移)
        for name, r_au, _rate, _l0 in _PLANETS:
            lon = math.radians(planet_longitude(name, jd))
            xx, yy = proj(r_au * px, lon)
            self._draw_sphere(p, xx, yy, sizes[name], QColor(0x9A, 0xA2, 0xAF))

        # ---- 旅行者历史轨迹 ----
        try:
            hist = voyager_history()
        except Exception:
            hist = None
        if hist:
            for key, color in (("v1", QColor(0x8E, 0x95, 0xA3)), ("v2", QColor(0xB9, 0xC0, 0xCA))):
                pts = hist.get(key) or []
                if len(pts) < 2:
                    continue
                p.setPen(QPen(color, 1, Qt.SolidLine))
                prev = None
                for r, lon_d, lat_d in pts:
                    lon = math.radians(lon_d)
                    lat = math.radians(lat_d)
                    cur = tuple(int(v) for v in proj(r * px, lon, lat))
                    if prev is not None:
                        p.drawLine(prev[0], prev[1], cur[0], cur[1])
                    prev = cur

        # ---- 旅行者一号/二号(实时监测;随垂直轴旋转) ----
        try:
            vp = voyager_positions()
        except Exception:
            vp = None
        if vp:
            for key, label in (("v1", "V1"), ("v2", "V2")):
                v = vp.get(key)
                if not v:
                    continue
                lon = math.radians(v["lon"])
                lat = math.radians(v["lat"])
                r_px = v["r"] * px
                xx, yy = proj(r_px, lon, lat)
                xx, yy, inside = clip_to_view(xx, yy)
                # 轨道线(从太阳径向延伸到标记处)
                p.setPen(QPen(QColor(0xB0, 0xB7, 0xC2), 1, Qt.DashLine))
                p.drawLine(int(cx), int(cy), int(xx), int(yy))
                # 位置标记
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0x6B, 0x74, 0x85))
                p.drawEllipse(int(xx) - 3, int(yy) - 3, 6, 6)
                p.setPen(QColor(0x6B, 0x74, 0x85))
                f = QFont(self.font())
                f.setPointSize(8)
                p.setFont(f)
                p.drawText(int(xx) + 6, int(yy) - 6, label)
                # 距离标注
                p.drawText(int(xx) + 6, int(yy) + 8, f"{v['r']:.0f} AU")

        # ---- 图例 ----
        p.setPen(QColor(0x8A, 0x94, 0xA6))
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        info = time.strftime("%Y-%m-%d %H:%M") + "  ·  斜视角太阳系 · 实时轨道"
        p.drawText(10, h - 12, info)

    def _draw_sphere(self, p, x, y, r, color):
        grad = QRadialGradient(x - r * 0.35, y - r * 0.35, r * 2.2)
        light = color.lighter(135)
        dark = color.darker(130)
        grad.setColorAt(0.0, light)
        grad.setColorAt(0.7, color)
        grad.setColorAt(1.0, dark)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(int(x - r), int(y - r), int(2 * r), int(2 * r))
