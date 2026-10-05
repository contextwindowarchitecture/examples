// The viewer: a run's results, organized by the CWA construct they exercised. Every page reads a run's summary.json
// and, for what it shows in detail, the job files the summary names.
//
//   #/<run>                          the constructs, the invariants and the models
//   #/<run>/construct/<id>           one construct: the cases that exercised it, and how each model did
//   #/<run>/case/<example>/<case>    one case: what CWA decided for each run of it, and each model's answer
//   #/<run>/numbers                  every number of the run, a row each and a column per model
//   #/<run>/numbers/<page>           one family of numbers: decisions, tokens, cost, speed, stability, grounding,
//                                    before-after, agents, checks
//   #/<run>/cases  #/<run>/models  #/runs

import * as data from "./data.js";
import * as show from "./decision.js";
import { count, dollars, html, number, plural, seconds } from "./html.js";
import { citedLeftOut, compared, marked, ordered, pairsOf } from "./beforeafter.js";
import { asked, cell } from "./question.js";
import * as figures from "./numbers.js";
import * as charts from "./charts.js";
import * as tour from "./tour.js";

const INVARIANTS = [
  ["payload_sent", "Every request the proxy saw carried exactly the payload the assembler rendered.", "R-7 · R-20"],
  ["refused_sends_nothing", "A refused assembly asked no model.", "R-17"],
  ["same_context", "Every 01–03 assembly froze a committed scenario's snapshot and rendered its payload.", "R-23"],
  ["replays", "Every recorded snapshot assembled again to the payload and outcome recorded beside it.", "R-23"],
];
const MEASURES = ["run", "invariant", "answer", "grounding", "conflict", "excluded", "untrusted", "actions", "refusal", "claims", "evals"];
// Every example pins contextwindowarchitecture-assembler to a tag of assembler-python (scripts/assembler_pin.py checks
// they agree); the run records the tag and the commit it locked.
const ASSEMBLER = "https://github.com/contextwindowarchitecture/assembler-python";
const view = document.getElementById("view");
const menu = document.getElementById("numbers");
const state = { repeat: "1", pick: 0, inference: null, sort: { by: null, down: true } };
let fills = 0;
const pending = new Set();

// Parts of a page that read more files fill in when they arrive.
function later(promise) {
  const id = `fill-${++fills}`;
  const filled = promise.then((markup) => {
    const node = document.getElementById(id);
    if (node) { node.innerHTML = String(markup); node.classList.remove("loading"); }
  }).catch((error) => {
    const node = document.getElementById(id);
    if (node) node.textContent = `Could not read it: ${error.message}`;
  });
  pending.add(filled);
  filled.finally(() => pending.delete(filled));
  return html`<div id="${id}" class="loading">Reading…</div>`;
}

// Once every part has filled in, the parts they added included.
async function settled() {
  while (pending.size) await Promise.all([...pending]);
}

const short = (model) => model.split("/").pop();
const caseHref = (run, key) => `#/${run}/case/${key}`;
const spec = (requirement) => html`<a href="https://contextwindowarchitecture.io/spec.html#${requirement}" target="_blank" rel="noopener">${requirement}</a>`;
const jobsOf = (s, results) => { const names = new Set(results.map((r) => r.job)); return s.jobs.filter((job) => names.has(job.job)); };
const ran = (s) => s.results.filter((r) => r.exit !== null);

function measurePills(s, construct, results) {
  const found = results.flatMap((r) => r.checks);
  const pills = [];
  for (const measure of construct.measures) {
    if (measure === "invariant") {
      for (const name of construct.invariants) {
        const counts = data.tally(jobsOf(s, results).flatMap((job) => job.invariants ?? []), (c) => c.check === name);
        if (counts[1]) pills.push(count(name, counts));
      }
    } else if (measure === "guard") {
      const refused = found.filter((c) => c.measure === "guard" && c.check.startsWith("refused")).length;
      pills.push(html`<span class="fg">guard refused ${refused}</span>`);
    } else {
      const counts = data.tally(found, (c) => c.measure === measure);
      pills.push(counts[1] ? count(measure, counts) : html`<span class="muted">no ${measure} checks</span>`);
    }
  }
  if (!construct.measures.length) pills.push(html`<span class="muted">recorded in every trace</span>`);
  return pills;
}

function checkRows(found) {
  return html`<div class="checks">${found.map((c) => html`
    <span class="${c.passed === false ? "fail" : c.passed ? "pass" : "muted"}">${c.passed === false ? "fail" : c.passed ? "pass" : "note"}</span>
    <span class="text">${c.measure} ${c.check} · ${c.detail}</span>`)}</div>`;
}

// A run's checks: its own, then its job's invariants, each once. On a construct's page, only that construct's.
function checksOf(s, r, c) {
  const job = s.jobs.find((one) => one.job === r.job);
  return [...r.checks.filter((check) => check.measure !== "invariant"), ...(job?.invariants ?? [])]
    .filter((check) => !c || (c.measures.includes(check.measure) && (check.measure !== "invariant" || c.invariants.includes(check.check))));
}

