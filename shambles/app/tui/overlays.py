"""Persistent service results and optional same-terminal launch choices."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ..service import ActionPlan, ActionResult


def overlay_panel_classes(node, *extra: str) -> str:
    """Gold overlay chrome, with ASCII borders when the app is not unicode."""
    classes = ["overlay-panel", *extra]
    if not getattr(node.app, "unicode", True):
        classes.append("ascii")
    return " ".join(classes)


class ConfirmAction(ModalScreen[bool]):
    """Show the service's prompt and warnings before accepting a plan."""

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    ConfirmAction { align: center middle; }
    """

    def __init__(self, plan: ActionPlan):
        super().__init__(id="confirm-action")
        self.plan = plan

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes=overlay_panel_classes(self, "danger")):
            yield Static(self.plan.prompt, classes="overlay-title", markup=False)
            for warning in self.plan.warnings:
                yield Static(warning, markup=False)
            yield Static("\nEnter Confirm   Esc Cancel   q Quit", markup=False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ResultScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("enter", "launch", "Launch"),
        Binding("escape", "cancel", "Accounts"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    ResultScreen { align: center middle; }
    """

    def __init__(self, result: ActionResult, *, provider: str | None = None):
        super().__init__(id="result")
        self.result = result
        self.provider = provider

    @property
    def can_launch(self) -> bool:
        return (
            self.result.ok and self.result.action == "switch"
            and self.provider is not None
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return self.can_launch if action == "launch" else True

    def compose(self) -> ComposeResult:
        extra = ("danger",) if not self.result.ok else ()
        with VerticalScroll(classes=overlay_panel_classes(self, *extra)):
            if self.result.summary:
                yield Static(self.result.summary, classes="overlay-title", markup=False)
            if self.result.error is not None:
                yield Static(
                    self.result.error.message,
                    classes="overlay-title" if not self.result.summary else None,
                    markup=False,
                )
                if self.result.error.recovery:
                    yield Static(self.result.error.recovery, markup=False)
            for warning in self.result.warnings:
                yield Static(warning, markup=False)
            if self.can_launch:
                yield Static(
                    "\nExisting sessions keep their loaded login.\n"
                    "Restart them to use the switched account.\n\n"
                    f"Enter Launch {self.provider} here",
                    markup=False,
                )
            yield Static(
                "Esc Return to accounts   q Quit",
                markup=False,
            )

    def action_launch(self) -> None:
        if self.can_launch:
            self.dismiss(self.provider)

    def action_cancel(self) -> None:
        self.dismiss(None)
