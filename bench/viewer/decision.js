// What CWA decided for one assembly, read from its trace and snapshot: the budget by plane, what was sent and how
// it is marked, what was left out and why, conflicts, relevance against the threshold, placement and provenance.

import { html, number } from "./html.js";

const PLANES = ["governance", "state", "evidence", "interaction"];
const COLOR = { governance: "var(--p-gov)", state: "var(--p-state)", evidence: "var(--p-evid)", interaction: "var(--p-inter)" };
export const planeOf = (slot) => COLOR[slot.split(".")[0]] ?? "var(--line)";
const percent = (part, whole) => `${(part / whole * 100).toFixed(3)}%`;
const excerpt = (text, length = 110) => (text && text.length > length ? `${text.slice(0, length).trimEnd()}…` : text ?? "");

export function refusal(a) {
  const refused = a.trace.refused;
  return refused.bool
    ? html`<div class="note">Refused: <b class="mono">${refused.reason}</b>. Nothing was rendered, so no model was asked (R-17).</div>`
    : "";
}

export function budget(a) {
  const { trace } = a;
  if (!trace.result) return refusal(a);
  const input = trace.budget.input, used = trace.result.input_tokens;
  const byPlane = Object.fromEntries(PLANES.map((plane) => [plane, 0]));
  for (const row of trace.included) byPlane[row.slot.split(".")[0]] += row.tokens;
  const inItems = Object.values(byPlane).reduce((sum, n) => sum + n, 0);
  const outside = Math.max(0, used - inItems);
  const margin = Math.round(input * (trace.budget.margin_percent ?? 0) / 100);
  return html`
    <div class="budget-head"><span>${number(used)} input tokens of ${number(input)}</span>
      <span class="muted">${trace.budget.margin_percent ?? 0}% margin · ${number(trace.budget.reserved_output)} reserved for output</span></div>
    <div class="budget" role="img" aria-label="${number(used)} of ${number(input)} input tokens, by plane">
      ${PLANES.map((plane) => html`<span style="width: ${percent(byPlane[plane], input)}; background: ${COLOR[plane]};"></span>`)}
      ${outside ? html`<span style="width: ${percent(outside, input)}; background: var(--line);"></span>` : ""}
      ${margin ? html`<span class="margin" style="width: ${percent(margin, input)};"></span>` : ""}
    </div>
    <div class="legend">
      ${PLANES.map((plane) => html`<span><i class="swatch" style="background: ${COLOR[plane]};"></i>${plane} ${number(byPlane[plane])}</span>`)}
      ${outside ? html`<span><i class="swatch" style="background: var(--line);"></i>not in an item ${number(outside)}</span>` : ""}
      ${margin ? html`<span><i class="swatch" style="border: 1px dashed var(--muted);"></i>margin ${number(margin)}</span>` : ""}
    </div>`;
}

export function sent(a, highlight = () => false) {
  const compressed = new Map(a.trace.compressed.map((row) => [row.item_id, row]));
  return html`
    <div class="label" style="margin-bottom: 6px;">Sent · ${a.trace.included.length} items, in placement order</div>
    ${a.trace.included.map((row) => {
      const item = a.items.get(row.item_id) ?? {};
      const summary = compressed.get(row.item_id);
      const marks = [item.authority, item.trust, item.injection_risk && item.injection_risk !== "none" ? item.injection_risk : null]
        .filter(Boolean).join(" · ");
      return html`<div class="slotrow" style="--plane: ${planeOf(row.slot)};">
        <div class="slotname">${row.slot}</div><div class="slotmeta">${number(row.tokens)} tokens</div>
        <div class="slotid">${row.item_id}${summary ? html`<span class="fail"> · its summary, ${summary.from} → ${summary.to} tokens</span>` : ""}${
          highlight(row, item) ? html`<span class="fail"> · ${highlight(row, item)}</span>` : ""}</div>
        <div class="slotmeta">${marks}</div>
      </div>`;
    })}`;
}

