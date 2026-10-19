"""
Общие helper-функции форматирования и переиспользуемые виджеты TUI.
"""
import re

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, RichLog, Static

from utils import copy_to_clipboard, get_theme_colors, replace_flag_emojis

try:
    from textual.strip import Strip
except Exception:  # старый Textual: подсветка отключится, копирование останется
    Strip = None

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


class _BoldText(Static):
    """Текст с гарантированно жирным начертанием. Жирность в содержимом
    (Text(style="bold ...")), а не в CSS — не зависит от консоли."""

    DEFAULT_CSS = """
    _BoldText {
        content-align: center middle;
        text-align: center;
    }
    """

    HOVER_CLASSES = ("btn-action", "btn-lang", "btn-ping", "quit-btn",
                     "group-btn", "th-btn")

    def __init__(self, content="", color: str = "", hover_bg: str = "",
                 hover_text: str = "", **kwargs):
        super().__init__(**kwargs)
        self._bold_text = content
        self._color = color
        # Пер-кнопочные hover-цвета (иначе hover брался из ТЕКУЩЕЙ темы
        # и мог совпадать с фоном кнопки — «не реагирует на курсор»)
        self._hover_bg = hover_bg
        self._hover_text = hover_text

    def on_mount(self) -> None:
        self._sync_bold_text()

    def on_enter(self, event) -> None:
        self._apply_enter()

    def on_leave(self, event) -> None:
        self._apply_leave()

    def _apply_enter(self) -> None:
        if self.has_class(*self.HOVER_CLASSES):
            th = get_theme_colors()
            self.styles.background = self._hover_bg or th["button_hover"]
            ht = self._hover_text or th.get("button_hover_text") or th["button_text"]
            self._sync_bold_text(color=ht)

    def _apply_leave(self) -> None:
        if self.has_class(*self.HOVER_CLASSES):
            th = get_theme_colors()
            self.styles.background = th["button_bg"]
            self._sync_bold_text()

    def _set_hover(self, hovered: bool) -> None:
        """Hover-фон жёлтых кнопок: inline-стили, т.к. CSS :hover на
        родителе не срабатывает, когда курсор над дочерним Static."""
        if self.has_class("btn-action", "btn-lang", "btn-ping", "quit-btn",
                          "group-btn", "th-btn"):
            th = get_theme_colors()
            self.styles.background = th["button_hover"] if hovered else th["button_bg"]

    def _sync_bold_text(self, color: str = "") -> None:
        text = self._bold_text
        plain = text.plain if isinstance(text, Text) else str(text)
        color = color or self._color or get_theme_colors()["button_text"]
        self.update(Text(plain, style=f"bold {color}"))

    def update_text(self, content) -> None:
        self._bold_text = content
        try:
            self._sync_bold_text()
        except Exception:
            pass


class BoldLabel(_BoldText):
    """Однострочная подпись с гарантированно жирным текстом."""


class FlatButton(_BoldText):
    """Кнопка на базе Static. Клик шлёт стандартное Button.Pressed —
    обработчики экрана работают без изменений."""

    def on_click(self) -> None:
        if self.disabled:
            return
        self.post_message(Button.Pressed(self))


class _NodeCell(Static):
    """Ячейка строки ноды: пересылает Enter/Leave в строку (hover
    через дочерние Static к родителю в Textual не проваливается)."""

    def __init__(self, row: "NodeRow", content="", **kwargs):
        super().__init__(content, **kwargs)
        self._row = row

    def on_enter(self, event) -> None:
        self._row._hover(1)

    def on_leave(self, event) -> None:
        self._row._hover(-1)


