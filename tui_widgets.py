"""
Общие helper-функции форматирования и переиспользуемые виджеты TUI.
"""
import re

from textual.app import ComposeResult
from textual.containers import Container
from textual.widget import Widget
from rich.text import Text
from textual.widgets import Static

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
        yield Static(Text(display), classes="node-name")
        yield Static(Text(self._delay), classes="node-delay")
        yield Static(Text(self._alive), classes="node-status")


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
            ("sport", "col-sport"),
            ("dport", "col-dport"),
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
            # Кнопка как статик: точный размер 3x1 и видимый текст.
            # id не задаём (дубли по экрану запрещены); обработка — внутри строки.
            yield Static(Text("[X]"), classes="close-x")

    def on_click(self, event) -> None:
        # Клик по [X] закрывает соединение; событие дальше не пускаем.
        ctrl = event.control
        if isinstance(ctrl, Static) and ctrl.has_class("close-x"):
            event.stop()
            if self._on_close is not None:
                self._on_close(self.conn_id)

    def set_data(self, domain, sport, dport, server, rule, ds, dt, us, ut, raw=None):
        # Text(...) — иначе квадратные скобки ([CZ], порты) съедаются
        # Rich-разметкой Static.
        for key, value in (
            ("domain", domain), ("sport", sport), ("dport", dport),
            ("server", server), ("rule", rule),
            ("ds", ds), ("dt", dt), ("us", us), ("ut", ut),
        ):
            self._cells[key].update(Text(str(value)))
        if raw:
            self._raw = raw

