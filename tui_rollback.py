"""
Модальное окно отката ядра на одну из сохранённых версий.
"""
import time

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from core import CoreArchive
from utils import apply_scrollbar_palette, get_theme_colors, get_theme_name, t


class RbItem(Button):
    """Строка версии ядра в окне отката. Подсветка под курсором —
    цветами выделенной ноды в списке нод (select_bg/select_text).
    Цвета читаются из ЖИВОЙ палитры — при смене темы строки не залипают."""

    def __init__(self, label: str, **kwargs):
        super().__init__(label, classes="rb-item", **kwargs)
        self._hovered = False

    def on_mount(self) -> None:
        self._apply_base()

    def on_enter(self, event) -> None:
        self._hv_enter()

    def on_leave(self, event) -> None:
        self._hv_leave()

    def _apply_base(self) -> None:
        th = get_theme_colors()
        self.styles.background = "transparent"
        # Строки версий — rollback_item палитры (monokai: жёлтый темы)
        self.styles.color = th["rollback_item"]

    def _hv_enter(self) -> None:
        self._hovered = True
        th = get_theme_colors()
        self.styles.background = th["select_bg"]
        self.styles.color = th.get("select_text") or th["button_text"]

    def _hv_leave(self) -> None:
        self._hovered = False
        self._apply_base()


class RollbackScreen(ModalScreen):
    """Показывает архивы из archives/ и возвращает выбранный тег через dismiss."""

    CSS = """
    RollbackScreen {
        background: $background;
        layout: vertical;
        align: center middle;
    }
    .rb-panel {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        border: heavy $primary;
        background: $panel;
        color: $foreground;
        padding: 1 2;
    }
    .rb-title {
        width: 100%;
        text-align: center;
        color: $primary;  /* = цвет оформления/обрамления окон темы */
        text-style: bold;
        margin: 0 0 1 0;
    }
    #rb_scroll {
        height: auto;
        max-height: 1fr;
        scrollbar-size: 1 1;
        scrollbar-background: $panel;
        /* Цвета ползунка — инлайн из палитры кнопок групп (on_mount) */
    }
    .rb-item {
        width: 100%;
        height: 1;
        border: none;
        background: transparent;
        color: $accent;  /* = tech_text: текст строк версий = текст окна лога */
        text-align: left;
    }
    /* Подсветка строки под курсором — ТОЛЬКО через CSS :hover: в Textual 8
       screen-CSS перебивает инлайн-стили, подсветка из _hv_enter невидима.
       Селектор строго специфичнее базового .rb-item. Цвета = select_bg/
       select_text палитры — как выделенная нода в списке нод. */
    .th-varekai .rb-item:hover { background: #fccf44; color: #1a1a1a; }
    .th-nanita .rb-item:hover { background: #313d4e; color: #FFFFFF; }
    .th-geek_green .rb-item:hover { background: #033C1E; color: #0cf07a; }
    .th-blue_fir .rb-item:hover { background: #313d4e; color: #F6C884; }
    .th-monokai .rb-item:hover { background: #3F3309; color: #FCD13A; }
    .th-ikigai .rb-item:hover { background: #BD93F9; color: #282A36; }
    .rb-empty {
        width: 100%;
        text-align: center;
        color: $primary;
        margin: 1 0;
    }
    .rb-cancel {
        width: 100%;
        height: 1;
        border: none;
        background: #F50A0A;
        color: #ffffff;
        text-style: bold;
        margin: 1 0 0 0;
    }
    .rb-cancel:hover { background: #ff4444; }
    /* Рамка окна отката совпадает с рамками основного окна: у nanita
       и blue_fir они переопределены per-theme классом (см. tui_app) */
    .th-nanita .rb-panel { border: heavy #aeaeae; }
    .th-blue_fir .rb-panel { border: heavy #349da8; }
    .th-monokai .rb-panel { border: heavy #FCD13A; }
    /* Заголовок и фон панели красятся инлайн в on_mount из палитры:
       у nanita фон — серый tech_bg (modal_bg), текст строк — тёмный
       tech_text ($accent), заголовок — tech_text, у остальных тем —
       fill_text. */

    """

    BINDINGS = [
        ("escape", "close_screen", "Close"),
    ]

    def __init__(self, archives: list[CoreArchive], current_version: str):
        super().__init__()
        self._archives = archives
        self._current_version = current_version or ""

    def on_mount(self) -> None:
        # Класс темы — для per-theme CSS (рамка панели, см. выше)
        try:
            self.add_class(f"th-{get_theme_name()}")
        except Exception:
            pass
        # Фон окна — из палитры (modal_bg; у nanita — серый tech_bg,
        # как фон тех. окон). Заголовок — fill_text, на сером фоне
        # nanita — тёмный tech_text
        try:
            th = get_theme_colors()
            panel = self.query_one(".rb-panel", Container)
            panel.styles.background = th["modal_bg"]
            # Обрамление — как у основного окна (frame_color). Инлайн:
            # per-theme CSS descendant-правила в Textual 8 не матчатся.
            # Nanita — исключение: рамка = основной фон главного окна
            # (fill_bg), как на скриншоте.
            border_color = th["fill_bg"] if get_theme_name() == "nanita" else th["frame_color"]
            panel.styles.border = ("heavy", border_color)
            # Текст заголовка — rollback_title палитры (varekai: жёлтый,
            # как фон основных кнопок; nanita: чёрный на сером)
            self.query_one(".rb-title", Static).styles.color = th["rollback_title"]
        except Exception:
            pass
        try:
            apply_scrollbar_palette(self.query_one("#rb_scroll"))
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Container(classes="rb-panel"):
            yield Static(t("rollback_title"), classes="rb-title")
            if not self._archives:
                yield Static(t("rollback_empty"), classes="rb-empty")
            else:
                with VerticalScroll(id="rb_scroll"):
                    for i, arch in enumerate(self._archives):
                        marker = f"  ← {t('rollback_current')}" if arch.tag == self._current_version else ""
                        date = time.strftime("%Y-%m-%d %H:%M", time.localtime(arch.mtime))
                        yield RbItem(
                            f"{arch.tag}   {date}{marker}",
                            id=f"rb_{i}",
                        )
            yield Button(t("rollback_cancel"), id="rb_cancel", classes="rb-cancel")

    def action_close_screen(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "rb_cancel":
            self.dismiss(None)
            return
        if bid and bid.startswith("rb_"):
            try:
                idx = int(bid.split("_", 1)[1])
            except ValueError:
                return
            if 0 <= idx < len(self._archives):
                self.dismiss(self._archives[idx].tag)
