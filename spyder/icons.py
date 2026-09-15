"""The icons, drawn rather than fetched.

kitty draws its icons as inline line-art on a 16px grid; these are the same
idea in QPainter. Drawing them has two advantages over the icon font the app
used before: they are identical on every machine - Segoe Fluent Icons ships
with Windows 11, Segoe MDL2 with 10, and neither exists anywhere else, so the
old code carried a text fallback for a case it could not test - and they take
the app's stroke weight instead of a font designer's.

Everything is defined on its own square viewbox and scaled to the rect it is
asked for, so one definition serves a 10px window control and a 16px button.

Joins and caps are round. At this size that is what makes a corner read as
crafted rather than merely small, and it means each glyph is a polyline rather
than a path full of arc segments.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

# name -> (viewbox, stroke width in viewbox units, draw function)
_GLYPHS: dict = {}


def _glyph(name: str, viewbox: float, stroke: float):
    def register(function):
        _GLYPHS[name] = (viewbox, stroke, function)
        return function

    return register


def _line(path: QPainterPath, *points) -> None:
    """A polyline through the given (x, y) pairs."""
    path.moveTo(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))


# ------------------------------------------------------------ app icons (16)


@_glyph("link", 16, 1.35)
def _link(path: QPainterPath) -> None:
    """Two half-capsules joined by a bar - a chain link seen side on."""
    # Qt measures angles anticlockwise from three o'clock, in degrees.
    path.arcMoveTo(QRectF(1.5, 4.5, 7, 7), 60)
    path.arcTo(QRectF(1.5, 4.5, 7, 7), 60, 240)
    path.arcMoveTo(QRectF(7.5, 4.5, 7, 7), 300)
    path.arcTo(QRectF(7.5, 4.5, 7, 7), 300, 120)
    _line(path, (5.8, 8), (10.2, 8))


@_glyph("folder", 16, 1.35)
def _folder(path: QPainterPath) -> None:
    _line(path, (2.4, 5.4), (2.4, 3.8), (6.2, 3.8), (7.6, 5.4))
    path.addRoundedRect(QRectF(2.4, 5.4, 11.2, 7.6), 1.6, 1.6)


@_glyph("external", 16, 1.35)
def _external(path: QPainterPath) -> None:
    """A panel with an arrow leaving it: opens somewhere that is not here."""
    _line(path, (8.8, 3.6), (3.6, 3.6), (3.6, 12.4), (12.4, 12.4), (12.4, 7.2))
    _line(path, (7.4, 8.6), (12.4, 3.6))
    _line(path, (8.8, 3.6), (12.4, 3.6), (12.4, 7.2))


@_glyph("chevron", 16, 1.5)
def _chevron(path: QPainterPath) -> None:
    _line(path, (4.5, 6.5), (8, 10), (11.5, 6.5))


@_glyph("check", 16, 1.6)
def _check(path: QPainterPath) -> None:
    _line(path, (3.5, 8.4), (6.5, 11.4), (12.5, 4.6))


# ------------------------------------------------- window controls (10, 1.1)

# Deliberately the same weight as kitty's: a hairline, because these three sit
# in the corner of every screenshot and a heavy glyph there is the first thing
# the eye finds.


@_glyph("minimise", 10, 1.1)
def _minimise(path: QPainterPath) -> None:
    _line(path, (1, 5), (9, 5))


@_glyph("maximise", 10, 1.1)
def _maximise(path: QPainterPath) -> None:
    path.addRect(QRectF(1.5, 1.5, 7, 7))


@_glyph("close", 10, 1.1)
def _close(path: QPainterPath) -> None:
    _line(path, (1.5, 1.5), (8.5, 8.5))
    _line(path, (8.5, 1.5), (1.5, 8.5))


# ------------------------------------------------------------------- drawing


def draw(painter: QPainter, name: str, rect: QRectF, colour: str) -> None:
    """Stroke one glyph, scaled to fill rect and centred in it."""
    viewbox, stroke, build = _GLYPHS[name]

    path = QPainterPath()
    build(path)

    # The shorter side decides the scale, so a glyph asked for in an oblong
    # stays square and centred rather than stretching to the corners.
    side = min(rect.width(), rect.height())
    scale = side / viewbox

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(
        rect.x() + (rect.width() - side) / 2,
        rect.y() + (rect.height() - side) / 2,
    )
    painter.scale(scale, scale)

    pen = QPen(QColor(colour), stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


def pixmap(name: str, size: int, colour: str, ratio: float = 1.0) -> QPixmap:
    """One glyph as a pixmap, for the places Qt wants an image rather than paint."""
    image = QPixmap(round(size * ratio), round(size * ratio))
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    draw(painter, name, QRectF(0, 0, size, size), colour)
    painter.end()
    return image
