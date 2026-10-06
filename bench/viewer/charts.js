// The charts on a page of numbers, drawn with D3 from what charts.py wrote: a chart is a list of marks with their
// places, and nothing is computed here but where a place falls on the screen.
//
// D3 is the one thing the viewer does not hold itself: index.html loads it from a CDN, a fixed version checked against
// its hash. Without it a chart says so and the page keeps its tables, which hold every value a chart shows.
//
// Colour does one job in each chart, named by a mark's tone (charts.py). A model is never a colour: it is a row, a
// panel or a label, so a run of a dozen models reads like a run of three.

import { shown } from "./numbers.js";

const TONE = {
  ink: "var(--fg)", quiet: "var(--c-quiet)", accent: "var(--accent)", governance: "var(--c-gov)", state: "var(--c-state)",
  evidence: "var(--c-evid)", interaction: "var(--c-inter)", around: "var(--c-around)",
};
const SVG = "http://www.w3.org/2000/svg";
const MONO = "12.5px 'IBM Plex Mono', monospace";
const ROW = 34;      // a row's height: its marks are thin, and the whole row answers to the pointer
const R = 5;         // a dot's radius; it wears a 2px ring of the surface, so it stays whole where marks cross
let mounted = null;  // the page whose charts are drawn, to draw them again when the window's width changes

export function mount(root, page) {
  mounted = { root, page };
  for (const figure of root.querySelectorAll("figure[data-chart]")) {
    const chart = page.charts.find((one) => one.id === figure.dataset.chart);
    const plot = figure.querySelector(".chart-plot");
    plot.replaceChildren();
    figure.querySelector(".chart-legend").replaceChildren(...(chart?.legend ?? []).map(key));
    if (!chart) continue;
    if (!globalThis.d3) {
      plot.textContent = "This chart is drawn with D3, which the page loads from cdn.jsdelivr.net. It did not load, so read the values from the tables on this page.";
      continue;
    }
    ({ rows, panels, grid, scatter, lines })[chart.kind]?.(plot, chart);
  }
}

let resizing = 0;
window.addEventListener("resize", () => {
  clearTimeout(resizing);
  resizing = setTimeout(() => { if (mounted?.root.isConnected) mount(mounted.root, mounted.page); }, 150);
});