class NodeRow(Widget):
    DEFAULT_CSS = """
    NodeRow {
        layout: horizontal;
        height: 1;
        width: 100%;
    }
    NodeRow Static { color: $accent; }
    NodeRow.current { background: $primary; }
    NodeRow.current Static { color: $secondary !important; }
    NodeRow .node-name { width: 1fr; text-align: left; }
    NodeRow .node-delay { width: 10; text-align: center; }
    NodeRow .node-status { width: 10; text-align: center; }
    """

    def __init__(self, index: int, name: str, delay: str, alive: str, current: bool,
                 group: str = "", on_select=None, key: str = ""):
        super().__init__(classes=("current " if current else "") + "node-row")
        self.index = index
        self._name = name      # отображаемый текст (может быть переводом)
        self._key = key        # служебный ключ (например AUTO_RESET)
        self._delay = delay
        self._alive = alive
        self._group = group
        self._on_select = on_select
        self._hov_depth = 0

    def compose(self) -> ComposeResult:
        # replace_flag_emojis: на Windows 🇷🇺 -> [RU], как в app.log
        name = replace_flag_emojis(self._name)
        display = f"[+] {name}" if "current" in self.classes else name
        yield _NodeCell(self, Text(display), classes="node-name")
        yield _NodeCell(self, Text(self._delay), classes="node-delay")
        yield _NodeCell(self, Text(self._alive), classes="node-status")

    def _hover(self, delta: int) -> None:
        self._hov_depth = max(0, self._hov_depth + delta)
        if self._hov_depth:
            self._apply_hover(True)
        else:
            self.call_after_refresh(self._maybe_hover_off)

    def _maybe_hover_off(self) -> None:
        if not self._hov_depth:
            self._apply_hover(False)

    def _apply_hover(self, hovered: bool) -> None:
        th = get_theme_colors()
        self.styles.background = th["button_hover"] if hovered else "transparent"
        if hovered:
            text = th.get("button_hover_text") or th["button_text"]
        else:
            text = th["tech_text"]
        for cls in ("node-name", "node-delay", "node-status"):
            try:
                self.query_one(f".{cls}", Static).styles.color = text
            except Exception:
                pass

    def on_click(self, event) -> None:
        if self._on_select is not None:
            self._on_select(self._group, self._key or self._name)

    def update_state(self, delay: str, alive: str, current: bool) -> None:
        """Обновить строку ноды без пересоздания виджета (пинг/статус/
        подсветка текущей) — иначе панель моргала каждый тик."""
        try:
            self.query_one(".node-delay", Static).update(Text(delay))
            self.query_one(".node-status", Static).update(Text(alive))
            self.set_class(current, "current")
            name = replace_flag_emojis(self._name)
            display = f"[+] {name}" if current else name
            self.query_one(".node-name", Static).update(Text(display))
        except Exception:
            pass


class GroupRow(Widget):
    """Группа прокси: жёлтая кнопка (FlatButton — тот же проверенный путь
    клика, что у главных кнопок) + опциональный список нод под ней.
    Клик по кнопке раскрывает/скрывает список (аккордеон)."""

    DEFAULT_CSS = """
    GroupRow {
        layout: vertical;
        height: 2;
        width: 100%;
        margin: 0 0 1 0;
    }
    /* Выпавший список нод: фон/текст как в таблице соединений (#1a0a30) */
    /* Высоту даёт проверенное правило, фон списка — чистый класс */
    GroupRow.open { height: auto; }
    .group-open { background: $background; }
    GroupRow FlatButton {
        width: 100%; height: 2;
        background: $primary;
        padding: 0 1;
    }
    /* Классом: центрирование идёт из content-align _BoldText,
       переопределяем оба свойства */
    .group-btn {
        content-align: left middle;
        text-align: left;
    }
    """

    def __init__(self, name: str, label: str, is_open: bool, button_id: str):
        super().__init__(classes="group-open open" if is_open else "")
        self.group_name = name
        self._label = label
        self._button_id = button_id

    def compose(self) -> ComposeResult:
        yield FlatButton(Text(self._label), id=self._button_id, classes="group-btn btn-action")

    def update_label(self, label: str) -> None:
        """Обновить подпись кнопки без пересборки (антимерцание)."""
        self._label = label
        try:
            self.query_one(FlatButton).update_text(Text(label))
        except Exception:
            pass


