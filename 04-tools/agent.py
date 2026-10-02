"""The help-center bot as an agent. For one question it runs a bounded loop, and every inference is assembled from a
snapshot of its own:

    offer tools (capability policy) -> freeze -> assemble -> ask the model
        -> an answer: done
        -> tool calls: the guard decides each; approved ones run on the MCP server and come back as observations
        -> next inference, up to MAX_TURNS; the last offers no tools

    uv run agent.py --user u_ada "Is our webhook still disabled? Please turn it back on."      # dry run: turn 1 only
    uv run agent.py --user u_ada --provider openai "Is our webhook still disabled? ..."        # a live run, saved
    uv run agent.py --user u_ada --provider openai --record scenarios/NAME "..."             # record a scenario

A live run is saved under runs/<task>/, one folder per inference (snapshot.json, trace.json, payload.json) and
run.json with every tool call, the guard's decision and the answer.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, TextIO

from cwa import AssemblyResult

import capabilities
import context
import producers
import providers
import report
import routes
import tools
from conversation import Conversation, now
from providers import Call, Reply

MAX_TURNS = 6
RUNS = Path(__file__).parent / "runs"
ACCOUNTS = Path(__file__).parent / "data" / "accounts.json"


class Model(Protocol):
    source: str

    def __call__(self, system: list[str], offered: list[dict[str, Any]], messages: list[dict[str, str]]) -> Reply: ...


class LiveModel:
    """A model behind a provider's SDK. It keeps every reply, so a run can be recorded and replayed."""

    def __init__(self, provider: str, options: dict[str, Any], max_tokens: int) -> None:
        self.provider, self.options, self.max_tokens = provider, options, max_tokens
        self.source = f"recorded from {options['model']} through the {provider} provider"
        self.replies: list[Reply] = []

    def __call__(self, system: list[str], offered: list[dict[str, Any]], messages: list[dict[str, str]]) -> Reply:
        reply = providers.chat(self.provider, self.options, system, offered, messages, self.max_tokens)
        self.replies.append(reply)
        return reply


class ScriptedModel:
    """Replies read from a scenario: a recorded live model, or a script written to test what the guard catches."""

    def __init__(self, source: str, replies: list[dict[str, Any]]) -> None:
        self.source = source
        self._replies = [Reply(reply["text"], [Call(**call) for call in reply["calls"]]) for reply in replies]

    def __call__(self, system: list[str], offered: list[dict[str, Any]], messages: list[dict[str, str]]) -> Reply:
        return self._replies.pop(0)


class DryRun:
    """No model: print the first inference's request and stop."""
    source = "dry run"

    def __init__(self, out: TextIO) -> None:
        self.out = out

    def __call__(self, system: list[str], offered: list[dict[str, Any]], messages: list[dict[str, str]]) -> Reply:
        for text in system:
            print("\n── system ──\n" + text, file=self.out)
        for tool in offered:
            print("\n── tool ──\n" + json.dumps(tool, indent=2), file=self.out)
        for message in messages:
            print(f"\n── {message['role']} ──\n" + message["content"], file=self.out)
        return Reply("(dry run: no model was asked)")


class Clock:
    """Every time the agent reads the clock. Recorded in a live run, replayed in a scenario, so that every snapshot,
    assembly time and observation time comes out the same (R-23)."""

    def __init__(self, recorded: list[str] | None = None) -> None:
        self._recorded = list(recorded) if recorded is not None else None
        self.read: list[str] = []

    def __call__(self) -> str:
        value = self._recorded.pop(0) if self._recorded is not None else now()
        self.read.append(value)
        return value


@dataclass
class Inference:
    document: dict[str, Any]
    result: AssemblyResult


@dataclass
class Run:
    inferences: list[Inference] = field(default_factory=list)
    steps: list[producers.Step] = field(default_factory=list)
    answer: str | None = None
    refused: str | None = None


