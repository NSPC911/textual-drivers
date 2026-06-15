from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option


class NarrowOptionsWithInput(ModalScreen[str | None]):
    DEFAULT_CSS = """
    NarrowOptionsWithInput {
        align: center middle;
        layout: horizontal;
        VerticalGroup {
            border: round $primary;
            max-width: 60vw;
            max-height: 60vh;
            padding: 0 0;
        }
        OptionList {
            border: none;
        }
        Input {
            margin: 0 1;
        }
    }
    """

    def __init__(
        self, options: list = [], placeholder: str = "Don't drop your jaw!", border_title: str = ""
    ) -> None:
        super().__init__()
        self.border_title = border_title
        self.placeholder = placeholder
        self.options = options

    def compose(self) -> ComposeResult:
        with VerticalGroup(id="root"):
            yield Input(placeholder=self.placeholder, compact=True)
            yield OptionList(*self.options)

    def on_mount(self) -> None:
        self.query_one(OptionList).can_focus = False
        self.query_one(Input).focus()
        self.query_one(VerticalGroup).border_title = self.border_title

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value
        optionlist: OptionList = self.query_one(OptionList)
        optionlist.clear_options()
        for option in self.options:
            if isinstance(option, Option):
                if value.lower() in option.prompt.lower():
                    optionlist.add_option(option)
            elif isinstance(option, str):
                if value.lower() in option.lower():
                    optionlist.add_option(option)
            else:
                raise TypeError(f"Unexpected {type(option)} found.")
        if optionlist.option_count == 0:
            optionlist.add_option(Option("--no matches--", disabled=True))
        optionlist.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        optionlist = self.query_one(OptionList)
        if optionlist.highlighted is None:
            optionlist.highlighted = 0
        optionlist.action_select()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))

    def on_key(self, event: events.Key) -> None:
        """Handle key presses."""
        match event.key:
            case "escape":
                self.dismiss(None)
            case "down":
                optionlist = self.query_one(OptionList)
                if optionlist.options:
                    optionlist.action_cursor_down()
            case "up":
                optionlist = self.query_one(OptionList)
                if optionlist.options:
                    optionlist.action_cursor_up()
            case "tab":
                self.focus_next()
            case "shift+tab":
                self.focus_previous()