// Which run's files a section shows. A case has a run per model and repeat, too many to lay out as buttons, so they
// are options grouped by model; each option's value is the run's place in the list given. It goes in a toolbar, after
// the place where the line saying what a pick changed appears.
function picker(runs, picked) {
  const models = [...new Set(runs.map((r) => r.model))];
  return html`<span class="changed" aria-hidden="true"></span><span class="runpick"><label for="pick-run">Run</label><select id="pick-run" data-action="pick">${models.map((model) => html`
    <optgroup label="${model}">${runs.map((r, n) => r.model === model ? html`
      <option value="${n}"${n === picked ? html` selected` : ""}>${short(r.model)} · ${r.variant ? `${r.variant} · ` : ""}repeat ${r.repeat}</option>` : "")}</optgroup>`)}</select></span>`;
}

function repeatChips(s) {
  const repeats = [...new Set(ran(s).map((r) => String(r.repeat)))].sort();
  if (repeats.length < 2) return "";
  return html`<div class="pills" style="margin-bottom: 18px;">${[...repeats, "all"].map((value) => html`
    <button type="button" class="ghost" data-action="repeat" data-value="${value}" aria-pressed="${state.repeat === value}">${value === "all" ? "All repeats" : `Repeat ${value}`}</button>`)}</div>`;
}
const inRepeat = (r) => state.repeat === "all" || String(r.repeat) === state.repeat;

// Pages

