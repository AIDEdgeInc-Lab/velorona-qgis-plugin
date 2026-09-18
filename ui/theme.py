"""Velorona's own surface theme.

The tokens are the ones the Velorona web product already ships
(aei-link-clearance/web/style.css) -- same background, same accent blue, same
text ramp -- so the QGIS plugin and the web map read as one product rather than
two. They are applied only to Velorona's own widgets; no QGIS global preference
is touched and no other plugin or panel is affected.

The surface tones follow the host application: QGIS's UI theme is the user's
choice (default, Night Mapping, Blend of Gray, ...), so the panel reads the
active palette and picks the matching Velorona ramp rather than forcing one.
The accent blue is constant in both, because that is the brand.

No QGIS preference is ever written from here.
"""

BG = "#05090C"
SURFACE = "#081116"
SURFACE_RAISED = "#0d1922"
ACCENT = "#5F98D1"
ACCENT_SECONDARY = "#7AAEE3"
ACCENT_STRONG = "#99C6F3"
ACCENT_DEEP = "#224B75"
ACCENT_SOFT = "rgba(95, 152, 209, 0.12)"
ACCENT_LINE = "rgba(153, 198, 243, 0.24)"
BORDER = "rgba(96, 108, 118, 0.22)"
BORDER_STRONG = "rgba(96, 108, 118, 0.40)"
TEXT = "#F5F7FA"
TEXT_MUTED = "#AAB8C2"
TEXT_FAINT = "#7c8790"

# Status hues, also from the web product.
CLEAR = "#3FBE72"
MARGINAL = "#E0A73B"
OBSTRUCTED = "#E2594F"
NEAR_THRESHOLD = "#B98CE0"

# Light counterparts, for when the host QGIS theme is light. Same accent, same
# status hues; only the surface/text ramp flips so contrast stays correct.
LIGHT_BG = "#FFFFFF"
LIGHT_SURFACE = "#F5F7FA"
LIGHT_SURFACE_RAISED = "#EDF1F6"
LIGHT_TEXT = "#0D1922"
LIGHT_TEXT_MUTED = "#4A5A68"
LIGHT_TEXT_FAINT = "#5E6A75"   # 5.5:1 on white; #7C8790 measured 3.67:1
LIGHT_ACCENT_STRONG = "#224B75"
LIGHT_BORDER = "rgba(13, 25, 34, 0.16)"
LIGHT_BORDER_STRONG = "rgba(13, 25, 34, 0.3)"

SEVERITY_COLORS = {"low": CLEAR, "moderate": MARGINAL, "high": OBSTRUCTED}
REPRESENTATIVENESS_COLORS = {
    "consistent": CLEAR,
    "moderate_disagreement": MARGINAL,
    "high_disagreement": OBSTRUCTED,
    "insufficient_evidence": TEXT_FAINT,
}


def palette_is_dark(widget=None) -> bool:
    """True when the host QGIS theme is dark.

    The application palette is authoritative: switching the QGIS UI theme sets
    it, while an already-built widget can still be holding the palette it was
    created with. Night Mapping, Blend of Gray and any custom theme are all
    handled without Velorona knowing their names."""
    try:
        from qgis.PyQt.QtWidgets import QApplication
        palette = QApplication.palette()
        if palette is None and widget is not None:
            palette = widget.palette()
        return palette.window().color().lightness() < 128
    except Exception:
        return True


def tokens(dark: bool = True) -> dict:
    """The surface/text ramp for the active host theme. Accent and status hues
    are identical in both -- only the surfaces flip."""
    if dark:
        return {
            "bg": BG, "surface": SURFACE, "surface_raised": SURFACE_RAISED,
            "text": TEXT, "text_muted": TEXT_MUTED, "text_faint": TEXT_FAINT,
            "accent": ACCENT, "accent_strong": ACCENT_STRONG, "accent_deep": ACCENT_DEEP,
            "accent_soft": ACCENT_SOFT, "accent_line": ACCENT_LINE,
            "border": BORDER, "border_strong": BORDER_STRONG,
        }
    return {
        "bg": LIGHT_BG, "surface": LIGHT_SURFACE, "surface_raised": LIGHT_SURFACE_RAISED,
        "text": LIGHT_TEXT, "text_muted": LIGHT_TEXT_MUTED, "text_faint": LIGHT_TEXT_FAINT,
        "accent": ACCENT, "accent_strong": LIGHT_ACCENT_STRONG, "accent_deep": ACCENT_DEEP,
        "accent_soft": ACCENT_SOFT, "accent_line": "rgba(34, 75, 117, 0.28)",
        "border": LIGHT_BORDER, "border_strong": LIGHT_BORDER_STRONG,
    }


