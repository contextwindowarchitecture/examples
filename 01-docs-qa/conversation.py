"""A chat session: the turns so far, and the question being asked now. Both apps take the same shape, loaded from a
scenario file or built up turn by turn in the chat loop."""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
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
    session: str
    turns: list[Turn] = field(default_factory=list)
    question: str = ""
    asked_at: str = ""

    @classmethod
    def new(cls) -> Conversation:
        return cls(session=f"s_{secrets.token_hex(4)}")

    @classmethod
    def load(cls, path: str | Path) -> Conversation:
        """A conversation file: {"session", "asked_at", "turns": [{"role", "text", "at"}], "question"}."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(session=data["session"], turns=[Turn(**turn) for turn in data["turns"]],
                   question=data["question"], asked_at=data["asked_at"])

    def save(self, path: str | Path) -> None:
        """Write the conversation file load() reads."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def ask(self, question: str) -> None:
        self.question, self.asked_at = question, now()

    def answered(self, answer: str) -> None:
        """Move the question and its answer into the turns, ready for the next question."""
        self.turns += [Turn("user", self.question, self.asked_at), Turn("assistant", answer, now())]
        self.question, self.asked_at = "", ""

    def unanswered(self) -> None:
        """Forget a question that got no answer, so it does not linger in the history."""
        self.question, self.asked_at = "", ""