class ConnectionRow(Widget):
    DEFAULT_CSS = """
    ConnectionRow {
        layout: horizontal;
        height: 1;
        width: 100%;
    }
    ConnectionRow Static { color: $accent; }
    ConnectionRow.selected { background: $primary; }
    """

    def __init__(self, conn_id: str, on_close=None):
        super().__init__()
        self.conn_id = conn_id
        self._on_close = on_close
        self._cells = {}
        self._raw = {}

    def _apply_state(self) -> None:
        """Цвета под текущее состояние выделения. Inline-стили надёжнее
        CSS-каскада (ID-правила экрана перебивают классовые)."""
        active = "selected" in self.classes
        th = get_theme_colors()
        text_color = th["button_text"] if active else th["tech_text"]
        sep_color = th["button_text"] if active else th["button_bg"]
        for st in self._cells.values():
            st.styles.color = text_color
        for sep in self.query("Static.col-sep"):
            sep.styles.color = sep_color

    def _toggle_select(self) -> None:
        if "selected" in self.classes:
            self.remove_class("selected")
            self._apply_state()
        else:
            if self.parent is not None:
                for sibling in self.parent.query(ConnectionRow):
                    if sibling is not self and "selected" in sibling.classes:
                        # Снятие класса без обновления цветов оставило бы
                        # чёрный текст на тёмном фоне — «невидимую» строку.
                        sibling.remove_class("selected")
                        sibling._apply_state()
            self.add_class("selected")
            self._apply_state()

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
            st = Static("", classes=cls)
            self._cells[key] = st
            yield st
            yield Static("|", classes="col-sep")
        with Container(classes="col-act"):
            # Кнопка как статик: точный размер 3x1 и видимый текст.
            # id не задаём (дубли по экрану запрещены); обработка — внутри строки.
            yield Static(Text("[X]", style="bold #1a1a1a"), classes="close-x")

    def on_mount(self) -> None:
        try:
            self._apply_state()
        except Exception:
            pass

    def on_click(self, event) -> None:
        ctrl = event.control
        if isinstance(ctrl, Static) and ctrl.has_class("close-x"):
            # Клик по [X] закрывает соединение; событие дальше не пускаем.
            event.stop()
            if self._on_close is not None:
                self._on_close(self.conn_id)
            return
        # Клик по строке — выделение (полоса появляется только так)
        self._toggle_select()

    def set_data(self, domain, sport, dport, server, rule, ds, dt, us, ut, raw=None):
        # Text(...) — иначе квадратные скобки ([CZ], порты) съедаются
        # Rich-разметкой Static. Обновление безусловное: гейт по «значение
        # не изменилось» давал пустые ячейки на части сборок Textual.
        for key, value in (
            ("domain", domain), ("sport", sport), ("dport", dport),
            ("server", server), ("rule", rule),
            ("ds", ds), ("dt", dt), ("us", us), ("ut", ut),
        ):
            self._cells[key].update(Text(str(value)))
        if raw:
            self._raw = raw
