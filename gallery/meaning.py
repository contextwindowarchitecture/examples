"""What a run's numbers say about CWA. metrics.py computes each number and says how; this says what it is evidence of.

    SAYS     for each page, what its numbers have to do with CWA and the requirement they speak to
    MEANS    for each number, the one thing it says about CWA, or plainly that it is not CWA's doing
    reading  for each page, a few sentences computed from the run's own values

The first two are the same for every run. A reading is built from the numbers on its page and from nothing else, and
leaves out any sentence the run has no value for.
"""
from __future__ import annotations

from typing import Any

SAYS = {
    "decisions": (
        "This is CWA with no model in it. Each count is a decision the specification requires to be made outside the "
        "model and written down: what admission let in, what a conflict excluded (R-11), what fitting shed or sent as "
        "a summary (R-16, R-18), and when an assembly refused instead of sending less (R-12, R-17). A request built by "
        "hand makes the same decisions, and nothing records them. That 01–03's counts are the same for every model is "
        "the point: the context is decided by policy, before the model that will read it is known (R-23)."),
    "tokens": (
        "R-16 puts budget.input in the model's own tokens and leaves the counting to the application: a tokenizer that "
        "counts them, or an estimate with a margin that covers its error. No conformance case can test that a count "
        "matches a model, so it rests on the application's word. These numbers are that test, made after the fact. "
        "The assembler's count is right by its own tokenizer, and close to OpenRouter's common one, yet a model's own "
        "count can be several times it. Where the declared margin does not cover a model, a route sized to that "
        "model's real limit would send more than the limit holds, and what CWA refuses to do on purpose, truncate, "
        "would happen by accident. The remedy is the application's: a margin measured for the model, and the tokens "
        "its host adds taken off budget.input."),
    "cost": (
        "CWA decides what is sent, and the bill is where that decision is charged. The same payload costs each model "
        "differently for reasons CWA does not control: how the model counts, what its host adds, what it reads from "
        "cache and how much it reasons. What CWA does control shows as absence: a refused assembly costs nothing "
        "(R-17), and what was kept out is never billed. The share read from cache speaks to placement: a profile puts "
        "governance first, the part of a request that repeats between calls and so the part a cache can reuse, and "
        "leaves cache breakpoints to the application."),
    "speed": (
        "Speed is the model's and its host's. Assembly asks no model (R-18) and is not what these numbers time. CWA "
        "changes them only through what it sends and whether it sends anything, so they are the backdrop for Before "
        "and after, where one model is timed on two requests for the same question. The time to first token is how "
        "long a reader waits whatever the context held; reasoning is how much of the wait is the model's own."),
    "stability": (
        "R-23 makes an assembly deterministic: the same snapshot gives the same request to the byte, and the replays "
        "invariant checks it for every assembly of the run. So when a model's answers to one case differ between "
        "repeats, the context did not move; the model did. That separation is what lets a profile be evaluated at all "
        "(R-19). A suite run once cannot tell a profile that works from one that worked that time, and the gap "
        "between passing on average and passing every repeat is the size of that risk, model by model."),
    "grounding": (
        "CWA gives every article an id and keeps user and fetched content as material, never instruction (R-10), so "
        "an answer can be held to what it was sent. A citation that names nothing in the request is the model's "
        "invention; an answer whose words are not in its request drew on something else. Neither number says an "
        "answer is right. They say whether the request CWA assembled is where the answer came from, which is what "
        "thresholds and refusal exist to control (R-12, R-13)."),
    "before-after": (
        "This is the one place the same model answers the same question with and without CWA. before.py sends its top "
        "chunks whatever they scored; after.py sends what the route's threshold admits, and refuses when that is "
        "nothing (R-12, R-13). A left-out chunk that before.py's answer cites shows the threshold mattered: the model "
        "used what it was given. What before.py spent on questions after.py refused is the price of answering from "
        "nothing. CWA is not compression, and after.py's request can be the larger of the two."),
    "agents": (
        "An agent's snapshots are built from what its own tool calls returned, so here the model shapes its context, "
        "and CWA's part is what holds whatever it does. Tools are offered by the user's role, and a guard outside the "
        "model decides every call (R-5, R-15). A tool result is evidence marked as untrusted, never an instruction "
        "(R-10). A newer look at a thing replaces the older one (R-25). A call the guard refused is an invariant "
        "holding without the model's cooperation. An injected instruction that is tried, recommended or repeated is "
        "the model failing where marking alone could not stop it, which is why the guard exists."),
    "checks": (
        "The invariants hold for every model whatever it answers; these checks are the part that depends on the "
        "model. When nearly all of them pass for everyone, the cases are doing what they were written for, showing "
        "each construct at work, and are too few and too gentle to rank capable models. Read a pass rate with its "
        "range, and look to the numbers that vary between models: tokens, cost, time and stability."),
}

