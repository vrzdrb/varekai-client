"""
Общие helper-функции форматирования и переиспользуемые виджеты TUI.
"""
import re

from textual.app import ComposeResult
from textual.containers import Container
from textual.widget import Widget
from textual.widgets import Button, Static

from utils import replace_flag_emojis

_TS_FRAC_RE = re.compile(r"(\d{2}:\d{2}:\d{2})\.\d+")


def fmt_core_line(line: str) -> str:
    return _TS_FRAC_RE.sub(r"\1", line)


def fmt_bytes(n) -> str:
    try:
        n = float(n)
    except Exception:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_speed(bps) -> str:
    return fmt_bytes(bps) + "/s"


class NodeRow(Widget):
    DEFAULT_CSS = """
    NodeRow {
        layout: horizontal;
        height: 1;
        width: 100%;
    }
    NodeRow Static { color: #0CEBE0; }
    NodeRow:hover { background: #F0C60A; }
    NodeRow:hover Static { color: #1a1a1a; }
    NodeRow.current { background: #F0C60A; }
    NodeRow.current Static { color: #1a1a1a !important; }
    NodeRow .node-name { width: 1fr; text-align: left; }
    NodeRow .node-delay { width: 10; text-align: center; }
    NodeRow .node-status { width: 10; text-align: center; }
    """

    def __init__(self, index: int, name: str, delay: str, alive: str, current: bool):
        super().__init__(classes="current" if current else "")
        self.index = index
        self._name = name
        self._delay = delay
        self._alive = alive

    def compose(self) -> ComposeResult:
        # replace_flag_emojis: на Windows 🇷🇺 -> [RU], как в app.log
        name = replace_flag_emojis(self._name)
        display = f"[+] {name}" if "current" in self.classes else name
        yield Static(display, classes="node-name")
        yield Static(self._delay, classes="node-delay")
        yield Static(self._alive, classes="node-status")


class _ConnCell(Static):
    """Ячейка строки: пересылает Enter/Leave в родительскую строку,
    чтобы жёлтое выделение срабатывало над всей строкой, а не только
    над её собственным фоном (Textual :hover до родителя не доводит)."""

    def __init__(self, row: "ConnectionRow", content: str = "", **kwargs):
        super().__init__(content, **kwargs)
        self._row = row

    def on_enter(self, event) -> None:
        self._row._cell_hover(+1)

    def on_leave(self, event) -> None:
        self._row._cell_hover(-1)


class ConnectionRow(Widget):
    DEFAULT_CSS = """
    ConnectionRow {
        layout: horizontal;
        height: 1;
        width: 100%;
    }
    ConnectionRow Static { color: #0CEBE0; }
    ConnectionRow:hover, ConnectionRow.row-hover { background: #F0C60A; }
    ConnectionRow:hover Static, ConnectionRow.row-hover Static { color: #1a1a1a; }
    """

    def __init__(self, conn_id: str, on_close=None):
        super().__init__()
        self.conn_id = conn_id
        self._on_close = on_close
        self._cells = {}
        self._raw = {}
        self._hover_depth = 0
        self._self_hover = False

    def _cell_hover(self, delta: int) -> None:
        self._hover_depth = max(0, self._hover_depth + delta)
        self._apply_hover()

    def on_enter(self, event) -> None:
        self._self_hover = True
        self._apply_hover()

    def on_leave(self, event) -> None:
        self._self_hover = False
        self._apply_hover()

    def _apply_hover(self) -> None:
        active = self._self_hover or self._hover_depth > 0
        self.set_class(active, "row-hover")
        # Inline-стили надёжнее CSS-каскада: текст и разделители в жёлтой
        # полосе — чёрные, иначе — бирюзовые.
        text_color = "#1a1a1a" if active else "#0CEBE0"
        sep_color = "#1a1a1a" if active else "#F0C60A"
        for st in self._cells.values():
            st.styles.color = text_color
        for sep in self.query("Static.col-sep"):
            sep.styles.color = sep_color

    def compose(self) -> ComposeResult:
        for key, cls in (
            ("domain", "col-domain"),
            ("server", "col-server"),
            ("rule", "col-rule"),
            ("ds", "col-ds"), ("dt", "col-dt"),
            ("us", "col-us"), ("ut", "col-ut"),
        ):
            st = _ConnCell(self, "", classes=cls)
            self._cells[key] = st
            yield st
            yield Static("|", classes="col-sep")
        with Container(classes="col-act"):
            # id не задаём (дубли по экрану запрещены); обработка — внутри строки.
            yield Button("✕", classes="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Обрабатываем здесь, а не на экране: событие никуда всплывать не должно.
        event.stop()
        if event.button.has_class("close-btn") and self._on_close is not None:
            self._on_close(self.conn_id)

    def set_data(self, domain, server, rule, ds, dt, us, ut, raw=None):
        self._cells["domain"].update(domain)
        self._cells["server"].update(server)
        self._cells["rule"].update(rule)
        self._cells["ds"].update(ds)
        self._cells["dt"].update(dt)
        self._cells["us"].update(us)
        self._cells["ut"].update(ut)
        if raw:
            self._raw = raw

