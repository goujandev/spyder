"""The pieces Qt does not provide in this style.

Three groups live here. The first is the window itself: Spyder draws its own
title bar, so the drag, the double-click and the edge resize that the OS frame
used to provide have to be given back by hand (TitleBar, WindowControls,
EdgeResizer). The second is the canvas, which paints the dot texture. The third
is the two controls this style forbids Qt from floating - the quality dropdown
and the message box - both reimplemented as children of the main window.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEvent,
    QEventLoop,
    QObject,
    QPoint,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

POPUP_ROW_HEIGHT = 32
POPUP_PADDING = 4

# The dialog panel. Fixed rather than proportional, and comfortably inside the
# window's minimum width.
PANEL_WIDTH = 420
PANEL_INSET = 34  # the panel's own padding and border, both sides


def _centred(box, size: float) -> QRectF:
    """A square of the given size, centred in box."""
    return QRectF(
        box.x() + (box.width() - size) / 2,
        box.y() + (box.height() - size) / 2,
        size,
        size,
    )


def repolish(widget: QWidget) -> None:
    """Re-evaluate style sheet rules after a dynamic property has changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def section_label(text: str) -> QLabel:
    """UPPERCASE, small and letter-spaced. Names a group without shouting."""
    label = QLabel(text.upper())
    label.setObjectName("section")
    label.setFont(theme.label_font())
    return label


def action_button(text: str, kind: str = "") -> QPushButton:
    """A text button. kind is "primary" or "danger", or empty for a plain one."""
    button = QPushButton(text)
    if kind:
        button.setObjectName(kind)
    button.setFixedHeight(theme.ROW_HEIGHT)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


# ------------------------------------------------------------------- glyphs


class IconLabel(QLabel):
    """A glyph that is not a control: it states something, you cannot press it."""

    def __init__(
        self,
        name: str,
        object_name: str,
        size: int = 16,
        colour: str = theme.MUTED,
    ) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self._name = name
        self._size = size
        self._colour = colour
        # Room for the glyph plus whatever padding the style sheet adds.
        self.setMinimumWidth(size)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        painter = QPainter(self)
        icons.draw(
            painter, self._name, _centred(self.contentsRect(), self._size), self._colour
        )
        painter.end()


class IconButton(QPushButton):
    """An icon-only button.

    The glyph takes its colour from the button's state rather than from the
    style sheet, because a style sheet can colour text and a painted path is
    not text. The two states it has are named in theme.py, so this is still
    reading the palette rather than inventing one.
    """

    GLYPH = 16

    def __init__(self, name: str, tooltip: str, size: int = GLYPH) -> None:
        super().__init__()
        self.setObjectName("icon")
        self._name = name
        self._size = size
        self.setToolTip(tooltip)
        self.setFixedSize(theme.ROW_HEIGHT, theme.ROW_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _colour(self) -> str:
        if not self.isEnabled():
            return theme.MUTED
        return theme.TEXT if self.underMouse() else theme.MUTED

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)  # the style sheet's fill and radius
        painter = QPainter(self)
        icons.draw(painter, self._name, _centred(self.rect(), self._size), self._colour())
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().leaveEvent(event)
        self.update()


# ----------------------------------------------------------- window controls


class WinControl(QPushButton):
    """One of minimise, maximise, close."""

    GLYPH = 10

    def __init__(self, name: str, tooltip: str, closes: bool = False) -> None:
        super().__init__()
        self.setObjectName("wincontrolClose" if closes else "wincontrol")
        self._name = name
        self._closes = closes
        self.setToolTip(tooltip)
        self.setFixedSize(theme.WINCONTROL_WIDTH, theme.HEAD_HEIGHT)

    def _colour(self) -> str:
        if not self.underMouse():
            return theme.MUTED
        return "#ffffff" if self._closes else theme.TEXT

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        painter = QPainter(self)
        icons.draw(painter, self._name, _centred(self.rect(), self.GLYPH), self._colour())
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().leaveEvent(event)
        self.update()