MEANS = {
    ("decisions", "refused"): "A refusal is an outcome, not an error: the route would rather send nothing than answer from nothing (R-12) or cut protected content to fit (R-17).",
    ("decisions", "sent"): "Admission is the first decision. What producers offer is a proposal, and policy decides what the model reads.",
    ("decisions", "kept_out"): "What a request built by hand would have sent, dropped without a word, or cut short. Here each item left out has a reason in the trace.",
    ("decisions", "summarized"): "Fitting swaps a long item for a summary written ahead of time before it drops anything, and calls no model to do it (R-16, R-18).",
    ("decisions", "saved"): "The room those summaries made, which let the rest of the request stay whole.",
    ("decisions", "assemblies"): "One snapshot per inference: an agent's context is assembled afresh each time, never appended to.",
    ("decisions", "left_out_each"): "How much an agent's assembler declines at each step, mostly knowledge below the threshold and tools the user's role lacks.",
    ("decisions", "not_offered"): "A tool the user's role lacks is never in the request, so the model cannot be talked into calling it (R-15).",
    ("decisions", "superseded"): "Only a model that looks at a thing twice exercises it. The stale result is left out, so the model never weighs it against the fresh one (R-25).",
    ("decisions", "conflicts_decided"): "Each was decided by the route's policy from groups the application declared, never by a model reading two statements and choosing (R-11).",
    ("decisions", "budget_peak"): "How near an agent came to the point where fitting must shed (R-16). The examples leave room.",
    ("tokens", "normalized_over_estimate"): "Near one, the published estimate does what it claims against a common tokenizer, and the gaps below are each model's own.",
    ("tokens", "tokenizer"): "A margin belongs to a tokenizer: models of one family should need the same one.",
    ("tokens", "tokens_per_estimated"): "Less one, the margin_percent a route needs for this model on ordinary text (R-16).",
    ("tokens", "tokens_added"): "What to take off budget.input for this host before any margin. A percentage cannot cover a fixed amount.",
    ("tokens", "tokens_per_estimated_pasted"): "R-16 asks for a margin that covers the error for the route's text. A route that takes pasted logs needs a larger one than a route that takes questions.",
    ("tokens", "margin_needed"): "What budget.margin_percent would have had to be for the count R-16 requires to hold for this model.",
    ("tokens", "margin_covered"): "Below 100%, the margin the routes declare does not carry to this model.",
    ("tokens", "over_budget"): "At a real context limit, each is a request the assembler passed and the host could not take whole: the silent truncation R-17 rules out, arriving through the count.",
    ("tokens", "context"): "What budget.input and the reserved output must stay within, together (R-16).",
    ("tokens", "budget_share"): "Why nothing overflowed in this run: the examples' budgets are caps the application chose, far below the limit.",
    ("tokens", "cached_share"): "A profile places governance first, the part that repeats between calls and that a cache can reuse. Cache breakpoints are the application's to set.",
    ("tokens", "resend_factor"): "An agent's cost grows with every inference, since each is a whole request. Supersession and the budget are what keep one request from growing without bound (R-16, R-25).",
    ("cost", "spend"): "What the run cost. A refused assembly adds nothing to it.",
    ("cost", "planned"): "The plan prices the assembler's count, so it runs low for a model that counts more.",
    ("cost", "spent_over_planned"): "Above one where a host counts more than the estimate or the model reasons at length; below it where answers are short.",
    ("cost", "charged_over_list"): "The host's pricing, not CWA's. It is here to read the other costs by.",
    ("cost", "prompt_share_of_spend"): "The part of the bill CWA's decisions act on: what is sent.",
    ("cost", "cost_per_passed_check"): "A price for what the checks can see. With the checks this near their ceiling, it mostly ranks price.",
    ("cost", "cost_per_clean_result"): "The same, per case answered with nothing failed.",
    ("speed", "seconds_p50"): "The model's and its host's. CWA changes it only through what it sends.",
    ("speed", "seconds_p90"): "The tail a user feels. Hosts differ more here than at the median.",
    ("speed", "seconds_p99"): "The call to plan a timeout around.",
    ("speed", "first_token_p50"): "The wait before anything comes back, whatever the context held.",
    ("speed", "first_token_p90"): "The same wait, in the tail.",
    ("speed", "in_one_piece"): "For these, the time to first token is the time to the whole reply: the host did not stream it.",
    ("speed", "first_visible"): "Reasoning delays what a reader sees. This is the wait with it counted.",
    ("speed", "outside"): "The harness's overhead and OpenRouter's, much the same for every model.",
    ("speed", "tokens_per_second"): "Throughput as a user would measure it.",
    ("speed", "generating_per_second"): "The host's rate once it has started, without the wait.",
    ("speed", "visible_per_second"): "The rate at which the answer itself arrives.",
    ("speed", "reasoning_share"): "Output the route reserves room for and pays for, which no reader and no check sees. budget.reserved_output has to cover it (R-16).",
    ("speed", "retried"): "Rate limits and outages. A retry carries the same payload: nothing is assembled again.",
    ("speed", "tried_more_hosts"): "The same request can be answered by another host, which may count it and run it differently.",
    ("speed", "cut_short"): "An answer that ran out of reserved output. budget.reserved_output is the route's to size (R-16).",
    ("stability", "pass_average"): "What a suite run once would report.",
    ("stability", "pass_every"): "What a profile's evaluation should be held to: a case that passes only sometimes is a case that fails in production (R-19).",
    ("stability", "cases_some"): "The context was identical each time (R-23), so each of these is the model changing its answer.",
    ("stability", "cases_none"): "A steady failure: the model's, or a check that misses its phrasing.",
    ("stability", "temperature"): "Why answers move at all: the examples send no sampling settings, so each host uses its default.",
    ("stability", "answer_similarity"): "With the request fixed to the byte, this is how much of an answer is the model's choice of words.",
    ("stability", "same_citations"): "Whether a model grounds itself in the same articles each time it is sent the same ones.",
    ("stability", "same_tool_path"): "Whether an agent reaches for the same tools in the same order. When it does not, its later snapshots differ too.",
    ("grounding", "words_in_context"): "How much of an answer is drawn from the request CWA assembled.",
    ("grounding", "words_in_context_before"): "The same when the request is built by hand. A higher share here is not better: that request carries chunks the route would not admit.",
    ("grounding", "cited_of_sent"): "How much of what admission let through the model used. Low, and the threshold admits more than answers need.",
    ("grounding", "citations_sent"): "Below 100%, a model cites what it was never sent. An id on every article is what makes that checkable.",
    ("grounding", "uncited"): "An answer with no citation cannot be traced to its evidence, whatever it says.",
    ("grounding", "cited_rank"): "The route orders knowledge by relevance. A model that cites from the top follows that order.",
    ("grounding", "cites_first"): "How often the article the route ranked first is one the answer rests on.",
    ("before-after", "left_out_cited"): "A model uses what it is sent. Each of these is a chunk the route's threshold would have kept out (R-13).",
    ("before-after", "answers_citing_left_out"): "How often the threshold changed what an answer rested on.",
    ("before-after", "prompt_change"): "CWA is not compression. Negative where admission left chunks out; positive where it kept what the route protects.",
    ("before-after", "cost_change"): "What the difference between the two requests cost, at this model's prices and with its reasoning.",
    ("before-after", "seconds_change"): "The same difference, in time.",
    ("before-after", "words_change"): "Fewer chunks to answer from tends to mean a shorter answer.",
    ("before-after", "asked_anyway"): "The price of answering from nothing. after.py's assembly refused these, and no model was asked (R-12, R-17).",
    ("agents", "steps_median"): "How direct a path the model takes to the same task.",
    ("agents", "steps_most"): "The longest path. Each tool call is another assembly.",
    ("agents", "recorded_path"): "The recording is one model's path, not the right one. Another path is not a failure.",
    ("agents", "steps_over_recorded"): "Below one, the model did the task in fewer calls than the recording.",
    ("agents", "tried"): "Every one of them went through the guard.",
    ("agents", "refused_by_guard"): "Each is the invariant holding without the model's cooperation (R-5).",
    ("agents", "injected_attempted"): "Marking a tool result untrusted does not stop a model trying what it says (R-10). The guard does.",
    ("agents", "injected_recommended"): "The injected text reaching the user through the answer, where no guard stands.",
    ("agents", "injected_repeated"): "The same, in the injected text's own words.",
    ("agents", "claims_mismatch"): "An answer that misreports what the run did. CWA records the actions; nothing makes a model describe them truly.",
    ("agents", "inferences_median"): "Each is a snapshot, a trace and a payload that can be assembled again (R-23).",
    ("agents", "growth_per_inference"): "What a tool result adds to the next snapshot.",
    ("agents", "inferences_until_budget"): "How long an agent can run before fitting sheds its oldest history.",
    ("checks", "failed"): "What the checks found wrong, across everything graded.",
    ("checks", "always_passed"): "The share of the checks that cannot tell these models apart.",
    ("checks", "cases_with_failure"): "Where the models differ at all.",
    ("checks", "checks_passed"): "Where two models' ranges overlap, this run does not rank them on its checks.",
    ("checks", "hosts"): "One model, several hosts: a result may be the host's as much as the model's.",
    ("checks", "busiest_host_share"): "How much of a model's results one host accounts for.",
}