class SelectableRichLog(RichLog):
    """RichLog с выделением текста мышью (drag) и копированием выделения
    через Ctrl+C. Координаты — в клетках отрендеренных строк (Strip),
    поэтому переносы длинных строк (wrap=True) обрабатываются сами.
    Подсветка рисуется заменой элементов списка self.lines: исходные
    Strip'ы запоминаются и возвращаются на место при смене выделения."""

    BINDINGS = [Binding("ctrl+c", "copy_selection", "Copy")]

    def __init__(self, *args, on_copy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_copy_cb = on_copy
        self._sel_anchor = None   # (strip_idx, cell) начала
        self._sel_focus = None    # (strip_idx, cell) конца при drag
        self._selection = None    # зафиксированное выделение для копирования
        self._orig_strips = {}    # strip_idx -> исходный Strip (до подсветки)
        self._captured = False

    # --- hit-testing ---

    def _lines(self):
        return getattr(self, "lines", None) or []

    def _content_hit(self, event):
        """(strip_idx, cell_x) под курсором или None (скроллбар/мимо)."""
        lines = self._lines()
        if not lines:
            return None
        x_local = event.screen_x - self.region.x
        y_local = event.screen_y - self.region.y
        width = self.region.width
        if width and x_local >= width - 1:
            return None  # столбец скроллбара (scrollbar-gutter: stable)
        if x_local < 0 or y_local < 0:
            return None
        idx = self.scroll_offset.y + y_local
        if not (0 <= idx < len(lines)):
            return None
        strip = lines[idx]
        cell = max(0, min(x_local, strip.cell_length - 1)) if strip.cell_length else 0
        return (idx, cell)

    @staticmethod
    def _norm(sel_a, sel_b):
        return (sel_a, sel_b) if sel_a <= sel_b else (sel_b, sel_a)

    # --- подсветка ---

    def _paint_selection(self):
        self._restore_strips()
        if not self._sel_anchor or not self._sel_focus:
            return
        if self._sel_anchor == self._sel_focus:
            return  # просто клик без drag — выделения нет
        (a_i, a_x), (b_i, b_x) = self._norm(self._sel_anchor, self._sel_focus)
        lines = self._lines()
        th = get_theme_colors()
        hl_fg = th.get("button_hover_text") or th["button_text"]
        hl_style = Style(color=hl_fg, bgcolor=th["button_hover"])
        for i in range(a_i, b_i + 1):
            if i >= len(lines):
                break
            strip = lines[i]
            if i not in self._orig_strips:
                self._orig_strips[i] = strip
            lo = a_x if i == a_i else 0
            hi = (b_x + 1) if i == b_i else strip.cell_length
            lines[i] = self._highlight_strip(strip, lo, hi, hl_style)
        self.refresh()

    @staticmethod
    def _highlight_strip(strip, start, end, style):
        if Strip is None or end <= start:
            return strip
        segs = getattr(strip, "_segments", None) or getattr(strip, "segments", None)
        if segs is None:
            return strip
        try:
            parts = Segment.divide(list(segs), [start, end])
            mid = []
            for seg in parts[1]:
                seg_style = seg.style if seg.style is not None else Style()
                mid.append(Segment(seg.text, seg_style + style))
            return Strip(list(parts[0]) + mid + list(parts[2]), strip.cell_length)
        except Exception:
            return strip

    def _restore_strips(self):
        lines = self._lines()
        for idx, strip in self._orig_strips.items():
            if 0 <= idx < len(lines):
                lines[idx] = strip
        self._orig_strips = {}

    def _reset_selection(self):
        self._restore_strips()
        self._sel_anchor = None
        self._sel_focus = None
        self._selection = None

    def clear(self):
        # Перерисовка буфера (переключение логов, новая строка) снимает
        # выделение: индексы Strip'ов больше не соответствуют тексту.
        self._reset_selection()
        return super().clear()

    # --- мышь ---

    def _on_mouse_down(self, event) -> None:
        try:
            super()._on_mouse_down(event)  # scrollbar-логика ScrollView
        except Exception:
            pass
        if getattr(event, "button", 1) != 1:
            return
        hit = self._content_hit(event)
        if hit is None:
            return
        self.focus()
        self._reset_selection()
        self._sel_anchor = hit
        self._sel_focus = hit
        try:
            self.capture_mouse()  # drag за пределы окна тоже ловим
            self._captured = True
        except Exception:
            pass

    def _on_mouse_move(self, event) -> None:
        try:
            super()._on_mouse_move(event)
        except Exception:
            pass
        if self._sel_anchor is None or not self._captured:
            return
        hit = self._content_hit(event)
        if hit is not None and hit != self._sel_focus:
            self._sel_focus = hit
            self._paint_selection()

    def _on_mouse_up(self, event) -> None:
        try:
            super()._on_mouse_up(event)
        except Exception:
            pass
        if not self._captured:
            return
        try:
            self.release_mouse()
        except Exception:
            pass
        self._captured = False
        if self._sel_anchor is not None and self._sel_focus is not None \
                and self._sel_anchor != self._sel_focus:
            self._selection = self._norm(self._sel_anchor, self._sel_focus)
        else:
            self._reset_selection()
        self._sel_anchor = None
        self._sel_focus = None

    # --- копирование ---

    @staticmethod
    def _slice_cells(text, start, end):
        """Срез строки по КЛЕТКАМ терминала (wide-символы = 2 клетки)."""
        if end <= start:
            return ""
        from rich.cells import cell_width

        out = []
        cell = 0
        for ch in text:
            w = cell_width(ch)
            if w < 1:
                w = 1
            ch_end = cell + w
            if ch_end <= start:
                cell = ch_end
                continue
            if cell >= end:
                break
            out.append(ch)
            cell = ch_end
        return "".join(out)

    def _selected_text(self):
        if not self._selection:
            return ""
        (a_i, a_x), (b_i, b_x) = self._selection
        lines = self._lines()
        parts = []
        for i in range(a_i, b_i + 1):
            if i >= len(lines):
                break
            text = lines[i].text
            if i == a_i and i == b_i:
                part = self._slice_cells(text, a_x, b_x + 1)
            elif i == a_i:
                part = self._slice_cells(text, a_x, 10 ** 9)
            elif i == b_i:
                part = self._slice_cells(text, 0, b_x + 1)
            else:
                part = text
            parts.append(part.rstrip(" "))
        return "\n".join(parts)

    def action_copy_selection(self) -> None:
        text = self._selected_text()
        if not text:
            return
        ok = copy_to_clipboard(text)
        if self._on_copy_cb is not None:
            try:
                self._on_copy_cb(text, ok)
            except Exception:
                pass