function home(run, s) {
  const invariantChecks = s.jobs.flatMap((job) => (job.invariants ?? []).map((check) => ({ ...check, job: job.job })));
  const broken = invariantChecks.filter((c) => c.measure === "invariant" && c.passed === false);
  const calls = Object.values(s.models).reduce((sum, m) => sum + m.calls, 0);
  return html`
    <section class="wrap head">
      <div class="kicker ruled">Benchmark · run ${run}</div>
      <h1>Constructs</h1>
      <p class="lede">The decisions the assembler made for every request in this run. Each card names the requirement behind it, the cases that exercised it, and how the models did with the context it produced.</p>
      <div class="meta" data-tour="run"><span>commit <b>${s.repository.commit.slice(0, 7)}</b></span>
        <span data-tour="assembler">assembler ${[...new Map(s.assembler.map((pin) => [`${pin.tag} ${pin.commit}`, pin])).values()].map((pin) => html`<a href="${ASSEMBLER}/tree/${pin.commit ?? pin.tag}" target="_blank" rel="noopener">assembler-python</a> <b>${pin.tag} · ${(pin.commit ?? "").slice(0, 7)}</b>`)}</span>
        <span>${plural(Object.keys(s.models).length, "model")} · ${plural(s.jobs.length, "job")} · ${plural(calls, "call")}</span>
        <span>spent <b>${dollars(s.spent)}</b>${s.max_cost_usd ? ` of ${dollars(s.max_cost_usd)}` : ""}</span><span>started ${s.started}</span></div>
      <button type="button" class="ghost" data-action="tour">New here? Take the tour →</button>
      ${s.repository.dirty ? html`<div class="note">This run started from a tree with uncommitted changes. The manifest records it, and commit ${s.repository.commit.slice(0, 7)} alone won't reproduce it.</div>` : ""}
      ${s.skipped.length ? html`<div class="note">${s.skipped.join(". ")}.</div>` : ""}
    </section>
    <section class="band surface"><div class="wrap">
      <div class="kicker">Invariants</div>
      <h2>${broken.length ? "Broken in this run." : "Held in every job."}</h2>
      <p class="body">These hold for every model, whatever it answers. A failure here is a bug in an example or the assembler, not a finding about a model.</p>
      ${broken.map((c) => html`<div class="note"><b class="mono">${c.check}</b> failed in <span class="mono">${c.job}</span>: ${c.detail}</div>`)}
      <div class="hair four" data-tour="invariants">${INVARIANTS.map(([name, copy, requirement]) => {
        const [passed, graded] = data.tally(invariantChecks, (c) => c.check === name);
        return html`<div class="cell"><div class="label">${name}</div><div class="big ${passed < graded ? "fail" : ""}">${graded ? `${passed} / ${graded}` : "—"}</div>
          <div class="card-copy">${copy}</div><div class="mono muted" style="margin-top: auto; font-size: 11.5px;">${requirement}</div></div>`;
      })}</div>
    </div></section>
    <section class="band"><div class="wrap">
      <div class="kicker">Constructs</div>
      <h2>${s.constructs.length} decisions, by what this run exercised.</h2>
      <p class="body">Which results exercised a construct is read from their own traces and tool calls, so in 04 and 05 it follows each model's path. Faded cards were not exercised in this run.</p>
      <div class="hair cards">${s.constructs.map((construct) => {
        const first = construct === s.constructs.find((one) => one.cases.length);
        const results = s.results.filter((r) => construct.cases.includes(r.case));
        if (!construct.cases.length) {
          return html`<div class="cell faded"><div class="fade" style="display: flex; flex-direction: column; gap: 10px;">
            <div class="label split"><span>${construct.spec.join(" · ")}</span><span>0 cases</span></div>
            <div class="card-title">${construct.title}</div><div class="card-copy">${construct.description}</div></div>
            <div class="card-foot muted">Not exercised in this run</div></div>`;
        }
        return html`<a class="cell" href="#/${run}/construct/${construct.id}"${first ? html` data-tour="construct"` : ""}>
          <div class="label split"><span>${construct.spec.join(" · ")}</span><span>${plural(construct.cases.length, "case")}</span></div>
          <div class="card-title">${construct.title}</div><div class="card-copy">${construct.description}</div>
          <div class="card-foot">${measurePills(s, construct, results)}</div></a>`;
      })}</div>
    </div></section>
    <section class="band surface"><div class="wrap">
      <div class="kicker">Models</div>
      <h2>What each model was sent, and what it cost.</h2>
      <p class="body">Every call went through the recording proxy. Hosts are the ones OpenRouter says answered; checks count those graded, and a count in the accent colour has a failure in it.</p>
      <div data-tour="models">${modelsTable(s)}</div>
    </div></section>`;
}

function modelsTable(s) {
  const columns = "minmax(240px, 2fr) 150px 70px 170px 150px 80px 120px minmax(260px, 3fr)";
  return html`<div class="panel scroll"><div style="min-width: 1100px;">
    <div class="row headrow" style="grid-template-columns: ${columns};"><span>Model</span><span>Jobs</span><span>Calls</span><span>Tokens in · out</span><span>Call median · longest</span><span>Cost</span><span>Hosts</span><span>Checks passed</span></div>
    ${Object.entries(s.models).map(([model, m]) => html`<div class="row" style="grid-template-columns: ${columns};">
      <span class="fg">${model}<span class="sub">${m.free ? "free" : `$${(m.input_price * 1e6).toFixed(2)} · $${(m.output_price * 1e6).toFixed(2)} per million`}</span></span>
      <span>${m.done} done${m.failed ? html`<span class="fail"> · ${m.failed} failed</span>` : ""}${m.not_run ? ` · ${m.not_run} not run` : ""}</span>
      <span>${number(m.calls)}</span>
      <span>${number(m.tokens.prompt)} · ${number(m.tokens.completion)}<span class="sub">${number(m.tokens.reasoning)} reasoning</span></span>
      <span>${seconds(m.ms.median)} · ${seconds(m.ms.most)}</span>
      <span>${dollars(m.cost)}</span>
      <span>${Object.keys(m.hosts).join(", ") || "—"}</span>
      <span style="display: flex; flex-wrap: wrap; gap: 2px 12px;">${MEASURES.filter((name) => m.measures[name]).map((name) => count(name, m.measures[name]))}</span>
    </div>`)}
  </div></div>`;
}

function models(run, s) {
  return html`<section class="wrap head"><div class="crumb"><a href="#/${run}">Run ${run}</a> / Models</div>
    <div class="kicker">Models · ${plural(Object.keys(s.models).length, "model")}</div><h1>Models</h1>
    <p class="lede">What each model was sent, what it cost, and the checks its answers passed.</p>${modelsTable(s)}</section>`;
}

function cases(run, s) {
  const columns = "minmax(260px, 1.4fr) minmax(280px, 2fr) minmax(220px, 1.4fr)";
  return html`<section class="wrap head"><div class="crumb"><a href="#/${run}">Run ${run}</a> / Cases</div>
    <div class="kicker">Cases · ${plural(s.cases.length, "case")}</div><h1>Cases</h1>
    <p class="lede">Every question this run asked, with the constructs its results exercised.</p>
    <div class="panel scroll"><div style="min-width: 860px;">
      <div class="row headrow" style="grid-template-columns: ${columns};"><span>Case</span><span>Question</span><span>Constructs</span></div>
      ${s.cases.map((c) => html`<a class="row" href="${caseHref(run, c.key)}" style="grid-template-columns: ${columns};">
        <span>${c.key}${c.variants.length ? html`<span class="sub">${ordered(c.variants).join(" and ")}</span>` : ""}</span>
        ${cell(c.question)}
        <span class="muted">${c.constructs.length ? c.constructs.join(", ") : "none"}</span></a>`)}
    </div></div></section>`;
}

function runs(index) {
  const columns = "minmax(260px, 2fr) 120px 140px 240px 90px";
  return html`<section class="wrap head"><div class="kicker">Runs</div><h1>Every graded run</h1>
    <p class="lede">Newest first. A run is graded when it ends; grade.py grades one again from its files.</p>
    <div class="panel scroll"><div style="min-width: 860px;">
      <div class="row headrow" style="grid-template-columns: ${columns};"><span>Run</span><span>Commit</span><span>Assembler</span><span>Jobs</span><span>Spent</span></div>
      ${index.runs.map((r) => html`<a class="row" href="#/${r.run}" style="grid-template-columns: ${columns};">
        <span>${r.run}<span class="sub">${r.models.map(short).join(", ")}</span></span>
        <span>${r.commit.slice(0, 7)}${r.dirty ? html`<span class="fail"> · changes</span>` : ""}</span><span>${r.assembler.join(", ")}</span>
        <span>${r.done} done · ${r.failed} failed · ${r.not_run} not run</span><span>${dollars(r.spent)}</span></a>`)}
    </div></div></section>`;
}

// See the numbers: one page of the run's numbers.json, or with no page named, all of them.
function numbers(run, id) {
  const file = data.href(run, "numbers.json");
  const found = data.numbers(run);
  const drawn = later(found.then((all) => (id ? figures.page(run, all, id, state.sort, file) : figures.all(run, all, file)), () => figures.missing(run)));
  // The page fills in first: this is asked of the same promise after it. Then its charts have somewhere to be drawn.
  found.then((all) => Promise.resolve().then(() => { const page = all.pages.find((one) => one.id === id); if (page) charts.mount(view, page); }), () => {});
  return drawn;
}

// One construct: the evidence each case gives of it, then how every run of the case did on its measures.
function construct(run, s, id) {
  const c = s.constructs.find((one) => one.id === id);
  if (!c) return html`<section class="wrap head"><h1>No such construct</h1></section>`;
  const results = s.results.filter((r) => c.cases.includes(r.case));
  return html`
    <section class="wrap head">
      <div class="crumb"><a href="#/${run}">Constructs</a> / ${c.title}</div>
      <div class="kicker">Construct · ${c.spec.join(" · ")}${c.measures.length ? ` · measures ${c.measures.join(", ")}` : ""}</div>
      <h1>${c.title}</h1><p class="lede">${c.description}</p>
      <div class="meta"><span>${plural(c.cases.length, "case")} in this run</span>${measurePills(s, c, results)}
        ${c.spec.map((requirement) => html`<span>${spec(requirement)} in the spec →</span>`)}</div>
      ${repeatChips(s)}
    </section>
    ${c.cases.map((key, n) => {
      const one = s.cases.find((x) => x.key === key);
      const caseResults = ran(s).filter((r) => r.case === key && inRepeat(r));
      const question = asked(one?.question ?? key, { small: true });
      return html`<section class="band ${n % 2 ? "" : "surface"}"><div class="wrap">
        <div class="label" style="margin-bottom: 10px;"><a href="${caseHref(run, key)}">${key} →</a></div>
        <h2 class="case">${question.title}</h2>${question.more}
        <div style="margin: 20px 0 28px;"${n ? "" : html` data-tour="evidence"`}>${later(evidence(run, s, c, key))}</div>
        ${one?.variants.length ? html`<div class="label" style="margin-bottom: 10px;">What each model did, before and after</div>${pairRows(run, s, pairsOf(caseResults), c)}`
          : html`<div class="label" style="margin-bottom: 10px;">What each run did</div><div class="hair wide">${caseResults.map((r) => resultCard(run, s, r, c))}</div>`}
      </div></section>`;
    })}`;
}

// The run of a case that shows a construct best: one whose own traces exercised it, else any that assembled.
function representative(s, c, key) {
  const candidates = ran(s).filter((r) => r.case === key && r.assemblies.length);
  return candidates.find((r) => r.constructs.includes(c.id)) ?? candidates[0];
}

async function evidence(run, s, c, key) {
  const r = representative(s, c, key);
  if (!r) return html`<p class="body">No run of this case assembled anything.</p>`;
  const all = await Promise.all(r.assemblies.map((folder) => data.assembly(run, folder)));
  const showing = (a) => html`<p class="mono muted" style="font-size: 12px; margin: 10px 0 0;">From ${short(r.model)} · ${r.variant ? `${r.variant} · ` : ""}repeat ${r.repeat} · assembly ${all.indexOf(a) + 1} of ${all.length}</p>`;
  const first = all[0], last = all[all.length - 1];
  const withReason = (...reasons) => all.find((a) => a.trace.excluded.some((row) => reasons.includes(row.reason))) ?? last;
  const caseInfo = s.cases.find((x) => x.key === key);
  switch (c.id) {
    case "relevance-threshold":
    case "evidence-required":
      return html`${show.refusal(first)}${show.relevance(first, caseInfo?.variants.includes("before"))}${showing(first)}`;
    case "budget-and-fitting": {
      const a = all.find((one) => one.trace.compressed.length || one.trace.excluded.some((row) => row.reason === "over_budget")) ?? last;
      return html`<div class="panel"><div class="panel-body">${show.budget(a)}</div><div class="split-panel"><div class="main">${show.sent(a)}</div>
        <div class="side">${show.leftOut(a, ["over_budget"])}</div></div></div>${showing(a)}`;
    }
    case "escalation":
      return html`${show.attempts(all)}${showing(last)}`;
    case "conflicts": {
      const a = all.find((one) => one.trace.conflicts.some((group) => group.decided_by !== "moot")) ?? last;
      return html`${show.conflicts(a)}${showing(a)}`;
    }
    case "scope": { const a = withReason("out_of_scope"); return html`${show.leftOut(a, ["out_of_scope"])}${showing(a)}`; }
    case "producer-exclusions": { const a = withReason("expired", "revoked"); return html`${show.leftOut(a, ["expired", "revoked"])}${showing(a)}`; }
    case "supersession": { const a = withReason("superseded"); return html`${show.leftOut(a, ["superseded"])}${showing(a)}`; }
    case "capabilities-and-guard":
      return html`<div class="label" style="margin-bottom: 8px;">Offered</div>
        <div class="pills" style="margin-bottom: 16px;">${first.trace.included.filter((row) => row.slot === "governance.capabilities").map((row) => html`<span class="pill">${row.item_id}</span>`)}</div>
        ${show.leftOut(first, ["capability_not_allowed"])}${showing(first)}`;
    case "untrusted-content": {
      const a = [...all].reverse().find((one) => one.trace.included.some((row) => row.slot === "evidence.tool_results")) ?? last;
      return html`${show.toolResults(a)}${showing(a)}`;
    }
    case "placement-and-rendering": {
      const a = all.find((one) => one.trace.result) ?? first;
      return html`${show.placement(a, data.href(run, `${a.folder}/payload.json`))}${showing(a)}`;
    }
    case "determinism-and-replay":
      return html`<div class="panel">${Object.entries(caseInfo?.snapshots ?? {}).map(([digest, n]) => html`
        <div class="row" style="grid-template-columns: 200px minmax(0, 1fr);"><span class="fg">snapshot ${digest}</span><span class="muted">first assembly of ${plural(n, "run")}</span></div>`)}</div>
        <p class="body" style="margin-top: 12px;">In 01–03 every model is sent the same snapshot, so one digest per assembly is what holds. In 04 and 05 each run freezes its own, at its own time.</p>`;
    case "provenance":
      return html`${show.provenance(first)}${showing(first)}`;
    default:
      return html`<p class="body">05's own grader graded each run of its suite; each card below carries its verdict.</p>`;
  }
}

