// Watch an assembly: the home page replays, example by example, decisions the assembler made in a run. Every frame is
// read from a recorded snapshot and trace (data.assembly): nothing here admits, scores, fits or renders. What it adds
// is order and motion, so the steps of one assembly can be seen apart.
//
// A chapter is an example, and it replays the cases that show what the example adds: 01 a relevance threshold and a
// refusal, 02 who is asking, 03 a budget per route, 04 an agent's turns. An item is a square in its plane's colour. It
// is offered, then left out for the reason its trace gives, or rendered into the request as its share of the budget.

import * as data from "./data.js";
import { answers, tell } from "./charts.js";
import { shown } from "./numbers.js";

const PLANES = ["governance", "state", "evidence", "interaction"];
const TONE = { governance: "var(--c-gov)", state: "var(--c-state)", evidence: "var(--c-evid)", interaction: "var(--c-inter)" };
const SVG = "http://www.w3.org/2000/svg";
const SIZE = 14, GAP = 4, ROW = 24, BAR = 26;
const HOLD = 2600;   // how long a step stays before the next, at play
const MOVE = 750;    // how long an item takes to move

export const CHAPTERS = [
  { n: "01", title: "A threshold, and a refusal",
    adds: "01 is a help-center bot. Its route admits an article only when it scores at or above a relevance threshold, and when nothing does, it refuses: the route requires evidence, so no model is asked.",
    beats: [{ case: "01-docs-qa/01-answer", variant: "after" }, { case: "01-docs-qa/03-off-topic", variant: "after" }] },
  { n: "02", title: "Who is asking",
    adds: "02 knows who is asking: their account, and what it remembers about them. Where the account and a memory disagree, the route's policy decides; a memory from another scope is left out.",
    beats: [{ case: "02-account-aware/02-memory-disagrees" }, { case: "02-account-aware/03-memory-leak" }] },
  { n: "03", title: "A budget per route",
    adds: "03 sends the same items on a large route and a small one. The small route fits them by summarizing, then omitting, in the order its policy names. Content it may not cut is refused rather than cut, until the request is escalated to the large route.",
    beats: [{ case: "03-budget-and-routes/01-large-route" }, { case: "03-budget-and-routes/02-small-route" }, { case: "03-budget-and-routes/03-pasted-log" }] },
  { n: "04", title: "An agent, turn by turn",
    adds: "04 is an agent. Its tools are offered by the user's role, a guard outside the model decides every call, and each result joins the next snapshot as untrusted evidence, so the request grows turn by turn. Each model takes its own path: pick one.",
    beats: [{ case: "04-tools/01-owner-reenables", turns: true }] },
];

const NAMES = { offer: "Offer", withheld: "Withheld", admit: "Admit", conflict: "Conflicts", fit: "Fit", render: "Render", refuse: "Refuse" };

// The steps of one assembly, from its trace: only those it took. A producer withholds before the snapshot; the
// assembler then admits, resolves conflicts, fits, and renders or refuses.
function stepsOf(a) {
  const t = a.trace;
  const left = (test) => t.excluded.filter(test);
  const steps = [{ kind: "offer" }];
  const withheld = left((e) => e.stage === "producer");
  const lost = left((e) => e.stage !== "producer" && e.reason === "conflict_lost");
  const fit = left((e) => e.stage !== "producer" && e.reason === "over_budget");
  const admit = left((e) => e.stage !== "producer" && !lost.includes(e) && !fit.includes(e));
  if (withheld.length) steps.push({ kind: "withheld", items: withheld });
  if (admit.length) steps.push({ kind: "admit", items: admit });
  if (lost.length) steps.push({ kind: "conflict", items: lost });
  if (fit.length || t.compressed.length) steps.push({ kind: "fit", items: fit });
  steps.push({ kind: t.refused.bool ? "refuse" : "render" });
  return steps;
}

