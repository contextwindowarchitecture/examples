"""A chat session: who is asking, the turns so far, and the question being asked now. Loaded from a scenario file or
built up turn by turn in the chat loop."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    """The current time as RFC 3339, to the second, in UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Turn:
    role: str  # "user" or "assistant"
    text: str
    at: str    # when it was said, RFC 3339


@dataclass
class Conversation:
    workspace: str  # the signed-in user's workspace: the request's tenant
    user: str       # the signed-in user
    session: str
    turns: list[Turn] = field(default_factory=list)
    question: str = ""
    asked_at: str = ""
    # Faults to inject into the producers, for scenarios that show what the assembler catches when one is wrong.
    faults: list[str] = field(default_factory=list)

    @classmethod
    def new(cls, workspace: str, user: str) -> Conversation:
        return cls(workspace=workspace, user=user, session=f"s_{secrets.token_hex(4)}")

    @classmethod
    def load(cls, path: str | Path) -> Conversation:
        """A conversation file: {"workspace", "user", "session", "asked_at", "turns": [{"role", "text", "at"}],
        "question", and optionally "faults"}."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(workspace=data["workspace"], user=data["user"], session=data["session"],
                   turns=[Turn(**turn) for turn in data["turns"]], question=data["question"],
                   asked_at=data["asked_at"], faults=data.get("faults", []))

    def ask(self, question: str) -> None:
        self.question, self.asked_at = question, now()

    def answered(self, answer: str) -> None:
        """Move the question and its answer into the turns, ready for the next question."""
        self.turns += [Turn("user", self.question, self.asked_at), Turn("assistant", answer, now())]
        self.question, self.asked_at = "", ""

    def unanswered(self) -> None:
        """Forget a question that got no answer, so it does not linger in the history."""
        self.question, self.asked_at = "", ""