function resultCard(run, s, r, c) {
  const measures = c ? c.measures : MEASURES;
  const found = checksOf(s, r, c);
  const agent = r.case.startsWith("04-") || r.case.startsWith("05-");
  return html`<div class="cell">
    <div class="label split"><span>${short(r.model)}</span><span>${r.variant ? `${r.variant} · ` : ""}repeat ${r.repeat}</span></div>
    ${r.answer ? later(data.file(run, r.answer).then((answered) => html`
      ${agent && c && ["capabilities-and-guard", "untrusted-content"].includes(c.id) ? html`<div>${show.steps(answered)}</div>` : ""}
      <blockquote class="answer" style="max-height: 180px;">${answered.answer ?? (answered.error ? `error: ${answered.error}` : "no answer")}</blockquote>`)) : html`<div class="muted mono" style="font-size: 12px;">${r.exit === null ? "Not run." : "Nothing was sent, so there is no answer."}</div>`}
    <div class="card-foot" style="display: block;">${found.length ? checkRows(found) : html`<span class="muted">No ${measures.join(" or ")} checks for this run.</span>`}</div>
    <a href="${caseHref(run, r.case)}" class="mono" style="font-size: 12px;">the case →</a>
  </div>`;
}

// One case: the decision for a picked run and inference, then every run's tool calls, answer and checks.
function caseView(run, s, key) {
  const one = s.cases.find((x) => x.key === key);
  if (!one) return html`<section class="wrap head"><h1>No such case</h1></section>`;
  if (one.variants.length) return pairedCase(run, s, key, one);
  const [example, ...rest] = key.split("/");
  const results = ran(s).filter((r) => r.case === key);
  const index = Math.min(state.pick, results.length - 1);
  const picked = results[index];
  const question = asked(one.question || key);
  return html`
    <section class="wrap head">
      <div class="crumb"><a href="#/${run}/cases">Cases</a> / ${example} / ${rest.join("/")}</div>
      <div class="kicker">Case · ${example}${one.variants.length ? ` · ${one.variants.join(" and ")}` : ""}</div>
      <h1>${question.title}</h1>${question.more}
      <div class="meta"><span>${plural(results.length, "run")}</span><span>${plural(new Set(results.map((r) => r.model)).size, "model")}</span><span>${plural(Object.keys(one.snapshots).length, "first snapshot")}</span></div>
      <div class="pills">${one.constructs.map((id) => html`<a class="pill" href="#/${run}/construct/${id}">${s.constructs.find((c) => c.id === id)?.title ?? id}</a>`)}</div>
    </section>
    <section class="band surface"><div class="wrap">
      <div class="kicker">What CWA decided</div>
      <h2>The request the model answered from.</h2>
      <p class="body">Each run gets a snapshot per inference, so a model that takes another path is sent other requests. Pick a run, and for an agent, an inference.</p>
      <div class="toolbar">${picker(results, index)}</div>
      ${picked ? later(decided(run, picked)) : html`<p class="body">No run of this case finished.</p>`}
    </div></section>
    <section class="band"><div class="wrap">
      <div class="kicker">What each model did</div>
      <h2>Same question, every answer.</h2>
      <p class="body">Every tool call went through the guard. Answers are quoted from their runs as they came back.</p>
      ${repeatChips(s)}
      <div class="hair wide">${results.filter(inRepeat).map((r) => modelCard(run, s, r))}</div>
    </div></section>`;
}

