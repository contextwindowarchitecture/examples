// A guided tour of the viewer. A step at a time it opens the page a part is on, scrolls to the part, dims the rest of
// the page, and says what the part shows and what it has to do with CWA. Parts are marked data-tour="<name>" where the
// pages draw them, so the tour points at what is there, not at positions.

import { dollars, html, plural } from "./html.js";

const EXAMPLES = "https://github.com/contextwindowarchitecture/examples";
const ASSEMBLER = "https://github.com/contextwindowarchitecture/assembler-python";
const SPEC = "https://contextwindowarchitecture.io/spec.html";
const link = (href, text) => html`<a href="${href}" target="_blank" rel="noopener">${text} →</a>`;

// page: where the step is, under the run's route; parts: the data-tour names to point at, the first found wins, none
// for a step that stands alone; when: whether this run has what the step shows.
const STEPS = [
  {
    page: "", kicker: "Welcome", title: "What this site shows.",
    body: () => "CWA bench runs the example applications of Context Window Architecture, a draft specification for how an application builds what it sends a model, against a list of models on OpenRouter. Every request was put together by the same assembler, so each page can set two things side by side: what CWA decided to send, and what each model did with it.",
    links: () => [link(EXAMPLES, "The examples on GitHub"), link(SPEC, "The specification")],
    next: "Start the tour →", end: "Not now",
  },
  {
    page: "", parts: ["run"], kicker: "This run", title: "A run is pinned, so it can be read again.",
    body: (s) => `It records the examples' commit, ${s.repository.commit.slice(0, 7)}, the assembler every example used, ${plural(Object.keys(s.models).length, "model")}, ${plural(s.jobs.length, "job")} and ${dollars(s.spent)} spent. Every graded run is kept: open another from Run at the top of the page.`,
  },
  {
    page: "", parts: ["assembler"], kicker: "The assembler", title: "Every request was assembled by assembler-python.",
    body: (s) => `assembler-python is the Python implementation of the CWA assembler. Every example pins the same release, ${pins(s)}, and never builds a request itself: it hands the assembler a snapshot of what its producers proposed, and sends what comes back.`,
    links: () => [link(ASSEMBLER, "assembler-python on GitHub")],
  },
  {
    page: "", parts: ["invariants"], kicker: "Invariants", title: "Four things that hold for every model.",
    body: () => "The payload sent is exactly the one the assembler rendered, a refused assembly asks no model, 01–03 use their committed snapshots, and every snapshot assembles again to the same bytes. A failure here is a bug in an example or the assembler, not a finding about a model.",
  },
  {
    page: "", parts: ["construct"], kicker: "Constructs", title: "Each card is one decision CWA makes.",
    body: () => "Relevance thresholds, budgets, conflicts, scope, the guard on tools: each card names the requirement in the spec behind it, the cases that exercised it in this run, and how the models' answers did on its checks.",
  },
  {
    page: "", parts: ["models"], kicker: "Models", title: "What each model cost, and how it did.",
    body: () => "Calls, tokens, latency, cost and the hosts OpenRouter routed each call to, then the checks passed, by measure. A count in clay has a failure in it.",
  },
  {
    page: "construct/relevance-threshold", parts: ["evidence"], kicker: "A construct", title: "The evidence comes from the run's own trace.",
    when: (s) => s.constructs.some((c) => c.id === "relevance-threshold" && c.cases.length),
    body: () => "For the relevance threshold: every chunk retrieval proposed, against the route's min_relevance. Above the line it was sent; below it, it was left out, and the trace says by how much. Under the evidence, every run's answer with this construct's checks.",
  },
  {
    page: "case/01-docs-qa/01-answer", parts: ["differs", "compared"], kicker: "Before and after", title: "The same question, built two ways.",
    when: (s) => s.cases.some((c) => c.key === "01-docs-qa/01-answer"),
    body: () => "01 asks each question twice: before.py builds the request by hand, after.py builds it through CWA. Each row is an item after.py's snapshot holds, with what each script did with it. A dot marks a row where they differ, like this one: before.py sent it, and the assembler left it out and said why.",
  },
  {
    page: "case/01-docs-qa/01-answer", parts: ["pair"], kicker: "What each model did", title: "Two answers per model, side by side.",
    when: (s) => s.cases.some((c) => c.key === "01-docs-qa/01-answer"),
    body: () => "before.py's answer on the left, after.py's on the right, each with its checks, and a line on what differed. A citation marked in clay names a chunk CWA left out: only before.py's request could have carried it.",
  },
  {
    page: "case/05-production/injected-instruction", parts: ["budget"], kicker: "An agent's request", title: "Everything CWA decided for one inference.",
    when: (s) => s.cases.some((c) => c.key === "05-production/injected-instruction"),
    body: () => "05 is an agent, so a run is several inferences, each assembled from its own snapshot. Here, the budget by plane. Below it, every item sent as a slot row with its authority and trust, the tool result that carries injected text, and what was left out and why.",
  },
  {
    parts: ["sources"], kicker: "Where it comes from", title: "Run it yourself.",
    body: () => "The examples and this benchmark are in one repository, the assembler in another. bench/ runs every example against the models in bench.toml, records what was sent, and grades it: uv run --env-file .env run.py.",
    links: () => [link(EXAMPLES, "The examples on GitHub"), link(ASSEMBLER, "assembler-python on GitHub")],
    next: "Finish",
  },
];