// Elements, and the text that goes in them. Labels come from a run's files, so they are set as text, never as markup.
function el(name, attributes = {}, text) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
function div(className, text) {
  const node = document.createElement("div");
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
const canvas = document.createElement("canvas").getContext("2d");
function width(text, font = MONO) { canvas.font = font; return canvas.measureText(text).width; }
// A label too long for its place ends in an ellipsis: text is never clipped by its own mark or by the page's edge.
// The whole of it is in the tooltip and in what a screen reader is told.
function fit(text, room) {
  if (width(text) <= room) return text;
  let cut = text;
  while (cut.length > 1 && width(`${cut}…`) > room) cut = cut.slice(0, -1);
  return `${cut}…`;
}

// A legend's key mirrors the mark it names.
function key(entry) {
  const item = div("chart-key");
  const swatch = el("svg", { width: 22, height: 12, "aria-hidden": "true" });
  const tone = TONE[entry.tone];
  if (entry.mark === "dot") swatch.append(el("circle", { cx: 11, cy: 6, r: R, fill: tone }));
  else if (entry.mark === "ring") swatch.append(el("circle", { cx: 11, cy: 6, r: R - 1, fill: "var(--bg)", stroke: tone, "stroke-width": 2 }));
  else if (entry.mark === "cell") swatch.append(el("rect", { x: 3, y: 1, width: 16, height: 10, fill: "var(--accent-soft)" }));
  else if (entry.mark === "tick") swatch.append(el("line", { x1: 11, x2: 11, y1: 1, y2: 11, stroke: tone, "stroke-width": 2.5, "stroke-linecap": "round" }));
  else if (entry.mark === "segment" || entry.mark === "bar") swatch.append(el("rect", { x: 3, y: 1, width: 16, height: 10, fill: tone }));
  else swatch.append(el("line", { x1: 1, x2: 21, y1: 6, y2: 6, stroke: tone, "stroke-width": 2, "stroke-linecap": "round" }));
  const label = document.createElement("span");
  label.textContent = entry.label;
  item.append(swatch, label);
  return item;
}

// One tooltip for the page. It adds nothing a table does not hold; the value leads and its name follows.
const tip = div("chart-tip");
tip.hidden = true;
document.body.append(tip);
export function tell(target, title, lines) {
  tip.replaceChildren(div("tip-title", title), ...lines.map(([value, name, tone]) => {
    const line = div("tip-line");
    const mark = document.createElement("i");
    mark.style.background = tone ?? "transparent";
    const strong = document.createElement("b");
    strong.textContent = value;
    const label = document.createElement("span");
    label.textContent = name;
    line.append(mark, strong, label);
    return line;
  }));
  tip.hidden = false;
  const box = target.getBoundingClientRect();
  const left = Math.min(Math.max(8, box.left + box.width / 2 - tip.offsetWidth / 2), window.innerWidth - tip.offsetWidth - 8);
  const above = box.top - tip.offsetHeight - 10;
  tip.style.left = `${left}px`;
  tip.style.top = `${above > 8 ? above : box.bottom + 10}px`;
}
const hush = () => { tip.hidden = true; };
// The page scrolling under the pointer leaves the tooltip behind, so it goes. A mark that holds the keyboard's focus
// keeps its tooltip, moved to where the mark now is: tabbing to a mark is itself what scrolls it into view.
const shows = new WeakMap();
window.addEventListener("scroll", () => (shows.get(document.activeElement) ?? hush)(), { passive: true });

// What answers to the pointer answers to the keyboard: the same details on focus as on hover.
export function answers(node, label, show) {
  node.setAttribute("tabindex", "0");
  node.setAttribute("role", "img");
  node.setAttribute("aria-label", label);
  node.classList.add("hit");
  shows.set(node, show);
  node.addEventListener("pointerenter", show);
  node.addEventListener("focus", show);
  node.addEventListener("pointerleave", () => (document.activeElement === node ? show() : hush()));
  node.addEventListener("blur", hush);
}

// A chart is as wide as its place on the page. One that needs more, a grid of many models on a phone, scrolls in it.
function frame(plot, height, label, wide = plot.clientWidth) {
  const svg = el("svg", { width: wide, height, viewBox: `0 0 ${wide} ${height}`, role: "group", "aria-label": label });
  plot.append(svg);
  return svg;
}

// An axis is hairlines one step off the surface and a few round numbers: it recedes, and the data does not.
function axisX(svg, scale, unit, top, bottom, label, ticks = 5) {
  // A scale of ratios is ticked at 1, 2 and 5 in each power of ten: its every tick would be a wall of labels.
  const leads = (value) => [1, 2, 5].includes(Math.round(value / 10 ** Math.floor(Math.log10(value))));
  const values = ticks === "ratios" ? scale.ticks().filter(leads) : scale.ticks(ticks);
  for (const value of values) {
    svg.append(el("line", { x1: scale(value), x2: scale(value), y1: top, y2: bottom, class: "grid" }));
    svg.append(el("text", { x: scale(value), y: bottom + 16, class: "tick", "text-anchor": "middle" }, shown(value, unit)));
  }
  if (label) svg.append(el("text", { x: scale.range()[1], y: bottom + 34, class: "axis-label", "text-anchor": "end" }, label));
}
function axisY(svg, scale, unit, left, right, ticks = 4) {
  for (const value of scale.ticks(ticks)) {
    svg.append(el("line", { x1: left, x2: right, y1: scale(value), y2: scale(value), class: "grid" }));
    svg.append(el("text", { x: left - 8, y: scale(value) + 4, class: "tick", "text-anchor": "end" }, shown(value, unit)));
  }
}

// A bar grows from its baseline: square there, and rounded at the end that carries its value.
function barPath(from, to, y, height) {
  const length = Math.max(to - from, 0), r = Math.min(4, length, height / 2);
  return `M${from},${y}h${length - r}a${r},${r} 0 0 1 ${r},${r}v${height - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${-(length - r)}z`;
}

// A row per model or request, on one axis.
function rows(plot, chart) {
  const total = plot.clientWidth;
  const longest = Math.max(...chart.rows.map((row) => width(row.label)));
  const above = longest > total * 0.4;  // on a narrow page a long label takes a line of its own, over its marks
  const left = above ? 16 : Math.ceil(longest) + 18, right = 28, top = 6;
  const step = above ? ROW + 16 : ROW;
  const bottom = top + step * chart.rows.length;
  const xs = chart.rows.flatMap((row) => row.marks.flatMap((mark) => [mark.x, mark.from, mark.to].filter((value) => value !== undefined)));
  const low = chart.x.zero ? 0 : d3.min(xs), high = chart.x.to ?? d3.max(xs);
  const pad = chart.x.zero ? 0 : (high - low || 1) * 0.12;
  const x = chart.x.log ? d3.scaleLog().domain([low / 1.3, high * 1.3]).range([left, total - right])
    : d3.scaleLinear().domain([low - pad, chart.x.to ?? high + (chart.x.zero ? 0 : pad)]).range([left, total - right]);
  if (chart.x.to === undefined && !chart.x.log) x.nice();
  const svg = frame(plot, bottom + 42, chart.title);
  axisX(svg, x, chart.x.unit, top, bottom, chart.x.label, chart.x.log ? "ratios" : 5);
  chart.rows.forEach((row, n) => {
    const group = el("g");
    const mid = top + step * n + (above ? 16 + ROW / 2 : ROW / 2);
    group.append(el("rect", { x: 0, y: top + step * n, width: total, height: step, class: "band" }));
    group.append(above ? el("text", { x: left, y: top + step * n + 14, class: "row-label" }, fit(row.label, total - left - 8))
      : el("text", { x: left - 12, y: mid + 4, class: "row-label", "text-anchor": "end" }, row.label));
    // Points over the lines they sit on, and a dot over a ring it shares a place with, whatever the order a reader
    // meets them in.
    const layer = { ring: 1, dot: 2 };
    for (const mark of [...row.marks].sort((a, b) => (layer[a.mark] ?? 0) - (layer[b.mark] ?? 0))) {
      const tone = TONE[mark.tone];
      if (mark.mark === "bar") group.append(el("path", { d: barPath(x(x.domain()[0]), x(mark.x), mid - 6, 12), fill: tone }));
      // Segments that touch are parted by 2px of the surface, never by a line drawn round them.
      if (mark.mark === "segment" && x(mark.to) - x(mark.from) > 2) group.append(el("rect", { x: x(mark.from) + 1, y: mid - 7, width: x(mark.to) - x(mark.from) - 2, height: 14, fill: tone }));
      if (mark.mark === "link" || mark.mark === "range") group.append(el("line", { x1: x(mark.from), x2: x(mark.to), y1: mid, y2: mid, stroke: tone, "stroke-width": 2, "stroke-linecap": "round" }));
      // A tick marks a value on a line: a tall one is what the row is measured by, a short one what it is set against.
      if (mark.mark === "tick") group.append(el("line", { x1: x(mark.x), x2: x(mark.x), y1: mid - (mark.tall ? 9 : 5), y2: mid + (mark.tall ? 9 : 5), stroke: tone, "stroke-width": mark.tall ? 2.5 : 2, "stroke-linecap": "round" }));
      if (mark.mark === "dot") group.append(el("circle", { cx: x(mark.x), cy: mid, r: R, fill: tone, class: "ringed" }));
      if (mark.mark === "ring") group.append(el("circle", { cx: x(mark.x), cy: mid, r: R - 1, fill: "var(--bg)", stroke: tone, "stroke-width": 2 }));
    }
    const said = row.marks.filter((mark) => mark.name).map((mark) => [
      mark.value !== undefined ? shown(mark.value, mark.unit) : mark.x !== undefined ? shown(mark.x, chart.x.unit) : `${shown(mark.from, chart.x.unit)} to ${shown(mark.to, chart.x.unit)}`,
      mark.name, TONE[mark.tone]]);
    answers(group, `${row.label}: ${said.map(([value, name]) => `${name} ${value}`).join("; ")}`, () => tell(group, row.label, said));
    if (row.opens) opens(group, row.opens);
    svg.append(group);
  });
}

// A row that stands for a model opens its card on the page, by pointer or by Enter, and gives the card the focus.
function opens(group, model) {
  const open = () => {
    const card = [...document.querySelectorAll("details[data-model]")].find((one) => one.dataset.model === model);
    if (!card) return;
    hush();
    card.open = true;
    card.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    card.querySelector("summary").focus({ preventScroll: true });
  };
  group.classList.add("opens");
  group.addEventListener("click", open);
  group.addEventListener("keydown", (event) => { if (event.key === "Enter") open(); });
}

// One small plot per model, all on the same axes, so a slope in one can be set against a slope in another by eye.
function panels(plot, chart) {
  const total = plot.clientWidth;
  const columns = Math.max(1, Math.min(chart.panels.length, Math.floor(total / 250)));
  const size = Math.floor(total / columns), left = 52, right = 16, top = 44, tall = 168, down = 34;
  const points = chart.panels.flatMap((panel) => panel.points);
  const x = d3.scaleLinear().domain([0, d3.max(points, (point) => point.x) * 1.08]).range([left, size - right]);
  const y = d3.scaleLinear().domain([0, d3.max(points, (point) => point.y) * 1.08]).nice().range([top + tall, top]);
  const each = top + tall + down + 14;
  const svg = frame(plot, each * Math.ceil(chart.panels.length / columns), chart.title);
  chart.panels.forEach((panel, n) => {
    const group = el("g", { transform: `translate(${(n % columns) * size},${Math.floor(n / columns) * each})` });
    const clip = `clip-${chart.id}-${n}`;
    const clipped = el("clipPath", { id: clip });
    clipped.append(el("rect", { x: left, y: top, width: size - right - left, height: tall }));
    group.append(clipped, el("text", { x: left, y: 16, class: "panel-title" }, panel.label), el("text", { x: left, y: 32, class: "tick" }, panel.note));
    axisX(group, x, chart.x.unit, top, top + tall, null, 3);
    axisY(group, y, chart.y.unit, left, size - right);
    const across = x.domain()[1];
    const through = (line, tone, thick) => el("line", {
      x1: x(0), y1: y(line.intercept ?? 0), x2: x(across), y2: y((line.intercept ?? 0) + line.slope * across), stroke: TONE[tone],
      "stroke-width": thick, "stroke-linecap": "round", "clip-path": `url(#${clip})` });
    for (const rule of chart.rules) group.append(through(rule, rule.tone, 1.25));
    if (panel.line) group.append(through(panel.line, "ink", 2));
    for (const point of panel.points) {
      group.append(point.hollow ? el("circle", { cx: x(point.x), cy: y(point.y), r: R - 1, fill: "var(--bg)", stroke: TONE.ink, "stroke-width": 2 })
        : el("circle", { cx: x(point.x), cy: y(point.y), r: R, fill: TONE.ink, class: "ringed" }));
      // The target is larger than the dot: nobody lands on eight pixels.
      const hit = el("circle", { cx: x(point.x), cy: y(point.y), r: 13, fill: "transparent" });
      const said = [[shown(point.y, chart.y.unit), chart.y.label, TONE.ink], [shown(point.x, chart.x.unit), chart.x.label],
                    [shown(point.ratio, "ratio"), "The count over the estimate"]];
      answers(hit, `${panel.label}, ${point.label}: ${chart.y.label} ${shown(point.y, chart.y.unit)}, ${chart.x.label} ${shown(point.x, chart.x.unit)}`,
        () => tell(hit, `${panel.label} · ${point.label}`, said));
      group.append(hit);
    }
    svg.append(group);
  });
  const said = div("chart-rules");
  said.append(...chart.rules.map((rule) => key({ mark: "line", tone: rule.tone, label: rule.label })));
  plot.append(said);
}

// A cell per case and model. What is quiet is fine; what is filled is the point, and says its count or its measure.
function grid(plot, chart) {
  const total = plot.clientWidth;
  // The last column's slanted name leans past its cell, so the cells leave it room at the right edge. Where that
  // squeezes the cells, the rows' names give up width first, ending in an ellipsis and whole in the tooltip; where
  // even the narrowest cells leave too little, the plot scrolls rather than cut the name off.
  const leans = width(chart.columns[chart.columns.length - 1]) * 0.8 + 8;
  const room = (left) => Math.floor((total - left - 8 - leans) / (chart.columns.length - 0.5));
  const named = Math.min(Math.ceil(Math.max(...chart.rows.map((row) => width(row.label)))) + 18, Math.floor(total * 0.5));
  const left = room(named) >= 34 ? named : Math.min(named, Math.floor(total * 0.4));
  const size = Math.max(32, Math.min(96, room(left)));
  const head = Math.ceil(Math.max(...chart.columns.map((column) => width(column))) * 0.62) + 26, tall = 30;
  const wide = Math.ceil(Math.max(left + size * chart.columns.length + 8, left + size * (chart.columns.length - 0.5) + leans + 8));
  const svg = frame(plot, head + tall * chart.rows.length + 8, chart.title, Math.max(total, wide));
  chart.columns.forEach((column, n) => {
    const at = left + size * n + size / 2;
    svg.append(el("text", { x: at, y: head - 12, class: "row-label", transform: `rotate(-38 ${at} ${head - 12})` }, column));
  });
  chart.rows.forEach((row, r) => {
    const top = head + tall * r;
    svg.append(el("line", { x1: 0, x2: left + size * chart.columns.length, y1: top, y2: top, class: "grid" }));
    svg.append(el("text", { x: left - 12, y: top + tall / 2 + 4, class: "row-label", "text-anchor": "end" }, fit(row.label, left - 16)));
    row.cells.forEach((cell, c) => {
      if (!cell) return;
      // A cell counts repeats passed of those run, or holds a measure that is over what it is set against or not.
      const counted = cell.of !== undefined;
      const group = el("g"), x = left + size * c, quiet = counted ? cell.value === cell.of : !cell.over;
      const value = counted ? `${cell.value} of ${cell.of}` : shown(cell.value, chart.unit);
      // In the cell, a share is a whole percentage: its tenths are in the tooltip, and would not fit a narrow cell.
      const brief = counted ? `${cell.value}/${cell.of}` : chart.unit === "percent" ? `${Math.round(cell.value * 100)}%` : value;
      group.append(el("rect", { x: x + 1, y: top + 1, width: size - 2, height: tall - 2, class: quiet ? "band" : "cell-failed" }));
      group.append(quiet ? el("circle", { cx: x + size / 2, cy: top + tall / 2, r: 3, fill: TONE.quiet })
        : el("text", { x: x + size / 2, y: top + tall / 2 + 4, class: "cell-count", "text-anchor": "middle" }, brief));
      const name = counted ? "repeats passed" : chart.name;
      answers(group, `${chart.columns[c]}, ${row.label}: ${name} ${value}`, () => tell(group, `${chart.columns[c]} · ${row.label}`, [[value, name, quiet ? TONE.quiet : TONE.accent]]));
      if (chart.opens) opens(group, chart.opens[c]);
      svg.append(group);
    });
  });
}

// A labelled point per model on two axes. The label is the model: a point's colour says nothing.
function scatter(plot, chart) {
  const total = plot.clientWidth, left = 60, right = 28, top = 14, tall = Math.min(340, Math.max(240, total * 0.4));
  const xs = chart.points.map((point) => point.x), ys = chart.points.map((point) => point.y);
  const x = (chart.x.log ? d3.scaleLog().domain([d3.min(xs) / 1.6, d3.max(xs) * 1.6]) : d3.scaleLinear().domain([0, d3.max(xs) * 1.1])).range([left, total - right]);
  const spread = (d3.max(ys) - d3.min(ys)) || 0.1;
  const y = d3.scaleLinear().domain([d3.min(ys) - spread * 0.25, d3.max(ys) + spread * 0.25]).range([top + tall, top]);
  const svg = frame(plot, top + tall + 44, chart.title);
  axisX(svg, x, chart.x.unit, top, top + tall, chart.x.label, chart.x.log ? "ratios" : 5);
  axisY(svg, y, chart.y.unit, left, total - right);
  svg.append(el("text", { x: left, y: top - 2, class: "axis-label" }, chart.y.label));
  const taken = chart.points.map((point) => ({ left: x(point.x) - 8, right: x(point.x) + 8, top: y(point.y) - 8, bottom: y(point.y) + 8 }));
  const free = (box) => box.left > left && box.right < total - 4 && !taken.some((other) => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top);
  for (const point of chart.points) {
    const cx = x(point.x), cy = y(point.y), wide = width(point.label);
    // A label sits where it collides with nothing: right of its point, else left, above or below. One with no room
    // is left to the pointer and the table, since a label on top of another reads as neither.
    const places = [[cx + 10, cy + 4, "start", cx + 10], [cx - 10, cy + 4, "end", cx - 10 - wide], [cx, cy - 12, "middle", cx - wide / 2], [cx, cy + 22, "middle", cx - wide / 2]];
    const place = places.find(([, at, , from]) => free({ left: from, right: from + wide, top: at - 12, bottom: at + 3 }));
    if (place) {
      svg.append(el("text", { x: place[0], y: place[1], class: "row-label", "text-anchor": place[2] }, point.label));
      taken.push({ left: place[3], right: place[3] + wide, top: place[1] - 12, bottom: place[1] + 3 });
    }
    svg.append(el("circle", { cx, cy, r: R, fill: TONE.ink, class: "ringed" }));
    const hit = el("circle", { cx, cy, r: 14, fill: "transparent" });
    const said = [[shown(point.x, chart.x.unit), chart.x.label, TONE.ink], [shown(point.y, chart.y.unit), chart.y.label, TONE.ink]];
    answers(hit, `${point.label}: ${chart.x.label} ${shown(point.x, chart.x.unit)}, ${chart.y.label} ${shown(point.y, chart.y.unit)}`, () => tell(hit, point.label, said));
    if (point.opens) opens(hit, point.opens);
    svg.append(hit);
  }
}

// A line per model. The lines share one ink and lie close, which is the finding; the pointer picks out which is whose.
function lines(plot, chart) {
  const total = plot.clientWidth, left = 60, right = 28, top = 26, tall = 240;
  const all = chart.series.flatMap((series) => series.points);
  const last = d3.max(all, ([at]) => at);
  const x = d3.scaleLinear().domain([1, Math.max(last, 2)]).range([left, total - right]);
  const y = d3.scaleLinear().domain([0, d3.max([...all.map(([, value]) => value), ...chart.rules.map((rule) => rule.y)])]).nice().range([top + tall, top]);
  const svg = frame(plot, top + tall + 44, chart.title);
  axisY(svg, y, chart.y.unit, left, total - right);
  for (let at = 1; at <= last; at += 1) svg.append(el("text", { x: x(at), y: top + tall + 16, class: "tick", "text-anchor": "middle" }, String(at)));
  svg.append(el("text", { x: total - right, y: top + tall + 34, class: "axis-label", "text-anchor": "end" }, chart.x.label));
  svg.append(el("text", { x: left, y: top - 12, class: "axis-label" }, chart.y.label));
  for (const rule of chart.rules) {
    svg.append(el("line", { x1: left, x2: total - right, y1: y(rule.y), y2: y(rule.y), stroke: TONE[rule.tone], "stroke-width": 1.5 }));
    svg.append(el("text", { x: total - right, y: y(rule.y) - 7, class: "row-label", "text-anchor": "end" }, `${rule.label}, ${shown(rule.y, chart.y.unit)}`));
  }
  const path = d3.line().x(([at]) => x(at)).y(([, value]) => y(value));
  for (const series of chart.series) {
    svg.append(el("path", { d: path(series.points), fill: "none", stroke: TONE.ink, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", opacity: 0.55 }));
    const [at, value] = series.points[series.points.length - 1];
    svg.append(el("circle", { cx: x(at), cy: y(value), r: R - 1, fill: TONE.ink, class: "ringed" }));
  }
  // The pointer finds the inference, not a 2px line: one readout there for every model that reached it.
  for (let at = 1; at <= last; at += 1) {
    const here = chart.series.map((series) => [series.label, series.points.find(([n]) => n === at)?.[1]]).filter(([, value]) => value !== undefined);
    const near = (x(Math.min(at + 1, Math.max(last, 2))) - x(Math.max(at - 1, 1))) / 2 || total - left - right;
    const hit = el("rect", { x: x(at) - near / 2, y: top, width: near, height: tall, fill: "transparent" });
    const hair = el("line", { x1: x(at), x2: x(at), y1: top, y2: top + tall, class: "crosshair" });
    const said = here.map(([label, value]) => [shown(value, chart.y.unit), label, TONE.ink]);
    answers(hit, `${chart.x.label} ${at}: ${here.map(([label, value]) => `${label} ${shown(value, chart.y.unit)}`).join("; ")}`, () => tell(hair, `${chart.x.label} ${at}`, said));
    svg.append(hair, hit);
  }
}