def explain(pages: list[dict[str, Any]], models: list[str]) -> list[dict[str, Any]]:
    """Each page with what it says about CWA, what each of its numbers means, and a reading of this run."""
    for page in pages:
        for entry in [*page["numbers"], *page.get("totals", [])]:
            entry["means"] = MEANS[page["id"], entry["id"]]
        page["says"] = SAYS[page["id"]]
        page["reading"] = [line for line in READINGS[page["id"]](_Page(page), models) if line]
    return pages


class _Page:
    """A page's values, for reading: each number by model, each total, each table's rows."""

    def __init__(self, page: dict[str, Any]) -> None:
        self.numbers = {one["id"]: one for one in page["numbers"]}
        self.totals = {one["id"]: one for one in page.get("totals", [])}
        self.tables = {one["id"]: one["rows"] for one in page["tables"]}

    def values(self, id: str) -> dict[str, Any]:
        """A number's values, for the models that have one."""
        return {model: value for model, value in self.numbers[id]["values"].items() if value is not None}

    def total(self, id: str) -> Any:
        return self.totals[id]["value"]


def _decisions(page: _Page, models: list[str]) -> list[str | None]:
    requests = page.tables["requests"]
    refused = [row for row in requests if row["outcome"] != "sent"]
    reasons = [row for row in page.tables["reasons"] if row["committed"]]
    most = max(reasons, key=lambda row: row["committed"], default=None)
    looked = page.values("superseded")
    twice = [model for model, count in looked.items() if count]
    return [
        requests and f"01–03's {_plural(len(requests), 'request')} sent {_count(page.total('sent'))} of the "
                     f"{_count(page.totals['sent']['of'])} items their producers offered and kept out {_count(page.total('kept_out'))} tokens.",
        refused and f"{len(refused)} {'was' if len(refused) == 1 else 'were'} refused and asked no model: "
                    + _and([f"{row['request']} ({row['outcome'].removeprefix('refused: ')})" for row in refused]) + ".",
        most and f"Most of what was left out was {most['reason']}: {_plural(most['committed'], 'item')}.",
        page.total("summarized") and f"{_plural(page.total('summarized'), 'item')} went as a summary written ahead of time, "
                                     f"which saved {_count(page.total('saved'))} tokens.",
        looked and (f"In 04 and 05 only {_some(twice, models)} looked at the same thing twice, so only {_its(twice, models)} "
                    "traces show a newer result replacing an older one." if twice and len(twice) < len(looked)
                    else None if twice else "In 04 and 05 no model looked at the same thing twice, so no trace shows supersession."),
    ]