// The first part of that name a reader can see: one inside a closed disclosure has no box.
const shown = (name) => [...document.querySelectorAll(`[data-tour="${name}"]`)].find((node) => node.getClientRects().length);
const pins = (s) => [...new Set(s.assembler.map((pin) => `${pin.tag} at commit ${(pin.commit ?? "").slice(0, 7)}`))].join(", ");

let tour = null;       // { steps, at, s, run, visit, ready, opener }
let navigating = false;
let frame = 0;
const shade = element("div", "tour-shade");
const hole = element("div", "tour-hole");
const card = element("div", "tour-card");
card.setAttribute("role", "dialog");
card.setAttribute("aria-labelledby", "tour-title");
card.tabIndex = -1;

function element(tag, className) {
  const node = document.createElement(tag);
  node.className = className;
  node.hidden = true;
  if (tag === "div" && className !== "tour-card") node.setAttribute("aria-hidden", "true");
  document.body.append(node);
  return node;
}

// Starts at the first step. visit(hash) opens a page and resolves once it has drawn; ready() once every part of the
// page has filled in.
export function start({ run, s, visit, ready, opener }) {
  tour = { steps: STEPS.filter((step) => !step.when || step.when(s)), at: 0, run, s, visit, ready, opener };
  document.documentElement.classList.add("touring");
  opener?.setAttribute("aria-pressed", "true");
  show(0);
}

export function end() {
  if (!tour) return;
  const { opener } = tour;
  tour = null;
  for (const node of [shade, hole, card]) node.hidden = true;
  document.documentElement.classList.remove("touring");
  document.body.style.paddingBottom = "";
  opener?.setAttribute("aria-pressed", "false");
  opener?.focus({ preventScroll: true });
}

async function show(at) {
  const step = tour.steps[at];
  tour.at = at;
  if (step.page !== undefined) {
    const hash = `#/${tour.run}${step.page ? `/${step.page}` : ""}`;
    if (location.hash !== hash) {
      navigating = true;
      await tour.visit(hash);
      navigating = false;
    }
  }
  await tour.ready();
  if (!tour || tour.at !== at) return;
  const target = (step.parts ?? []).map(shown).find(Boolean) ?? null;
  card.innerHTML = String(content(step, at));
  card.hidden = false;
  card.firstElementChild.scrollTop = 0;
  card.classList.toggle("alone", !target);
  tour.target = target;
  // On a phone the card is a sheet over the bottom of the page, so the page gets room below it for its last parts.
  document.body.style.paddingBottom = narrow() ? `${card.offsetHeight}px` : "";
  if (target) scrollTo(target);
  place();
  card.focus({ preventScroll: true });
}

function content(step, at) {
  const last = at === tour.steps.length - 1;
  return html`<div class="tour-body">
    <div class="tour-top"><span>Tour · ${at + 1} of ${tour.steps.length}</span>
      <button type="button" class="tour-end" data-step="end">${step.end ?? "End tour"}</button></div>
    <div class="kicker">${step.kicker}</div>
    <h2 id="tour-title">${step.title}</h2>
    <p>${step.body(tour.s)}</p>
    ${step.links ? html`<div class="tour-links">${step.links()}</div>` : ""}
    <div class="tour-progress" aria-hidden="true">${tour.steps.map((_, n) => html`<span class="${n <= at ? "done" : ""}"></span>`)}</div>
    <div class="tour-nav">${at ? html`<button type="button" class="ghost" data-step="back">Back</button>` : html`<span></span>`}
      <button type="button" class="tour-next" data-step="next">${step.next ?? (last ? "Finish" : "Next →")}</button></div>
  </div>`;
}

