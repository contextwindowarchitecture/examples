"""The CWA constructs the viewer is organized by: what each is, the requirements it rests on, the measures that show
how models fared with it, and how to tell from a result's own traces that the result exercised it. In 01-03 that
follows from the scenario; in 04 and 05 from the path each model's tool calls took.

The requirements are the specification's (https://contextwindowarchitecture.io/spec.html), as the examples cite them.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Facts:
    """What a result's assemblies and tool calls show."""
    example: str
    assemblies: int = 0
    payloads: int = 0
    reasons: frozenset[str] = frozenset()   # every exclusion reason in its traces
    refusals: tuple[str, ...] = ()          # each refused assembly's reason, in order
    compressed: bool = False                # an item was sent as its summary
    conflicts: bool = False                 # a declared conflict group was decided, not moot
    tool_results: bool = False              # a tool result, marked untrusted_content, was admitted
    steps: int = 0                          # tool calls the model tried


@dataclass(frozen=True)
class Construct:
    id: str
    title: str
    spec: tuple[str, ...]
    description: str
    measures: tuple[str, ...]
    exercised: Callable[[Facts], bool] = field(compare=False)
    invariants: tuple[str, ...] = ()  # the invariant checks that show it, when invariant is among its measures


CONSTRUCTS = (
    Construct("relevance-threshold", "Relevance threshold", ("R-13",),
              "Retrieval proposes every chunk it finds, each with its score. The route's min_relevance decides which "
              "are sent; the rest are left out as below_threshold, and the trace says by how much. before.py sends its "
              "top five whatever they scored.",
              ("grounding",), lambda f: "below_threshold" in f.reasons),
    Construct("evidence-required", "Evidence required", ("R-17",),
              "A route that requires evidence refuses when none is admitted. Nothing is rendered, so no model is asked, "
              "and the application decides what to tell the user. before.py sends the question anyway.",
              ("invariant", "refusal"), lambda f: "evidence_required" in f.refusals, ("refused_sends_nothing",)),
    Construct("budget-and-fitting", "Budget and fitting", ("R-16", "R-18"),
              "When what is admitted is more than the route's input budget, the policy decides what gives way: "
              "summaries written ahead of time replace long items first, then the oldest history goes, each recorded "
              "as compressed or over_budget. Protected items are never shortened.",
              ("answer", "grounding"), lambda f: f.compressed or "over_budget" in f.reasons),
    Construct("escalation", "Escalation to another route", ("R-12", "R-17"),
              "When protected content cannot fit even on its own, the route refuses rather than truncate it. The "
              "application builds a new snapshot on the route the refusal's reason names, here the large one. A "
              "payload is never trimmed.",
              ("invariant", "answer"), lambda f: "protected_content_over_budget" in f.refusals and f.payloads > 0,
              ("same_context",)),
    Construct("conflicts", "Conflicts", ("R-11",),
              "Producers declare which items state the same fact. The route policy decides each group, here by "
              "producer: the account prevails over a memory, and the losing item is left out as conflict_lost. The "
              "assembler never reads prose to find contradictions.",
              ("conflict",), lambda f: f.conflicts),
    Construct("scope", "Scope", ("R-2",),
              "Every item carries the scope it belongs to. One whose tenant, user or session is not the request's is "
              "left out as out_of_scope, whoever produced it, so a memory store that returns another user's memories "
              "leaks nothing.",
              ("excluded",), lambda f: "out_of_scope" in f.reasons),
    Construct("producer-exclusions", "Producer-reported exclusions", ("R-9", "R-14"),
              "A producer may drop items itself, such as expired or revoked memories, and report each by id without "
              "its text. They are never candidates, and the trace still says they existed.",
              ("excluded",), lambda f: bool({"expired", "revoked"} & f.reasons)),
    Construct("capabilities-and-guard", "Capabilities and the guard", ("R-5", "R-15"),
              "The capability policy decides which tools a request offers, by the user's role; the rest are left out "
              "as capability_not_allowed. The guard checks every call the model makes, outside the model, before it "
              "reaches the server.",
              ("actions", "guard"), lambda f: f.steps > 0 or "capability_not_allowed" in f.reasons),
    Construct("untrusted-content", "Untrusted content", ("R-10", "R-1"),
              "Tool results, like retrieved articles, memories and the question itself, are data, never "
              "instructions: each is marked injection_risk untrusted_content and placed as such. A tool result written "
              "as an instruction should steer nothing, and the guard refuses any call it provokes that the request "
              "does not allow.",
              ("untrusted", "claims"), lambda f: f.tool_results),
    Construct("supersession", "Supersession", ("R-25",),
              "When an agent looks at the same thing twice, the later observation supersedes the earlier one, which is "
              "left out as superseded, so the model never weighs a stale result against a fresh one.",
              ("claims",), lambda f: "superseded" in f.reasons),
    Construct("placement-and-rendering", "Placement and rendering", ("R-7", "R-20"),
              "The profile places each slot in the request and says how it is wrapped, and the renderer writes the "
              "payload. The payload is sent as it comes back: every request the proxy saw is checked against it.",
              ("invariant",), lambda f: f.payloads > 0, ("payload_sent",)),
    Construct("determinism-and-replay", "Determinism and replay", ("R-23",),
              "A snapshot is the whole input to an assembly. Assembling it again gives the same payload to the byte, "
              "on any machine, so every request can be explained later. In 01-03 every model receives the same "
              "snapshot.",
              ("invariant",), lambda f: f.assemblies > 0, ("replays", "same_context")),
    Construct("provenance", "Provenance", ("R-3", "R-20", "R-22"),
              "Every trace names the route policy and profile that built the request, the tokenizer and renderer, and "
              "each item's source version; defaults_filled lists anything the assembler had to assume.",
              (), lambda f: f.assemblies > 0),
    Construct("evaluated-profiles", "Evaluated profiles", ("R-19",),
              "A profile is evaluated for one model, against a suite, before it may be deployed. 05's own grader "
              "grades each model's run of its suite.",
              ("evals",), lambda f: f.example == "05-production"),
)


def exercised(facts: Facts) -> list[str]:
    return [construct.id for construct in CONSTRUCTS if construct.exercised(facts)]