def _tokens(page: _Page, models: list[str]) -> list[str | None]:
    covered, needed, added, over = (page.values(id) for id in ("margin_covered", "margin_needed", "tokens_added", "over_budget"))
    declared = sorted({row["declared"] for row in page.tables["margin_by_case"]})
    whole, none = [m for m, share in covered.items() if share == 1], [m for m, share in covered.items() if share == 0]
    part = [m for m in covered if m not in whole and m not in none]
    most = max(needed, key=needed.get, default=None)
    calls, worst = sum(over.values()), max(over, key=over.get, default=None)
    ratio = page.total("normalized_over_estimate")
    return [
        covered and len(declared) == 1 and f"The routes declare a margin of {_percent(declared[0])}. It covered " + _clauses(
            [*([f"every 01–03 request for {_some(whole, models)}"] if whole else []), *([f"none for {_some(none, models)}"] if none else []),
             *([f"some for {_some(part, models)}"] if part else [])]) + ".",
        most and needed[most] > 0 and f"{_short(most)} needed the largest margin, {_percent(needed[most])}" + (
            f"; its host adds about {_count(round(added[most], -1))} tokens to every request." if added.get(most, 0) >= 100 else "."),
        calls and f"{_plural(calls, 'call')} {'was' if calls == 1 else 'were'} counted over their route's budget.input, "
                  + (f"all of them {_short(worst)}'s." if over[worst] == calls else f"{_count(over[worst])} of them {_short(worst)}'s."),
        ratio and f"OpenRouter's own count of the same requests is {_times(ratio)} the assembler's estimate.",
    ]


