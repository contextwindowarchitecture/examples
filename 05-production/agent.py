"""The help-center bot as an agent. For one question it runs a bounded loop, and every inference is assembled from a
snapshot of its own:

    offer tools (capability policy) -> freeze -> assemble -> ask the model
        -> an answer: done
        -> tool calls: the guard decides each; approved ones run on the MCP server and come back as observations
        -> next inference, up to MAX_TURNS; the last offers no tools

    uv run agent.py --user u_ada "Is our webhook still disabled? Please turn it back on."      # dry run: turn 1 only
    uv run agent.py --user u_ada --provider openai "Is our webhook still disabled? ..."        # a live run, saved
    uv run agent.py --user u_ada --provider openai --record scenarios/NAME "..."             # record a scenario

A live run is stored in the snapshot store (store.py) and traced with OpenTelemetry (telemetry.py). --record also writes
it as a folder that replays without a model: scenario.json, one folder per inference (snapshot.json, trace.json,
payload.json) and run.json with every tool call, the guard's decision and the answer. --deployment refuses to run
unless the route's profile has been evaluated for the model (evals.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, TextIO

from cwa import AssemblyResult
from cwa.registry import Registry, RegistryError

import capabilities
import context
import producers
import providers
import report
import routes
import store
import telemetry
import tools
from conversation import Conversation, now
from providers import Call, Reply

MAX_TURNS = 6
ACCOUNTS = Path(__file__).parent / "data" / "accounts.json"
LOCK = Path(__file__).parent / "policy" / "registry.lock.json"
TRACER = telemetry.TRACER


class Model(Protocol):
    name: str
    source: str

    def __call__(self, system: list[str], offered: list[dict[str, Any]], messages: list[dict[str, str]]) -> Reply: ...


class LiveModel:
    """A model behind a provider's SDK. It keeps every reply, so a run can be recorded and replayed."""

    def __init__(self, provider: str, options: dict[str, Any], max_tokens: int) -> None:
        self.provider, self.options, self.max_tokens = provider, options, max_tokens
        self.name = options["model"]
        self.source = f"recorded from {options['model']} through the {provider} provider"
        self.replies: list[Reply] = []

    def __call__(self, system: list[str], offered: list[dict[str, Any]], messages: list[dict[str, str]]) -> Reply:
        reply = providers.chat(self.provider, self.options, system, offered, messages, self.max_tokens)
        self.replies.append(reply)
        return reply


class ScriptedModel:
    """Replies read from a scenario: a recorded live model, or a script written to test what the guard catches."""

    def __init__(self, source: str, replies: list[dict[str, Any]], name: str = "scripted") -> None:
        self.source, self.name = source, name
        self._replies = [Reply(reply["text"], [Call(**call) for call in reply["calls"]]) for reply in replies]

    def __call__(self, system: list[str], offered: list[dict[str, Any]], messages: list[dict[str, str]]) -> Reply:
        return self._replies.pop(0)


