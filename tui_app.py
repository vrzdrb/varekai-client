"""
Главное TUI-приложение varekai на базе Textual.
"""
import asyncio
import time
from collections import deque
from functools import partial
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from clash_api import ClashAPI
from config import get_api_secret, get_proxy_groups_order
from core import (
    get_core_pid,
    get_current_core_info,
    get_current_version,
    list_core_archives,
    rollback_to_tag,
    start_vpn,
    stop_vpn,
    update_core,
    update_profile,
)
from tui_connections import ConnectionsScreen
from tui_rollback import RollbackScreen
from tui_widgets import (
    _BoldText,
    BoldLabel,
    ConnectionRow,
    FlatButton,
    GroupRow,
    NodeRow,
    SelectableRichLog,
    fmt_core_line,
)
from utils import (
    APP_VERSION,
    CORE_BINARY,
    CORE_LOG,
    THEMES,
    format_group_name,
    get_theme_colors,
    get_theme_name,
    get_language,
    get_os,
    load_settings,
    replace_flag_emojis,
    save_settings,
    set_language,
    t,
)

def _lc(ok: bool) -> str:
    """Цвет строки лога (успех/ошибка) из палитры текущей темы."""
    return get_theme_colors()["log_ok" if ok else "log_err"]


AUTO_RESET = "__AUTO_RESET__"
NO_CONN = "__NO_CONN__"
UI_REV = "gr36"  # маркер сборки интерфейса (для проверки, какой код реально запущен)