def _cost(page: _Page, models: list[str]) -> list[str | None]:
    spend, clean, listing = page.values("spend"), page.values("cost_per_clean_result"), page.values("charged_over_list")
    paid = {model: cost for model, cost in clean.items() if cost}
    low, high = min(paid, key=paid.get, default=None), max(paid, key=paid.get, default=None)
    return [
        spend and f"The run spent {_dollars(sum(spend.values()))}.",
        low and low != high and f"A result with every check passed cost {_dollars(paid[low])} from {_short(low)} and "
                                f"{_dollars(paid[high])} from {_short(high)}, {_times(paid[high] / paid[low])} as much.",
        len(listing) > 1 and f"Hosts charged from {_times(min(listing.values()))} to {_times(max(listing.values()))} the prices listed when the run was planned.",
    ]


def _speed(page: _Page, models: list[str]) -> list[str | None]:
    first, whole, reasoning = page.values("first_token_p50"), page.values("in_one_piece"), page.values("reasoning_share")
    at_once = [model for model, share in whole.items() if share >= 0.9]
    flowing = {model: seconds for model, seconds in first.items() if model not in at_once}
    quick, slow = min(flowing, key=flowing.get, default=None), max(flowing, key=flowing.get, default=None)
    most, least = max(reasoning, key=reasoning.get, default=None), min(reasoning, key=reasoning.get, default=None)
    return [
        quick and quick != slow and f"The median wait for a first token ran from {_seconds(flowing[quick])} for {_short(quick)} "
                                    f"to {_seconds(flowing[slow])} for {_short(slow)}.",
        at_once and f"{_names(at_once)} sent {'its' if len(at_once) == 1 else 'their'} replies in one piece, so "
                    f"{'its' if len(at_once) == 1 else 'their'} time to first token is the time to the whole reply.",
        most and most != least and f"Reasoning was {_percent(reasoning[most])} of {_short(most)}'s output and "
                                   f"{_percent(reasoning[least])} of {_short(least)}'s.",
        # What went wrong is rare, so it is said of the models it happened to, never set out as a column of zeros.
        _went(page.values("retried"), models, "had to be retried after a rate limit or an outage", "No call had to be retried."),
        _went(page.values("tried_more_hosts"), models, "went to a second host before one answered",
              "Every call was answered by the first host OpenRouter tried."),
        _went(page.values("cut_short"), models, "ran out of reserved output and were cut short", "No answer ran out of reserved output."),
    ]