// What a step says, in the words of the trace and the snapshot it read.
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const humane = (reason) => reason.replaceAll("_", " ");
function say(beat, step) {
  const { a } = beat, t = a.trace, budget = t.budget.input;
  const items = [...a.items.values()];
  switch (step.kind) {
    case "offer": {
      const producers = new Set(a.snapshot.batches.map((batch) => batch.producer.id)).size;
      return `${beat.lead ?? ""}${plural(items.length, "item")} offered by ${plural(producers, "producer")}, for a route whose budget is ${shown(budget)} tokens.`;
    }
    case "withheld":
      return `${plural(step.items.length, "item")} withheld by ${step.items.length === 1 ? "its producer" : "their producers"} before the snapshot was frozen: ${[...new Set(step.items.map((e) => humane(e.reason)))].join(", ")}. The assembler never sees ${step.items.length === 1 ? "it" : "them"}.`;
    case "admit":
      return [...new Set(step.items.map((e) => e.reason))].map((reason) => [reason, step.items.filter((e) => e.reason === reason)]).map(([reason, found]) => {
        const threshold = a.snapshot.route_policy.slots?.[found[0].slot]?.min_relevance;
        if (reason === "below_threshold") return `${plural(found.length, "item")} scored below the route's threshold of ${threshold} and ${found.length === 1 ? "is" : "are"} left out (R-12).`;
        if (reason === "out_of_scope") return `${plural(found.length, "item")} came from outside the request's scope and ${found.length === 1 ? "is" : "are"} left out.`;
        if (reason === "superseded") return `${plural(found.length, "earlier look")} ${found.length === 1 ? "is" : "are"} left out: a newer result replaced ${found.length === 1 ? "it" : "each"} (R-25).`;
        return `${plural(found.length, "item")} left out: ${humane(reason)}.`;
      }).join(" ");
    case "conflict":
      return step.items.map((e) => {
        const group = t.conflicts.find((one) => one.items.includes(e.item_id));
        return group ? `${e.item_id} and ${group.winner} disagree on ${group.group_id}; ${group.decided_by === "policy" ? "the route's policy" : group.decided_by} decides for ${group.winner} (R-11).` : `${e.item_id} lost a conflict and is left out (R-11).`;
      }).join(" ");
    case "fit": {
      const parts = [t.compressed.length && `${plural(t.compressed.length, "item")} summarized`, step.items.length && `${plural(step.items.length, "item")} omitted`].filter(Boolean);
      return `Over the route's budget of ${shown(budget)} tokens, so ${parts.join(", then ")}, in the order the route's policy names (R-16).`;
    }
    case "refuse":
      return `Refused: ${humane(t.refused.reason)}. Nothing is rendered, and no model is asked (R-17).`;
    default:
      return `${plural(t.included.length, "item")} rendered in the order the profile places their slots: ${shown(t.result.input_tokens)} of ${shown(budget)} tokens.`;
  }
}