// The part sits just below the sticky header when the card fits under it. When it does not, the part sits lower, with
// room above it for the card, over the section's heading, so the card never covers the part. On a phone the card is a
// sheet at the bottom and the part sits at the top.
function scrollTo(target) {
  const header = document.querySelector(".hdr")?.offsetHeight ?? 0;
  const box = target.getBoundingClientRect();
  const room = card.offsetHeight + 22 + 10;
  const fits = box.height + 10 + room + 16 <= window.innerHeight - header - 28;
  const above = !fits && !narrow();
  window.scrollTo(0, window.scrollY + box.top - header - 28 - (above ? room : 0));
}

// The hole is the part's box with a margin, and its shadow dims everything else. The card goes below the part, else
// above it, else beside it, else in the corner of the window; on a phone it is a sheet at the bottom.
function place() {
  if (!tour) return;
  const target = tour.target;
  shade.hidden = Boolean(target);
  hole.hidden = !target;
  card.style.left = card.style.top = "";
  card.dataset.arrow = "";
  if (!target) return;
  const box = visible(target);
  const pad = 10, gap = 22, edge = 16;
  Object.assign(hole.style, { left: `${box.left - pad}px`, top: `${box.top - pad}px`, width: `${box.width + pad * 2}px`, height: `${box.height + pad * 2}px` });
  if (narrow()) return;
  const width = card.offsetWidth, height = card.offsetHeight;
  const header = document.querySelector(".hdr")?.offsetHeight ?? 0;
  const left = Math.min(Math.max(box.left, edge), window.innerWidth - width - edge);
  let x, y;
  if (window.innerHeight - box.bottom - pad >= height + gap + edge) [x, y, card.dataset.arrow] = [left, box.bottom + pad + gap, "up"];
  else if (box.top - pad - header >= height + gap + edge) [x, y, card.dataset.arrow] = [left, box.top - pad - gap - height, "down"];
  else if (window.innerWidth - box.right - pad >= width + gap + edge) {
    [x, y, card.dataset.arrow] = [box.right + pad + gap, Math.min(Math.max(box.top, header + edge), window.innerHeight - height - edge), "left"];
  } else [x, y] = [window.innerWidth - width - edge, window.innerHeight - height - edge];
  card.style.left = `${x}px`;
  card.style.top = `${y}px`;
  card.style.setProperty("--arrow", `${Math.min(Math.max(box.left + 24 - x, 20), width - 32)}px`);
}

const narrow = () => window.matchMedia("(max-width: 620px)").matches;

// The part's box, cut to what its scrolling panel shows: a row of a table wider than the window runs past its edge.
function visible(target) {
  const box = target.getBoundingClientRect();
  const panel = target.parentElement?.closest(".scroll")?.getBoundingClientRect();
  if (!panel) return box;
  const left = Math.max(box.left, panel.left), right = Math.min(box.right, panel.right);
  return { left, right, top: box.top, bottom: box.bottom, width: right - left, height: box.height };
}

const follow = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(place); };
window.addEventListener("scroll", follow, { passive: true });
window.addEventListener("resize", follow);

card.addEventListener("click", (event) => {
  const action = event.target.closest("button[data-step]")?.dataset.step;
  if (!action || !tour) return;
  if (action === "end") end();
  if (action === "back" && tour.at > 0) show(tour.at - 1);
  if (action === "next") tour.at < tour.steps.length - 1 ? show(tour.at + 1) : end();
});

document.addEventListener("keydown", (event) => {
  if (!tour) return;
  if (event.key === "Escape") { event.preventDefault(); end(); return; }
  if (event.target.closest?.("input, select, textarea")) return;
  if (event.key === "ArrowRight" && tour.at < tour.steps.length - 1) show(tour.at + 1);
  if (event.key === "ArrowLeft" && tour.at > 0) show(tour.at - 1);
});

// A page opened by the reader, not by the tour, ends it.
window.addEventListener("hashchange", () => { if (tour && !navigating) end(); });