def _went(counts: dict[str, int], models: list[str], happened: str, none: str) -> str | None:
    """Calls something happened to: the models it happened to, most first, or that it happened to none."""
    found = sorted(((model, count) for model, count in counts.items() if count), key=lambda pair: -pair[1])
    if not counts:
        return None
    if not found:
        return none
    (top, most), total = found[0], sum(count for _, count in found)
    if len(found) > 3:
        return f"{_plural(total, 'call')} {happened}, across {_some([model for model, _ in found], models)}; {_count(most)} of them {_short(top)}'s."
    parts = [f"{_count(count)} of {_short(model)}'s" for model, count in found]
    return f"{_and([parts[0] + ' calls', *parts[1:]])} {happened}" + ("." if len(found) == len(counts) else "; no other model's did.")


def _stability(page: _Page, models: list[str]) -> list[str | None]:
    every, some, none, alike = (page.values(id) for id in ("pass_every", "cases_some", "cases_none", "answer_similarity"))
    steady = [model for model, share in every.items() if share == 1]
    moved = [model for model in every if some.get(model)]
    return [
        steady and f"{_cap(_some(steady, models))} passed every graded case in every repeat.",
        moved and f"{_cap(_some(moved, models))} changed {_its(moved, models)} result on at least one case between repeats. "
                  "The request was the same to the byte each time.",
        len(alike) > 1 and f"Answers to the same request shared from {_percent(min(alike.values()))} to {_percent(max(alike.values()))} of their words between repeats.",
    ]


def _grounding(page: _Page, models: list[str]) -> list[str | None]:
    sent, used, words = page.values("citations_sent"), page.values("cited_of_sent"), page.values("words_in_context")
    invented = [model for model, share in sent.items() if share < 1]
    return [
        sent and (f"{_cap(_some(invented, models))} cited an article {_its(invented, models)} request did not carry." if invented
                  else "Every citation named an article its request carried."),
        len(used) > 1 and f"Models cited from {_percent(min(used.values()))} to {_percent(max(used.values()))} of the articles they were sent.",
        len(words) > 1 and f"From {_percent(min(words.values()))} to {_percent(max(words.values()))} of an answer's words were in the request it answered.",
    ]


def _before_after(page: _Page, models: list[str]) -> list[str | None]:
    citing, anyway, prompt = page.values("answers_citing_left_out"), page.values("asked_anyway"), page.values("prompt_change")
    did, did_not = [model for model, share in citing.items() if share], [model for model, share in citing.items() if not share]
    return [
        did and f"Sent by before.py, a chunk the assembly left out was cited by {_some(did, models)}"
                + (f", and never by {_some(did_not, models)}." if did_not else "."),
        citing and not did and "No model cited a chunk the assembly left out.",
        anyway and sum(anyway.values()) and f"before.py spent {_dollars(sum(anyway.values()))} asking questions after.py's assembly refused.",
        len(prompt) > 1 and f"By each model's own count, after.py's request ran from {_change(min(prompt.values()))} to "
                            f"{_change(max(prompt.values()))} than before.py's.",
    ]