async def run(conversation: Conversation, route: routes.Route, model: Model, clock: Clock,
              out: TextIO = sys.stdout) -> Run:
    task = f"t_{conversation.session}"
    outcome = Run()
    async with tools.FernwayAPI(conversation.faults) as api:
        proposed = await api.proposed()  # what the server offers; the capability policy decides what the model sees
        role = producers.role(conversation)
        for number in range(1, MAX_TURNS + 1):
            moment = clock()
            batch, grant, granted = capabilities.offer(proposed, role, moment, final_turn=number == MAX_TURNS)
            turn = context.Turn(task, number, MAX_TURNS, moment, list(outcome.steps), batch, grant)
            document = context.snapshot(conversation, route, turn)
            result = context.assemble(document)
            outcome.inferences.append(Inference(document, result))
            print(f"\nturn {number}", file=out)
            report.report(document, result, out)
            if result.payload is None:
                outcome.refused = result.trace["refused"]["reason"]  # nothing to send, so no model is asked (R-17)
                return outcome
            payload = json.loads(result.payload)  # cwa-messages/v1: system, tools and one user message
            reply = model([entry["text"] for entry in payload["system"]],
                          [json.loads(entry["text"]) for entry in payload["tools"]], payload["messages"])
            if not reply.calls:
                outcome.answer = reply.text
                return outcome
            for call in reply.calls:
                # The guard runs outside the model, on the call itself, before the server sees it (R-5, R-15).
                decision = capabilities.authorize(call.name, call.arguments, granted, document["scope"])
                if decision.approved:
                    result_of_call = await api.call(call.name, call.arguments)
                    step = producers.Step(call.name, call.arguments, True, decision.reason, result_of_call.ok,
                                          result_of_call.value, clock())
                else:
                    step = producers.Step(call.name, call.arguments, False, decision.reason)
                outcome.steps.append(step)
                verdict = ("called" if step.ok else "called, and it failed") if step.approved else f"denied: {step.reason}"
                print(f"  > {call.name} {json.dumps(call.arguments, sort_keys=True)}: {verdict}", file=out)
    return outcome  # the last turn still asked for tools: no answer


def _json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def files(outcome: Run) -> dict[str, bytes | None]:
    """Everything a run produced, by path: each inference's snapshot, trace and payload, and run.json."""
    written: dict[str, bytes | None] = {}
    for number, inference in enumerate(outcome.inferences, start=1):
        trace = {key: value for key, value in inference.result.trace.items() if key not in ("trace_id", "timings")}
        written[f"turn-{number}/snapshot.json"] = _json(inference.document)
        written[f"turn-{number}/trace.json"] = _json(trace)
        written[f"turn-{number}/payload.json"] = inference.result.payload
    written["run.json"] = _json({"steps": [asdict(step) for step in outcome.steps], "answer": outcome.answer,
                                 "refused": outcome.refused})
    return written


def save(directory: Path, outcome: Run) -> None:
    for name, content in files(outcome).items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            path.write_bytes(content)


def record(directory: Path, conversation: Conversation, model: LiveModel, clock: Clock) -> None:
    """Write a scenario: the conversation, the model's replies and the clock, everything replay needs."""
    directory.mkdir(parents=True, exist_ok=True)
    scenario = {"workspace": conversation.workspace, "user": conversation.user, "session": conversation.session,
                "asked_at": conversation.asked_at, "faults": conversation.faults, "turns": [], "question": conversation.question,
                "model": {"source": model.source, "replies": [asdict(reply) for reply in model.replies]},
                "clock": clock.read}
    (directory / "scenario.json").write_bytes(_json(scenario))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--user", default=os.environ.get("DOCS_QA_USER", "u_ada"),
                        help="the signed-in user, from data/accounts.json: u_ada (default), u_ben or u_cho")
    parser.add_argument("--provider", choices=["none", "anthropic", "openai"], default=os.environ.get("DOCS_QA_PROVIDER", "none"),
                        help="where to send each inference; none, the default, prints the first request instead")
    parser.add_argument("--model", default=os.environ.get("DOCS_QA_MODEL"),
                        help="ask this model, on the endpoint the environment names, instead of the route's")
    parser.add_argument("--fault", action="append", default=[], choices=["injected-response"],
                        help="make the MCP server misbehave: injected-response puts an instruction in a tool result")
    parser.add_argument("--record", metavar="DIR", help="save the run as a scenario that replays without a model")
    args = parser.parse_args(argv)

    users = json.loads(ACCOUNTS.read_text(encoding="utf-8"))["users"]
    if args.user not in users:
        parser.error(f"no user {args.user!r}; try one of {', '.join(sorted(users))}")
    conversation = Conversation.new(users[args.user]["workspace"], args.user)
    conversation.faults = list(args.fault)
    clock = Clock()
    conversation.ask(args.question)
    route = routes.load(routes.default())
    if args.provider == "none":
        model: Model = DryRun(sys.stdout)
    else:
        # --model replaces the route's settings for the provider, endpoint included: that model, on the endpoint the
        # environment names (OPENAI_BASE_URL), such as a local server instead of the route's hosted one.
        options = {"model": args.model} if args.model else dict(route.models[args.provider])
        model = LiveModel(args.provider, options, route.budget["reserved_output"])
    try:
        outcome = asyncio.run(run(conversation, route, model, clock))
    except providers.ProviderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.provider == "none":
        return 0
    directory = Path(args.record) if args.record else RUNS / f"t_{conversation.session}"
    if args.record:
        assert isinstance(model, LiveModel)
        record(directory, conversation, model, clock)
    save(directory, outcome)
    print(f"\n{outcome.answer}" if outcome.answer is not None else
          f"\nno answer: {'refused, ' + outcome.refused if outcome.refused else 'the last turn still asked for tools'}")
    print(f"\nsaved under {directory}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