export function leftOut(a, reasons = null) {
  const rows = a.trace.excluded.filter((row) => !reasons || reasons.includes(row.reason));
  if (!rows.length) return html`<div class="muted mono" style="font-size: 12px;">Nothing left out${reasons ? ` as ${reasons.join(" or ")}` : ""}.</div>`;
  return html`
    <div class="label" style="margin-bottom: 4px;">Left out · ${rows.length}</div>
    ${rows.map((row) => {
      const body = a.items.get(row.item_id)?.body;
      const by = row.stage === "producer" ? "reported by its producer" : row.superseded_by ? `superseded by ${row.superseded_by}` : "";
      return html`<div class="leftrow" style="flex-direction: column; gap: 2px;">
        <div style="display: flex; justify-content: space-between; gap: 12px;"><span class="struck">${row.item_id}</span><span class="fg" style="white-space: nowrap;">${row.reason}</span></div>
        ${by ? html`<span class="muted">${by}</span>` : ""}
        ${body ? html`<span class="excerpt">${excerpt(body)}</span>` : ""}
      </div>`;
    })}`;
}

export function conflicts(a) {
  if (!a.trace.conflicts.length) return html`<div class="muted mono" style="font-size: 12px;">No conflict groups.</div>`;
  return a.trace.conflicts.map((group) => html`
    <div class="label" style="margin: 0 0 8px;">Conflict · ${group.group_id} · ${group.decided_by === "moot" ? "moot, fewer than two admitted" : `decided by ${group.decided_by}`}</div>
    <div class="box" style="margin-bottom: 12px;">
      ${group.items.map((id) => {
        const won = group.winner === id, body = a.items.get(id)?.body;
        return html`<div class="${won ? "fg" : "struck"}">${id}${won ? " · prevails" : ""}</div>${body ? html`<div class="excerpt" style="margin-bottom: 6px;">${excerpt(body)}</div>` : ""}`;
      })}
    </div>`);
}

// The retrieved chunks against the route's min_relevance. before.py, which 01 runs too, sends its top five whatever
// they score; the snapshot's candidates are those five.
export function relevance(a, withBefore) {
  const slot = a.snapshot.route_policy?.slots?.["evidence.knowledge"] ?? {};
  const threshold = slot.min_relevance ?? 0;
  const candidates = [...a.items.values()].filter((item) => item.slot === "evidence.knowledge" && typeof item.relevance === "number")
    .sort((one, other) => other.relevance - one.relevance);
  const included = new Map(a.trace.included.map((row) => [row.item_id, row.tokens]));
  const excluded = new Map(a.trace.excluded.map((row) => [row.item_id, row.reason]));
  const scale = Math.max(4, threshold * 2, ...candidates.map((item) => item.relevance));
  const columns = `minmax(260px, 2.4fr) minmax(200px, 1.6fr) 64px 170px${withBefore ? " 100px" : ""}`;
  return html`<div class="panel scroll"><div style="min-width: ${withBefore ? 880 : 760}px;">
    <div class="panel-head"><span>Candidates · evidence.knowledge</span><span>min_relevance ${threshold}</span></div>
    <div class="row headrow" style="grid-template-columns: ${columns};"><span>Chunk</span><span>Relevance</span><span>Score</span><span>Sent</span>${withBefore ? html`<span>before.py</span>` : ""}</div>
    ${candidates.map((item) => {
      const tokens = included.get(item.id);
      return html`<div class="row" style="grid-template-columns: ${columns}; align-items: center;">
        <div style="min-width: 0;"><div class="fg">${item.id}</div><div class="excerpt clip">${item.body}</div></div>
        <div class="relbar"><div class="track"><i style="width: ${percent(item.relevance, scale)}; opacity: ${tokens ? 1 : 0.5};"></i></div><span class="threshold" style="left: ${percent(threshold, scale)};" aria-hidden="true"></span></div>
        <span>${item.relevance.toFixed(3)}</span>
        <span class="${tokens ? "fg" : "muted"}">${tokens ? `sent · ${tokens} tokens` : excluded.get(item.id) ?? "not sent"}</span>
        ${withBefore ? html`<span class="fg">sent</span>` : ""}
      </div>`;
    })}
    <div class="legend" style="padding: 0 18px 14px;"><span><i class="swatch" style="width: 1px; background: var(--accent);"></i>the route's threshold</span></div>
  </div></div>`;
}

// The assemblies one question took, in order: a refused route, then the route it escalated to (R-12).
export function attempts(list) {
  return html`<div class="panel">${list.map((a, n) => html`
    <div class="row" style="grid-template-columns: 40px minmax(0, 1fr) minmax(0, 1fr);">
      <span class="muted">${n + 1}</span><span class="fg">route ${a.snapshot.profile?.route ?? a.snapshot.route_policy?.route}</span>
      <span class="${a.trace.refused.bool ? "fail" : "fg"}">${a.trace.refused.bool ? `refused · ${a.trace.refused.reason}` : `sent · ${number(a.trace.result.input_tokens)} tokens of ${number(a.trace.budget.input)}`}</span>
    </div>`)}</div>`;
}