// Where every item is at a step: offered in its slot's row, left out in its reason's row, or a share of the request.
function frame(beat, at, width) {
  const { a, steps } = beat, t = a.trace, kind = steps[at].kind;
  const offered = [...a.items.values()];
  const plane = (slot) => PLANES.indexOf(slot.split(".")[0]);
  const slots = [...new Set(offered.map((item) => item.slot))].sort((x, y) => plane(x) - plane(y));
  const reasons = [...new Set(steps.flatMap((step) => (step.items ?? []).map((e) => e.reason)))];
  const wide = width >= 760, label = Math.min(176, Math.floor((wide ? width * 0.5 : width) * 0.5));
  const left = { x: 0, y: 22 }, right = wide ? { x: Math.floor(width * 0.54), y: 22 } : { x: 0, y: 22 + slots.length * ROW + 34 };
  const outTop = right.y + Math.max(reasons.length, 1) * ROW;
  const barY = Math.max(left.y + slots.length * ROW, outTop) + 44;
  const scale = width / t.budget.input;
  const out = new Map();  // item id: [reason, the step it left at]
  steps.forEach((step, n) => (step.items ?? []).forEach((e) => out.set(e.item_id, [e.reason, n])));
  const squashed = new Map(t.compressed.map((one) => [one.item_id, one]));
  const fitted = steps.findIndex((step) => step.kind === "fit");
  // A summarized item may be sent as its variant: it is still the item that was offered.
  const original = new Map(t.compressed.filter((one) => one.variant_id).map((one) => [one.variant_id, one.item_id]));
  const idOf = (row) => original.get(row.item_id) ?? row.item_id;
  const tokens = new Map(t.included.map((row) => [idOf(row), row.tokens]));
  const placed = a.snapshot.profile.placement.map((one) => one.slot);
  const sent = kind === "render" ? t.included.slice().sort((x, y) => placed.indexOf(x.slot) - placed.indexOf(y.slot)) : [];
  const segment = new Map();
  let along = 0;
  for (const row of sent) { segment.set(idOf(row), along); along += row.tokens; }
  const counts = new Map();
  const next = (key) => { const n = counts.get(key) ?? 0; counts.set(key, n + 1); return n; };
  // An offered item keeps its place in its slot's row: one that leaves leaves a gap, and nothing shifts into it.
  const place = new Map(slots.flatMap((slot) => offered.filter((item) => item.slot === slot).map((item, n) => [item.id, n])));
  const chips = [];
  for (const item of offered) {
    const gone = out.get(item.id), tone = TONE[item.slot.split(".")[0]];
    let box;
    if (gone && gone[1] <= at) {
      box = { x: right.x + label + next(gone[0]) * (SIZE + GAP), y: right.y + reasons.indexOf(gone[0]) * ROW + (ROW - SIZE) / 2, w: SIZE, h: SIZE, faded: true };
    } else if (segment.has(item.id)) {
      box = { x: segment.get(item.id) * scale, y: barY, w: Math.max(tokens.get(item.id) * scale - 1, 2), h: BAR };
    } else {
      const small = squashed.has(item.id) && fitted >= 0 && at >= fitted;
      const inset = small ? 3 : 0;
      box = { x: left.x + label + place.get(item.id) * (SIZE + GAP) + inset, y: left.y + slots.indexOf(item.slot) * ROW + (ROW - SIZE) / 2 + inset,
              w: SIZE - 2 * inset, h: SIZE - 2 * inset, dim: kind === "refuse" };
    }
    chips.push({ id: item.id, item, tone, gone: gone && gone[1] <= at ? gone[0] : null, squashed: squashed.get(item.id), tokens: tokens.get(item.id), ...box });
  }
  // A producer's withheld item never reached the snapshot: it appears where it was left out, and only then.
  for (const e of t.excluded.filter((one) => one.stage === "producer")) {
    const [reason, n] = out.get(e.item_id);
    if (n > at) continue;
    chips.push({ id: e.item_id, item: { id: e.item_id, slot: e.slot ?? "withheld" }, tone: "var(--c-quiet)", gone: reason, withheld: true,
                 x: right.x + label + next(reason) * (SIZE + GAP), y: right.y + reasons.indexOf(reason) * ROW + (ROW - SIZE) / 2, w: SIZE, h: SIZE, faded: true });
  }
  const rows = [...slots.map((slot, n) => ({ key: `slot ${slot}`, text: slot, x: left.x + label - 10, y: left.y + n * ROW + ROW / 2 + 4 })),
                ...reasons.map((reason, n) => ({ key: `out ${reason}`, text: humane(reason), x: right.x + label - 10, y: right.y + n * ROW + ROW / 2 + 4 }))];
  const around = kind === "render" ? { x: along * scale, w: Math.max((t.result.input_tokens - along) * scale, 0) } : null;
  const link = kind === "conflict" ? steps[at].items.map((e) => {
    const group = t.conflicts.find((one) => one.items.includes(e.item_id));
    const from = chips.find((chip) => chip.id === e.item_id), to = group && chips.find((chip) => chip.id === group.winner);
    return from && to ? { from, to } : null;
  }).filter(Boolean) : [];
  return { chips, rows, around, link, barY, height: barY + BAR + 26, width, heads: { left, right, wide }, kind, used: t.result?.input_tokens, budget: t.budget.input };
}

// The section: its controls, the stage, and what each step says. One per page; drawing the home page again replaces it.
let current = null;
export function mount(root, run, s) {
  current?.stop();
  current = root ? player(root, run, s) : null;
}