class WindowControls(QWidget):
    """The three buttons, reaching the corner - where a hand goes for close."""

    def __init__(self, window: QWidget) -> None:
        super().__init__()
        self._window = window

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        minimise = WinControl("minimise", "Minimise")
        minimise.clicked.connect(window.showMinimized)
        maximise = WinControl("maximise", "Maximise")
        maximise.clicked.connect(self.toggle_maximised)
        close = WinControl("close", "Close", closes=True)
        close.clicked.connect(window.close)

        for button in (minimise, maximise, close):
            row.addWidget(button)

    def toggle_maximised(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()


class TitleBar(QWidget):
    """The strip the window is dragged by.

    Owing the user what the OS frame gave them means both gestures, not just
    the obvious one: press and drag moves the window, and a double-click
    maximises it. Handing the drag to startSystemMove rather than moving the
    window by hand is what keeps Aero Snap working - Windows runs the move
    loop, so dragging to an edge still snaps.
    """

    doubleClicked = pyqtSignal()  # noqa: N815 - mirrors Qt's own naming

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("head")
        self.setFixedHeight(theme.HEAD_HEIGHT)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            return
        super().mouseDoubleClickEvent(event)


class EdgeResizer(QObject):
    """Edge and corner resize for a window with no frame.

    The window's children cover it to the pixel, so there is no border left for
    the window itself to receive a press on. This watches events before they
    reach anyone, and only acts within a few pixels of an edge; everywhere else
    it is not there at all.

    Like the drag, the resize is handed to the OS rather than done by hand, so
    it behaves like every other window on the desktop.
    """

    MARGIN = 6

    _CURSORS = {
        Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
        Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._override = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _edge_at(self, position) -> int:
        """Which edges the pointer is within reach of, as a Qt.Edge flag set."""
        window = self._window
        if window.isMaximized() or window.isFullScreen() or not window.isVisible():
            return 0

        local = window.mapFromGlobal(position)
        x, y = local.x(), local.y()
        width, height = window.width(), window.height()
        if not (-1 <= x <= width and -1 <= y <= height):
            return 0

        margin = self.MARGIN
        edges = 0
        if x <= margin:
            edges |= Qt.Edge.LeftEdge.value
        elif x >= width - margin:
            edges |= Qt.Edge.RightEdge.value
        if y <= margin:
            edges |= Qt.Edge.TopEdge.value
        elif y >= height - margin:
            edges |= Qt.Edge.BottomEdge.value
        return edges

    def _set_override(self, shape) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if shape is None:
            if self._override:
                app.restoreOverrideCursor()
                self._override = False
            return
        if self._override:
            app.changeOverrideCursor(shape)
        else:
            app.setOverrideCursor(shape)
            self._override = True

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        kind = event.type()
        if kind not in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Leave,
        ):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self._window:
            return False

        if kind == QEvent.Type.Leave:
            self._set_override(None)
            return False

        edges = self._edge_at(event.globalPosition().toPoint())
        if kind == QEvent.Type.MouseMove:
            # No button held: the pointer is only passing through.
            if event.buttons() == Qt.MouseButton.NoButton:
                self._set_override(self._CURSORS.get(Qt.Edge(edges)) if edges else None)
            return False

        if edges and event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                self._set_override(None)
                handle.startSystemResize(Qt.Edge(edges))
                return True
        return False


# ------------------------------------------------------------------- canvas


class DotCanvas(QFrame):
    """Everything below the title strip, as one rounded panel inset from the
    window, filled with the dot texture.

    The texture is a tiled brush rather than a few thousand drawn circles, so
    a resize costs one fill no matter how large the window gets. The tile is
    rebuilt only when the screen's pixel ratio changes, because a 4px grid
    drawn at the wrong ratio is the one thing this texture cannot survive.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("canvas")
        self._ratio = 0.0
        self._brush = QBrush()

    def _refresh_tile(self) -> None:
        ratio = self.devicePixelRatioF()
        if ratio != self._ratio:
            self._ratio = ratio
            self._brush = QBrush(theme.dot_tile(ratio))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._refresh_tile()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Half a pixel in, so the 1px border lands on the pixel grid rather
        # than straddling it and rendering as two grey half-lines.
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(body, theme.R_LG, theme.R_LG)

        painter.fillPath(path, self._brush)
        painter.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


class ElidedLabel(QLabel):
    """A label that shrinks its text to fit rather than widening its row.

    Elides in the middle, because the end of a file name carries the extension.
    """

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(name)
        self._full = ""
        # Ignored, so a long name never pushes the row wider than the window.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        room = max(0, self.width() - 2)
        self.setText(
            self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, room)
        )


class Omnibox(QFrame):
    """The URL field, and the name of the site the link points at.

    Solid and a step up from the canvas, so it reads as an object standing on
    the texture rather than a hole cut into it. No ring until focus: a box that
    draws one the moment you click into it spends the whole time you are typing
    pointing at itself, and the caret has already said what the ring would.
    """

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("omnibox")
        self.setFixedHeight(theme.ROW_HEIGHT + 8)
        self.setProperty("focused", False)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrame(False)
        self.edit.installEventFilter(self)

        self._platform = QLabel("")
        self._platform.setObjectName("omniPlatform")
        self._platform.setFont(theme.label_font())
        self._platform.setVisible(False)
        self._platform.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(IconLabel("link", "omniIcon"))
        row.addWidget(self.edit, 1)
        row.addWidget(self._platform)

    def set_platform(self, name: str) -> None:
        """Name the site behind the current link, or pass "" to say nothing."""
        self._platform.setText(name.upper())
        self._platform.setVisible(bool(name))

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if obj is self.edit and event.type() in (
            QEvent.Type.FocusIn,
            QEvent.Type.FocusOut,
        ):
            self.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            repolish(self)
        return super().eventFilter(obj, event)


class BlockSelect(QFrame):
    """A dropdown whose menu is our own rows, drawn inside the window.

    The platform combo box popup is a floating window with its own frame and
    shadow. This style does not allow one, for the same reason the window draws
    its own title bar, so the popup here is a plain child widget of the main
    window raised over the page.
    """

    currentIndexChanged = pyqtSignal(int)  # noqa: N815 - mirrors QComboBox

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("select")
        self.setFixedHeight(theme.ROW_HEIGHT + 6)
        self.setProperty("open", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._placeholder = placeholder
        self._items: list[str] = []
        self._index = -1
        self._popup: QFrame | None = None

        self._text = QLabel(placeholder)
        self._text.setObjectName("selectText")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._text, 1)
        row.addWidget(IconLabel("chevron", "selectChevron"))

    # ------------------------------------------------------------------ model

    def set_items(self, items: list[str]) -> None:
        self.close_popup()
        self._items = list(items)
        self._index = 0 if self._items else -1
        self._text.setText(self._items[0] if self._items else self._placeholder)

    def clear(self) -> None:
        self.set_items([])

    def current_index(self) -> int:
        return self._index

    def count(self) -> int:
        return len(self._items)

    # ------------------------------------------------------------------ popup

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._items:
            if self._popup is not None:
                self.close_popup()
            else:
                self.open_popup()
            # Must be accepted. An ignored press is re-sent to the parent, and
            # that second delivery reaches the filter this press just installed,
            # which would read it as a click outside and shut the menu again.
            event.accept()
            return
        super().mousePressEvent(event)

    def open_popup(self) -> None:
        host = self.window()
        popup = QFrame(host)
        popup.setObjectName("popup")

        column = QVBoxLayout(popup)
        column.setContentsMargins(
            POPUP_PADDING, POPUP_PADDING, POPUP_PADDING, POPUP_PADDING
        )
        column.setSpacing(0)
        for index, label in enumerate(self._items):
            row = QPushButton(label, popup)
            row.setObjectName("row")
            row.setFixedHeight(POPUP_ROW_HEIGHT)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            # The chosen row is said in the accent, not with a fill.
            row.setProperty("selected", index == self._index)
            row.clicked.connect(lambda _checked=False, i=index: self._choose(i))
            column.addWidget(row)

        popup.adjustSize()
        width = max(self.width(), popup.sizeHint().width())
        height = popup.sizeHint().height()

        anchor = self.mapTo(host, QPoint(0, self.height() + 4))
        top = anchor.y()
        if top + height > host.height():
            # Not enough room below: open upwards, or pin to the window edge.
            above = self.mapTo(host, QPoint(0, 0)).y() - height - 4
            top = above if above >= 0 else max(0, host.height() - height)
        popup.setGeometry(anchor.x(), top, width, height)
        popup.show()
        popup.raise_()

        self._popup = popup
        self.setProperty("open", True)
        repolish(self)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def close_popup(self) -> None:
        if self._popup is None:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._popup.hide()
        self._popup.deleteLater()
        self._popup = None
        self.setProperty("open", False)
        repolish(self)

    def _choose(self, index: int) -> None:
        self.close_popup()
        if not 0 <= index < len(self._items) or index == self._index:
            return
        self._index = index
        self._text.setText(self._items[index])
        self.currentIndexChanged.emit(index)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if self._popup is not None:
            kind = event.type()
            # Only widget presses count. The same press also reaches the QWindow,
            # and closing on that would destroy the row before it is clicked.
            if kind == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget):
                inside = (
                    obj is self._popup
                    or self._popup.isAncestorOf(obj)
                    or obj is self
                    or self.isAncestorOf(obj)
                )
                if not inside:
                    self.close_popup()
            elif kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.close_popup()
                return True
            elif kind == QEvent.Type.Resize and obj is self.window():
                # The popup is positioned absolutely; a resize would strand it.
                self.close_popup()
            elif kind == QEvent.Type.WindowDeactivate:
                self.close_popup()
        return super().eventFilter(obj, event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.close_popup()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.close_popup()
        super().changeEvent(event)


class BlockDialog(QWidget):
    """A modal panel drawn over the page, in place of QMessageBox.

    It washes the page behind rather than hiding it, so you can still see what
    you were doing, and freezes the widgets around it so none of it is
    reachable.
    """

    def __init__(
        self,
        page: QWidget,
        tone: str,
        heading: str,
        message: str,
        buttons: list[tuple[str, str]],
        escape_index: int = 0,
    ) -> None:
        super().__init__(page)
        self.setObjectName("overlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # A QWidget subclass ignores its style sheet background unless told to
        # draw one, and without it the wash does not appear at all.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._result = escape_index
        self._escape_index = escape_index
        self._loop: QEventLoop | None = None
        self._frozen: list[QWidget] = []
        self._default: QPushButton | None = None

        panel = QFrame(self)
        panel.setObjectName("dialog")
        panel.setProperty("tone", tone)
        # A fixed width, not a maximum: a wrapped label only reports the height
        # it needs once the width it must wrap to is settled, and a panel sized
        # from an unwrapped hint clips its own message.
        panel.setFixedWidth(PANEL_WIDTH)

        column = QVBoxLayout(panel)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(12)
        column.addWidget(section_label(heading))

        text = QLabel(message)
        text.setObjectName("dialogText")
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        # A centred layout item is handed its size hint and never asked to
        # resolve height-for-width, so the wrapped height is measured here.
        inner = PANEL_WIDTH - PANEL_INSET
        text.setFixedWidth(inner)
        text.setFixedHeight(text.heightForWidth(inner))
        column.addWidget(text)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        for index, (label, kind) in enumerate(buttons):
            button = action_button(label, kind)
            button.clicked.connect(lambda _checked=False, i=index: self.finish(i))
            if kind == "primary" or self._default is None:
                self._default = button
            row.addWidget(button)
        column.addLayout(row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(2)
        outer.addWidget(panel, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(3)

    def exec(self, freeze: tuple[QWidget, ...] = ()) -> int:
        """Show the dialog and block until a button is pressed."""
        page = self.parentWidget()
        page.installEventFilter(self)
        self.setGeometry(page.rect())

        candidates = [
            child
            for child in page.children()
            if isinstance(child, QWidget) and child is not self
        ]
        candidates.extend(freeze)
        self._frozen = [widget for widget in candidates if widget.isEnabled()]
        for widget in self._frozen:
            widget.setEnabled(False)

        self.show()
        self.raise_()
        if self._default is not None:
            self._default.setFocus()
        else:
            self.setFocus()

        self._loop = QEventLoop()
        self._loop.exec()
        return self._result

    def finish(self, index: int) -> None:
        self._result = index
        page = self.parentWidget()
        if page is not None:
            page.removeEventFilter(self)
        for widget in self._frozen:
            widget.setEnabled(True)
        self._frozen = []
        self.hide()
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        self.deleteLater()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.finish(self._escape_index)
            return
        super().keyPressEvent(event)
