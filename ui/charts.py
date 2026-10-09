"""Small charts for the Summary / Details views, drawn with QPainter.

Each chart answers one question named in the view that shows it (Is rain getting
worse? Where is the tightest point?). Data comes straight from the Brief; nothing
is smoothed, filled in or extrapolated. Missing hours are left as gaps.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from qgis.PyQt.QtCore import QPointF, QRect, Qt
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF

from ..core.presentation.history import VARIABLES
from ..core.presentation.terrain import CLEAR_THRESHOLD
from . import theme

WIDTH, HEIGHT = 400, 110
PAD_L, PAD_R, PAD_T, PAD_B = 44, 10, 10, 20


def _canvas(dark: bool):
    t = theme.tokens(dark)
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    image.fill(QColor(t["surface"]))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return image, painter, t


def _draw(painter: QPainter, t: dict, xs: Sequence[float], series: List[dict], x_unit: str, y_unit: str,
          mark_x: Optional[float] = None) -> None:
    """series: [{ys, color, dashed}]; None entries are gaps."""
    values = [y for s in series for y in s["ys"] if y is not None]
    if not values or len(xs) < 2:
        painter.setPen(QColor(t["text_faint"]))
        painter.drawText(8, HEIGHT // 2, "No data to chart")
        return
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    x0, x1 = xs[0], xs[-1]
    w, h = WIDTH - PAD_L - PAD_R, HEIGHT - PAD_T - PAD_B

    def px(x): return PAD_L + (x - x0) / (x1 - x0) * w
    def py(y): return PAD_T + (hi - y) / (hi - lo) * h

    font = QFont()
    font.setPointSize(8)
    painter.setFont(font)
    painter.setPen(QPen(QColor(t["text_faint"]), 1))
    painter.drawLine(PAD_L, PAD_T, PAD_L, PAD_T + h)
    painter.drawLine(PAD_L, PAD_T + h, PAD_L + w, PAD_T + h)
    painter.setPen(QColor(t["text_muted"]))
    painter.drawText(2, PAD_T + 8, f"{max(values):.1f}")
    painter.drawText(2, PAD_T + h, f"{min(values):.1f}")
    painter.drawText(PAD_L, HEIGHT - 5, f"{x0:g}")
    painter.drawText(QRect(PAD_L, HEIGHT - 17, w, 14), Qt.AlignmentFlag.AlignRight, f"{x1:.1f} {x_unit}")
    painter.drawText(2, PAD_T + 22, y_unit)

    for s in series:
        pen = QPen(QColor(s["color"]), 2 if not s.get("dashed") else 1.4)
        if s.get("dashed"):
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        run: List[QPointF] = []
        for x, y in zip(xs, s["ys"]):
            if y is None:
                if len(run) > 1:
                    painter.drawPolyline(QPolygonF(run))
                run = []
                continue
            run.append(QPointF(px(x), py(y)))
        if len(run) > 1:
            painter.drawPolyline(QPolygonF(run))
        if s.get("dots"):
            painter.setBrush(QColor(s["color"]))
            for x, y in zip(xs, s["ys"]):
                if y is not None:
                    painter.drawEllipse(QPointF(px(x), py(y)), 2.5, 2.5)
    if mark_x is not None:
        main = series[0]
        y = next((yy for xx, yy in zip(xs, main["ys"]) if xx == mark_x), None)
        if y is not None:
            painter.setPen(QPen(QColor(theme.OBSTRUCTED), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(px(mark_x), py(y)), 6, 6)


def trend_chart(history, variable: str, dark: bool = True) -> QImage:
    """Hourly values for one variable. The x axis is hours before the latest."""
    _, unit, attr = VARIABLES[variable]
    pts = history.points
    n = len(pts)
    xs = [-(n - 1 - i) for i in range(n)]
    ys = [getattr(p, attr) for p in pts]
    image, painter, t = _canvas(dark)
    _draw(painter, t, xs, [{"ys": ys, "color": t["accent_strong"], "dots": True}], "h", unit, mark_x=0)
    painter.end()
    return image


def clearance_chart(profile: Sequence[dict], dark: bool = True) -> QImage:
    """Clearance available (solid) vs required (dashed, 60% of each sample's own
    first Fresnel radius) along the path; the library's critical point ringed."""
    xs = [p["distance_from_a_km"] for p in profile]
    available = [p["clearance_m"] for p in profile]
    required = [CLEAR_THRESHOLD * p["fresnel_radius_m"] for p in profile]
    crit = next((p["distance_from_a_km"] for p in profile if p["critical"]), None)
    image, painter, t = _canvas(dark)
    _draw(painter, t, xs, [{"ys": available, "color": t["accent_strong"]},
                           {"ys": required, "color": theme.MARGINAL, "dashed": True}], "km", "m", mark_x=crit)
    painter.end()
    return image


def images_for(names: Sequence[str], brief, dark: bool = True) -> Dict[str, QImage]:
    out: Dict[str, QImage] = {}
    for name in names:
        if name == "clearance" and brief.data.get("profile"):
            out[name] = clearance_chart(brief.data["profile"], dark)
        elif name in VARIABLES:
            history = (brief.data.get("history") or {}).get(brief.data.get("driver_site_id"))
            if history is not None:
                out[name] = trend_chart(history, name, dark)
    return out