// A case 01 runs both ways, read as people read a change: before, then after. First what each script sent, item by
// item; then each model's two answers side by side.
function pairedCase(run, s, key, one) {
  const [example, ...rest] = key.split("/");
  const results = ran(s).filter((r) => r.case === key);
  const pairs = pairsOf(results);
  const index = Math.min(state.pick, pairs.length - 1);
  const question = asked(one.question || key);
  const runsOf = (variant) => results.filter((r) => r.variant === variant).length;
  const snapshots = Object.keys(one.snapshots);
  return html`
    <section class="wrap head">
      <div class="crumb"><a href="#/${run}/cases">Cases</a> / ${example} / ${rest.join("/")}</div>
      <div class="kicker">Case · ${example} · ${ordered(one.variants).join(" and ")}</div>
      <h1>${question.title}</h1>${question.more}
      <p class="lede">Each run asks the question twice: before.py builds its request by hand, after.py builds it through CWA. Both go to the same model, so the difference between its two answers is the difference between the two requests.</p>
      <div class="meta"><span>${plural(new Set(results.map((r) => r.model)).size, "model")} · ${plural(new Set(results.map((r) => r.repeat)).size, "repeat")}</span>
        <span>${plural(runsOf("before"), "run")} of before.py</span><span>${plural(runsOf("after"), "run")} of after.py</span>
        <span>${snapshots.length === 1 ? `1 snapshot, ${snapshots[0]}` : plural(snapshots.length, "first snapshot")}</span></div>
      <div class="pills">${one.constructs.map((id) => html`<a class="pill" href="#/${run}/construct/${id}">${s.constructs.find((c) => c.id === id)?.title ?? id}</a>`)}</div>
    </section>
    <section class="band surface"><div class="wrap">
      <div class="kicker">What CWA decided</div>
      <h2>What each script sent.</h2>
      <p class="body">${snapshots.length === 1 ? `after.py froze the same snapshot in all ${runsOf("after")} of its runs, so every model was sent the same request.` : `after.py's runs froze ${snapshots.length} different snapshots; this is the picked run's.`}
        Below is every item in it, with what before.py did with it and what after.py's assembly decided. before.py records nothing, so where it put each item is read from its request.</p>
      ${pairs[index] ? later(sentBoth(run, pairs[index], picker(pairs, index))) : html`<p class="body">No run of this case finished.</p>`}
    </div></section>
    <section class="band"><div class="wrap">
      <div class="kicker">What each model did</div>
      <h2>Same question, before and after.</h2>
      <p class="body">One row per model: before.py's answer on the left, after.py's on the right. A citation marked <mark class="left">[like this]</mark> names a chunk after.py's assembly left out, so only before.py's request could have carried it.</p>
      ${repeatChips(s)}
      ${pairRows(run, s, pairs.filter(inRepeat), null)}
    </div></section>`;
}

