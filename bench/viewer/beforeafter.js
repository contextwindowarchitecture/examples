// 01 runs each question twice: before.py builds its request by hand, after.py builds it through CWA. A case with
// both is read before, then after: what each script sent, then what each model answered to each.

import { planeOf } from "./decision.js";
import { html, number, plural } from "./html.js";

const ORDER = ["before", "after"];
export const ordered = (variants) => [...ORDER.filter((v) => variants.includes(v)), ...variants.filter((v) => !ORDER.includes(v))];

// A case's results as one row per model and repeat, holding its before and its after.
export function pairsOf(results) {
  const rows = new Map();
  for (const r of results) {
    const key = `${r.model} ${r.repeat}`;
    if (!rows.has(key)) rows.set(key, { model: r.model, repeat: r.repeat });
    rows.get(key)[r.variant] = r;
  }
  return [...rows.values()].sort((one, other) => one.repeat - other.repeat);
}

// The chunks before.py's answer cited that after.py's assembly left out, read from the grounding check.
export function citedLeftOut(r) {
  const detail = r?.checks.find((c) => c.check === "cites_what_cwa_left_out")?.detail ?? "none";
  return [...detail.matchAll(/(\S+) \(([a-z_]+)\)/g)].map((match) => match[1]);
}

// An answer with each citation of a chunk CWA left out marked.
export function marked(text, ids) {
  if (!ids.length) return text;
  const pattern = new RegExp(`\\[(${ids.map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\]`, "g");
  const parts = [];
  let at = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push(text.slice(at, match.index), html`<mark class="left" title="CWA left this chunk out">${match[0]}</mark>`);
    at = match.index + match[0].length;
  }
  parts.push(text.slice(at));
  return parts;
}

// Where before.py put an item of after.py's snapshot: before.py records nothing, so its request is searched for the
// item's text. A turn is a message of its own; the instructions and the chunks are pasted into the system prompt.
function placedBefore(request, item) {
  const body = (item.body ?? "").trim();
  if (!body) return null;
  if (request.messages.some((message) => typeof message.content === "string" && message.content.trim() === body)) return "sent as a message";
  if ([request.system].flat().join("\n\n").includes(body)) return item.slot === "evidence.knowledge" ? "pasted into the system prompt" : "in the system prompt";
  return null;
}

// Every item after.py's snapshot holds, with what before.py did with it and what after.py's assembly decided.
export function compared(a, request) {
  const included = new Map(a.trace.included.map((row) => [row.item_id, row]));
  const excluded = new Map(a.trace.excluded.map((row) => [row.item_id, row]));
  const refused = a.trace.refused.bool;
  const threshold = a.snapshot.route_policy?.slots?.["evidence.knowledge"]?.min_relevance;
  const rows = [...a.items.values()].map((item) => {
    const before = placedBefore(request, item);
    const sent = included.get(item.id);
    const after = sent ? `sent · ${number(sent.tokens)} tokens` : excluded.has(item.id) ? `left out · ${excluded.get(item.id).reason}`
      : refused ? "not sent · the assembly refused" : "not sent";
    return { item, before, sent, after, differs: Boolean(before) !== Boolean(sent) };
  });
  const chunks = (test) => rows.filter((row) => row.item.slot === "evidence.knowledge" && test(row)).length;
  const turns = (test) => rows.filter((row) => row.item.slot.startsWith("interaction.") && test(row)).length;
  const columns = "16px minmax(260px, 2.2fr) minmax(170px, 1fr) minmax(190px, 1.1fr)";
  return html`<div class="panel scroll"><div style="min-width: 820px;">
    <div class="panel-head"><span>Every item after.py's snapshot holds${threshold === undefined ? "" : ` · min_relevance ${threshold}`}</span>
      <span class="legend" style="margin: 0;"><span><i class="dot" aria-hidden="true"></i>before and after differ</span></span></div>
    <div class="row headrow" style="grid-template-columns: ${columns};"><span></span><span>Item</span><span>Before · before.py</span><span>After · after.py</span></div>
    ${rows.map(({ item, before, sent, after, differs }) => html`<div class="row compare" style="grid-template-columns: ${columns}; --plane: ${planeOf(item.slot)};">
      <span>${differs ? html`<i class="dot" title="before and after differ"></i>` : ""}</span>
      <span style="min-width: 0;"><span class="fg" style="display: block; overflow-wrap: anywhere;">${item.id}</span>
        <span class="slotname" style="display: block;">${item.slot}${typeof item.relevance === "number" ? ` · relevance ${item.relevance.toFixed(3)}` : ""}</span>
        <span class="excerpt clip" style="display: block;">${item.body}</span></span>
      <span class="${before ? "fg" : "muted"}">${before ?? "not sent · nothing records it"}</span>
      <span class="${differs ? "fail" : sent ? "fg" : "muted"}">${after}</span>
    </div>`)}
    <div class="row compare total" style="grid-template-columns: ${columns};"><span></span><span class="muted">In all</span>
      <span class="fg">${plural(chunks((row) => row.before), "chunk")} in the system prompt · ${plural(request.messages.length, "message")}</span>
      <span class="fg">${refused ? `nothing: refused, ${a.trace.refused.reason}`
        : `${plural(chunks((row) => row.sent), "chunk")} · ${plural(turns((row) => row.sent), "turn")} · ${number(a.trace.result.input_tokens)} of ${number(a.trace.budget.input)} tokens`}</span>
    </div>
  </div></div>`;
}
