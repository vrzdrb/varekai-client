"""
TUI интерфейс для varekai на базе Textual
"""
import re
import time
from collections import deque
import httpx
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button, RichLog, Label, Static, Select
)
from textual.containers import Horizontal, VerticalScroll, Container
from textual.reactive import reactive
from pathlib import Path
from utils import (
    t, CORE_LOG, CORE_BINARY, load_settings, save_settings, set_language, get_language,
    replace_flag_emojis
)
from core import (
    get_core_pid, get_current_core_info, start_vpn, stop_vpn,
    update_core, update_profile, get_latest_archived_version
)
from config import get_api_secret, get_proxy_groups_order

AUTO_RESET = "__AUTO_RESET__"
NO_CONN = "__NO_CONN__"
CONN_POLL_INTERVAL = 1.0

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


class ClashAPI:
    def __init__(self, secret=""):
        self.base_url = "http://127.0.0.1:9090"
        self.headers = {"Authorization": f"Bearer {secret}"} if secret else {}

    async def get_proxies(self):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/proxies", headers=self.headers)
                if r.status_code == 200:
                    return r.json().get("proxies", {})
        except Exception:
            pass
        return {}

    async def switch_proxy(self, group_name, node_name):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.put(
                    f"{self.base_url}/proxies/{group_name}",
                    headers=self.headers,
                    json={"name": node_name},
                )
                return r.status_code in (200, 204)
        except Exception:
            return False

    async def unpin_proxy(self, group_name):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.delete(
                    f"{self.base_url}/proxies/{group_name}",
                    headers=self.headers,
                )
                return r.status_code in (200, 204)
        except Exception:
            return False

    async def get_connections(self):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/connections", headers=self.headers)
                if r.status_code == 200:
                    return r.json().get("connections", [])
        except Exception:
            pass
        return []

    async def close_connection(self, conn_id):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.delete(
                    f"{self.base_url}/connections/{conn_id}",
                    headers=self.headers,
                )
                return r.status_code in (200, 204)
        except Exception:
            return False


class NodeRow(Widget):
    DEFAULT_CSS = """
    NodeRow {
        layout: horizontal;
        height: 1;
        width: 100%;
    }
    NodeRow:hover { background: #6b5099; }
    NodeRow.current { background: #F0C60A; }
    NodeRow.current Static { color: #1a1a1a !important; }
    NodeRow .node-name { width: 60%; text-align: left; }
    NodeRow .node-delay { width: 20%; text-align: right; }
    NodeRow .node-status { width: 20%; text-align: right; }
    """

    def __init__(self, index: int, name: str, delay: str, alive: str, current: bool):
        super().__init__(classes="current" if current else "")
        self.index = index
        self._name = name
        self._delay = delay
        self._alive = alive

    def compose(self) -> ComposeResult:
        display = f">> {self._name}" if "current" in self.classes else self._name
        yield Static(display, classes="node-name")
        yield Static(self._delay, classes="node-delay")
        yield Static(self._alive, classes="node-status")