class DryRun:
    """No model: print the first inference's request and stop."""
    source = name = "dry run"

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
    with TRACER.start_as_current_span("agent.run", attributes={
            "cwa.task": task, "cwa.route": route.name, "enduser.id": conversation.user, "cwa.tenant": conversation.workspace,
            "gen_ai.request.model": model.name}) as span:
        async with tools.FernwayAPI(conversation.faults) as api:
            proposed = await api.proposed()  # what the server offers; the capability policy decides what the model sees
            role = producers.role(conversation)
            for number in range(1, MAX_TURNS + 1):
                moment = clock()
                batch, grant, granted = capabilities.offer(proposed, role, moment, final_turn=number == MAX_TURNS)
                turn = context.Turn(task, number, MAX_TURNS, moment, list(outcome.steps), batch, grant)
                with TRACER.start_as_current_span("cwa.assemble", attributes={"cwa.turn": number}) as assembling:
                    document = context.snapshot(conversation, route, turn)
                    result = context.assemble(document)
                    assembling.set_attributes(telemetry.assembly(result.trace))
                outcome.inferences.append(Inference(document, result))
                print(f"\nturn {number}", file=out)
                report.report(document, result, out)
                if result.payload is None:
                    outcome.refused = result.trace["refused"]["reason"]  # nothing to send, so no model is asked (R-17)
                    break
                payload = json.loads(result.payload)  # cwa-messages/v1: system, tools and one user message
                with TRACER.start_as_current_span(f"chat {model.name}", attributes={
                        "gen_ai.operation.name": "chat", "gen_ai.request.model": model.name,
                        "cwa.payload.sha256": result.trace["result"]["hash"]}) as asking:
                    reply = model([entry["text"] for entry in payload["system"]],
                                  [json.loads(entry["text"]) for entry in payload["tools"]], payload["messages"])
                    asking.set_attribute("gen_ai.response.tool_calls", [call.name for call in reply.calls])
                if not reply.calls:
                    outcome.answer = reply.text
                    break
                for call in reply.calls:
                    with TRACER.start_as_current_span(f"tool {call.name}", attributes={"gen_ai.tool.name": call.name}) as calling:
                        # The guard runs outside the model, on the call itself, before the server sees it (R-5, R-15).
                        decision = capabilities.authorize(call.name, call.arguments, granted, document["scope"])
                        calling.set_attributes({"cwa.guard.approved": decision.approved, "cwa.guard.reason": decision.reason})
                        if decision.approved:
                            result_of_call = await api.call(call.name, call.arguments)
                            step = producers.Step(call.name, call.arguments, True, decision.reason, result_of_call.ok,
                                                  result_of_call.value, clock())
                            calling.set_attribute("cwa.tool.ok", bool(step.ok))
                        else:
                            step = producers.Step(call.name, call.arguments, False, decision.reason)
                    outcome.steps.append(step)
                    verdict = ("called" if step.ok else "called, and it failed") if step.approved else f"denied: {step.reason}"
                    print(f"  > {call.name} {json.dumps(call.arguments, sort_keys=True)}: {verdict}", file=out)
        span.set_attributes({"cwa.inferences": len(outcome.inferences), "cwa.answered": outcome.answer is not None,
                             "cwa.refused": outcome.refused or "",
                             "cwa.denied_calls": [step.tool for step in outcome.steps if not step.approved]})
    return outcome  # without an answer when refused, or when the last turn still asked for tools


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


def deployable(route: routes.Route, model: str) -> routes.Route:
    """The route as a deployment may use it: its route policy and profile loaded through the registry, so content that
    changed without a version increase is refused (R-20), the profile must be evaluated (R-19), and the model must be
    the one the profile was evaluated for."""
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    registry = Registry.from_json(lock, [route.profile], [route.policy])
    profile = registry.profile(route.profile["id"], route.profile["version"], deployment=True)
    if profile["model_family"] != model:
        raise RegistryError([f"profile {profile['id']} v{profile['version']} was evaluated for {profile['model_family']}, not {model}"])
    return replace(route, profile=profile, policy=registry.route_policy(route.policy["route"], route.policy["version"]))


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
    parser.add_argument("--record", metavar="DIR", help="also save the run as a scenario that replays without a model")
    parser.add_argument("--deployment", action="store_true",
                        help="run as a deployment: pinned policy, an evaluated profile, and only the model it was evaluated for")
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
    if args.deployment:
        try:
            route = deployable(route, model.name)
        except RegistryError as error:
            print(f"not deployable: {error}", file=sys.stderr)
            return 2
    provider = telemetry.configure()
    try:
        outcome = asyncio.run(run(conversation, route, model, clock))
    except providers.ProviderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        provider.shutdown()  # flush the spans
    if args.provider == "none":
        return 0
    run_id = f"t_{conversation.session}"
    with store.connect() as db:
        store.save(db, run_id, conversation.asked_at, conversation.workspace, conversation.user, conversation.question,
                   model.name, outcome)
    if args.record:
        assert isinstance(model, LiveModel)
        record(Path(args.record), conversation, model, clock)
        save(Path(args.record), outcome)
    print(f"\n{outcome.answer}" if outcome.answer is not None else
          f"\nno answer: {'refused, ' + outcome.refused if outcome.refused else 'the last turn still asked for tools'}")
    print(f"\nstored as {run_id} in {store.path()}" + (f", recorded in {args.record}" if args.record else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
