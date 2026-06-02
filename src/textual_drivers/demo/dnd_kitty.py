import re

from textual.app import ComposeResult
from textual.message import Message

from textual_drivers import DrivenApp


# -- Custom messages --
class DragOver(Message):
    """Fired when a drag is in progress and the mouse moves over the app.
    Must receive a \033]72;t=m:x=<x>:y=<y>:X=<X>:Y=<Y>:o=<O>;<mime>\033\\

    Run through:
        t=m: indicates operation (can ignore)
        x=<x>: current x mouse cell position
        y=<y>: current y mouse cell position
        X=<X>: current x mouse pixel position
        Y=<Y>: current y mouse pixel position
        o=<O>: current drag operation (1=copy,2=move,3=either)
        mime: ignore it

    More important information:
        - X and Y are optional~ish, if x=y=-1 (when mouse is outside app), X, Y, o and mime are not sent.
    """
    def __init__(self, data: str) -> None:
        super().__init__()
        # parse data for me thanks

        m = re.match(r"t=m:x=(?P<x>-?\d+):y=(?P<y>-?\d+)(:X=(?P<X>-?\d+):Y=(?P<Y>-?\d+):o=(?P<o>\d);(?P<mime>.+))?", data)
        if not m:
            raise ValueError(f"Invalid DragOver data: {data!r}")
        self.x = int(m.group("x"))
        self.y = int(m.group("y"))
        if m.group("X") is not None:
            self.X = int(m.group("X"))
            self.Y = int(m.group("Y"))
            self.o = int(m.group("o"))
            self.mime = m.group("mime")
        else:
            self.X = None
            self.Y = None
            self.o = None
            self.mime = None


class Drop(Message):
    """Fired when a drag is in progress and the mouse is released over the app.
    Must receive a \033]72;t=M:x=<x>:y=<y>:X=<X>:Y=<Y>:o=<O>;<mime>\033\\

    """


class DndKitty(DrivenApp):
    ...
