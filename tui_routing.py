"""
Модальное окно "Маршрутизация" (хоткей U).
Структура — точно как MainScreen: две panel-пополам + footer dock: bottom.

Правила применяются СРАЗУ: после любой правки smart-config.yaml
пересобирается и перечитывается живым ядром (PUT /configs?force=true).
"""

import asyncio

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from tui_widgets import FlatButton
from user_routing import add_rule, clear_rules, load_user_rules, remove_rule
from utils import (
    CONFIG_SMART,
    apply_scrollbar_palette,
    get_language,
    get_modal_chrome,
    get_os,
    get_script_dir,
    get_theme_colors,
    t,
)

# Строки, добавленные этим окном. Читаются через t(), при отсутствии
# ключа в общем словаре — из локальной таблицы (страховка на случай,
# если utils.py откатят к прежней версии).
_RT_L10N = {
    "ru": {
        "rt_remove_hint": "Номер правила для удаления (1–{n}):",
        "rt_remove_bad": "Введите число от 1 до {n}",
        "rt_applied": "Правила применены",
        "rt_saved": "Сохранено; применятся при запуске VPN",
        "rt_apply_fail": "Не удалось пересобрать конфиг",
    },
    "en": {
        "rt_remove_hint": "Rule number to delete (1–{n}):",
        "rt_remove_bad": "Enter a number from 1 to {n}",
        "rt_applied": "Rules applied",
        "rt_saved": "Saved; will apply on VPN start",
        "rt_apply_fail": "Failed to rebuild config",
    },
}