class QuitScreen(ModalScreen):
    """Подтверждение выхода при работающем VPN: Да — выйти, оставив VPN;
    Нет — остановить VPN и выйти; Esc — отмена."""

    CSS = """
    QuitScreen {
        background: $background;
        align: center middle;
    }
    .quit-panel {
        width: 52;
        max-width: 90%;
        height: auto;  /* иначе Container тянется на 1fr и центрировать нечего */
        border: heavy $primary;
        background: $panel;
        padding: 1 2;
    }
    .quit-text {
        width: 100%;
        text-align: center;
        color: $foreground;
        margin: 0 0 1 0;
    }
    .quit-row { width: 100%; height: 3; }
    .quit-btn {
        width: 1fr; height: 3; margin: 0;
        border: none;
        background: $primary; color: $secondary; text-style: bold;
    }
    .quit-btn:hover { background: $warning; }
    .quit-sep { width: 1; height: 3; background: $panel; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(classes="quit-panel"):
            yield Static(t("quit_dialog_msg"), classes="quit-text")
            with Horizontal(classes="quit-row"):
                yield FlatButton(t("quit_dialog_yes"), id="quit_yes", classes="quit-btn")
                yield Static("", classes="quit-sep")
                yield FlatButton(t("quit_dialog_no"), id="quit_no", classes="quit-btn")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit_yes":
            self.dismiss(True)   # оставить VPN работающим, выйти
        elif event.button.id == "quit_no":
            self.dismiss(False)  # остановить VPN и выйти


class ThemesScreen(ModalScreen):
    """Выбор темы оформления: кнопка каждой темы раскрашена её парой."""

    CSS = """
    ThemesScreen {
        background: $background;
        align: center middle;
    }
    .th-panel {
        width: 40;
        max-width: 90%;
        height: auto;
        border: heavy $primary;
        background: $panel;
        padding: 1 2;
    }
    .th-title {
        width: 100%; text-align: center;
        color: $foreground; text-style: bold;
        margin: 0 0 1 0;
    }
    .th-btn { width: 100%; height: 3; margin: 0 0 1 0; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(classes="th-panel"):
            yield Static(t("themes_title"), classes="th-title")
            current = get_theme_name()
            for name, th in THEMES.items():
                label = th["label"].get(get_language(), th["label"]["en"])
                if name == current:
                    label = f"[+] {label}"
                yield FlatButton(
                    Text(label), id=f"th_{name}",
                    classes=f"th-btn btn-action thbtn-{name}",
                    color=th["button_text"],
                    hover_bg=th["button_hover"],
                    hover_text=th.get("button_hover_text") or th["button_text"],
                )

    def on_mount(self) -> None:
        # фон кнопок задаётся CSS-классами .thbtn-<тема> —
        # инлайн-фон подавлял :hover
        pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("th_"):
            self.dismiss(bid[3:])


class VarekaiApp(App):
    TITLE = "varekai"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen { background: $background; text-style: bold; }

    #app_header {
        dock: top;
        height: 1;
        background: $panel;
        color: $foreground;
        text-align: center;
        text-style: bold;
        padding: 0;
        margin: 0;
    }

    #footer_bar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $foreground;
        padding: 0 1 0 3;
    }

    .panel {
        border: heavy $primary;
        padding: 1 2;
        margin: 0;
        background: $panel;
        color: $foreground;
    }
    .left-panel { width: 1fr; height: 100%; }
    .right-panel { width: 1fr; height: 100%; }

    #status_label {
        width: 100%;
        height: 1;
        text-align: center;
        color: #1a1a1a;
        text-style: bold;
        margin: 0 0 1 0;
    }
    #status_label.status-on  { background: #34C421; }
    #status_label.status-off { background: #F50A0A; }
    /* Дочерний Static _BoldText ловит глобальное Static{color:#e0e0e0}
       по типу, а не по наследованию — чёрный задаём явно */
    #status_label .fb-a { color: #1a1a1a; }
    .btn-action .fb-a, .btn-lang .fb-a, .quit-btn .fb-a { color: $secondary; }

    #info_label { width: 100%; text-align: center; margin: 0 0 1 0; }

    .btn-row { width: 100%; height: 3; margin: 1 0; }
    .btn-action {
        width: 1fr; height: 100%; margin: 0;
        border: none;
        background: $primary; color: $secondary; text-style: bold;
    }
    .btn-action:hover { background: $warning; }
    .btn-sep { width: 1; height: 3; background: $panel; }
    .lang-row { width: 100%; height: 3; margin: 0 0 1 0; }
    .btn-lang {
        width: 1fr; height: 100%;
        border: none;
        background: $primary; color: $secondary; text-style: bold;
    }
    .btn-lang:hover { background: $warning; }

    #log_title {
        width: 100%; text-align: center;
        color: $foreground; text-style: bold; margin: 0 0 1 0;
    }

    #log_frame {
        height: 1fr;
        border: heavy $primary;
        background: transparent;
        padding: 0 0 0 1;  /* левый отступ = ширине скроллбара справа */
        margin: 0;
    }
    #brief_log {
        width: 100%;
        height: 100%;
        background: $background;
        color: $accent;
        border: none;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;  /* место под скроллбар всегда занято */
        scrollbar-background: $panel;  /* = фон панели: поле справа как отступ слева */
        /* Ползунок в цвет фона лога: никаких глифов скроллбара ни на
        одной консоли (в т.ч. conhost), симметрия отступов сохраняется. */
        scrollbar-color: $surface;
        scrollbar-color-active: $surface;
    }

    #label_group { width: 100%; text-align: center; margin: 0 0; }

    Select { width: 100%; height: 3; background: transparent; margin: 1 0 1 0; }
    SelectCurrent {
        width: 100%; height: 100%;
        padding: 0 1;
        border: none;
        background: #F0C60A;
        color: #1a1a1a;
    }
    SelectCurrent Static, SelectCurrent Label {
        background: transparent;
        color: #1a1a1a !important;
        text-style: bold;
        height: 100%;
        content-align-vertical: middle;
    }
    SelectCurrent:focus {
        border: none;
        background: #F0C60A;
        color: #1a1a1a;
    }

    SelectOverlay {
        border: double #F0C60A;
        background: #1a0a30;
        height: auto;
        max-height: 100vh;
    }
    SelectOverlay OptionList,
    SelectOverlay .option-list {
        height: auto;
        background: #1a0a30;
    }
    SelectOverlay .option-list--option {
        background: #1a0a30;
        color: #0CEBE0 !important;
    }
    SelectOverlay .option-list--option:hover,
    SelectOverlay .option-list--option-highlighted,
    SelectOverlay .option-list--option-highlight {
        background: #F0C60A !important;
        color: #1a1a1a !important;
    }

    #groups_scroll NodeRow Static { color: $accent; }
    #groups_scroll NodeRow:hover Static { color: $secondary; }
    NodeRow.current, NodeRow.current Static {
        color: $secondary !important;
    }

    .node-header {
        layout: horizontal;
        height: 1;
        width: 100%;
        background: #5a4280;
    }
    .node-header Static { color: $foreground; text-style: bold; text-align: center; }
    /* «Задержка» — кликабельная кнопка теста пинга, стиль как у кнопок */
    #hdr_node_delay { background: #F0C60A; color: #1a1a1a; }
    #hdr_node_delay:hover { background: #f5d020; }
    .node-header .node-name { width: 1fr; }
    .node-header .node-delay { width: 10; }
    .node-header .node-status { width: 10; }

    #nodes_frame {
        height: 1fr;
        border: heavy $primary;
        background: transparent;
        padding: 0;
        margin: 0;
    }
    #groups_scroll {
        width: 100%;
        height: 1fr;
        background: $background;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;  /* скроллбар не появляется/не прячется при ресайзе */
        scrollbar-background: $panel;
        scrollbar-color: $primary;
        scrollbar-color-active: $warning;
    }
    .groups-title-row { width: 100%; height: 3; margin: 0 0 1 0; }
    #groups_title {
        width: 1fr; height: 3;
        color: $foreground; text-style: bold;
        content-align-vertical: middle;
    }
    .btn-ping {
        width: 16; height: 3;
        background: $primary;
    }
    .btn-ping:hover { background: $warning; }
    .btn-ping .fb-a { color: $secondary; }
    #groups_col1 { width: 100%; height: auto; }


    Button { background: $panel; color: $primary; border: none; }

    Button:hover { background: #6b5099; }
    Label { color: #e0e0e0; text-style: bold; margin: 1 0; }
    Static { color: $foreground; text-style: bold; }

    .col-domain { width: 1fr; min-width: 8; text-align: left; }
    .col-sport { width: 6; min-width: 0; text-align: right; }
    .col-dport { width: 6; min-width: 0; text-align: right; }
    .col-server { width: 25; min-width: 0; text-align: left; }
    .col-rule   { width: 36; min-width: 0; text-align: left; }
    .col-ds     { width: 8;  min-width: 0; text-align: right; }
    .col-dt     { width: 9;  min-width: 0; text-align: right; }
    .col-us     { width: 8;  min-width: 0; text-align: right; }
    .col-ut     { width: 9;  min-width: 0; text-align: right; }
    .col-act    { width: 3;  min-width: 0; text-align: center; align-horizontal: center; color: $primary; text-style: bold; }
    .col-sep    { width: 1;  text-align: center; color: $primary; }

    /* hover строк нод — в screen-CSS: псевдо-правила из DEFAULT_CSS
       виджетов в Textual 8 не срабатывают */
    #groups_scroll .node-row:hover { background: $warning; }
    #groups_scroll .node-row:hover Static { color: $secondary; }
    /* Кнопки групп: без фиксации высоты класс btn-action растягивал
       кнопку на всю раскрытую группу */
    #groups_scroll .group-btn { height: 2; width: 100%; }
    /* Кнопки выбора тем: фон ЧЕРЕЗ CSS (инлайн глушил :hover) */
    .thbtn-varekai { background: #fccf44; }
    .thbtn-black_on_white { background: #FFFFFF; }
    .thbtn-meshtastic { background: #033C1E; }
    .thbtn-nicedark { background: #7B7BFF; }
    .thbtn-monokai { background: #3F3309; }
    .thbtn-dracula { background: #BD93F9; }
    /* Ч/б: рамки всех окон — серые (мягче чистого чёрного) */
    .th-black_on_white .panel,
    .th-black_on_white #log_frame,
    .th-black_on_white #nodes_frame {
        border: heavy #aeaeae;
    }
    """

    # Дубли с русскими буквами: при русской раскладке те же клавиши
    # приходят как "й"/"ы"/"к"/"д"/"с" (и заглавные с Shift).
    BINDINGS = [
        ("q", "quit", "Quit"), ("й", "quit", "Quit"), ("Й", "quit", "Quit"),
        ("s", "toggle_vpn", "Toggle"), ("ы", "toggle_vpn", "Toggle"), ("Ы", "toggle_vpn", "Toggle"),
        ("r", "show_rollback", "Rollback"), ("к", "show_rollback", "Rollback"), ("К", "show_rollback", "Rollback"),
        ("l", "toggle_language", "Lang"), ("д", "toggle_language", "Lang"), ("Д", "toggle_language", "Lang"),
        ("c", "show_connections", "Connections"), ("с", "show_connections", "Connections"), ("С", "show_connections", "Connections"),
        ("t", "show_themes", "Theme"), ("е", "show_themes", "Theme"), ("Е", "show_themes", "Theme"),
        ("pageup", "log_page_up", "Log page up"),
        ("pagedown", "log_page_down", "Log page down"),
    ]

    vpn_running = reactive(False)

    def _lang_label(self) -> str:
        return f" {t('lang_current_name')}"

    @staticmethod
    def _btn_caption(plain: str, icon: str, frame: str = "[]") -> Text:
        """Подпись жёлтой кнопки. Windows-консоль рендерит эмодзи
        квадратами и ест '[...]' как разметку — там текст в скобках,
        обёрнутый в Text (без Rich-разметки)."""
        if get_os() == "windows":
            label = f">> {plain} <<" if frame == ">>" else f"[{plain}]"
        else:
            label = f"{icon} {plain}"
        return Text(label)

    def _toggle_caption(self) -> Text:
        running = self.vpn_running
        return self._btn_caption(
            t("btn_toggle_off") if running else t("btn_toggle_on"),
            "\u25a0" if running else "\u00bb",
        )

    def _conn_label(self) -> Text:
        return self._btn_caption(t("key_connections"), "\U0001F310")

    def _footer_text(self) -> str:
        kc = get_theme_colors().get("key_text") or get_theme_colors()["tech_text"]
        return (
            f"[bold][bold {kc}]S[/] {t('key_toggle')}    "
            f"[bold {kc}]C[/] {t('key_connections')}    "
            f"[bold {kc}]PgUp/PgDn[/] {t('key_log_scroll')}    "
            f"[bold {kc}]L[/] {t('key_lang')}    "
            f"[bold {kc}]R[/] {t('key_rollback')}    "
            f"[bold {kc}]T[/] {t('key_theme')}    "
            f"[bold {kc}]Q[/] {t('key_quit')}[/]"
        )

    def compose(self) -> ComposeResult:
        yield Static(f"varekai {APP_VERSION}", id="app_header")
        with Horizontal():
            with Container(classes="panel left-panel"):
                yield BoldLabel("", id="status_label", color="#1a1a1a")
                yield Static(id="info_label")
                with Horizontal(classes="btn-row"):
                    yield FlatButton(
                        self._btn_caption(t("btn_update_run"), "\U0001F504", frame=">>"),
                        id="btn_update_run", classes="btn-action",
                    )
                    yield Static("", classes="btn-sep")
                    yield FlatButton(
                        self._btn_caption(t("btn_toggle_on"), "\u00bb"),
                        id="btn_toggle", classes="btn-action",
                    )
                with Horizontal(classes="lang-row"):
                    yield FlatButton(
                        self._btn_caption(t("btn_logs"), "\U0001F4DC"),
                        id="btn_logs", classes="btn-lang",
                    )
                    yield Static("", classes="btn-sep")
                    yield FlatButton(self._conn_label(), id="btn_conn", classes="btn-lang")
                yield Static(t("log_app"), id="log_title")
                with Container(id="log_frame"):
                    yield SelectableRichLog(id="brief_log", max_lines=1000, wrap=True, markup=True,
                                  on_copy=self._on_log_copied)
            with Container(classes="panel right-panel"):
                with Horizontal(classes="groups-title-row"):
                    yield Static(t("groups_title"), id="groups_title")
                    yield FlatButton(t("btn_test_ping"), id="btn_ping", classes="btn-ping")
                with Container(id="nodes_frame"):
                    with VerticalScroll(id="groups_scroll"):
                        with Vertical(id="groups_col1"):
                            pass
        yield Static(self._footer_text(), id="footer_bar")

    def on_mount(self) -> None:
        self.api = ClashAPI(get_api_secret())
        self.log_offset = 0
        self.current_group = None
        self.current_country = ""
        self._node_order = []
        self._nodes_sig = None
        self._opts_sig = None
        self._groups_sig = None
        self._open_group = None
        self._groups_lock = asyncio.Lock()
        self._group_by_button = {}
        self._seen_errors = set()
        self._groups_order = get_proxy_groups_order()
        self.log_source = "app"
        self._app_buf = deque(maxlen=1000)
        self._core_buf = deque(maxlen=1000)
        self.update_status()
        self.set_interval(0.3, self.tail_logs)
        self.set_interval(0.3, self._hover_sanity)
        self.set_interval(2.0, self.poll_proxies)
        self._register_themes()
        self._apply_theme(get_theme_name(), save=False)
        self._hovered_widget = None
        self._hovered_row = None
        self._last_mouse = None

    def update_status(self):
        pid = get_core_pid()
        status_label = self.query_one("#status_label", BoldLabel)
        btn_toggle = self.query_one("#btn_toggle", FlatButton)
        status_label.remove_class("status-on", "status-off")
        if pid:
            status_label.add_class("status-on")
            status_label.update_text(t("status_running"))
            self.vpn_running = True
            btn_toggle.update_text(self._toggle_caption())
        else:
            status_label.add_class("status-off")
            status_label.update_text(t("status_stopped"))
            self.vpn_running = False
            btn_toggle.update_text(self._toggle_caption())
        self.update_info_line()

    def update_info_line(self):
        country = replace_flag_emojis(self.current_country or t("country_unknown"))
        # Text(...) — иначе [RU] из замены флагов съедается Rich-разметкой Static
        self.query_one("#info_label", Static).update(
            Text(f"{get_current_core_info()} | {t('current_country', country=country)}")
        )

    def _render_log(self):
        widget = self.query_one("#brief_log", SelectableRichLog)
        widget.clear()
        if self.log_source == "core":
            for line in self._core_buf:
                widget.write(Text(line, style="bold"))
        else:
            for line in self._app_buf:
                widget.write(line)

    def brief_log(self, message: str):
        message = f"[bold]{message}[/]"
        self._app_buf.append(message)
        if self.log_source == "app":
            try:
                self.query_one("#brief_log", SelectableRichLog).write(message)
            except Exception:
                pass

    def _append_core(self, line: str):
        line = fmt_core_line(line)
        self._core_buf.append(line)
        if self.log_source == "core":
            try:
                self.query_one("#brief_log", SelectableRichLog).write(Text(line, style="bold"))
            except Exception:
                pass

    def _on_log_copied(self, text: str, ok: bool) -> None:
        """Ctrl+C в окне лога: отчёт о копировании в лог приложения."""
        if ok:
            self.brief_log(t("log_copied", n=len(text)))
        else:
            self.brief_log(f"[bold {_lc(False)}]{t('log_copy_fail')}[/]")

    def action_toggle_logs(self):
        self.log_source = "core" if self.log_source == "app" else "app"
        title = t("log_core") if self.log_source == "core" else t("log_app")
        self.query_one("#log_title", Static).update(title)
        self._render_log()

    def _request_toggle(self) -> None:
        """Мгновенная реакция UI + запуск рабочего потока.
        Без этого экран не менялся все секунды, пока ядро стартует,
        а при исключении в воркере оставался рассинхронизированным."""
        btn_toggle = self.query_one("#btn_toggle", FlatButton)
        if btn_toggle.disabled:
            return  # операция уже выполняется
        btn_toggle.disabled = True
        starting = not self.vpn_running
        message = t("brief_starting") if starting else t("brief_stopping")
        self.query_one("#status_label", BoldLabel).update_text(message)
        self.brief_log(message)
        self.run_worker(self._worker_toggle, thread=True)

    def action_quit(self) -> None:
        if self.vpn_running:
            self.push_screen(QuitScreen(), self._on_quit_answer)
        else:
            self.exit()

    def _on_quit_answer(self, leave_vpn) -> None:
        if leave_vpn is None:
            return
        if leave_vpn:
            self.exit()
        else:
            self.run_worker(self._worker_stop_and_quit, thread=True)

    def _worker_stop_and_quit(self) -> None:
        stop_vpn()
        self.call_from_thread(self.exit)

    def action_toggle_vpn(self):
        self._request_toggle()

    def action_show_rollback(self):
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return
        archives = list_core_archives()
        self.push_screen(
            RollbackScreen(archives, get_current_version()),
            self._on_rollback_selected,
        )

    def _on_rollback_selected(self, tag):
        if not tag:
            return
        self.run_worker(partial(self._worker_rollback, tag), thread=True)

    def _worker_rollback(self, tag: str):
        th = get_theme_colors()
        self.call_from_thread(self.brief_log, t("rollback_title") + f": {tag} ...")
        ok, msg = rollback_to_tag(tag)
        if ok:
            self.call_from_thread(self.brief_log, f"[bold {th['log_ok']}]{msg}[/]")
        else:
            self.call_from_thread(self.brief_log, f"[bold {th['log_err']}]{msg}[/]")
        self.call_from_thread(self.update_status)

    def action_show_connections(self):
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return
        self.push_screen(ConnectionsScreen(self.api))

    def action_toggle_language(self):
        new_lang = "en" if get_language() == "ru" else "ru"
        settings = load_settings()
        settings["language"] = new_lang
        save_settings(settings)
        set_language(new_lang)
        self._update_ui_texts()
        self.brief_log(t("brief_lang_changed", lang=new_lang))

    def on_mouse_move(self, event) -> None:
        """Единый hover для кнопок и строк нод: Enter/Leave в Textual 8 не
        доходят до виджетов внутри скроллов, а CSS :hover снимается с
        задержкой — отслеживаем курсор сами и красим инлайн мгновенно.
        API поиска виджета под курсором в v8 мог быть переименован —
        перебираем варианты с однократной диагностикой."""
        self._last_mouse = (event.screen_x, event.screen_y)
        self._update_hover(event.screen_x, event.screen_y)

    def _update_hover(self, x, y) -> None:
        """Пересчёт hover по координатам экрана (тело трекера)."""
        screen = self.screen
        getter = getattr(screen, "get_widget_at", None) or getattr(screen, "widget_at", None)
        if getter is None:
            if not getattr(self, "_hover_api_warned", False):
                self._hover_api_warned = True
                self.brief_log("hover: API get_widget_at не найден")
            return
        try:
            result = getter(x, y)
        except TypeError:
            try:
                result = getter(int(x), int(y))
            except Exception:
                return
        except Exception:
            return
        widget = result[0] if isinstance(result, tuple) else result
        # Один подъём по родителям: ищем и кнопку (_BoldText), и строку ноды
        bold_target = None
        row_target = None
        node = widget
        while node is not None:
            if bold_target is None and isinstance(node, _BoldText) and node.has_class(*_BoldText.HOVER_CLASSES):
                bold_target = node
            if row_target is None and isinstance(node, NodeRow):
                row_target = node
            if bold_target is not None and row_target is not None:
                break
            node = getattr(node, "parent", None)
        # Кнопки: hover-инлайн как раньше
        if bold_target is not self._hovered_widget:
            old = self._hovered_widget
            self._hovered_widget = bold_target
            if isinstance(old, _BoldText):
                try:
                    old._apply_leave()
                except Exception:
                    pass
            if isinstance(bold_target, _BoldText):
                try:
                    bold_target._apply_enter()
                except Exception:
                    pass
        # Строки нод: CSS :hover в Textual 8 «залипает» и снимается с
        # задержкой — hover строк дублируем инлайн: включается и
        # ВЫКЛЮЧАЕТСЯ мгновенно, по событию движения курсора
        if row_target is not self._hovered_row:
            old_row = self._hovered_row
            self._hovered_row = row_target
            if old_row is not None:
                try:
                    old_row._apply_hover(False)
                except Exception:
                    pass
            if row_target is not None:
                try:
                    row_target._apply_hover(True)
                except Exception:
                    pass

    def _rehover_at_last_pos(self) -> None:
        """Пересчёт hover по последней известной позиции курсора."""
        if self._last_mouse is None:
            return
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return  # под модалками трекер главного экрана молчит
        self._update_hover(*self._last_mouse)

    def _hover_sanity(self) -> None:
        """Страховка от «залипания»: если события движения по какой-то
        причине не дошли до приложения (скролл колесом, рывок курсора,
        окно временно расфокусировано), hover пересчитывается по последней
        известной позиции — без ожидания следующего движения мыши."""
        self._rehover_at_last_pos()

    def on_mouse_scroll_down(self, event) -> None:
        self._rehover_at_last_pos()  # контент под курсором съехал при прокрутке

    def on_mouse_scroll_up(self, event) -> None:
        self._rehover_at_last_pos()

    def _register_themes(self) -> bool:
        try:
            from textual.theme import Theme
        except Exception:
            return False
        ok = False
        for name, th in THEMES.items():
            try:
                self.register_theme(Theme(
                    name=name,
                    primary=th["button_bg"],
                    secondary=th["button_text"],
                    warning=th["button_hover"],
                    accent=th["tech_text"],
                    background=th["fill_bg"],
                    surface=th["tech_bg"],
                    panel=th["panel_bg"],
                    foreground=th["fill_text"],
                ))
                ok = True
            except Exception:
                pass
        return ok

    def action_show_themes(self) -> None:
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen, ThemesScreen)):
            return
        self.push_screen(ThemesScreen(), self._on_theme_picked)

    def _on_theme_picked(self, name) -> None:
        if not name:
            return
        self._apply_theme(name, save=True)

    def _apply_theme(self, name: str, save: bool = False) -> None:
        th = get_theme_colors(name)
        if save:
            settings = load_settings()
            settings["theme"] = name
            save_settings(settings)
        try:
            self.theme = name
        except Exception:
            pass  # старый Textual: токены переключатся после перезапуска
        try:
            for cls in list(self.screen.classes):
                if cls.startswith("th-"):
                    self.screen.remove_class(cls)
            self.screen.add_class(f"th-{name}")
        except Exception:
            pass
        # Плашки шапки/футера — вне токенов
        for wid in ("#app_header", "#footer_bar"):
            try:
                self.query_one(wid, Static).styles.background = th["bar_bg"]
            except Exception:
                pass
        # Тех. окна — явное присвоение из палитры: на части сборок токен
        # $surface рендерился не тем оттенком, инлайн перебивает каскад
        for wid in ("#groups_scroll",):
            try:
                self.query_one(wid).styles.background = th["tech_bg"]
            except Exception:
                pass
        # Фон лога — чуть светлее заливки: прежний «фокусный» оттенок
        # теперь постоянный, щелчок по логу ничего не меняет (инлайн
        # перебивает любой focus-CSS)
        try:
            self.query_one("#brief_log").styles.background = th["log_bg"]
        except Exception:
            pass
        # Подписи кнопок с инлайн-цветом — ресинхрон под новую палитру
        for widget in self.query(_BoldText):
            try:
                widget._sync_bold_text()
            except Exception:
                pass
        # Выделенные строки соединений — перекраска под тему
        for row in self.query("ConnectionRow"):
            try:
                row._apply_state()
            except Exception:
                pass
        try:
            self.query_one("#footer_bar", Static).update(self._footer_text())
        except Exception:
            pass

    def action_log_page_up(self) -> None:
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return
        self.query_one("#brief_log", SelectableRichLog).scroll_page_up(animate=False)

    def action_log_page_down(self) -> None:
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return
        self.query_one("#brief_log", SelectableRichLog).scroll_page_down(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Обработчик кнопок ГЛАВНОГО экрана.
        # Кнопки окна соединений обрабатываются самим ConnectionsScreen
        # и ConnectionRow — сюда они доходить не должны.
        btn_id = event.button.id
        if btn_id == "btn_toggle":
            self._request_toggle()
        elif btn_id == "btn_update_run":
            self.run_worker(self._worker_update_and_run, thread=True)
        elif btn_id == "btn_lang":
            self.action_toggle_language()
        elif btn_id == "btn_logs":
            self.action_toggle_logs()
        elif btn_id == "btn_conn":
            self.action_show_connections()
        elif btn_id == "btn_ping":
            self.run_worker(self._test_group_delay())
        elif btn_id and btn_id.startswith("gr_"):
            group = self._group_by_button.get(btn_id)
            if group:
                self._on_group_toggle(group)

    def _log_result(self, ok: bool, msg: str):
        th = get_theme_colors()
        color = th["log_ok"] if ok else th["log_err"]
        self.call_from_thread(self.brief_log, f"[bold {color}]{msg}[/]")

    def _worker_toggle(self):
        try:
            if self.vpn_running:
                ok, msg = stop_vpn()
            else:
                if not Path(CORE_BINARY).exists():
                    self.call_from_thread(
                        self.brief_log, f"[bold {_lc(False)}]{t('core_not_found')}[/]"
                    )
                    return
                ok, msg = start_vpn()
            self._log_result(ok, msg)
        finally:
            def _finish() -> None:
                try:
                    self.query_one("#btn_toggle", FlatButton).disabled = False
                    self.update_status()
                    self.refresh()
                except Exception:
                    pass

            try:
                self.call_from_thread(_finish)
            except Exception:
                pass

    def _worker_update_and_run(self):
        if self.vpn_running or get_core_pid():
            self.call_from_thread(
                self.brief_log, f"[bold {_lc(False)}]{t('core_running_update')}[/]"
            )
            return

        self.call_from_thread(self.brief_log, t("brief_checking"))
        core_status, msg = update_core()
        if core_status == 0:
            self._log_result(True, msg)
        elif core_status == 1:
            self._log_result(True, msg)
        else:
            self._log_result(False, msg)
            return

        self.call_from_thread(self.brief_log, t("brief_updating_profile"))
        profile_status, msg = update_profile()
        self._log_result(profile_status == 1, msg)

        self.call_from_thread(self._reload_groups_order)
        self.call_from_thread(self.brief_log, t("brief_starting"))
        ok, msg = start_vpn()
        self._log_result(ok, msg)
        self.call_from_thread(self.update_status)

        if ok:
            self.call_from_thread(self.brief_log, t("brief_updating_rules"))
            ok_rules = self._update_rule_providers_sync()
            if ok_rules:
                th = get_theme_colors()
                self.call_from_thread(self.brief_log, f"[bold {th['log_ok']}]{t('rule_providers_ok')}[/]")
            else:
                self.call_from_thread(self.brief_log, f"[bold {th['log_err']}]{t('rule_providers_fail')}[/]")

    def _update_rule_providers_sync(self) -> bool:
        """Обновляет все rule-providers через API ядра (механизм clash-verge-rev):
        1. Ждём готовности API через GET /providers/rules.
        2. Берём имена и типы провайдеров из ответа ядра.
        3. Для каждого (кроме inline): PUT /providers/rules/{имя}.
        Возвращает True, если все провайдеры обновились успешно."""
        import urllib.parse

        import requests as req
        secret = get_api_secret()
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        base = "http://127.0.0.1:9090"
        providers = None
        for _ in range(15):
            try:
                r = req.get(f"{base}/providers/rules", headers=headers, timeout=3)
                if r.status_code == 200:
                    providers = r.json().get("providers") or {}
                    break
            except Exception:
                pass
            time.sleep(1)
        if providers is None:
            return False
        targets = [
            name for name, data in providers.items()
            if isinstance(data, dict)
            and str(data.get("type", "")).lower() in ("http", "file")
        ]
        if not targets:
            return True
        all_ok = True
        for name in targets:
            encoded = urllib.parse.quote(name, safe="")
            try:
                r = req.put(
                    f"{base}/providers/rules/{encoded}",
                    headers=headers,
                    timeout=30,
                )
                ok = r.status_code in (200, 204)
            except Exception:
                ok = False
            if ok:
                self.call_from_thread(
                    self.brief_log,
                    f"[bold {_lc(True)}]{t('rule_provider_ok', name=name)}[/]"
                )
            else:
                self.call_from_thread(
                    self.brief_log,
                    f"[bold {_lc(False)}]{t('rule_provider_fail', name=name)}[/]"
                )
                all_ok = False
        return all_ok

    def _reload_groups_order(self):
        self._groups_order = get_proxy_groups_order()
        self._nodes_sig = None
        self._opts_sig = None
        self._groups_sig = None

    async def _test_group_delay(self, group: str = "") -> None:
        """Тест задержек. С пустым group — ВСЕ selector-группы (кнопка
        «Проверить пинг», как test-all в zashboard); с группой — только
        она. Ядро обновляет history узлов, в конце точечное обновление."""
        proxies0 = await self.api.get_proxies()
        if not proxies0:
            self.brief_log(t("delay_test_fail"))
            return
        if group:
            groups = [group]
        else:
            groups = [
                g for g in self._ordered_groups(proxies0)
                if str(proxies0.get(g, {}).get("type", "")).lower() in ("selector", "select")
            ]
        # Каждая нода пингуется РОВНО ОДИН раз, независимо от того, в
        # скольких группах состоит: результат пишется в её history и
        # подхватывается всеми группами.
        nodes, seen = [], set()
        for g in groups:
            for n in proxies0.get(g, {}).get("all", []):
                if n not in seen:
                    seen.add(n)
                    nodes.append(n)
        if not nodes:
            self.brief_log(t("delay_test_fail"))
            return
        self.brief_log(t("delay_testing", group=", ".join(map(replace_flag_emojis, groups))))
        ok = 0
        for node in nodes:
            d = await self.api.proxy_delay(node, timeout_ms=4000)
            name = replace_flag_emojis(node)
            if d:
                ok += 1
                self.brief_log(f"[bold {_lc(True)}· {name} — {d}ms[/]")
            else:
                self.brief_log(f"[bold {_lc(False)}]· {name} — N/A[/]")
        self.brief_log(t("delay_test_done", ok=ok, total=len(nodes)))
        try:
            proxies = await self.api.get_proxies()
            if proxies:
                await self._refresh_groups_ui(proxies)
        except Exception:
            self._report_error("ping_refresh")

    def _update_ui_texts(self):
        self.query_one("#btn_update_run", FlatButton).update_text(
            self._btn_caption(t("btn_update_run"), "\U0001F504", frame=">>")
        )
        btn_toggle = self.query_one("#btn_toggle", FlatButton)
        btn_toggle.update_text(self._toggle_caption())
        self.query_one("#btn_conn", FlatButton).update_text(self._conn_label())
        self.query_one("#btn_logs", FlatButton).update_text(
            self._btn_caption(t("btn_logs"), "\U0001F4DC")
        )
        title = t("log_core") if self.log_source == "core" else t("log_app")
        self.query_one("#log_title", Static).update(title)
        self.query_one("#footer_bar", Static).update(self._footer_text())
        self._nodes_sig = None
        self._opts_sig = None
        self._groups_sig = None
        self.update_status()

    def _ordered_groups(self, proxies):
        managed = {}
        for name, data in proxies.items():
            if name.upper() == "GLOBAL":
                continue  # служебная группа, пользователю не нужна
            # Группа = запись с полем all (как в clash-verge-rev): не зависит
            # от строки type, которую разные сборки ядра называют по-разному.
            if not isinstance(data.get("all"), list):
                continue
            managed[name] = str(data.get("type", "")).lower()
        order = []
        seen = set()
        for name in self._groups_order:
            if name in managed and name not in seen:
                order.append(name)
                seen.add(name)
        order.extend(sorted(n for n in managed if n not in seen))
        # PROXY — главная группа, показываем первой
        order.sort(key=lambda g: 0 if g.upper() == "PROXY" else 1)
        return order

    async def _select_node(self, group: str, node: str) -> None:
        if not group:
            return
        if node == AUTO_RESET:
            ok = await self.api.unpin_proxy(group)
            self.brief_log(t("reset_auto_ok") if ok else t("reset_auto_fail"))
        else:
            ok = await self.api.switch_proxy(group, node)
            if ok:
                node_txt = replace_flag_emojis(node).replace("[", "\\[")
                self.brief_log(t("switch_ok", group=group, node=node_txt))
            else:
                self.brief_log(t("switch_fail", group=group))
        if not ok:
            return
        proxies = await self.api.get_proxies()
        if proxies:
            proxy_grp = next((g for g in proxies if g.upper() == "PROXY"), None)
            if proxy_grp:
                self.current_country = proxies.get(proxy_grp, {}).get("now", "") or ""
            self.update_info_line()
            await self._refresh_groups_ui(proxies)

    async def tail_logs(self):
        try:
            log_path = Path(CORE_LOG)
            if log_path.exists():
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self.log_offset)
                    lines = f.readlines()
                    if lines:
                        for line in lines:
                            self._append_core(line.rstrip())
                        self.log_offset = f.tell()
        except Exception:
            pass

    def _report_error(self, where: str) -> None:
        """Ошибки рендера раньше уходили в except: pass — интерфейс
        молча не обновлялся. Показываем в лог приложения один раз на
        каждый тип, с местом и текстом."""
        import traceback
        try:
            last = traceback.format_exc(limit=3).strip().splitlines()[-1]
        except Exception:
            last = "?"
        key = f"{where}: {last}"
        if key in self._seen_errors:
            return
        self._seen_errors.add(key)
        try:
            self.brief_log(f"[bold {_lc(False)}]{where}: {last}[/]")
        except Exception:
            pass

    async def poll_proxies(self):
        try:
            proxies = await self.api.get_proxies()
            if not proxies:
                return
            ordered = self._ordered_groups(proxies)
            if not ordered:
                return

            if self._open_group is not None and self._open_group not in ordered:
                self._open_group = None
            self.current_group = self._open_group

            proxy_grp = next((g for g in ordered if g.upper() == "PROXY"), None)
            if proxy_grp:
                self.current_country = proxies.get(proxy_grp, {}).get("now", "") or ""
            self.update_info_line()
            try:
                await self._refresh_groups_ui(proxies)
            except Exception:
                self._report_error("refresh_groups_ui")
        except Exception:
            self._report_error("poll_proxies")

    @staticmethod
    def _group_label(name_txt: str, now: str, delay: str) -> str:
        now_disp = replace_flag_emojis(str(now)) if get_os() == "windows" else str(now)
        line2 = f"→ {now_disp} · {delay}" if now else delay
        return f"{name_txt}\n{line2}"

    @staticmethod
    def _group_delay(proxies, g) -> str:
        now = proxies.get(g, {}).get("now") or ""
        hist = (proxies.get(now) or {}).get("history") or []
        if hist:
            dv = hist[-1].get("delay", 0)
            return f"{dv}ms" if dv > 0 else "N/A"
        return "N/A"

    async def _refresh_groups_ui(self, proxies) -> None:
        """Точечное обновление панели групп без полной пересборки:
        кнопки пересоздаются только при смене состава/порядка групп;
        подписи (now · пинг), класс open и список нод обновляются
        на месте — никаких лишних перерисовок (антимерцание)."""
        ordered = self._ordered_groups(proxies)
        struct_sig = repr(ordered)
        if struct_sig != self._groups_sig:
            self._groups_sig = struct_sig
            await self._render_groups(ordered, proxies)
        for row in self.query(GroupRow):
            g = row.group_name
            now = proxies.get(g, {}).get("now") or ""
            if get_os() == "windows":
                gtype = str(proxies.get(g, {}).get("type", "")).lower()
                name_txt = format_group_name(g, gtype == "smart", force_icon="●")
            else:
                name_txt = g
            row.update_label(self._group_label(name_txt, now, self._group_delay(proxies, g)))
            is_open = g == self._open_group
            row.set_class(is_open, "group-open")
            row.set_class(is_open, "open")
            if not is_open:
                for child in row.query(NodeRow):
                    try:
                        await child.remove()
                    except Exception:
                        pass
        await self._render_open_nodes(proxies)

    def _on_group_toggle(self, group: str) -> None:
        self._open_group = None if self._open_group == group else group
        self._nodes_sig = None  # закрытие/открытие — список нод пересобрать
        self._hovered_row = None  # строки пересоздаются, hover-ссылка протухнет
        # без цветовой разметки: в v8 тегированные строки в логе
        # местами рендерятся тёмным — обычный текст читается всегда
        self.brief_log(f"▸ {replace_flag_emojis(group)}")
        self.run_worker(self._rerender_groups())

    async def _rerender_groups(self) -> None:
        """Немедленная перерисовка панели групп (без ожидания тика опроса —
        так выпадающий список открывается мгновенно, как в clash-verge-rev)."""
        try:
            proxies = await self.api.get_proxies()
            if proxies:
                await self._refresh_groups_ui(proxies)
        except Exception:
            self._report_error("rerender_groups")

    def _on_node_select(self, group: str, node: str) -> None:
        self.run_worker(self._select_node(group, node))

    async def _render_groups(self, ordered, proxies) -> None:
        async with self._groups_lock:
            await self._render_groups_locked(ordered, proxies)

    async def _render_groups_locked(self, ordered, proxies) -> None:
        col1 = self.query_one("#groups_col1", Vertical)
        await col1.remove_children()
        self._group_by_button = {}
        for i, g in enumerate(ordered):
            gdata = proxies.get(g, {})
            gtype = str(gdata.get("type", "")).lower()
            now = gdata.get("now") or ""
            if get_os() == "windows":
                name_txt = format_group_name(g, gtype == "smart", force_icon="●")
            else:
                name_txt = g
            bid = f"gr_{i}"
            self._group_by_button[bid] = g
            row = GroupRow(
                g,
                self._group_label(name_txt, now, self._group_delay(proxies, g)),
                is_open=(g == self._open_group),
                button_id=bid,
            )
            await col1.mount(row)

    async def _render_open_nodes(self, proxies) -> None:
        if not self._open_group:
            return
        async with self._groups_lock:
            await self._render_open_nodes_locked(proxies)

    async def _render_open_nodes_locked(self, proxies) -> None:
        if not self._open_group:
            return
        grow = None
        for row in self.query(GroupRow):
            if row.group_name == self._open_group:
                grow = row
                break
        if grow is None:
            return
        data = proxies.get(self._open_group, {})
        p_type = str(data.get("type", "")).lower()
        now = data.get("now", "")
        all_names = list(data.get("all", []))

        # Пересборка списка нод только при смене состава/now; пинги и
        # статусы обновляются на месте — панель не моргает каждый тик.
        sig = repr((self._open_group, all_names))
        if sig == self._nodes_sig:
            for row in grow.query(NodeRow):
                if row._key == AUTO_RESET:
                    continue  # служебная строка «Вернуть автовыбор» — не трогаем
                nd = proxies.get(row._name) or {}
                hist = nd.get("history", [])
                delay = "N/A"
                if hist:
                    dv = hist[-1].get("delay", 0)
                    delay = f"{dv}ms" if dv > 0 else "N/A"
                alive = t("status_alive") if nd.get("alive", True) else t("status_dead")
                row.update_state(delay, alive, row._name == now)
            return
        self._nodes_sig = sig

        # Удаляем ТОЛЬКО строки нод: remove_children() сносил и кнопку
        # группы (она живёт в этом же GroupRow) — заголовок исчезал
        # после раскрытия, свернуть было нечем.
        for child in grow.query(NodeRow):
            await child.remove()
        rows = []
        if p_type == "smart":
            rows.append((AUTO_RESET, t("reset_auto"), "", "", False))
        for node_name in all_names:
            nd = proxies.get(node_name, {})
            delay = "N/A"
            hist = nd.get("history", [])
            if hist:
                dv = hist[-1].get("delay", 0)
                delay = f"{dv}ms" if dv > 0 else "N/A"
            alive = t("status_alive") if nd.get("alive", True) else t("status_dead")
            rows.append((node_name, node_name, delay, alive, node_name == now))
        widgets = [
            # Все аргументы по ключу: любая позиционная передача здесь
            # дважды давала «multiple values for argument ...»
            # (group, затем current).
            NodeRow(
                index=idx, name=display, delay=delay, alive=alive, current=cur,
                group=self._open_group, on_select=self._on_node_select,
                key=key,
            )
            for idx, (key, display, delay, alive, cur) in enumerate(rows)
        ]
        if widgets:
            await grow.mount(*widgets)


def run_tui():
    app = VarekaiApp()
    app.run()
