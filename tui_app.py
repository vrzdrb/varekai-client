"""
Главное TUI-приложение varekai на базе Textual.
"""
import time
from collections import deque
from functools import partial
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RichLog, Select, Static

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
from tui_widgets import NodeRow, fmt_core_line
from utils import (
    APP_VERSION,
    CORE_BINARY,
    CORE_LOG,
    format_group_name,
    get_language,
    get_os,
    load_settings,
    replace_flag_emojis,
    save_settings,
    set_language,
    t,
)

AUTO_RESET = "__AUTO_RESET__"
NO_CONN = "__NO_CONN__"

class _BoldText(Static):
    """Текст с гарантированно жирным начертанием. Жирность задаётся
    разметкой содержимого ([bold]...[/]), а не text-style из CSS:
    на Windows-консолях Textual сохраняет inline-стили содержимого,
    но теряет жирность base-стиля виджета (как у футера и лога — единый
    механизм для всех платформ, один проход отрисовки)."""

    DEFAULT_CSS = """
    _BoldText {
        layout: horizontal;
        align: center middle;
    }
    _BoldText .fb-spacer { width: 1fr; height: 1; }
    _BoldText .fb-a { width: auto; height: 1; }
    """

    def __init__(self, content="", color: str = "#1a1a1a", **kwargs):
        super().__init__(**kwargs)
        self._bold_text = content
        self._color = color

    def compose(self) -> ComposeResult:
        yield Static("", classes="fb-spacer")
        yield Static("", classes="fb-a")
        yield Static("", classes="fb-spacer")

    def on_mount(self) -> None:
        self._sync_bold_text()

    def _sync_bold_text(self) -> None:
        # Text со встроенным стилем: жирность и цвет идут в содержимом
        # (как в футере), а не через CSS виджета — не зависит ни от
        # каскада, ни от разметки, скобки [ ] не нужно экранировать.
        text = self._bold_text
        plain = text.plain if isinstance(text, Text) else str(text)
        self.query_one(".fb-a", Static).update(Text(plain, style=f"bold {self._color}"))

    def update_text(self, content) -> None:
        self._bold_text = content
        try:
            self._sync_bold_text()
        except Exception:
            pass


class BoldLabel(_BoldText):
    """Однострочная подпись с гарантированно жирным текстом."""


class FlatButton(_BoldText):
    """Кнопка на базе Static с гарантированно жирной подписью. Клик шлёт
    стандартное Button.Pressed — обработчики экрана работают без изменений."""

    def on_click(self) -> None:
        if self.disabled:
            return
        self.post_message(Button.Pressed(self))