export function placement(a, link) {
  return html`<div class="panel">
    <div class="panel-head"><span>Placement · ${a.snapshot.profile.id} v${a.snapshot.profile.version}</span><a href="${link}" target="_blank" rel="noopener">payload.json →</a></div>
    ${a.snapshot.profile.placement.map((row, n) => html`<div class="row" style="grid-template-columns: 40px minmax(0, 1fr) minmax(0, 1fr);">
      <span class="muted">${n + 1}</span><span style="color: ${planeOf(row.slot)};">${row.slot}</span><span class="fg">${row.wrap}</span></div>`)}
  </div>`;
}

export function provenance(a) {
  const context = a.trace.context;
  const facts = [["spec", context.spec], ["route policy", context.route_policy_version], ["profile", `${a.trace.profile.id} v${a.trace.profile.version}`],
    ["tokenizer", context.tokenizer], ["renderer", context.renderer], ["assembled at", context.assembly_time],
    ["snapshot", context.snapshot_digest.slice(0, 16)], ["defaults filled", a.trace.defaults_filled.length ? a.trace.defaults_filled.join(", ") : "none"]];
  return html`<div class="panel">${facts.map(([key, value]) => html`<div class="row" style="grid-template-columns: 150px minmax(0, 1fr);"><span class="muted">${key}</span><span class="fg">${value}</span></div>`)}
    ${a.trace.included.map((row) => {
      const item = a.items.get(row.item_id) ?? {};
      return html`<div class="row" style="grid-template-columns: 150px minmax(0, 1fr);"><span style="color: ${planeOf(row.slot)};">${row.item_id}</span>
        <span class="muted">${item.source ?? ""} · version ${item.source_version ?? "?"}${item.freshness ? ` · ${item.freshness}` : ""}${item.lineage ? ` · ${item.lineage}` : ""}</span></div>`;
    })}</div>`;
}

export function toolResults(a) {
  const rows = a.trace.included.filter((row) => row.slot === "evidence.tool_results");
  if (!rows.length) return html`<div class="muted mono" style="font-size: 12px;">No tool result reached this inference.</div>`;
  return rows.map((row) => {
    const item = a.items.get(row.item_id) ?? {};
    return html`<div class="slotrow" style="--plane: var(--p-evid); margin-bottom: 6px;">
      <div class="slotname">${row.slot}</div><div class="slotmeta">${number(row.tokens)} tokens</div>
      <div class="slotid">${row.item_id} · ${item.source}</div><div class="slotmeta">${item.authority} · ${item.trust} · ${item.injection_risk}</div>
    </div>`;
  });
}

// The tool calls a model tried, with the guard's decision on each (R-5).
export function steps(run) {
  const tried = run?.steps ?? [];
  if (!tried.length) return html`<div class="muted mono" style="font-size: 12px;">No tool call.</div>`;
  return tried.map((step) => html`<div class="step" title="${step.reason}">
    <span class="fg" style="overflow-wrap: anywhere;">${step.tool}(${Object.entries(step.arguments ?? {}).map(([key, value]) => `${key}=${value}`).join(", ")})</span>
    <span class="${step.approved ? "muted" : "fail"}" style="white-space: nowrap;">${step.approved ? (step.ok ? "allowed" : "allowed · failed") : "refused"}</span></div>`);
}

export function decision(a, links, highlight) {
  return html`<div class="panel">
    <div class="panel-head"><span>${a.trace.profile.id} v${a.trace.profile.version} · ${a.trace.context.route_policy_version}</span>
      <span><a href="${links.trace}" target="_blank" rel="noopener">trace</a> · <a href="${links.snapshot}" target="_blank" rel="noopener">snapshot</a>${a.trace.result ? html` · <a href="${links.payload}" target="_blank" rel="noopener">payload</a>` : ""}</span></div>
    <div class="panel-body">${budget(a)}</div>
    <div class="split-panel">
      <div class="main">${a.trace.result ? sent(a, highlight) : refusal(a)}</div>
      <div class="side"><div>${leftOut(a)}</div><div>${conflicts(a)}</div>
        <div class="mono muted" style="font-size: 11.5px; line-height: 1.7;">tokenizer ${a.trace.context.tokenizer}<br>renderer ${a.trace.context.renderer}<br>snapshot ${a.trace.context.snapshot_digest.slice(0, 12)}</div></div>
    </div>
  </div>`;
}
