"""
Модальное окно отката ядра на одну из сохранённых версий.
"""
import time

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from core import CoreArchive
from utils import t


class RollbackScreen(ModalScreen):
    """Показывает архивы из archives/ и возвращает выбранный тег через dismiss."""

    CSS = """
    RollbackScreen {
        background: #50007a;
        layout: vertical;
        align: center middle;
    }
    .rb-panel {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        border: heavy #F0C60A;
        background: #3a2855;
        color: #e0e0e0;
        padding: 1 2;
    }
    .rb-title {
        width: 100%;
        text-align: center;
        color: #F0C60A;
        text-style: bold;
        margin: 0 0 1 0;
    }
    #rb_scroll {
        height: auto;
        max-height: 1fr;
        scrollbar-size: 1 1;
        scrollbar-background: #241736;
        scrollbar-color: #F0C60A;
    }
    .rb-item {
        width: 100%;
        height: 1;
        border: none;
        background: transparent;
        color: #0CEBE0;
        text-align: left;
    }
    .rb-item:hover {
        background: #F0C60A;
        color: #1a1a1a;
    }
    .rb-empty {
        width: 100%;
        text-align: center;
        color: #0CEBE0;
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
    """

    BINDINGS = [
        ("escape", "close_screen", "Close"),
    ]

    def __init__(self, archives: list[CoreArchive], current_version: str):
        super().__init__()
        self._archives = archives
        self._current_version = current_version or ""

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
                        yield Button(
                            f"{arch.tag}   {date}{marker}",
                            id=f"rb_{i}",
                            classes="rb-item",
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
