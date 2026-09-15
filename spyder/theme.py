"""The Spyder look: neutral dark, rounded, and drawn entirely by the app.

Everything visual lives here - colours, the radius scale, the three type roles
and the global stylesheet - so the widget code stays about behaviour.

The language is borrowed wholesale from kitty (goujandev/kitty), and the parts
worth naming are the ones that are decisions rather than values:

  * **No blue in the greys.** A tint that reads as merely "cool" on one panel
    becomes a colour cast across a window full of them, so the neutrals are
    true neutrals and the only hue in the app is the accent.
  * **Four radii, not a value per element.** Every rounded thing picks one of
    R_XS/R_SM/R_MD/R_LG, so two controls of the same weight cannot disagree
    about how round they are.
  * **The window is ours.** Spyder draws its own title bar, because an OS frame
    above a carefully made app looks like a web page in a picture frame. Doing
    that means owing the user everything the frame gave them - drag, double
    click to maximise, edge resize and Aero Snap all still work; see
    widgets.TitleBar and win32.py.
  * **One accent, spent on state.** Never decoration.
"""

from __future__ import annotations

from string import Template

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
)

# ------------------------------------------------------------------- palette

# Behind the inset panel, so its rounded edge has something to sit on.
SHELL = "#0c0c0c"
BG = "#131313"           # the canvas
PANEL = "#1e1e1e"
PANEL_2 = "#232323"
PANEL_EDGE = "#292929"   # hairline
EDGE_STRONG = "#3a3a3a"  # a border that has to be noticed, as on a focused field
# Solid, and a step up from the panels around it, so a field reads as an object
# standing on the texture rather than a hole cut into it.
RAISED = "#2b2b2b"

TEXT = "#f5f5f5"
MUTED = "#8a8a8a"

ACCENT = "#2b948b"
ON_ACCENT = "#ffffff"    # text on an accent-filled control

READY = "#4ade80"
BLOCKED = "#e3b341"
DANGER = "#f87171"
# Windows' own close-button red. The one control that turns a colour on hover,
# because it is the one control you must not press by accident.
CLOSE_HOVER = "#c42b1c"

# --------------------------------------------------------------------- radii

R_XS = 6
R_SM = 9
R_MD = 12
R_LG = 16
R_FULL = 999

# ------------------------------------------------------------------- metrics

HEAD_HEIGHT = 38
# The strip stays flush because the close button has to reach the corner; the
# panel does not, because nothing in it does.
CANVAS_INSET = 9
ROW_HEIGHT = 34
WINCONTROL_WIDTH = 44

# --------------------------------------------------------------------- fonts

_UI_STACK = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans")
_MONO_STACK = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New")

UI_FONT = _UI_STACK[0]
MONO_FONT = _MONO_STACK[0]

UI_SIZE = 14
MONO_SIZE = 12
LABEL_SIZE = 10
TITLE_SIZE = 13


def _first_available(candidates: tuple[str, ...], families: set[str]) -> str | None:
    for name in candidates:
        if name in families:
            return name
    return None


def _resolve_fonts() -> None:
    """Pick the best font installed for each of the two type roles."""
    global UI_FONT, MONO_FONT
    families = set(QFontDatabase.families())
    UI_FONT = _first_available(_UI_STACK, families) or QFont().defaultFamily()
    MONO_FONT = (
        _first_available(_MONO_STACK, families)
        or QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    )


