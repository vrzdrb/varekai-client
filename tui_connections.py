"""
Модальное окно активных подключений.
"""
import time

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from clash_api import ClashAPI
from tui_widgets import ConnectionRow, fmt_bytes, fmt_speed
from utils import replace_flag_emojis, t

CONN_POLL_INTERVAL = 0.2  # 5 раз в секунду


class ConnectionsScreen(ModalScreen):
    CSS = """
    ConnectionsScreen {
        background: #1a0a30;
        layout: vertical;
    }
    ConnectionsScreen Static {
        color: #0CEBE0;
    }
    .conn-panel {
        width: 100%;
        height: 1fr;
        margin: 0;
        border: heavy #F0C60A;
        background: #1a0a30;
        color: #0CEBE0;
        padding: 0 1;
    }
    .conn-head {
        layout: horizontal;
        height: 1;
        width: 100%;
        margin: 1 0;
    }
    .conn-title { width: 1fr; color: #0CEBE0; text-style: bold; text-align: center; }
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
        background: #1a0a30;
    }
    .header-cell {
        color: #F0C60A;
        text-style: none;
        text-align: center;
    }
    #conn_scroll Static { text-style: none; }  /* таблица — нежирная, остальной текст жирный */
    #conn_scroll .close-x {
        width: 3; height: 1;
        background: #F50A0A; color: #1a1a1a;
        text-align: center;
        content-align: center middle;
    }
    #conn_scroll .close-x:hover { background: #ff2222; color: #ffffff; }
    .header-cell:hover {
        background: #2a1a45;
    }
    .header-cell.sorted {
        color: #ffffff;
        text-style: underline bold;
    }
    #conn_scroll {
        height: 1fr;
        background: #1a0a30;
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
        background: #1a0a30;
        color: #0CEBE0;
        padding: 0;
        margin: 0;
    }
    """

    BINDINGS = [
        ("c", "close_screen", "Close"), ("с", "close_screen", "Close"), ("С", "close_screen", "Close"),
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
        self._proxies_cache = {}
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
                yield Static(t("col_sport"), id="hdr_sport", classes="header-cell col-sport")
                yield Static("|", classes="col-sep")
                yield Static(t("col_dport"), id="hdr_dport", classes="header-cell col-dport")
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
                "hdr_sport": "sport",
                "hdr_dport": "dport",
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
        # Закрытие отдельной строки обрабатывает сам ConnectionRow
        # (событие там останавливается и сюда не доходит).
        if event.button.id == "conn_close_all":
            self.run_worker(self._close_all_conns())

    async def _close_all_conns(self) -> None:
        await self.api.close_all_connections()
        for row in list(self._rows.values()):
            try:
                await row.remove()
            except Exception:
                pass
        self._rows.clear()
        self._prev.clear()
        if self._empty is not None:
            self._empty.display = True

    async def _close_conn(self, conn_id: str) -> None:
        ok = await self.api.close_connection(conn_id)
        if not ok:
            try:
                self.query_one(".conn-title", Static).update(
                    f"[bold #F50A0A]{t('conn_del_fail')}[/]"
                )
            except Exception:
                pass

    def _request_close(self, cid: str) -> None:
        self.run_worker(self._close_conn(cid))

    def _update_header_styles(self):
        col_names = {
            "hdr_domain": t("col_domain"),
            "hdr_sport": t("col_sport"),
            "hdr_dport": t("col_dport"),
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

    def _resolve_node_name(self, name: str) -> str:
        """Если name — группа, чей текущий выбор ссылается на другую группу
        (Epic Games -> Автовыбор -> ...), спускаемся до конкретной ноды.
        Реальные ноды в /proxies не имеют поля now — цикл остановится сам,
        множество seen страхует от кольцевых настроек."""
        seen = set()
        while name in self._proxies_cache and name not in seen:
            seen.add(name)
            data = self._proxies_cache.get(name) or {}
            now = data.get("now")
            if not now or now == name:
                break
            name = str(now)
        return str(name)

    def _resolve_server(self, c) -> str:
        chains = c.get("chains") or []
        if not chains:
            return "DIRECT"
        last = str(chains[-1])
        if last == "PROXY" and self._proxy_now:
            resolved = self._resolve_node_name(str(self._proxy_now))
            return f"PROXY {replace_flag_emojis(resolved)}"
        # Последнее звено — группа: показываем её имя и конечную ноду
        # (подгруппы вроде Автовыбор прозрачно проскакиваются резолвером).
        if (self._proxies_cache.get(last) or {}).get("now"):
            group = replace_flag_emojis(last).strip()
            resolved = replace_flag_emojis(self._resolve_node_name(last))
            return f"{group} → {resolved}"
        return replace_flag_emojis(last)

    async def refresh_connections(self) -> None:
        try:
            proxies = await self.api.get_proxies()
            proxy_data = proxies.get("PROXY", {})
            self._proxy_now = proxy_data.get("now", "")
            self._proxies_cache = proxies
        except Exception:
            self._proxies_cache = {}
        conns = (await self.api.get_connections()) or []
        try:
            conns.sort(key=self._conn_sort_key)
        except Exception:
            pass
        now = time.monotonic()
        cur_ids = set()
        for c in conns:
            cid = c.get("id")
            if not cid:
                continue
            cur_ids.add(cid)
            meta = c.get("metadata", {}) or {}
            host = meta.get("host") or meta.get("destinationIP") or "?"

            def _port_num(v):
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return 0

            sport_num = _port_num(meta.get("sourcePort"))
            dport_num = _port_num(meta.get("destinationPort"))
            sport_txt = str(sport_num) if sport_num else "—"
            dport_txt = str(dport_num) if dport_num else "—"
            rule = str(c.get("rule", "") or "")
            payload = str(c.get("rulePayload", "") or "")
            chains = c.get("chains") or []
            last_chain = str(chains[-1]) if chains else ""
            rule_l = rule.lower()
            if rule_l == "match" and last_chain == "DIRECT":
                # Финальное MATCH-правило с исходом DIRECT показываем как DIRECT
                rule_txt = "DIRECT"
            elif rule_l == "ruleset":
                # Ядро может отдавать в rulePayload конкретное сработавшее
                # правило из набора (напр. DOMAIN-SUFFIX,google.com)
                rule_txt = payload if payload else "RuleSet"
            else:
                rule_txt = f"{rule} ({payload})" if (rule and payload) else (rule or payload or "—")
            server = self._resolve_server(c)
            dl = c.get("download", 0) or 0
            ul = c.get("upload", 0) or 0
            prev = self._prev.get(cid)
            ds = 0.0
            us = 0.0
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
                row = ConnectionRow(cid, on_close=self._request_close)
                await self._scroll.mount(row)
                self._rows[cid] = row
            raw_data = {
                "domain": host,
                "sport": sport_num,
                "dport": dport_num,
                "server": server,
                "rule": rule_txt,
                "ds": ds,
                "dt": dl,
                "us": us,
                "ut": ul,
            }
            row.set_data(host, sport_txt, dport_txt, server, rule_txt, ds_txt, fmt_bytes(dl), us_txt, fmt_bytes(ul), raw_data)
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