class QuitScreen(ModalScreen):
    """Подтверждение выхода при работающем VPN: Да — выйти, оставив VPN;
    Нет — остановить VPN и выйти; Esc — отмена."""

    CSS = """
    QuitScreen {
        background: #50007a;
        align: center middle;
    }
    .quit-panel {
        width: 52;
        max-width: 90%;
        height: auto;  /* иначе Container тянется на 1fr и центрировать нечего */
        border: heavy #F0C60A;
        background: #3a2855;
        padding: 1 2;
    }
    .quit-text {
        width: 100%;
        text-align: center;
        color: #e0e0e0;
        margin: 0 0 1 0;
    }
    .quit-row { width: 100%; height: 3; }
    .quit-btn {
        width: 1fr; height: 3; margin: 0;
        border: none;
        background: #F0C60A; color: #1a1a1a; text-style: bold;
    }
    .quit-btn:hover { background: #f5d020; }
    .quit-sep { width: 1; height: 3; background: #3a2855; }
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


class VarekaiApp(App):
    TITLE = "varekai"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen { background: #50007a; text-style: bold; }

    #app_header {
        dock: top;
        height: 1;
        background: #5a4480;
        color: #ffffff;
        text-align: center;
        text-style: bold;
        padding: 0;
        margin: 0;
    }

    #footer_bar {
        dock: bottom;
        height: 1;
        background: #5a4480;
        color: #e0e0e0;
        padding: 0 1 0 3;
    }

    .panel {
        border: heavy #F0C60A;
        padding: 1 2;
        margin: 0;
        background: #3a2855;
        color: #e0e0e0;
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
    .btn-action .fb-a, .btn-lang .fb-a, .quit-btn .fb-a { color: #1a1a1a; }

    #info_label { width: 100%; text-align: center; margin: 0 0 1 0; }

    .btn-row { width: 100%; height: 3; margin: 1 0; }
    .btn-action {
        width: 1fr; height: 100%; margin: 0;
        border: none;
        background: #F0C60A; color: #1a1a1a; text-style: bold;
    }
    .btn-action:hover { background: #f5d020; }
    .btn-sep { width: 1; height: 3; background: #3a2855; }
    .lang-row { width: 100%; height: 3; margin: 0 0 1 0; }
    .btn-lang {
        width: 1fr; height: 100%;
        border: none;
        background: #F0C60A; color: #1a1a1a; text-style: bold;
    }
    .btn-lang:hover { background: #f5d020; }

    #log_title {
        width: 100%; text-align: center;
        color: #ffffff; text-style: bold; margin: 0 0 1 0;
    }

    #log_frame {
        height: 1fr;
        border: heavy #F0C60A;
        background: transparent;
        padding: 0 0 0 1;  /* левый отступ = ширине скроллбара справа */
        margin: 0;
    }
    #brief_log {
        width: 100%;
        height: 100%;
        background: #1a0a30;
        color: #0CEBE0;
        border: none;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;  /* место под скроллбар всегда занято */
        scrollbar-background: #3a2855;  /* = фон панели: поле справа как отступ слева */
        scrollbar-color: #F0C60A;
        scrollbar-color-active: #f5d020;
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

    #nodes_scroll NodeRow Static { color: #0CEBE0; }
    #nodes_scroll NodeRow:hover Static { color: #1a1a1a; }
    NodeRow.current, NodeRow.current Static {
        color: #1a1a1a !important;
    }

    .node-header {
        layout: horizontal;
        height: 1;
        width: 100%;
        background: #5a4280;
    }
    .node-header Static { color: #ffffff; text-style: bold; text-align: center; }
    /* «Задержка» — кликабельная кнопка теста пинга, стиль как у кнопок */
    #hdr_node_delay { background: #F0C60A; color: #1a1a1a; }
    #hdr_node_delay:hover { background: #f5d020; }
    .node-header .node-name { width: 1fr; }
    .node-header .node-delay { width: 10; }
    .node-header .node-status { width: 10; }

    #nodes_frame {
        height: 1fr;
        border: heavy #F0C60A;
        background: transparent;
        padding: 0;
        margin: 0;
    }
    #nodes_scroll {
        height: 1fr;
        background: #1a0a30;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;  /* скроллбар не появляется/не прячется при ресайзе */
        scrollbar-background: #241736;
        scrollbar-color: #F0C60A;
        scrollbar-color-active: #f5d020;
    }

    Button { background: #5a4280; color: #F0C60A; border: none; }

    Button:hover { background: #6b5099; }
    Label { color: #e0e0e0; text-style: bold; margin: 1 0; }
    Static { color: #e0e0e0; text-style: bold; }

    .col-domain { width: 1fr; min-width: 8; text-align: left; }
    .col-sport { width: 5; min-width: 0; text-align: right; }
    .col-dport { width: 5; min-width: 0; text-align: right; }
    .col-server { width: 25; min-width: 0; text-align: left; }
    .col-rule   { width: 36; min-width: 0; text-align: left; }
    .col-ds     { width: 8;  min-width: 0; text-align: right; }
    .col-dt     { width: 9;  min-width: 0; text-align: right; }
    .col-us     { width: 8;  min-width: 0; text-align: right; }
    .col-ut     { width: 9;  min-width: 0; text-align: right; }
    .col-act    { width: 8;  min-width: 0; text-align: center; align-horizontal: center; color: #F0C60A; text-style: bold; }
    .col-sep    { width: 1;  text-align: center; color: #F0C60A; }
    """

    # Дубли с русскими буквами: при русской раскладке те же клавиши
    # приходят как "й"/"ы"/"к"/"д"/"с" (и заглавные с Shift).
    BINDINGS = [
        ("q", "quit", "Quit"), ("й", "quit", "Quit"), ("Й", "quit", "Quit"),
        ("s", "toggle_vpn", "Toggle"), ("ы", "toggle_vpn", "Toggle"), ("Ы", "toggle_vpn", "Toggle"),
        ("r", "show_rollback", "Rollback"), ("к", "show_rollback", "Rollback"), ("К", "show_rollback", "Rollback"),
        ("l", "toggle_language", "Lang"), ("д", "toggle_language", "Lang"), ("Д", "toggle_language", "Lang"),
        ("c", "show_connections", "Connections"), ("с", "show_connections", "Connections"), ("С", "show_connections", "Connections"),
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
        return (
            f"[bold][bold #F0C60A]S[/] {t('key_toggle')}    "
            f"[bold #F0C60A]C[/] {t('key_connections')}    "
            f"[bold #F0C60A]PgUp/PgDn[/] {t('key_log_scroll')}    "
            f"[bold #F0C60A]L[/] {t('key_lang')}    "
            f"[bold #F0C60A]R[/] {t('key_rollback')}    "
            f"[bold #F0C60A]Q[/] {t('key_quit')}[/]"
        )

    def compose(self) -> ComposeResult:
        yield Static(f"varekai {APP_VERSION}", id="app_header")
        with Horizontal():
            with Container(classes="panel left-panel"):
                yield BoldLabel(id="status_label")
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
                    yield RichLog(id="brief_log", max_lines=1000, wrap=True, markup=True)
            with Container(classes="panel right-panel"):
                yield Label(t("label_group"), id="label_group")
                yield Select(
                    [],
                    id="group_select",
                    allow_blank=True,
                    prompt="",
                )
                with Container(id="nodes_frame"):
                    with Horizontal(classes="node-header"):
                        yield Static(t("col_node"), id="hdr_node_name", classes="node-name")
                        yield Static("|", classes="col-sep")
                        yield Static(t("col_latency"), id="hdr_node_delay", classes="node-delay")
                        yield Static("|", classes="col-sep")
                        yield Static(t("col_status"), id="hdr_node_status", classes="node-status")
                    with VerticalScroll(id="nodes_scroll"):
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
        self._groups_order = get_proxy_groups_order()
        self.log_source = "app"
        self._app_buf = deque(maxlen=1000)
        self._core_buf = deque(maxlen=1000)
        self.update_status()
        self.set_interval(0.3, self.tail_logs)
        self.set_interval(2.0, self.poll_proxies)

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
        widget = self.query_one("#brief_log", RichLog)
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
                self.query_one("#brief_log", RichLog).write(message)
            except Exception:
                pass

    def _append_core(self, line: str):
        line = fmt_core_line(line)
        self._core_buf.append(line)
        if self.log_source == "core":
            try:
                self.query_one("#brief_log", RichLog).write(Text(line, style="bold"))
            except Exception:
                pass

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
        self.call_from_thread(self.brief_log, t("rollback_title") + f": {tag} ...")
        ok, msg = rollback_to_tag(tag)
        if ok:
            self.call_from_thread(self.brief_log, f"[bold #34C421]{msg}[/]")
        else:
            self.call_from_thread(self.brief_log, f"[bold #F50A0A]{msg}[/]")
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

    def action_log_page_up(self) -> None:
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return
        self.query_one("#brief_log", RichLog).scroll_page_up(animate=False)

    def action_log_page_down(self) -> None:
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return
        self.query_one("#brief_log", RichLog).scroll_page_down(animate=False)

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

    def _log_result(self, ok: bool, msg: str):
        color = "#34C421" if ok else "#F50A0A"
        self.call_from_thread(self.brief_log, f"[bold {color}]{msg}[/]")

    def _worker_toggle(self):
        try:
            if self.vpn_running:
                ok, msg = stop_vpn()
            else:
                if not Path(CORE_BINARY).exists():
                    self.call_from_thread(
                        self.brief_log, f"[bold #F50A0A]{t('core_not_found')}[/]"
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
                self.brief_log, f"[bold #F50A0A]{t('core_running_update')}[/]"
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
                self.call_from_thread(self.brief_log, f"[bold #34C421]{t('rule_providers_ok')}[/]")
            else:
                self.call_from_thread(self.brief_log, f"[bold #F50A0A]{t('rule_providers_fail')}[/]")

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
                    f"[bold #34C421]{t('rule_provider_ok', name=name)}[/]"
                )
            else:
                self.call_from_thread(
                    self.brief_log,
                    f"[bold #F50A0A]{t('rule_provider_fail', name=name)}[/]"
                )
                all_ok = False
        return all_ok

    def _reload_groups_order(self):
        self._groups_order = get_proxy_groups_order()
        self._nodes_sig = None
        self._opts_sig = None

    def on_click(self, event: events.Click) -> None:
        if isinstance(self.screen, (ConnectionsScreen, RollbackScreen)):
            return
        ctrl = event.control
        if isinstance(ctrl, Static) and ctrl.id == "hdr_node_delay":
            self.run_worker(self._test_group_delay())
            return
        while ctrl is not None and not isinstance(ctrl, NodeRow):
            ctrl = getattr(ctrl, "parent", None)
        if isinstance(ctrl, NodeRow) and 0 <= ctrl.index < len(self._node_order):
            self.run_worker(self._select_node(self._node_order[ctrl.index]))

    async def _test_group_delay(self) -> None:
        """Проверка пинга узлов текущей группы по клику на заголовок
        «Задержка» (как в clash-verge-rev). Ядро обновляет history узлов,
        поэтому после теста просто перечитываем список."""
        group = self.current_group
        if not group:
            return
        self.brief_log(t("delay_testing", group=replace_flag_emojis(group)))
        delays = await self.api.group_delay(group, timeout_ms=5000)
        if not delays:
            self.brief_log(t("delay_test_fail"))
            return
        ok = sum(1 for v in delays.values() if isinstance(v, (int, float)) and v > 0)
        self.brief_log(t("delay_test_done", ok=ok, total=len(delays)))
        self._nodes_sig = None
        proxies = await self.api.get_proxies()
        if proxies:
            await self._refresh_nodes(proxies)

    def _update_ui_texts(self):
        self.query_one("#btn_update_run", FlatButton).update_text(
            self._btn_caption(t("btn_update_run"), "\U0001F504", frame=">>")
        )
        btn_toggle = self.query_one("#btn_toggle", FlatButton)
        btn_toggle.label = self._toggle_caption()
        self.query_one("#btn_conn", FlatButton).update_text(self._conn_label())
        self.query_one("#btn_logs", FlatButton).update_text(
            self._btn_caption(t("btn_logs"), "\U0001F4DC")
        )
        self.query_one("#label_group", Label).update(t("label_group"))
        self.query_one("#hdr_node_name", Static).update(t("col_node"))
        self.query_one("#hdr_node_delay", Static).update(t("col_latency"))
        self.query_one("#hdr_node_status", Static).update(t("col_status"))
        title = t("log_core") if self.log_source == "core" else t("log_app")
        self.query_one("#log_title", Static).update(title)
        self.query_one("#footer_bar", Static).update(self._footer_text())
        try:
            sel = self.query_one("#group_select", Select)
            sel.set_options([])
            sel.prompt = ""
        except Exception:
            pass
        self._nodes_sig = None
        self._opts_sig = None
        self.update_status()

    def _ordered_groups(self, proxies):
        managed = {}
        for name, data in proxies.items():
            if name.upper() == "GLOBAL":
                continue  # служебная группа, пользователю не нужна
            p_type = str(data.get("type", "")).lower()
            if p_type in ("selector", "smart", "url-test", "load-balance", "fallback"):
                managed[name] = p_type
        order = []
        seen = set()
        for name in self._groups_order:
            if name in managed and name not in seen:
                order.append(name)
                seen.add(name)
        order.extend(sorted(n for n in managed if n not in seen))
        return order

    async def _refresh_nodes(self, proxies):
        scroll = self.query_one("#nodes_scroll", VerticalScroll)
        group = self.current_group
        rows = []
        if group:
            data = proxies.get(group, {})
            p_type = str(data.get("type", "")).lower()
            now = data.get("now", "")
            if p_type == "smart":
                rows.append((AUTO_RESET, t("reset_auto"), "", "", False))
            for node_name in data.get("all", []):
                nd = proxies.get(node_name, {})
                delay = "N/A"
                hist = nd.get("history", [])
                if hist:
                    dv = hist[-1].get("delay", 0)
                    delay = f"{dv}ms" if dv > 0 else "N/A"
                alive = t("status_alive") if nd.get("alive", True) else t("status_dead")
                # force_icon="●": в таблице нод единый кружочек у всех
                # строк (подгруппы вроде Автовыбор — тоже ●; ☻ остаётся
                # только в выпадающем списке групп)
                display = format_group_name(
                    node_name, str(nd.get("type", "")).lower() == "smart",
                    force_icon="●",
                )
                rows.append((node_name, display, delay, alive, node_name == now))

        sig = f"{group}|{[(r[1], r[2], r[3], r[4]) for r in rows]!r}"
        if sig == self._nodes_sig:
            return
        self._nodes_sig = sig
        self._node_order = [r[0] for r in rows]

        await scroll.remove_children()
        widgets = [
            NodeRow(i, display, delay, alive, cur)
            for i, (_key, display, delay, alive, cur) in enumerate(rows)
        ]
        if widgets:
            await scroll.mount(*widgets)

    async def _select_node(self, node: str) -> None:
        group = self.current_group
        if not group:
            return
        if node == AUTO_RESET:
            ok = await self.api.unpin_proxy(group)
            if ok:
                self.brief_log(t("reset_auto_ok"))
                self._nodes_sig = None
                proxies = await self.api.get_proxies()
                if proxies:
                    proxy_grp = next((g for g in proxies if g.upper() == "PROXY"), None)
                    if proxy_grp:
                        self.current_country = proxies.get(proxy_grp, {}).get("now", "") or ""
                    self.update_info_line()
                    await self._refresh_nodes(proxies)
            else:
                self.brief_log(t("reset_auto_fail"))
            return

        ok = await self.api.switch_proxy(group, node)
        if ok:
            node_txt = replace_flag_emojis(node).replace("[", "\\[")
            self.brief_log(t("switch_ok", group=group, node=node_txt))
            proxies = await self.api.get_proxies()
            if proxies:
                proxy_grp = next((g for g in proxies if g.upper() == "PROXY"), None)
                if proxy_grp:
                    self.current_country = proxies.get(proxy_grp, {}).get("now", "") or ""
                self.update_info_line()
                await self._refresh_nodes(proxies)
        else:
            self.brief_log(t("switch_fail", group=group))

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "group_select":
            return
        if event.value == NO_CONN or not isinstance(event.value, str) or not event.value:
            return
        self.current_group = event.value
        proxies = await self.api.get_proxies()
        if proxies:
            await self._refresh_nodes(proxies)

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

    async def poll_proxies(self):
        try:
            proxies = await self.api.get_proxies()
            if not proxies:
                return
            ordered = self._ordered_groups(proxies)
            if not ordered:
                return

            labels = []
            for g in ordered:
                gdata = proxies.get(g, {})
                now = gdata.get("now", "")
                g_disp = format_group_name(
                    g, str(gdata.get("type", "")).lower() == "smart",
                    force_icon="●",
                )
                # Экранируем '[' — опции Select рендерятся через разметку
                # и [RU] из замены флагов съедался бы как тег.
                label = (f"{g_disp}  →  {replace_flag_emojis(now)}" if now else g_disp)
                labels.append((label.replace("[", "\\["), g))
            sig_opts = repr(labels)
            if sig_opts != self._opts_sig:
                self._opts_sig = sig_opts
                sel = self.query_one("#group_select", Select)
                sel.set_options(labels)
                if self.current_group in ordered:
                    target = self.current_group
                elif "PROXY" in ordered:
                    target = "PROXY"
                else:
                    target = ordered[0]
                self.current_group = target
                sel.value = target

            proxy_grp = next((g for g in ordered if g.upper() == "PROXY"), None)
            if proxy_grp:
                self.current_country = proxies.get(proxy_grp, {}).get("now", "") or ""
            self.update_info_line()
            await self._refresh_nodes(proxies)
        except Exception:
            pass


def run_tui():
    app = VarekaiApp()
    app.run()