// The two requests of one run, compared item by item, then the files behind them and after.py's decision in full.
async function sentBoth(run, pair, choose) {
  const { before, after } = pair;
  const [request, a] = await Promise.all([
    before?.request ? data.file(run, before.request) : null,
    after?.assemblies.length ? data.assembly(run, after.assemblies[after.assemblies.length - 1]) : null]);
  if (!request || !a) return html`<p class="body">This run did not record both requests.</p><div class="toolbar">${choose}</div>`;
  const links = { trace: data.href(run, `${a.folder}/trace.json`), snapshot: data.href(run, `${a.folder}/snapshot.json`), payload: data.href(run, `${a.folder}/payload.json`) };
  const refused = a.trace.refused.bool;
  const link = (href, name) => html`<a href="${href}" target="_blank" rel="noopener">${name} →</a>`;
  return html`${show.refusal(a)}${compared(a, request)}
    <div class="toolbar" style="margin-top: 28px;"><span class="label">The files behind it</span>${choose}</div>
    <div class="hair" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));">
      <div class="cell"><div class="label">Before · before.py</div>
        <div class="mono fg" style="font-size: 12.5px; line-height: 1.7;">Its request, built by hand. There is no snapshot or trace: nothing recorded what it left out.</div>
        <span class="mono" style="font-size: 12px;">${link(data.href(run, before.request), "request.json")}</span></div>
      <div class="cell"><div class="label">After · after.py</div>
        <div class="mono fg" style="font-size: 12.5px; line-height: 1.7;">${refused ? "Its snapshot and trace. The refusal is the whole outcome: there is no payload." : "Its snapshot, its trace, and the payload it rendered, which the proxy saw sent byte for byte."}</div>
        <span class="mono links" style="font-size: 12px;">${link(links.snapshot, "snapshot.json")}${link(links.trace, "trace.json")}${refused ? "" : link(links.payload, "payload.json")}</span></div>
    </div>
    <details class="full"><summary class="label">after.py's decision in full: ${refused ? "the refusal, what was left out, provenance" : "the budget by plane, the slots, what was left out, provenance"}</summary>${show.decision(a, links)}</details>`;
}

// Each model's two answers to a case, before.py's then after.py's, with each one's checks: on a construct's page, only
// that construct's.
function pairRows(run, s, pairs, c) {
  // The tour points at a model whose before.py answer cited a chunk CWA left out, if one did.
  const shown = pairs.find((p) => citedLeftOut(p.before).length) ?? pairs[0];
  return html`<div class="pairs">
    <div class="pair head label"><span>Model</span><span>Before · before.py, built by hand</span><span>After · after.py, through CWA</span></div>
    ${pairs.map((p) => html`<div class="pair"${p === shown ? html` data-tour="pair"` : ""}>
      <div><div class="card-title">${p.model}</div><div class="label">repeat ${p.repeat}</div><p class="card-copy" style="margin: 0;">${verdict(s, p)}</p></div>
      ${side(run, s, p.before, c, "Before", citedLeftOut(p.before))}
      ${side(run, s, p.after, c, "After", [])}
    </div>`)}
  </div>`;
}