def _agents(page: _Page, models: list[str]) -> list[str | None]:
    tried, refused, claims = page.values("tried"), page.values("refused_by_guard"), page.values("claims_mismatch")
    injected = {kind: [model for model, count in page.values(f"injected_{kind}").items() if count] for kind in ("attempted", "recommended", "repeated")}
    misreported = [model for model, count in claims.items() if count]
    took = page.values("recorded_path")
    return [
        tried and f"The guard refused {_count(sum(refused.values()))} of {_plural(sum(tried.values()), 'tool call')}.",
        page.values("injected_attempted") and (
            _cap(_clauses([f"{_some(found, models)} {verb} what the injected text asked for" for verb, found in
                      (("tried", injected["attempted"]), ("recommended", injected["recommended"]), ("repeated", injected["repeated"])) if found])) + "."
            if any(injected.values()) else "No model tried, recommended or repeated what the injected text asked for."),
        claims and (f"{_plural(sum(claims.values()), 'answer')} did not match what {'its' if sum(claims.values()) == 1 else 'their'} run did, "
                    f"from {_some(misreported, models)}." if misreported else "Every answer matched what its run did."),
        took and f"From {_percent(min(took.values()))} to {_percent(max(took.values()))} of a model's runs took the path of 04's recording."
        if len(took) > 1 else None,
    ]


def _checks(page: _Page, models: list[str]) -> list[str | None]:
    failed, graded = page.total("failed"), page.totals["failed"]["of"]
    cases = page.totals["cases_with_failure"]
    worst = page.tables["failures"][0] if page.tables["failures"] else None
    ranges = [edges for edges in (page.numbers["checks_passed"].get("ranges") or {}).values() if edges]
    apart = len(ranges) > 1 and max(low for low, _ in ranges) > min(high for _, high in ranges)
    return [
        graded and (f"{_count(failed)} of {_count(graded)} graded checks failed, in {_count(cases['value'])} of {_count(cases['of'])} cases."
                    if failed else f"Every graded check passed: {_count(graded)} of them."),
        worst and f"{worst['check']} accounts for {_count(worst['failed'])} of them.",
        len(ranges) > 1 and ("At least two models' ranges do not overlap, so this run tells them apart on its checks." if apart
                             else "Every model's range overlaps every other's, so this run does not rank the models on its checks."),
    ]


READINGS = {"decisions": _decisions, "tokens": _tokens, "cost": _cost, "speed": _speed, "stability": _stability,
            "grounding": _grounding, "before-after": _before_after, "agents": _agents, "checks": _checks}


def _short(model: str) -> str:
    return model.split("/")[-1]


def _names(models: list[str]) -> str:
    return _and([_short(model) for model in models])


def _cap(text: str) -> str:
    """At the start of a sentence. A model's name keeps its case; a count starts with a figure."""
    return "Every model" + text[len("every model"):] if text.startswith("every model") else text


def _its(found: list[str], models: list[str]) -> str:
    return "its" if len(found) == 1 or set(found) == set(models) else "their"


def _some(found: list[str], models: list[str]) -> str:
    """Which models, in a run of a few or of many: every model, a count of them, or their names."""
    if set(found) == set(models):
        return "every model"
    return f"{len(found)} of the {len(models)} models" if len(found) > 5 else _names(found)


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1] if parts else ""


def _clauses(parts: list[str]) -> str:
    """Parts that may each hold a list of their own, so the last is set off with a comma."""
    if len(parts) < 2 or not any(" and " in part for part in parts):
        return _and(parts)
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def _change(share: float) -> str:
    return "the same size" if share == 0 else f"{_percent(abs(share))} {'smaller' if share < 0 else 'larger'}"


def _count(number: float) -> str:
    return f"{number:,.0f}"


def _plural(number: float, noun: str) -> str:
    return f"{_count(number)} {noun}{'' if number == 1 else 's'}"


def _percent(share: float) -> str:
    percent = share * 100
    return f"{percent:,.0f}%" if abs(percent - round(percent)) < 0.05 or abs(percent) >= 100 else f"{percent:,.1f}%"


def _times(ratio: float) -> str:
    return f"{ratio:,.0f}×" if ratio >= 10 else f"{ratio:,.2f}×"


def _seconds(seconds: float) -> str:
    return f"{seconds:,.2f} s"


def _dollars(amount: float) -> str:
    return f"${amount:,.2f}" if amount >= 1 else f"${amount:,.3f}" if amount >= 0.01 else f"${amount:.2g}"
