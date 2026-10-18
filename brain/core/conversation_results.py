"""Internal terminal feedback receipts, distinct from successful native replies.

Only their ordinary assistant frame is serialized. A typed receipt is not
authority by itself: the conversation owner must recognize its exact identity.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TerminalFailure:
    guest_id: str
    generation: int
    thread_id: str
    turn_id: str
    text: str
    lease: object = field(repr=False, compare=False)
    cleanup_confirmed: bool


class TerminalFailureFrames(list):
    """Text feedback with no successful-reply or automatic-speech receipt."""

    def __init__(self, receipt: TerminalFailure):
        super().__init__([{'type': 'assistant', 'text': receipt.text}])
        self.terminal_failure = receipt