function side(run, s, r, c, name, leftOut) {
  if (!r) return html`<div><div class="label side-label">${name}</div><p class="muted mono" style="font-size: 12px;">Not run.</p></div>`;
  const found = checksOf(s, r, c);
  return html`<div><div class="label side-label">${name}</div>
    ${r.answer ? later(data.file(run, r.answer).then((answered) => answered.answer
      ? html`<blockquote class="answer">${marked(answered.answer, leftOut)}</blockquote>` : unanswered(run, r, answered)))
      : html`<p class="muted mono" style="font-size: 12px;">Nothing was sent, so there is no answer.</p>`}
    <div class="tallies">${[...new Set(found.map((check) => check.measure))].map((measure) => {
      const counts = data.tally(found, (check) => check.measure === measure);
      return counts[1] ? count(measure, counts) : "";
    })}</div>
    ${checkRows(found.filter((check) => check.passed !== true))}
  </div>`;
}

// No answer: an error, or an assembly that refused, so no model was asked.
async function unanswered(run, r, answered) {
  if (answered.error) return html`<blockquote class="answer">error: ${answered.error}</blockquote>`;
  const trace = r.assemblies.length ? await data.file(run, `${r.assemblies[r.assemblies.length - 1]}/trace.json`) : null;
  return trace?.refused.bool
    ? html`<div class="box refused">Refused: ${trace.refused.reason}.<br><span class="muted">Nothing was rendered, so no model was asked and there is no answer.</span></div>`
    : html`<blockquote class="answer">no answer</blockquote>`;
}

// What differed for one model between before and after, in a line.
function verdict(s, p) {
  if (!p.before || !p.after) return "";
  // 01 assembles once per run, so an assembly refused in after.py's run is the run refusing.
  const refused = s.jobs.find((job) => job.job === p.after.job)?.invariants?.some((check) => check.check === "refused_sends_nothing");
  if (refused) {
    const [passed, graded] = data.tally(p.before.checks, (check) => check.measure === "refusal");
    return `after.py's assembly refused, so this model was never asked. before.py asked it anyway${graded ? (passed === graded ? ", and it declined." : ", and it answered.") : "."}`;
  }
  const ids = citedLeftOut(p.before);
  if (ids.length) return `Before, it cited ${ids.join(", ")}: ${ids.length === 1 ? "a chunk" : "chunks"} after.py's assembly left out, so after.py never sent ${ids.length === 1 ? "it" : "them"}.`;
  const failed = (r) => r.checks.filter((check) => check.passed === false && check.measure !== "invariant").length;
  const [then, now] = [failed(p.before), failed(p.after)];
  return then === now ? "It cited nothing after.py left out, and the checks see no difference between its two answers."
    : `It cited nothing after.py left out. Before, its answer failed ${plural(then, "check")}; after, ${plural(now, "check")}.`;
}

async function decided(run, r) {
  if (!r.assemblies.length) return html`<p class="body">Nothing was assembled.</p>`;
  const index = state.inference === null ? r.assemblies.length - 1 : Math.min(state.inference, r.assemblies.length - 1);
  const folder = r.assemblies[index];
  const a = await data.assembly(run, folder);
  const links = { trace: data.href(run, `${folder}/trace.json`), snapshot: data.href(run, `${folder}/snapshot.json`), payload: data.href(run, `${folder}/payload.json`) };
  return html`${r.assemblies.length > 1 ? html`<div class="pills" style="margin-bottom: 14px;">${r.assemblies.map((path, n) => html`
      <button type="button" class="ghost" data-action="inference" data-value="${n}" aria-pressed="${n === index}">${path.split("/").pop()}</button>`)}</div>` : ""}
    ${show.decision(a, links)}`;
}

function modelCard(run, s, r) {
  const found = checksOf(s, r, null);
  return html`<div class="cell" style="gap: 16px;">
    <div><div class="label split" style="margin-bottom: 8px;"><span>${r.variant ? `${r.variant} · ` : ""}repeat ${r.repeat}</span><span>${plural(r.assemblies.length, "assembly", "assemblies")}</span></div>
      <div class="card-title">${r.model}</div></div>
    ${r.answer ? later(data.file(run, r.answer).then((answered) => html`
      ${answered.steps ? html`<div><div class="label" style="margin-bottom: 8px;">Tool calls</div>${show.steps(answered)}</div>` : ""}
      <div><div class="label" style="margin-bottom: 8px;">Answer</div>
      <blockquote class="answer">${answered.answer ?? (answered.error ? `error: ${answered.error}` : `no answer${answered.refused ? `: ${answered.refused}` : ""}`)}</blockquote></div>`))
      : html`<div class="muted mono" style="font-size: 12px;">Nothing was sent, so there is no answer.</div>`}
    <div class="card-foot" style="display: block;">${checkRows(found)}</div>
  </div>`;
}

// Routing, the header, and the page's controls