def widget_stylesheet(dark: bool = True) -> str:
    """Qt stylesheet for Velorona's dock chrome and Records table."""
    t = tokens(dark)
    BG, SURFACE, SURFACE_RAISED = t["bg"], t["surface"], t["surface_raised"]
    TEXT, TEXT_MUTED, TEXT_FAINT = t["text"], t["text_muted"], t["text_faint"]
    ACCENT, ACCENT_STRONG, ACCENT_DEEP = t["accent"], t["accent_strong"], t["accent_deep"]
    ACCENT_SOFT, ACCENT_LINE = t["accent_soft"], t["accent_line"]
    BORDER, BORDER_STRONG = t["border"], t["border_strong"]
    return f"""
    QWidget#veloronaRoot {{ background: {BG}; color: {TEXT}; }}
    QTabWidget::pane {{ border: none; background: {BG}; }}
    QTabBar::tab {{
        background: transparent; color: {TEXT_FAINT};
        padding: 7px 14px; margin-right: 2px; border: none;
        font-size: 11px; letter-spacing: 0.04em;
    }}
    QTabBar::tab:selected {{ color: {ACCENT_STRONG}; border-bottom: 2px solid {ACCENT}; }}
    QTabBar::tab:hover {{ color: {TEXT_MUTED}; }}
    QLineEdit, QComboBox {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 6px;
        padding: 5px 8px; font-size: 11.5px;
        selection-background-color: {ACCENT_DEEP};
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE}; color: {TEXT};
        selection-background-color: {ACCENT_DEEP}; border: 1px solid {BORDER};
    }}
    QTableView {{
        background: {SURFACE}; alternate-background-color: {SURFACE_RAISED};
        color: {TEXT}; gridline-color: {BORDER};
        border: 1px solid {BORDER}; border-radius: 6px;
        selection-background-color: {ACCENT_DEEP}; selection-color: {TEXT};
        font-size: 11.5px;
    }}
    QHeaderView::section {{
        background: {BG}; color: {TEXT_FAINT};
        padding: 6px 8px; border: none; border-bottom: 1px solid {ACCENT_LINE};
        font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
    }}
    QTextBrowser {{
        background: {BG}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 6px;
    }}
    QLabel#veloronaRecordsStatus {{ color: {TEXT_FAINT}; font-size: 10.5px; padding: 2px; }}
    QWidget#veloronaHeader {{ background: {BG}; }}
    QLabel#veloronaHeaderLabel {{ color: {TEXT_FAINT}; font-size: 10px;
                                  letter-spacing: 0.1em; text-transform: uppercase; }}
    QComboBox#veloronaAppearance {{ padding: 3px 8px; font-size: 11px; min-width: 76px; }}
    QPushButton {{
        background: {ACCENT_SOFT}; color: {ACCENT_STRONG};
        border: 1px solid {ACCENT_LINE}; border-radius: 6px;
        padding: 6px 12px; font-size: 11.5px;
    }}
    QPushButton:hover {{ background: rgba(95, 152, 209, 0.22); border-color: {ACCENT}; }}
    QPushButton:pressed {{ background: {ACCENT_DEEP}; color: {TEXT}; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: {BG}; width: 10px; height: 10px; border: none; }}
    QScrollBar::handle {{ background: {BORDER_STRONG}; border-radius: 5px; min-height: 24px; }}
    QScrollBar::handle:hover {{ background: {ACCENT_DEEP}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def report_stylesheet(dark: bool = True) -> str:
    """CSS for the evidence report rendered inside the QTextBrowser."""
    t = tokens(dark)
    BG, TEXT, TEXT_MUTED, TEXT_FAINT = t["bg"], t["text"], t["text_muted"], t["text_faint"]
    ACCENT, ACCENT_STRONG, ACCENT_DEEP = t["accent"], t["accent_strong"], t["accent_deep"]
    ACCENT_SOFT, ACCENT_LINE, BORDER = t["accent_soft"], t["accent_line"], t["border"]
    return f"""
<style>
body {{ background: {BG}; color: {TEXT};
       font-family: 'Geist Sans', -apple-system, system-ui, sans-serif; font-size: 12px; }}
.kicker {{ font-size: 9.5px; letter-spacing: 0.14em; color: {ACCENT}; margin-bottom: 2px;
          text-transform: uppercase; }}
h3 {{ margin: 0 0 10px; font-size: 15px; color: {TEXT}; font-weight: 600; letter-spacing: -0.01em; }}
.sec {{ font-size: 9.5px; letter-spacing: 0.12em; color: {TEXT_FAINT}; text-transform: uppercase;
       margin: 15px 0 5px; border-top: 1px solid {BORDER}; padding-top: 7px; }}
.sub {{ font-size: 9.5px; letter-spacing: 0.1em; color: {ACCENT}; text-transform: uppercase;
       margin: 9px 0 3px; }}
.site {{ font-size: 12.5px; font-weight: 600; color: {ACCENT_STRONG}; margin: 12px 0 3px;
        border-left: 2px solid {ACCENT}; padding-left: 7px; }}
.site .coord {{ font-weight: normal; color: {TEXT_FAINT}; font-size: 10.5px; float: right; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2px; }}
td {{ padding: 2px 8px 2px 0; vertical-align: top; }}
td.fk {{ color: {TEXT_MUTED}; white-space: nowrap; width: 42%; }}
td.nd {{ color: {TEXT_FAINT}; font-style: italic; }}
table.grid {{ margin-top: 4px; font-size: 10.5px; }}
table.grid th {{ text-align: left; color: {TEXT_FAINT}; font-weight: normal; font-size: 9.5px;
                letter-spacing: 0.06em; text-transform: uppercase;
                border-bottom: 1px solid {ACCENT_LINE}; padding: 3px 6px 3px 0; }}
table.grid td {{ border-bottom: 1px solid {BORDER}; padding: 3px 6px 3px 0; color: {TEXT_MUTED}; }}
.note {{ color: {TEXT_FAINT}; font-size: 10.5px; }}
.pill {{ font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; font-size: 11px; }}
.caveat {{ color: {TEXT_FAINT}; font-size: 10.5px; margin: 6px 0; line-height: 1.45; }}
.src {{ color: {TEXT_MUTED}; font-size: 10.5px; margin: 2px 0 8px; }}
.assumption {{ font-size: 10.5px; background: {ACCENT_SOFT}; color: {TEXT_MUTED};
              border-left: 2px solid {ACCENT_DEEP}; padding: 5px 8px;
              white-space: pre-wrap; margin: 3px 0; }}
p {{ margin: 4px 0; line-height: 1.45; }}
</style>
"""