class ConnectionRow(Widget):
    DEFAULT_CSS = """
    ConnectionRow {
        layout: horizontal;
        height: 1;
        width: 100%;
    }
    ConnectionRow:hover { background: #4a3570; }
    """

    def __init__(self, conn_id: str):
        super().__init__()
        self.conn_id = conn_id
        self._cells = {}
        self._raw = {}

    def compose(self) -> ComposeResult:
        for key, cls in (
            ("domain", "col-domain"),
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
            yield Button("✕", id=f"close_{self.conn_id}", classes="close-btn")

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


class ConnectionsScreen(ModalScreen):
    CSS = """
    ConnectionsScreen {
        background: #1a0a30;
        layout: vertical;
    }
    .conn-panel {
        width: 100%;
        height: 1fr;
        margin: 0;
        border: solid #F0C60A;
        background: #3a2855;
        color: #e0e0e0;
        padding: 0 1;
    }
    .conn-head {
        layout: horizontal;
        height: 1;
        width: 100%;
        margin: 1 0;
    }
    .conn-title { width: 1fr; color: #F0C60A; text-style: bold; text-align: center; }
    .conn-close-all-btn {
        width: auto; height: 1;
        border: none;
        background: #F50A0A; color: #ffffff;
        text-style: bold;
    }
    .conn-close-all-btn:hover { background: #ff4444; }
    .conn-header {
        layout: horizontal;
        height: 1;
        width: 100%;
        padding: 0 1 0 0;
        background: #5a4280;
    }
    .header-cell {
        color: #F0C60A;
        text-style: bold;
        text-align: center;
    }
    .header-cell:hover {
        background: #6b5099;
    }
    .header-cell.sorted {
        color: #ffffff;
        text-style: underline bold;
    }
    #conn_scroll {
        height: 1fr;
        background: #3a2855;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;
        scrollbar-background: #241736;
        scrollbar-color: #F0C60A;
        scrollbar-color-active: #f5d020;
    }
    #conn_empty {
        width: 100%; text-align: center;
        color: #0CEBE0; margin: 1 0;
    }
    #conn_footer_bar {
        height: 1;
        background: #5a4480;
        color: #e0e0e0;
        padding: 0;
        margin: 0;
    }
    """

    BINDINGS = [
        ("c", "close_screen", "Close"),
        ("escape", "close_screen", "Close"),
    ]

    def __init__(self, api: ClashAPI):
        super().__init__()
        self.api = api
        self._rows = {}
        self._prev = {}
        self._scroll = None
        self._empty = None
        self._proxy_now = None
        self._sort_column = None
        self._sort_reverse = False

    def _conn_footer_text(self) -> str:
        return f"[bold]   [bold #F0C60A]C[/] {t('key_close_conn')}[/]"

    def compose(self) -> ComposeResult:
        with Container(classes="conn-panel"):
            with Horizontal(classes="conn-head"):
                yield Static(t("conn_title"), classes="conn-title")
                yield Button(t("conn_close_all"), id="conn_close_all", classes="conn-close-all-btn")
            with Horizontal(classes="conn-header"):
                yield Static(t("col_domain"), id="hdr_domain", classes="header-cell col-domain")
                yield Static("|", classes="col-sep")
                yield Static(t("col_server"), id="hdr_server", classes="header-cell col-server")
                yield Static("|", classes="col-sep")
                yield Static(t("col_rule"), id="hdr_rule", classes="header-cell col-rule")
                yield Static("|", classes="col-sep")
                yield Static(t("col_dspeed"), id="hdr_ds", classes="header-cell col-ds")
                yield Static("|", classes="col-sep")
                yield Static(t("col_dtotal"), id="hdr_dt", classes="header-cell col-dt")
                yield Static("|", classes="col-sep")
                yield Static(t("col_uspeed"), id="hdr_us", classes="header-cell col-us")
                yield Static("|", classes="col-sep")
                yield Static(t("col_utotal"), id="hdr_ut", classes="header-cell col-ut")
                yield Static("|", classes="col-sep")
                yield Static(t("col_terminate"), classes="col-act")
            with VerticalScroll(id="conn_scroll") as scroll:
                self._scroll = scroll
            yield Static(t("conn_empty"), id="conn_empty")
        yield Static(self._conn_footer_text(), id="conn_footer_bar")

    def on_mount(self) -> None:
        self._empty = self.query_one("#conn_empty", Static)
        self.set_interval(CONN_POLL_INTERVAL, self.refresh_connections)
        self.refresh_connections()

    def action_close_screen(self) -> None:
        self.dismiss()

    def on_click(self, event: events.Click) -> None:
        ctrl = event.control
        if isinstance(ctrl, Static) and ctrl.has_class("header-cell"):
            col_map = {
                "hdr_domain": "domain",
                "hdr_server": "server",
                "hdr_rule": "rule",
                "hdr_ds": "ds",
                "hdr_dt": "dt",
                "hdr_us": "us",
                "hdr_ut": "ut",
            }
            col = col_map.get(ctrl.id)
            if col:
                if self._sort_column == col:
                    self._sort_reverse = not self._sort_reverse
                else:
                    self._sort_column = col
                    self._sort_reverse = False
                self._update_header_styles()
                self.call_next(self._resort_rows)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "conn_close_all":
            self.run_worker(self._close_all_conns())
            return
        if event.button.has_class("close-btn"):
            row = self._find_row(event.button)
            if row is not None:
                self.run_worker(self._close_conn(row.conn_id))

    def _find_row(self, widget):
        ctrl = widget
        while ctrl is not None and not isinstance(ctrl, ConnectionRow):
            ctrl = getattr(ctrl, "parent", None)
        return ctrl if isinstance(ctrl, ConnectionRow) else None

    async def _close_all_conns(self) -> None:
        for cid in list(self._rows.keys()):
            await self.api.close_connection(cid)

    async def _close_conn(self, conn_id: str) -> None:
        ok = await self.api.close_connection(conn_id)
        if not ok:
            try:
                self.query_one(".conn-title", Static).update(
                    f"[bold #F50A0A]{t('conn_del_fail')}[/]"
                )
            except Exception:
                pass

    def _update_header_styles(self):
        col_names = {
            "hdr_domain": t("col_domain"),
            "hdr_server": t("col_server"),
            "hdr_rule": t("col_rule"),
            "hdr_ds": t("col_dspeed"),
            "hdr_dt": t("col_dtotal"),
            "hdr_us": t("col_uspeed"),
            "hdr_ut": t("col_utotal"),
        }
        for hdr_id, base_text in col_names.items():
            hdr = self.query_one(f"#{hdr_id}", Static)
            if hdr_id == f"hdr_{self._sort_column}":
                arrow = "▼" if self._sort_reverse else "▲"
                hdr.update(f"{base_text} {arrow}")
                hdr.add_class("sorted")
            else:
                hdr.update(base_text)
                hdr.remove_class("sorted")

    async def _resort_rows(self):
        if not self._sort_column:
            return
        col = self._sort_column
        reverse = self._sort_reverse
        rows_data = []
        for cid, row in self._rows.items():
            raw = row._raw
            if col in raw:
                rows_data.append((cid, raw[col], row))

        def sort_key(item):
            val = item[1]
            if isinstance(val, (int, float)):
                return val
            return str(val)

        rows_data.sort(key=lambda x: sort_key(x), reverse=reverse)

        scroll = self._scroll
        await scroll.remove_children()
        for cid, _, row in rows_data:
            await scroll.mount(row)
        self.refresh()

    @staticmethod
    def _conn_sort_key(c):
        meta = c.get("metadata") or {}
        rule = str(c.get("rule") or "")
        host = str(meta.get("host") or meta.get("destinationIP") or "")
        return (rule, host)

    def _resolve_server(self, c) -> str:
        chains = c.get("chains") or []
        if not chains:
            return "DIRECT"
        last = chains[-1]
        if last == "PROXY" and self._proxy_now:
            return replace_flag_emojis(f"PROXY [{self._proxy_now}]")
        return replace_flag_emojis(last)

    async def refresh_connections(self) -> None:
        try:
            proxies = await self.api.get_proxies()
            proxy_data = proxies.get("PROXY", {})
            self._proxy_now = proxy_data.get("now", "")
        except Exception:
            pass
        conns = await self.api.get_connections()
        conns.sort(key=self._conn_sort_key)
        now = time.monotonic()
        cur_ids = set()
        for c in conns:
            cid = c.get("id")
            if not cid:
                continue
            cur_ids.add(cid)
            meta = c.get("metadata", {}) or {}
            host = meta.get("host") or meta.get("destinationIP") or "?"
            rule = c.get("rule", "") or ""
            payload = c.get("rulePayload", "") or ""
            rule_txt = f"{rule} ({payload})" if (rule and payload) else (rule or payload or "—")
            server = self._resolve_server(c)
            dl = c.get("download", 0) or 0
            ul = c.get("upload", 0) or 0
            ds = 0.0
            us = 0.0
            prev = self._prev.get(cid)
            if prev:
                dt = now - prev[2]
                if dt > 0:
                    ds = max(0, dl - prev[0]) / dt
                    us = max(0, ul - prev[1]) / dt
                    ds_txt, us_txt = fmt_speed(ds), fmt_speed(us)
                else:
                    ds_txt, us_txt = "—", "—"
            else:
                ds_txt, us_txt = "—", "—"
            row = self._rows.get(cid)
            if row is None:
                row = ConnectionRow(cid)
                await self._scroll.mount(row)
                self._rows[cid] = row
            raw_data = {
                "domain": host,
                "server": server,
                "rule": rule_txt,
                "ds": ds,
                "dt": dl,
                "us": us,
                "ut": ul,
            }
            row.set_data(host, server, rule_txt, ds_txt, fmt_bytes(dl), us_txt, fmt_bytes(ul), raw_data)
            self._prev[cid] = (dl, ul, now)
        for cid in list(self._rows.keys()):
            if cid not in cur_ids:
                try:
                    await self._rows[cid].remove()
                except Exception:
                    pass
                del self._rows[cid]
                self._prev.pop(cid, None)
        if self._empty is not None:
            self._empty.display = (len(self._rows) == 0)


class VarekaiApp(App):
    TITLE = "varekai"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen { background: #7055a0; }

    #app_header {
        dock: top;
        height: 1;
        background: #5a4480;
        color: #F0C60A;
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
        border: solid #F0C60A;
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

    #info_label { margin: 0 0 1 0; }

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
        color: #F0C60A; text-style: bold; margin: 0 0 1 0;
    }

    #log_frame {
        height: 1fr;
        border: heavy #F0C60A;
        background: transparent;
        padding: 0;
        margin: 0;
    }
    #brief_log {
        width: 100%;
        height: 100%;
        background: #1a0a30;
        color: #0CEBE0;
        border: none;
        scrollbar-size: 1 1;
        scrollbar-background: #3a2855;
        scrollbar-color: #F0C60A;
        scrollbar-color-active: #f5d020;
    }

    #label_group { width: 100%; text-align: center; margin: 1 0; }

    Select { width: 100%; height: 3; background: transparent; margin: 0 0 1 0; }
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

    NodeRow.current, NodeRow.current Static {
        color: #1a1a1a !important;
    }

    .node-header {
        layout: horizontal;
        height: 1;
        width: 100%;
        background: #5a4280;
    }
    .node-header Static { color: #F0C60A; text-style: bold; text-align: center; }
    .node-header .node-name { width: 60%; }
    .node-header .node-delay { width: 20%; }
    .node-header .node-status { width: 20%; }

    #nodes_scroll {
        height: 1fr;
        background: #3a2855;
        scrollbar-size: 1 1;
        scrollbar-background: #241736;
        scrollbar-color: #F0C60A;
        scrollbar-color-active: #f5d020;
    }

    Button { background: #5a4280; color: #F0C60A; border: none; }

    Button:hover { background: #6b5099; }
    Label { color: #e0e0e0; text-style: bold; margin: 1 0; }
    Static { color: #e0e0e0; }

    .col-domain { width: 1fr; min-width: 0; text-align: left; }
    .col-server { width: 30; min-width: 0; text-align: left; }
    .col-rule   { width: 35; min-width: 0; text-align: left; }
    .col-ds     { width: 9;  min-width: 0; text-align: right; }
    .col-dt     { width: 10; min-width: 0; text-align: right; }
    .col-us     { width: 9;  min-width: 0; text-align: right; }
    .col-ut     { width: 10; min-width: 0; text-align: right; }
    .col-act    { width: 8;  min-width: 0; text-align: center; align-horizontal: center; color: #F0C60A; text-style: bold; }
    .col-sep    { width: 1;  text-align: center; color: #F0C60A; }
    .close-btn {
        width: 1; height: 1;
        min-width: 1;
        border: none;
        background: transparent; color: #F50A0A;
        text-style: bold; padding: 0;
    }
    .close-btn:hover { background: #F50A0A; color: #ffffff; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "toggle_vpn", "Toggle"),
        ("r", "refresh_status", "Refresh"),
        ("l", "toggle_language", "Lang"),
        ("c", "show_connections", "Connections"),
        ("pageup", "log_page_up", "Log page up"),
        ("pagedown", "log_page_down", "Log page down"),
    ]

    vpn_running = reactive(False)

    def _lang_label(self) -> str:
        return f" {t('lang_current_name')}"

    def _conn_label(self) -> str:
        return f"🌐 {t('key_connections')}"

    def _footer_text(self) -> str:
        return (
            f"[bold][bold #F0C60A]Q[/] {t('key_quit')}    "
            f"[bold #F0C60A]S[/] {t('key_toggle')}    "
            f"[bold #F0C60A]R[/] {t('key_refresh')}    "
            f"[bold #F0C60A]L[/] {t('key_lang')}    "
            f"[bold #F0C60A]C[/] {t('key_connections')}    "
            f"[bold #F0C60A]PgUp/PgDn[/] {t('key_log_scroll')}[/]"
        )

    def compose(self) -> ComposeResult:
        yield Static("varekai", id="app_header")
        with Horizontal():
            with Container(classes="panel left-panel"):
                yield Static(id="status_label")
                yield Static(id="info_label")
                with Horizontal(classes="btn-row"):
                    yield Button(t("btn_update_run"), id="btn_update_run", classes="btn-action")
                    yield Static("", classes="btn-sep")
                    yield Button(t("btn_toggle_on"), id="btn_toggle", classes="btn-action")
                with Horizontal(classes="lang-row"):
                    yield Button(t("btn_logs"), id="btn_logs", classes="btn-lang")
                    yield Static("", classes="btn-sep")
                    yield Button(self._conn_label(), id="btn_conn", classes="btn-lang")
                yield Static(t("log_app"), id="log_title")
                with Container(id="log_frame"):
                    yield RichLog(id="brief_log", max_lines=1000, wrap=True, markup=True)
            with Container(classes="panel right-panel"):
                yield Label(t("label_group"), id="label_group")
                yield Select(
                    [(NO_CONN, t("no_connection"))],
                    id="group_select",
                    allow_blank=True,
                    prompt=t("no_connection"),
                )
                with Horizontal(classes="node-header"):
                    yield Static(t("col_node"), classes="node-name")
                    yield Static("|", classes="col-sep")
                    yield Static(t("col_latency"), classes="node-delay")
                    yield Static("|", classes="col-sep")
                    yield Static(t("col_status"), classes="node-status")
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
        status_label = self.query_one("#status_label", Static)
        btn_toggle = self.query_one("#btn_toggle", Button)
        status_label.remove_class("status-on", "status-off")
        if pid:
            status_label.add_class("status-on")
            status_label.update(t("status_running"))
            btn_toggle.label = t("btn_toggle_off")
            self.vpn_running = True
        else:
            status_label.add_class("status-off")
            status_label.update(t("status_stopped"))
            btn_toggle.label = t("btn_toggle_on")
            self.vpn_running = False
        self.update_info_line()

    def update_info_line(self):
        country = replace_flag_emojis(self.current_country or t("country_unknown"))
        self.query_one("#info_label", Static).update(
            f"{get_current_core_info()} | {t('current_country', country=country)}"
        )

    def _active_buf(self):
        return self._core_buf if self.log_source == "core" else self._app_buf

    def _render_log(self):
        widget = self.query_one("#brief_log", RichLog)
        widget.clear()
        if self.log_source == "core":
            for line in self._core_buf:
                widget.write(Text(line))
        else:
            for line in self._app_buf:
                widget.write(line)

    def brief_log(self, message: str):
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
                self.query_one("#brief_log", RichLog).write(Text(line))
            except Exception:
                pass

    def action_toggle_logs(self):
        self.log_source = "core" if self.log_source == "app" else "app"
        title = t("log_core") if self.log_source == "core" else t("log_app")
        self.query_one("#log_title", Static).update(title)
        self._render_log()

    def action_toggle_vpn(self):
        self.run_worker(self._worker_toggle, thread=True)

    def action_refresh_status(self):
        self.update_status()
        self.brief_log(t("brief_refreshed"))

    def action_show_connections(self):
        if isinstance(self.screen, ConnectionsScreen):
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
        if isinstance(self.screen, ConnectionsScreen):
            return
        self.query_one("#brief_log", RichLog).scroll_page_up(animate=False)

    def action_log_page_down(self) -> None:
        if isinstance(self.screen, ConnectionsScreen):
            return
        self.query_one("#brief_log", RichLog).scroll_page_down(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_toggle":
            self.run_worker(self._worker_toggle, thread=True)
        elif btn_id == "btn_update_run":
            self.run_worker(self._worker_update_and_run, thread=True)
        elif btn_id == "btn_lang":
            self.action_toggle_language()
        elif btn_id == "btn_logs":
            self.action_toggle_logs()
        elif btn_id == "btn_conn":
            self.action_show_connections()

    def _worker_toggle(self):
        if self.vpn_running:
            self.call_from_thread(self.brief_log, t("brief_stopping"))
            stop_vpn()
            time.sleep(0.5)
            if get_core_pid() is None:
                self.call_from_thread(self.brief_log, f"[bold #34C421]{t('vpn_stop_ok')}[/]")
            else:
                self.call_from_thread(self.brief_log, f"[bold #F50A0A]{t('vpn_stop_fail')}[/]")
        else:
            if not Path(CORE_BINARY).exists():
                self.call_from_thread(self.brief_log, f"[bold #F50A0A]{t('core_not_found')}[/]")
                return
            self.call_from_thread(self.brief_log, t("brief_starting"))
            ok = start_vpn()
            if ok:
                self.call_from_thread(self.brief_log, f"[bold #34C421]{t('vpn_start_ok')}[/]")
            else:
                self.call_from_thread(self.brief_log, f"[bold #F50A0A]{t('vpn_start_fail')}[/]")
        self.call_from_thread(self.update_status)

    def _worker_update_and_run(self):
        self.call_from_thread(self.brief_log, t("brief_checking"))
        core_status = update_core()
        if core_status == 0:
            self.call_from_thread(self.brief_log, f"[bold #34C421]{t('core_already_latest')}[/]")
        elif core_status == 1:
            version = get_latest_archived_version() or "unknown"
            self.call_from_thread(self.brief_log, f"[bold #34C421]{t('core_updated', version=version)}[/]")
        else:
            self.call_from_thread(self.brief_log, f"[bold #F50A0A]{t('core_update_fail')}[/]")

        self.call_from_thread(self.brief_log, t("brief_updating_profile"))
        profile_status = update_profile()
        if profile_status == 1:
            self.call_from_thread(self.brief_log, f"[bold #34C421]{t('profile_updated')}[/]")
        else:
            self.call_from_thread(self.brief_log, f"[bold #F50A0A]{t('profile_update_fail')}[/]")

        self.call_from_thread(self._reload_groups_order)
        self.call_from_thread(self.brief_log, t("brief_starting"))
        ok = start_vpn()
        if ok:
            self.call_from_thread(self.brief_log, f"[bold #34C421]{t('vpn_start_ok')}[/]")
        else:
            self.call_from_thread(self.brief_log, f"[bold #F50A0A]{t('vpn_start_fail')}[/]")
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
        import requests as req
        import urllib.parse
        secret = get_api_secret()
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        base = "http://127.0.0.1:9090"
        providers = None
        for _ in range(15):
            try:
                r = req.get(f"{base}/providers/rules", headers=headers, timeout=3)
                if r.status_code == 200:
                    providers = r.json().get("providers", {})
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
        if isinstance(self.screen, ConnectionsScreen):
            return
        ctrl = event.control
        while ctrl is not None and not isinstance(ctrl, NodeRow):
            ctrl = getattr(ctrl, "parent", None)
        if isinstance(ctrl, NodeRow) and 0 <= ctrl.index < len(self._node_order):
            self.run_worker(self._select_node(self._node_order[ctrl.index]))

    def _update_ui_texts(self):
        self.query_one("#btn_update_run", Button).label = t("btn_update_run")
        btn_toggle = self.query_one("#btn_toggle", Button)
        btn_toggle.label = t("btn_toggle_off") if self.vpn_running else t("btn_toggle_on")
        self.query_one("#btn_conn", Button).label = self._conn_label()
        self.query_one("#btn_logs", Button).label = t("btn_logs")
        self.query_one("#label_group", Label).update(t("label_group"))
        title = t("log_core") if self.log_source == "core" else t("log_app")
        self.query_one("#log_title", Static).update(title)
        self.query_one("#footer_bar", Static).update(self._footer_text())
        try:
            sel = self.query_one("#group_select", Select)
            sel.set_options([(NO_CONN, t("no_connection"))])
            sel.prompt = t("no_connection")
        except Exception:
            pass
        self._nodes_sig = None
        self._opts_sig = None
        self.update_status()

    def _ordered_groups(self, proxies):
        managed = {}
        for name, data in proxies.items():
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
                alive = "alive" if nd.get("alive", True) else "dead"
                display = replace_flag_emojis(node_name)
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
            self.brief_log(t("switch_ok", group=group, node=replace_flag_emojis(node)))
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
                now = proxies.get(g, {}).get("now", "")
                labels.append((replace_flag_emojis(f"{g}  →  {now}" if now else g), g))
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