function player(root, run, s) {
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const agents = [...new Set(s.results.filter((r) => r.case.startsWith("04-") && r.assemblies.length).map((r) => r.model))];
  const state = { chapter: 0, beat: 0, step: 0, playing: false, paused: still, model: agents[0], beats: null, timer: 0, seen: false };
  root.replaceChildren();
  const tabs = el("div", "asm-chapters", { role: "group", "aria-label": "Examples" });
  const adds = el("p", "body asm-adds");
  const bar = el("div", "asm-bar");
  const beatName = el("span", "asm-beat mono");
  const pills = el("span", "asm-steps");
  const controls = el("span", "asm-controls");
  const back = button("Previous step", "←"), play = button("Play", "Play"), ahead = button("Next step", "→");
  const pick = el("select", "asm-model", { "aria-label": "Model" });
  pick.append(...agents.map((model) => Object.assign(document.createElement("option"), { value: model, textContent: model.split("/").pop() })));
  controls.append(back, play, ahead, pick);
  bar.append(beatName, pills, controls);
  const plot = el("div", "asm-plot chart");
  const told = el("p", "asm-say", { "aria-live": "polite" });
  root.append(tabs, adds, bar, plot, told);
  tabs.append(...CHAPTERS.map((chapter, n) => {
    const tab = button(`Example ${chapter.n}: ${chapter.title}`, "");
    tab.innerHTML = "";
    tab.append(el("b", "mono", {}, chapter.n), document.createTextNode(` ${chapter.title}`));
    tab.addEventListener("click", () => { pause(); open(n); });
    return tab;
  }));
  back.addEventListener("click", () => { pause(); move(-1); });
  ahead.addEventListener("click", () => { pause(); move(1); });
  play.addEventListener("click", () => (state.playing ? pause() : resume()));
  pick.addEventListener("change", () => { state.model = pick.value; open(state.chapter, true); });

  const svg = document.createElementNS(SVG, "svg");
  plot.append(svg);
  const layers = Object.fromEntries(["rows", "heads", "bar", "links", "chips"].map((name) => [name, svg.appendChild(document.createElementNS(SVG, "g"))]));

  async function load(chapter) {
    const found = [];
    for (const beat of CHAPTERS[chapter].beats) {
      const runs = s.results.filter((r) => r.case === beat.case && (!beat.variant || r.variant === beat.variant) && r.assemblies.length);
      if (beat.turns) {
        const r = runs.filter((one) => one.model === state.model).sort((x, y) => x.repeat - y.repeat)[0];
        if (!r) continue;
        const turns = await Promise.all(r.assemblies.map((folder) => data.assembly(run, folder)));
        turns.forEach((a, n) => {
          const before = n ? turns[n - 1].items : new Map();
          const fresh = [...a.items.values()].filter((item) => !before.has(item.id) && item.slot === "evidence.tool_results");
          const tools = fresh.map((item) => item.source.split("/").pop().split("?")[0]).map((tool) => `${/^[aeiou]/.test(tool) ? "an" : "a"} ${tool} result`);
          const lead = !n ? "Turn 1: " : tools.length ? `Turn ${n + 1}: ${tools.join(" and ")} ${tools.length === 1 ? "joins" : "join"} the snapshot as untrusted evidence (R-10). ` : `Turn ${n + 1}: no new tool result. `;
          found.push({ label: `${beat.case} · ${r.model.split("/").pop()} · turn ${n + 1} of ${turns.length}`, a, steps: stepsOf(a), lead });
        });
      } else {
        // Every assembly the case made: a request refused on one route may be escalated to another, and sent there.
        const r = runs.sort((x, y) => x.repeat - y.repeat)[0];
        if (!r) continue;
        const made = await Promise.all(r.assemblies.map((folder) => data.assembly(run, folder)));
        made.forEach((a, n) => {
          const route = r.assemblies[n].split("/record/")[1];
          const lead = n && made[n - 1].trace.refused.bool ? `Refused there, the application escalates the same request to the ${route} route. ` : "";
          found.push({ label: route ? `${beat.case} · ${route}` : beat.case, a, steps: stepsOf(a), lead });
        });
      }
    }
    return found;
  }

  async function open(chapter, keep = false) {
    state.chapter = chapter;
    state.beat = 0; state.step = 0;
    [...tabs.children].forEach((tab, n) => tab.setAttribute("aria-pressed", String(n === chapter)));
    adds.textContent = CHAPTERS[chapter].adds;
    pick.hidden = !CHAPTERS[chapter].beats.some((beat) => beat.turns) || agents.length < 2;
    pick.value = state.model ?? "";
    told.textContent = "Reading the run's traces…";
    if (!globalThis.d3) { told.textContent = "This is drawn with D3, which the page loads from cdn.jsdelivr.net. It did not load."; return; }
    const asked = chapter;
    const beats = await load(chapter).catch(() => []);
    if (state.chapter !== asked) return;
    state.beats = beats;
    if (!beats.length) { told.textContent = "This run recorded no assembly for this example."; clear(); return; }
    draw(!keep);
    schedule();
  }

  function move(by) {
    if (!state.beats?.length) return;
    let { beat, step } = state;
    step += by;
    if (step >= state.beats[beat].steps.length) { beat += 1; step = 0; }
    if (step < 0) { beat -= 1; step = beat >= 0 ? state.beats[beat].steps.length - 1 : 0; }
    if (beat >= state.beats.length) { open((state.chapter + 1) % CHAPTERS.length); return; }
    if (beat < 0) { beat = 0; step = 0; }
    const fresh = beat !== state.beat;
    Object.assign(state, { beat, step });
    draw(fresh);
    schedule();
  }

  function schedule() {
    clearTimeout(state.timer);
    play.textContent = state.playing ? "Pause" : "Play";
    told.setAttribute("aria-live", state.playing ? "off" : "polite");  // a reader stepping hears each step; autoplay stays quiet
    play.setAttribute("aria-label", state.playing ? "Pause" : "Play");
    if (!state.playing || !state.beats?.length) return;
    const last = state.beats[state.beat].steps[state.step].kind;
    state.timer = setTimeout(() => { if (root.isConnected) move(1); else stop(); }, last === "render" || last === "refuse" ? HOLD * 1.6 : HOLD);
  }
  function pause() { state.playing = false; state.paused = true; schedule(); }
  function resume() { state.playing = true; state.paused = false; schedule(); }
  function stop() { clearTimeout(state.timer); seen.disconnect(); window.removeEventListener("resize", resized); }

  // A step, drawn: every item moves from where it was to where this step puts it.
  function draw(fresh) {
    const beat = state.beats[state.beat], step = beat.steps[state.step];
    const f = frame(beat, state.step, plot.clientWidth);
    // A conflict's line starts where the loser was offered, the step before, not where it is left out.
    if (f.kind === "conflict" && state.step > 0) {
      const before = frame(beat, state.step - 1, plot.clientWidth).chips;
      f.link = f.link.map((link) => ({ ...link, from: before.find((chip) => chip.id === link.from.id) ?? link.from }));
    }
    const time = still ? 0 : MOVE;
    beatName.textContent = beat.label;
    pills.replaceChildren(...beat.steps.map((one, n) => {
      const pill = button(`${NAMES[one.kind]}, step ${n + 1} of ${beat.steps.length}`, NAMES[one.kind]);
      pill.className = "asm-pill";
      pill.setAttribute("aria-current", String(n === state.step));
      pill.addEventListener("click", () => { pause(); Object.assign(state, { step: n }); draw(false); schedule(); });
      return pill;
    }));
    told.textContent = say(beat, step);
    svg.setAttribute("width", f.width);
    svg.setAttribute("height", f.height);
    svg.setAttribute("viewBox", `0 0 ${f.width} ${f.height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${beat.label}, ${NAMES[step.kind]}: ${told.textContent}`);

    d3.select(layers.heads).selectAll("text").data([["Offered", f.heads.left], ["Left out", f.heads.right]]).join("text")
      .attr("class", "axis-label").attr("x", ([, at]) => at.x).attr("y", ([, at]) => at.y - 8).text(([text]) => text);
    d3.select(layers.rows).selectAll("text").data(f.rows, (row) => row.key).join(
      (enter) => enter.append("text").attr("class", "row-label").attr("text-anchor", "end").attr("opacity", 0).attr("x", (row) => row.x).attr("y", (row) => row.y),
      (update) => update, (exit) => exit.transition().duration(time / 2).attr("opacity", 0).remove())
      .text((row) => row.text).transition().duration(time).attr("x", (row) => row.x).attr("y", (row) => row.y).attr("opacity", 1);

    // The request: the route's budget as a track, what was rendered as the share of it each item took.
    const track = d3.select(layers.bar);
    track.selectAll("rect.asm-track").data([f]).join("rect").attr("class", "asm-track").attr("x", 0).attr("width", f.width).attr("height", BAR)
      .classed("refused", f.kind === "refuse").transition().duration(time).attr("y", f.barY);
    track.selectAll("rect.asm-around").data(f.around ? [f.around] : []).join(
      (enter) => enter.append("rect").attr("class", "asm-around").attr("y", f.barY).attr("height", BAR).attr("x", (d) => d.x).attr("width", 0),
      (update) => update, (exit) => exit.remove())
      .transition().delay(time).duration(time / 2).attr("x", (d) => d.x).attr("width", (d) => d.w).attr("y", f.barY);
    const caption = f.kind === "render" ? `Sent · ${shown(f.used)} of ${shown(f.budget)} tokens` : f.kind === "refuse" ? `Refused · nothing sent, no model asked` : `The request · a budget of ${shown(f.budget)} tokens`;
    track.selectAll("text").data([caption]).join("text").attr("class", "axis-label").attr("x", 0).text((d) => d)
      .classed("asm-refused", f.kind === "refuse").transition().duration(time).attr("y", f.barY - 8);

    // A conflict: the loser is drawn to the winner before it is left out.
    d3.select(layers.links).selectAll("path").data(f.link, (d) => d.from.id).join(
      (enter) => enter.append("path").attr("class", "asm-link"), (update) => update, (exit) => exit.remove())
      // From the loser's right edge to the winner's, bowed out past both, so it clears the squares between them.
      .attr("d", (d) => {
        const x1 = d.from.x + d.from.w, y1 = d.from.y + d.from.h / 2, x2 = d.to.x + d.to.w, y2 = d.to.y + d.to.h / 2;
        const bow = Math.max(x1, x2) + 28 + Math.abs(y2 - y1) * 0.25;
        return `M${x1},${y1} C${bow},${y1} ${bow},${y2} ${x2},${y2}`;
      });

    const wait = f.kind === "conflict" ? time : 0;
    d3.select(layers.chips).selectAll("rect").data(f.chips, (chip) => chip.id).join(
      (enter) => enter.append("rect").attr("class", "asm-chip").attr("rx", 2)
        .attr("x", (chip) => chip.x).attr("y", (chip) => chip.y - (chip.withheld ? 12 : 0)).attr("width", (chip) => chip.w).attr("height", (chip) => chip.h)
        .attr("opacity", 0).each(function (chip) { hover(this, chip); }),
      (update) => update.each(function (chip) { hover(this, chip); }),
      (exit) => exit.transition().duration(time / 2).attr("opacity", 0).remove())
      .attr("fill", (chip) => chip.tone).classed("squashed", (chip) => Boolean(chip.squashed))
      .transition().delay((chip, n) => (fresh && !still ? n * 35 : chip.gone && f.kind === "conflict" ? wait : 0))
      .duration(time).attr("x", (chip) => chip.x).attr("y", (chip) => chip.y).attr("width", (chip) => chip.w).attr("height", (chip) => chip.h)
      .attr("rx", (chip) => (chip.h === BAR ? 1 : 2)).attr("opacity", (chip) => (chip.faded ? 0.45 : chip.dim ? 0.3 : 1));
  }

  // An item tells what it is and what became of it, to the pointer and to the keyboard alike.
  function hover(node, chip) {
    const item = chip.item;
    const lines = [[item.slot, "slot", chip.tone]];
    if (item.relevance !== undefined) lines.push([String(item.relevance), "relevance"]);
    if (chip.squashed) lines.push([`${shown(chip.squashed.from)} → ${shown(chip.squashed.to)}`, "tokens, summarized"]);
    if (chip.tokens !== undefined) lines.push([shown(chip.tokens), "tokens in the request"]);
    if (chip.gone) lines.push([humane(chip.gone), chip.withheld ? "withheld by its producer" : "left out"]);
    if (item.injection_risk === "untrusted_content" || item.trust === "unverified") lines.push([item.trust ?? "untrusted", "material, never an instruction"]);
    const label = `${item.id}: ${lines.map(([value, name]) => `${name} ${value}`).join("; ")}`;
    if (!node.dataset.answers) { node.dataset.answers = "1"; answers(node, label, () => tell(node, node.__chip.item.id, node.__lines)); }
    node.setAttribute("aria-label", label);
    node.__chip = chip;
    node.__lines = lines;
  }

  function clear() { for (const layer of Object.values(layers)) layer.replaceChildren(); }

  let resizing = 0;
  function resized() { clearTimeout(resizing); resizing = setTimeout(() => state.beats?.length && root.isConnected && draw(false), 150); }
  window.addEventListener("resize", resized);
  // It plays while it can be seen, unless the reader paused it or asks for less motion.
  const seen = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting && !state.paused) { state.playing = true; schedule(); }
    if (!entry.isIntersecting && state.playing) { state.playing = false; schedule(); }
  }, { threshold: 0.35 });
  seen.observe(root);
  open(0);
  return { stop };
}

function el(name, className, attributes = {}, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
function button(label, text) {
  const node = el("button", "asm-button", { type: "button", "aria-label": label }, text);
  return node;
}