def _rt_t(key: str, **kwargs) -> str:
    try:
        val = t(key, **kwargs)
        if val and val != key:
            return val
    except Exception:
        pass
    table = _RT_L10N.get(get_language(), _RT_L10N["en"])
    return table.get(key, key).format(**kwargs)


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
    /* Кнопки — как «Логи» в главном окне (.btn-lang): без рамки,
       заливка и текст из палитры. border: none обязателен: на Windows
       legacy-консоль рисует отсутствующие в cp866 символы рамки как '?'. */
    .rt-buttons FlatButton {
        width: 100%;
        height: 3;
        margin: 0 0 1 0;
        border: none;
        background: $primary;
        color: $secondary;
        text-style: bold;
        content-align: center middle;
        text-align: center;
    }
    .rt-buttons FlatButton:hover { background: $warning; }
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
    #rt_input_field, #rt_remove_field {
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
    #rt_menu_input,
    #rt_menu_remove {
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
    #rt_status {
        width: 100%;
        height: 1;
        text-align: center;
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
                        with Vertical(id="rt_menu_remove"):
                            yield Static("", id="rt_remove_label", classes="rt-subtitle")
                            yield Container(
                                Input(id="rt_remove_field", type="integer"),
                                classes="rt-input-row",
                            )
                            yield FlatButton(t("routing_ok"), id="btn_rt_remove_ok", classes="btn-action")
                            yield FlatButton(t("routing_back"), id="btn_rt_remove_back", classes="btn-action")
                    yield Static("", classes="rt-spacer")
                with Container(classes="rt-right"):
                    yield Static(t("routing_list_title"), classes="rt-right-title")
                    with VerticalScroll(id="rt_rules_scroll"):
                        yield Vertical(id="rt_rules_list")
                    yield Static("", id="rt_status")
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
        apply_scrollbar_palette(self.query_one("#rt_rules_scroll", VerticalScroll))

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
                if st.id == "rt_status":
                    continue  # цвет задаёт _set_status по результату
                # Заголовки — цвет основного текста темы (nanita: белый),
                # остальной текст модалки — из chrome
                if st.has_class("rt-left-title") or st.has_class("rt-right-title"):
                    st.styles.color = th["fill_text"]
                else:
                    st.styles.color = chrome["text"]
        except Exception:
            pass
        # Кнопки — инлайн из палитры, как в главном окне. Инлайн не ломает
        # hover: _BoldText._apply_enter/_apply_leave сами пишут фон инлайн.
        try:
            for btn in self.query(".rt-buttons FlatButton"):
                btn.styles.border = ("none", th["button_bg"])
                btn.styles.background = th["button_bg"]
                btn.styles.color = th["button_text"]
        except Exception:
            pass
        try:
            footer = self.query_one("#rt_footer", Static)
            footer.styles.background = th["footer_bg"]
            footer.styles.color = th["footer_hint"]
        except Exception:
            pass

    def _style_input(self) -> None:
        """Поля ввода — цвета group_bg/group_text (НЕ group_btn_*):
        кнопки групп в varekai/ikigai потемнели, поля ввода — нет.

        border: none — у Input дефолтная рамка 'tall' (╻╹), этих символов
        нет в cp866, на legacy-консоли Windows они рисуются как '?'.
        """
        th = get_theme_colors()
        for fid in ("#rt_input_field", "#rt_remove_field"):
            try:
                inp = self.query_one(fid, Input)
                inp.styles.border = ("none", th["group_bg"])
                inp.styles.background = th["group_bg"]
                inp.styles.color = th["group_text"]
            except Exception:
                pass

    def _show_screen(self, name: str) -> None:
        for sid in ("rt_menu_main", "rt_menu_step1", "rt_menu_step2",
                    "rt_menu_input", "rt_menu_remove"):
            visible = sid == f"rt_menu_{name}"
            try:
                container = self.query_one(f"#{sid}", Vertical)
                container.display = visible
            except Exception:
                pass
        self.call_after_refresh(self._focus_first_visible)

    def _focus_first_visible(self) -> None:
        # Прежний вариант перебирал все FlatButton и проверял btn.display:
        # у кнопки внутри скрытого контейнера display остаётся True,
        # поэтому фокус уходил на невидимую кнопку главного меню.
        for sid, field in (("rt_menu_input", "#rt_input_field"),
                           ("rt_menu_remove", "#rt_remove_field")):
            try:
                if self.query_one(f"#{sid}", Vertical).display:
                    self.query_one(field, Input).focus()
                    return
            except Exception:
                pass
        for sid in ("rt_menu_main", "rt_menu_step1", "rt_menu_step2"):
            try:
                box = self.query_one(f"#{sid}", Vertical)
            except Exception:
                continue
            if not box.display:
                continue
            for btn in box.query(FlatButton):
                btn.focus()
                return

    def _refresh_list(self) -> None:
        rules = load_user_rules()
        container = self.query_one("#rt_rules_list", Vertical)
        container.remove_children()
        th = get_theme_colors()
        if not rules:
            container.mount(Static(t("routing_empty"), classes="rt-empty"))
        else:
            for i, rule in enumerate(rules):
                line = f"{i + 1}. {rule['type']},{rule['target']},{rule['proxy']}"
                st = Static(Text(line), classes="rt-rule-item")
                st.styles.color = th["tech_text"]
                container.mount(st)

    # --- удаление по номеру ---
    def _open_remove(self) -> None:
        rules = load_user_rules()
        if not rules:
            return
        self.query_one("#rt_remove_label", Static).update(
            Text(_rt_t("rt_remove_hint", n=len(rules)))
        )
        self.query_one("#rt_remove_field", Input).value = ""
        self._show_screen("remove")

    def _do_remove(self) -> None:
        raw = self.query_one("#rt_remove_field", Input).value.strip()
        rules = load_user_rules()
        try:
            num = int(raw)
        except (TypeError, ValueError):
            num = 0
        if not (1 <= num <= len(rules)):
            self.query_one("#rt_remove_label", Static).update(
                Text(_rt_t("rt_remove_bad", n=len(rules)))
            )
            return
        remove_rule(num - 1)
        self._show_screen("main")
        self._refresh_list()
        self._apply_rules()

    def _submit_value(self) -> None:
        value = self.query_one("#rt_input_field", Input).value.strip()
        if not value:
            return
        self._pending_value = value
        self._show_screen("step2")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter в поле ввода = кнопка OK."""
        if event.input.id == "rt_input_field":
            self._submit_value()
        elif event.input.id == "rt_remove_field":
            self._do_remove()

    # --- немедленное применение правил ---
    def _set_status(self, text: str, ok: bool) -> None:
        th = get_theme_colors()
        try:
            st = self.query_one("#rt_status", Static)
            st.styles.color = th["log_ok"] if ok else th["log_err"]
            st.update(Text(text))
        except Exception:
            pass

    def _apply_rules(self) -> None:
        """Пересобрать smart-config и перечитать его на живом ядре.
        exclusive: серия правок подряд не плодит параллельные релоады."""
        self.run_worker(self._apply_rules_worker(), group="rt_apply", exclusive=True)

    async def _apply_rules_worker(self) -> None:
        from config import generate_smart_config

        # Windows без wintun.dll: start_vpn форсирует gvisor. Без этого
        # флага регенерация вернула бы stack из профиля (mixed), и после
        # релоада TUN перестал бы работать.
        force_stack = None
        if get_os() == "windows" and not (get_script_dir() / "wintun.dll").exists():
            force_stack = "gvisor"

        # ruamel на большом профиле — сотни мс, в event loop это фризы.
        if not await asyncio.to_thread(generate_smart_config, force_stack):
            self._set_status(_rt_t("rt_apply_fail"), False)
            return

        api = getattr(self.app, "api", None)
        if api is None:
            self._set_status(_rt_t("rt_saved"), True)
            return
        try:
            yaml_text = await asyncio.to_thread(
                (get_script_dir() / CONFIG_SMART).read_text, "utf-8"
            )
        except Exception:
            self._set_status(_rt_t("rt_apply_fail"), False)
            return

        # Ядро не запущено -> connect refused мгновенно, это не ошибка:
        # конфиг подхватится при следующем старте.
        applied = await api.reload_config(yaml_text)
        msg = _rt_t("rt_applied" if applied else "rt_saved")
        self._set_status(msg, True)
        try:
            self.app.brief_log(msg)
        except Exception:
            pass

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
            self._submit_value()
            return
        if bid == "btn_rt_vpn":
            self._step2_proxy = "PROXY"
        elif bid == "btn_rt_direct":
            self._step2_proxy = "DIRECT"
        if bid in ("btn_rt_vpn", "btn_rt_direct"):
            add_rule(self._step1_type, self._pending_value, self._step2_proxy)
            self._show_screen("main")
            self._refresh_list()
            self._apply_rules()
            return
        if bid == "btn_rt_remove":
            self._open_remove()
            return
        if bid == "btn_rt_remove_ok":
            self._do_remove()
            return
        if bid == "btn_rt_remove_back":
            self._show_screen("main")
            return
        if bid == "btn_rt_clear":
            clear_rules()
            self._refresh_list()
            self._apply_rules()
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