function route() {
  const [path] = location.hash.replace(/^#\/?/, "").split("?");
  return path.split("/").filter(Boolean).map(decodeURIComponent);
}

async function draw() {
  const index = await data.index().catch(() => ({ runs: [] }));
  const parts = route();
  const picker = document.getElementById("run");
  if (parts[0] === "runs" || !index.runs.length) {
    header(index, null, "runs");
    view.innerHTML = String(index.runs.length ? runs(index) : html`<section class="wrap head"><div class="kicker">No runs yet</div><h1>Nothing graded yet</h1>
      <p class="lede">Run the benchmark with uv run --env-file .env run.py, then reload this page.</p></section>`);
    return;
  }
  const run = parts[0] ?? index.runs[0].run;
  if (!parts.length) { location.replace(`#/${run}`); return; }
  const s = await data.summary(run);
  const page = parts[1] ?? "constructs";
  header(index, run, page);
  picker.value = run;
  view.innerHTML = String(
    page === "construct" ? construct(run, s, parts[2])
      : page === "case" ? caseView(run, s, parts.slice(2).join("/"))
        : page === "cases" ? cases(run, s)
          : page === "models" ? models(run, s)
            : page === "numbers" ? numbers(run, parts[2])
              : home(run, s));
}

function header(index, run, page) {
  const picker = document.getElementById("run");
  picker.innerHTML = String(html`${index.runs.map((r) => html`<option value="${r.run}">${r.run}</option>`)}`);
  const current = run ?? index.runs[0]?.run ?? "";
  const links = { constructs: `#/${current}`, cases: `#/${current}/cases`, models: `#/${current}/models`, runs: "#/runs" };
  for (const [name, href] of Object.entries(links)) {
    const link = document.querySelector(`[data-nav="${name}"]`);
    link.href = href;
    const here = name === page || (name === "constructs" && page === "construct") || (name === "cases" && page === "case");
    if (here) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  // The menu's links lead to the same run's numbers; the one being read is marked, and so is the menu.
  const [, , shown] = route();
  menu.toggleAttribute("data-current", page === "numbers");
  for (const link of menu.querySelectorAll("[data-numbers]")) {
    link.href = `#/${current}/numbers${link.dataset.numbers ? `/${link.dataset.numbers}` : ""}`;
    if (page === "numbers" && link.dataset.numbers === (shown ?? "")) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
}

// A control on the page redraws it where the reader is. The first time a run's files are read, its parts show
// "Reading…" until they arrive, so the page would shrink and the browser would scroll to keep up, then scroll again as
// they fill in. Until every part has filled in, the page keeps its height, the browser does not anchor the scroll,
// and the scroll position stays; then the control used has the focus again, and what it changed is said.
async function redraw(control, notice) {
  const top = window.scrollY;
  view.style.minHeight = `${view.offsetHeight}px`;
  document.documentElement.classList.add("redrawing");
  try {
    await draw();
    await settled();
    window.scrollTo(0, top);
  } finally {
    view.style.minHeight = "";
    document.documentElement.classList.remove("redrawing");
  }
  document.querySelector(control)?.focus({ preventScroll: true });
  if (notice) announce(notice);
}

// What a control changed, said once: beside the control, where it fades out, and to a screen reader through the
// page's status region, which stays in the page so the change is announced.
function announce(text) {
  const shown = view.querySelector(".changed");
  if (shown) { shown.textContent = text; shown.classList.add("shown"); }
  document.getElementById("status").textContent = text;
}

view.addEventListener("click", (event) => {
  // Buttons only: the run picker is a select, and redrawing on its click would close it as it opens.
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, value } = button.dataset;
  if (action === "tour") { startTour(); return; }
  if (action === "sort") state.sort = { by: value, down: state.sort.by === value ? !state.sort.down : true };
  if (action === "repeat") state.repeat = value;
  if (action === "inference") state.inference = Number(value);
  redraw(`button[data-action="${action}"][data-value="${CSS.escape(value)}"]`);
});

view.addEventListener("change", (event) => {
  const select = event.target.closest("select[data-action='pick']");
  if (!select) return;
  state.pick = Number(select.value);
  state.inference = null;
  redraw("#pick-run", `Showing ${select.selectedOptions[0].text}`);
});

document.getElementById("run").addEventListener("change", (event) => { location.hash = `#/${event.target.value}`; });

// The menu closes when one of its pages is chosen, on a click anywhere else, and on Escape, which hands the focus back.
document.addEventListener("click", (event) => { if (!menu.contains(event.target) || event.target.closest("a")) menu.open = false; });
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !menu.open) return;
  menu.open = false;
  menu.querySelector("summary").focus();
});

const theme = document.getElementById("theme");
function setTheme(name) {
  document.documentElement.dataset.theme = name;
  theme.textContent = name === "dark" ? "Light" : "Dark";
  try { localStorage.setItem("cwa-theme", name); } catch { /* a private window keeps no storage */ }
}
theme.addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
try { setTheme(localStorage.getItem("cwa-theme") ?? "light"); } catch { setTheme("light"); }

let drawing = Promise.resolve();
window.addEventListener("hashchange", () => { state.pick = 0; state.inference = null; state.sort = { by: null, down: true }; drawing = draw().then(() => window.scrollTo(0, 0)); });

// The tour opens pages itself: visit resolves once the page it opened has drawn. This listener is added after the one
// above, so it runs after that one has started the draw.
function visit(hash) {
  const opened = new Promise((resolve) => window.addEventListener("hashchange", resolve, { once: true }));
  location.hash = hash;
  return opened.then(() => drawing);
}

// The tour runs on the run being read, or the newest when none is.
async function startTour() {
  const index = await data.index();
  const [first] = route();
  const run = first && first !== "runs" ? first : index.runs[0]?.run;
  if (!run) return;
  tour.start({ run, s: await data.summary(run), visit, ready: settled, opener: document.getElementById("tour") });
}
document.getElementById("tour").addEventListener("click", startTour);
draw().catch((error) => { view.innerHTML = String(html`<section class="wrap head"><h1>Could not read the results</h1><p class="lede">${error.message}</p></section>`); });