def label_font() -> QFont:
    """UPPERCASE, small and letter-spaced, for section labels.

    Qt style sheets have no letter-spacing property, so it is set on the font.
    """
    font = QFont(UI_FONT)
    font.setPixelSize(LABEL_SIZE)
    font.setWeight(QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
    return font


def title_font() -> QFont:
    font = QFont(UI_FONT)
    font.setPixelSize(TITLE_SIZE)
    font.setWeight(QFont.Weight.DemiBold)
    return font


# ----------------------------------------------------------------- dot matrix

DOT_SPACING = 4
_DOT_CORE = 0.9    # solid out to here
_DOT_EDGE = 1.9    # gone by here
_DOT_STRENGTH = 0.55


def dot_tile(ratio: float = 1.0) -> QPixmap:
    """One cell of the texture the canvas is filled with.

    A soft dot on a 4px grid, dark enough to read as tooth in the surface and
    no darker. The falloff matters: the first version stepped from solid to
    nothing across a tenth of a pixel, which on a display that is not at 100%
    scaling cannot be drawn - every dot landed on the pixel grid differently
    and the texture crawled instead of sitting still.

    The dot darkens the background the way a multiply blend would. Since the
    surface underneath is one flat colour, that is the same as laying part
    opaque black over it, which is what this does.
    """
    size = max(1, round(DOT_SPACING * ratio))
    tile = QPixmap(size, size)
    tile.setDevicePixelRatio(ratio)
    tile.fill(QColor(BG))

    centre = DOT_SPACING / 2
    gradient = QRadialGradient(QPointF(centre, centre), _DOT_EDGE)
    dark = QColor(0, 0, 0)
    dark.setAlphaF(_DOT_STRENGTH)
    clear = QColor(0, 0, 0, 0)
    gradient.setColorAt(_DOT_CORE / _DOT_EDGE, dark)
    gradient.setColorAt(1.0, clear)

    painter = QPainter(tile)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(ratio, ratio)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRect(0, 0, DOT_SPACING, DOT_SPACING)
    painter.end()
    return tile


# ---------------------------------------------------------------- stylesheet

# $-substitution rather than str.format, because QSS is full of braces.
_QSS = Template("""
QWidget {
    background-color: $bg;
    color: $text;
    font-family: "$ui";
    font-size: ${ui_size}px;
}

/* --------------------------------------------------------------- the window */

/* The colour behind the inset canvas, and the only thing the OS frame would
   have covered. */
QWidget#shell { background-color: $shell; }

QWidget#head { background-color: $shell; }
QLabel#headTitle {
    background-color: transparent;
    color: $text;
    font-size: ${title_size}px;
}
QLabel#headSub {
    background-color: transparent;
    color: $muted;
    font-size: ${title_size}px;
}

/* Minimise, maximise, close. Square, flush to the corner, and quiet until
   pointed at - the only colour is the one that says "this one closes it". */
QPushButton#wincontrol {
    background-color: transparent;
    border: 0px;
    color: $muted;
    padding: 0px;
}
QPushButton#wincontrol:hover {
    background-color: $panel;
    color: $text;
}
QPushButton#wincontrolClose:hover {
    background-color: $close_hover;
    color: #ffffff;
}

/* The canvas paints its own rounded body and dot texture; see DotCanvas. */
QFrame#canvas { background-color: transparent; border: 0px; }
QWidget#page { background-color: transparent; }
QWidget#toolbar { background-color: transparent; }

QLabel#detailText {
    background-color: transparent;
    color: $muted;
    font-size: ${mono_size}px;
}

/* ----------------------------------------------------------------- omnibox */

/* Solid and a step up from the canvas, so it reads as an object on the texture
   rather than a hole cut into it. No border until focus: a box that draws a
   ring the moment you click into it spends the whole time you are typing
   pointing at itself, and the caret has already said what the ring would. */
QFrame#omnibox {
    background-color: $raised;
    border: 1px solid $raised;
    border-radius: ${r_md}px;
}
QFrame#omnibox[focused="true"] { border: 1px solid $edge_strong; }
QFrame#omnibox:disabled {
    background-color: $panel;
    border: 1px solid $panel;
}
QFrame#omnibox QLineEdit {
    background-color: transparent;
    border: 0px;
    color: $text;
    font-family: "$mono";
    font-size: ${mono_size}px;
    padding: 0px 4px 0px 0px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QFrame#omnibox QLineEdit:disabled { color: $muted; }
QLabel#omniIcon {
    background-color: transparent;
    color: $muted;
    padding: 0px 8px 0px 11px;
}

/* The recognised platform. State, so it takes the accent. */
QLabel#omniPlatform {
    background-color: $panel_2;
    border-radius: ${r_sm}px;
    color: $accent;
    margin: 5px 5px 5px 0px;
    padding: 0px 9px;
}
QFrame#omnibox:disabled QLabel#omniPlatform {
    background-color: $panel;
    color: $muted;
}

/* ----------------------------------------------------------------- buttons */

QPushButton {
    background-color: $panel_2;
    color: $text;
    border: 0px;
    border-radius: ${r_md}px;
    padding: 0px 16px;
}
QPushButton:hover { background-color: $panel_edge; }
QPushButton:pressed { background-color: $panel; }
QPushButton:disabled {
    background-color: $panel;
    color: $muted;
}
QPushButton#primary {
    background-color: $accent;
    color: $on_accent;
}
QPushButton#primary:hover { background-color: $accent_lit; }
QPushButton#primary:pressed { background-color: $accent_deep; }
QPushButton#primary:disabled {
    background-color: $panel;
    color: $muted;
}
QPushButton#danger { color: $danger; }
QPushButton#danger:hover { background-color: $panel_edge; }
QPushButton#danger:disabled { color: $muted; }

/* Square-ish, icon only, no fill until pointed at. */
QPushButton#icon {
    background-color: $panel_2;
    color: $muted;
    padding: 0px;
}
QPushButton#icon:hover { background-color: $panel_edge; color: $text; }
QPushButton#icon:disabled { background-color: $panel; color: $muted; }

/* ------------------------------------------------------------------ labels */

QLabel#section {
    background-color: transparent;
    color: $muted;
}
QLabel#status {
    background-color: transparent;
    color: $muted;
    font-family: "$mono";
    font-size: ${mono_size}px;
}

/* ---------------------------------------------------------------- surfaces */

QLineEdit#field {
    background-color: $panel;
    border: 1px solid $panel;
    border-radius: ${r_md}px;
    color: $muted;
    font-family: "$mono";
    font-size: ${mono_size}px;
    padding: 0px 12px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QPlainTextEdit#log {
    background-color: $panel;
    border: 0px;
    border-radius: ${r_md}px;
    color: $muted;
    font-family: "$mono";
    font-size: ${mono_size}px;
    padding: 8px 10px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}

/* ------------------------------------------------------------------ select */

QFrame#select {
    background-color: $panel;
    border: 1px solid $panel;
    border-radius: ${r_md}px;
}
QFrame#select[open="true"] { border: 1px solid $edge_strong; }
QFrame#select:hover { background-color: $panel_2; }
QFrame#select:disabled { background-color: $panel; }
QLabel#selectText {
    background-color: transparent;
    color: $text;
    padding: 0px 14px;
}
QFrame#select:disabled QLabel#selectText { color: $muted; }
QLabel#selectChevron {
    background-color: transparent;
    color: $muted;
    padding: 0px 12px 0px 0px;
}

/* The menu, drawn as a child of the window rather than a floating system
   popup, so nothing in the app has a frame the app did not draw. */
QFrame#popup {
    background-color: $panel_2;
    border: 1px solid $panel_edge;
    border-radius: ${r_md}px;
}
QPushButton#row {
    background-color: transparent;
    border: 0px;
    border-radius: ${r_sm}px;
    color: $text;
    padding: 0px 12px;
    text-align: left;
}
QPushButton#row:hover { background-color: $panel; }
/* The chosen one is said in the accent rather than with a fill, so the menu
   reads as a list with one answer in it rather than a row of buttons. */
QPushButton#row[selected="true"] { color: $accent; }

/* ------------------------------------------------------------------ result */

QFrame#result {
    background-color: $panel;
    border: 0px;
    border-radius: ${r_md}px;
}
QLabel#resultIcon {
    background-color: transparent;
    color: $ready;
    padding: 0px 10px 0px 12px;
}
QLabel#resultName {
    background-color: transparent;
    color: $text;
}
QLabel#resultSize {
    background-color: transparent;
    color: $muted;
    font-family: "$mono";
    font-size: ${mono_size}px;
    padding: 0px 10px;
}
QPushButton#reveal {
    background-color: $panel_2;
    border-radius: ${r_sm}px;
    color: $text;
    font-size: ${mono_size}px;
    padding: 0px 12px;
}
QPushButton#reveal:hover { background-color: $panel_edge; }

/* ---------------------------------------------------------------- progress */

QProgressBar {
    background-color: $panel;
    border: 0px;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: $accent;
    border-radius: 3px;
}

/* ----------------------------------------------------------------- dialogs */

/* A panel over the page rather than a floating QMessageBox, for the same
   reason the window draws its own frame. */
QWidget#overlay { background-color: rgba(12, 12, 12, 190); }
/* A step below the buttons inside it, so a plain one still reads as a control
   rather than a word printed on the panel. */
QFrame#dialog {
    background-color: $panel;
    border: 1px solid $panel_edge;
    border-radius: ${r_lg}px;
}
QLabel#dialogText {
    background-color: transparent;
    color: $muted;
}
QFrame#dialog QLabel#section { color: $text; }
QFrame#dialog[tone="danger"] QLabel#section { color: $danger; }
QFrame#dialog[tone="warning"] QLabel#section { color: $blocked; }

/* --------------------------------------------------------------- scrollbar */

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: $panel_edge;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: $edge_strong; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { height: 0px; }

QToolTip {
    background-color: $panel_2;
    color: $text;
    border: 1px solid $panel_edge;
    border-radius: ${r_sm}px;
    padding: 5px 9px;
    font-size: ${mono_size}px;
}
""")


def _shade(colour: str, factor: float) -> str:
    """Lighten (>1) or darken (<1) a hex colour, for the two button states."""
    c = QColor(colour)
    return QColor.fromHsvF(
        c.hueF(),
        c.saturationF(),
        max(0.0, min(1.0, c.valueF() * factor)),
    ).name()


def stylesheet() -> str:
    return _QSS.substitute(
        shell=SHELL,
        bg=BG,
        panel=PANEL,
        panel_2=PANEL_2,
        panel_edge=PANEL_EDGE,
        edge_strong=EDGE_STRONG,
        raised=RAISED,
        text=TEXT,
        muted=MUTED,
        accent=ACCENT,
        accent_lit=_shade(ACCENT, 1.12),
        accent_deep=_shade(ACCENT, 0.9),
        on_accent=ON_ACCENT,
        ready=READY,
        blocked=BLOCKED,
        danger=DANGER,
        close_hover=CLOSE_HOVER,
        ui=UI_FONT,
        mono=MONO_FONT,
        ui_size=UI_SIZE,
        mono_size=MONO_SIZE,
        label_size=LABEL_SIZE,
        title_size=TITLE_SIZE,
        r_xs=R_XS,
        r_sm=R_SM,
        r_md=R_MD,
        r_lg=R_LG,
        r_full=R_FULL,
    )


def _palette() -> QPalette:
    """QPalette for the parts Qt draws itself: carets, selections, disabled text."""
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: PANEL,
        QPalette.ColorRole.AlternateBase: PANEL_2,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.PlaceholderText: MUTED,
        QPalette.ColorRole.Button: PANEL_2,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.ToolTipBase: PANEL_2,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: ON_ACCENT,
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, colour in roles.items():
        pal.setColor(role, QColor(colour))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(MUTED))
    return pal


def apply(app) -> None:
    """Point a QApplication at the theme. Call once, before the window is built."""
    _resolve_fonts()
    app.setStyle("Fusion")
    app.setPalette(_palette())

    font = QFont(UI_FONT)
    font.setPixelSize(UI_SIZE)
    app.setFont(font)

    app.setStyleSheet(stylesheet())
