"""
Модальное окно "Маршрутизация" (хоткей U).
Структура — точно как MainScreen: две panel-пополам + footer dock: bottom.
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from tui_widgets import FlatButton
from user_routing import add_rule, clear_rules, load_user_rules, remove_rule
from utils import apply_scrollbar_palette, get_modal_chrome, get_theme_colors, t


class RoutingScreen(ModalScreen):
    """Окно управления пользовательскими правилами маршрутизации."""

    CSS = """
    RoutingScreen {
        background: $background;
    }
    RoutingScreen > Vertical {
        width: 100%;
        height: 100%;
    }
    RoutingScreen > Vertical > Horizontal {
        layout: horizontal;
        width: 100%;
        height: 1fr;
    }
    .rt-left {
        width: 1fr;
        height: 100%;
        border: heavy $primary;
        background: $panel;
        padding: 1 2;
    }
    .rt-right {
        width: 1fr;
        height: 100%;
        border: heavy $primary;
        background: $panel;
        padding: 1 2;
    }
    .rt-left-title {
        width: 100%;
        height: 1;
        text-align: center;
        color: $foreground;
        text-style: bold;
        margin: 0 0 1 0;
    }
    .rt-spacer {
        height: 1fr;
        min-height: 1;
    }
    .rt-buttons {
        height: auto;
        layout: vertical;
    }
    .rt-buttons FlatButton {
        width: 100%;
        height: 3;
        margin: 0 0 1 0;
        content-align-vertical: middle;
    }
    .rt-subtitle {
        width: 100%;
        height: 1;
        text-align: center;
        color: $foreground;
        text-style: bold;
        margin: 0 0 1 0;
    }
    .rt-input-row {
        height: auto;
        margin: 1 0 1 0;
    }
    #rt_input_field {
        width: 100%;
    }
    .rt-right-title {
        width: 100%;
        height: 1;
        text-align: center;
        color: $foreground;
        text-style: bold;
        margin: 0 0 1 0;
    }
    #rt_menu_step1,
    #rt_menu_step2,
    #rt_menu_input {
        display: none;
    }
    .rt-footer {
        dock: bottom;
        height: 1;
        background: $background;
        color: $accent;
        padding: 0;
        margin: 0;
    }
    .rt-rule-item {
        width: 100%;
        text-align: left;
        padding: 0 1;
    }
    .rt-empty {
        width: 100%;
        text-align: center;
        color: $foreground 50%;
    }
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", t("routing_exit")),
        Binding("u", "app.pop_screen", t("routing_exit")),
        Binding("г", "app.pop_screen", t("routing_exit")),
        Binding("Г", "app.pop_screen", t("routing_exit")),
        Binding("pageup", "scroll_up", t("scroll_up")),
        Binding("pagedown", "scroll_down", t("scroll_down")),
    ]

    def _rt_footer_text(self) -> str:
        th = get_theme_colors()
        kc = th["footer_key"]
        hc = th["footer_hint"]
        return (
            f"[bold]   [bold {kc}]Esc, U[/] - [bold {hc}]{t('routing_exit')}[/]"
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal():
                with Container(classes="rt-left"):
                    yield Static(t("routing_title"), classes="rt-left-title")
                    yield Static("", classes="rt-spacer")
                    with Vertical(classes="rt-buttons"):
                        with Vertical(id="rt_menu_main"):
                            yield FlatButton(t("routing_add"), id="btn_rt_add", classes="btn-action")
                            yield FlatButton(t("routing_remove"), id="btn_rt_remove", classes="btn-action")
                            yield FlatButton(t("routing_clear"), id="btn_rt_clear", classes="btn-action")
                            yield FlatButton(t("routing_exit"), id="btn_rt_exit", classes="btn-action")
                        with Vertical(id="rt_menu_step1"):
                            yield Static(t("routing_what"), classes="rt-subtitle")
                            yield FlatButton(t("routing_domain_suffix"), id="btn_rt_suffix", classes="btn-action")
                            yield FlatButton(t("routing_domain"), id="btn_rt_domain", classes="btn-action")
                            yield FlatButton(t("routing_ip"), id="btn_rt_ip", classes="btn-action")
                            yield FlatButton(t("routing_process"), id="btn_rt_process", classes="btn-action")
                            yield FlatButton(t("routing_back"), id="btn_rt_back1", classes="btn-action")
                        with Vertical(id="rt_menu_step2"):
                            yield Static(t("routing_where"), classes="rt-subtitle")
                            yield FlatButton(t("routing_to_vpn"), id="btn_rt_vpn", classes="btn-action")
                            yield FlatButton(t("routing_to_direct"), id="btn_rt_direct", classes="btn-action")
                            yield FlatButton(t("routing_back"), id="btn_rt_back2", classes="btn-action")
                        with Vertical(id="rt_menu_input"):
                            yield Static("", id="rt_input_label", classes="rt-subtitle")
                            yield Container(Input(id="rt_input_field"), classes="rt-input-row")
                            yield FlatButton(t("routing_ok"), id="btn_rt_ok", classes="btn-action")
                            yield FlatButton(t("routing_back"), id="btn_rt_back3", classes="btn-action")
                    yield Static("", classes="rt-spacer")
                with Container(classes="rt-right"):
                    yield Static(t("routing_list_title"), classes="rt-right-title")
                    with VerticalScroll(id="rt_rules_scroll"):
                        yield Vertical(id="rt_rules_list")
            yield Static(self._rt_footer_text(), id="rt_footer", classes="rt-footer")

    def on_mount(self) -> None:
        self._step1_type = None
        self._step2_proxy = None
        self._pending_value = ""
        self._show_screen("main")
        self._refresh_list()
        self._apply_chrome()
        self._style_input()
        apply_scrollbar_palette(self)

    def _apply_chrome(self) -> None:
        chrome = get_modal_chrome()
        th = get_theme_colors()
        try:
            from utils import get_theme_name
            bg_color = th["fill_bg"] if get_theme_name() == "nanita" else chrome["bg"]
            for pan in self.query(".rt-left, .rt-right"):
                pan.styles.border = ("heavy", chrome["border"])
                pan.styles.background = bg_color
            for st in self.query("Static"):
                if st.has_class("rt-footer") or st.has_class("rt-spacer"):
                    continue
                # Заголовки — цвет основного текста темы (nanita: белый),
                # остальной текст модалки — из chrome
                if st.has_class("rt-left-title") or st.has_class("rt-right-title"):
                    st.styles.color = th["fill_text"]
                else:
                    st.styles.color = chrome["text"]
        except Exception:
            pass
        try:
            footer = self.query_one("#rt_footer", Static)
            footer.styles.background = th["footer_bg"]
            footer.styles.color = th["footer_hint"]
        except Exception:
            pass

    def _style_input(self) -> None:
        """Поле ввода — цвета кнопок групп (group_bg/group_text)."""
        th = get_theme_colors()
        try:
            inp = self.query_one("#rt_input_field", Input)
            inp.styles.background = th["group_bg"]
            inp.styles.color = th["group_text"]
        except Exception:
            pass

    def _show_screen(self, name: str) -> None:
        for sid in ("rt_menu_main", "rt_menu_step1", "rt_menu_step2", "rt_menu_input"):
            visible = sid == f"rt_menu_{name}"
            try:
                container = self.query_one(f"#{sid}", Vertical)
                container.display = visible
            except Exception:
                pass
        self.call_after_refresh(self._focus_first_visible)

    def _focus_first_visible(self) -> None:
        if self.query_one("#rt_menu_input", Vertical).display:
            try:
                self.query_one("#rt_input_field", Input).focus()
            except Exception:
                pass
            return
        for btn in self.query(FlatButton):
            if btn.display:
                btn.focus()
                break

    def _refresh_list(self) -> None:
        rules = load_user_rules()
        container = self.query_one("#rt_rules_list", Vertical)
        container.remove_children()
        th = get_theme_colors()
        if not rules:
            container.mount(Static(t("routing_empty"), classes="rt-empty"))
        else:
            for i, rule in enumerate(rules):
                line = f"{i+1}. {rule['type']},{rule['target']},{rule['proxy']}"
                st = Static(line, classes="rt-rule-item")
                st.styles.color = th["tech_text"]
                container.mount(st)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.control
        bid = btn.id

        if bid == "btn_rt_exit":
            self.dismiss()
            return

        if bid == "btn_rt_add":
            self._show_screen("step1")
            return

        if bid in ("btn_rt_back1", "btn_rt_back2", "btn_rt_back3"):
            self._show_screen("main" if bid == "btn_rt_back1" else "step1")
            return

        type_map = {
            "btn_rt_suffix": "DOMAIN-SUFFIX",
            "btn_rt_domain": "DOMAIN",
            "btn_rt_ip": "IP-CIDR",
            "btn_rt_process": "PROCESS-NAME-REGEX",
        }
        if bid in type_map:
            self._step1_type = type_map[bid]
            label = self.query_one("#rt_input_label", Static)
            if bid == "btn_rt_process":
                label.update(t("routing_hint_process"))
            elif bid == "btn_rt_ip":
                label.update(t("routing_hint_ip"))
            elif bid == "btn_rt_suffix":
                label.update(t("routing_hint_domain_suffix"))
            else:
                label.update(t("routing_hint_domain"))
            self.query_one("#rt_input_field", Input).value = ""
            self._show_screen("input")
            return

        if bid == "btn_rt_ok":
            value = self.query_one("#rt_input_field", Input).value.strip()
            if not value:
                return
            self._pending_value = value
            self._show_screen("step2")
            return

        if bid == "btn_rt_vpn":
            self._step2_proxy = "PROXY"
        elif bid == "btn_rt_direct":
            self._step2_proxy = "DIRECT"

        if bid in ("btn_rt_vpn", "btn_rt_direct"):
            add_rule(self._step1_type, self._pending_value, self._step2_proxy)
            self._show_screen("main")
            self._refresh_list()
            return

        if bid == "btn_rt_remove":
            rules = load_user_rules()
            if rules:
                remove_rule(len(rules) - 1)
                self._refresh_list()
            return

        if bid == "btn_rt_clear":
            clear_rules()
            self._refresh_list()
            return

    def action_scroll_up(self) -> None:
        try:
            self.query_one("#rt_rules_scroll", VerticalScroll).scroll_page_up()
        except Exception:
            pass

    def action_scroll_down(self) -> None:
        try:
            self.query_one("#rt_rules_scroll", VerticalScroll).scroll_page_down()
        except Exception:
            pass
