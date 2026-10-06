// See the Numbers: a run's numbers.json, a page per family and one table of everything. Nothing is computed here.
// metrics.py wrote every value with its label, its unit and the formula behind it, so one renderer draws every page:
// a number is one value per model, a table is a breakdown with columns of its own.

import { html, number, opens } from "./html.js";

const short = (model) => model.split("/").pop();
const decimals = (value, places) => value.toLocaleString("en-US", { minimumFractionDigits: places, maximumFractionDigits: places });

// A value as its unit reads. A share is held as a fraction; dollars keep two figures below a cent, since a check can
// cost a hundredth of one.
export function shown(value, unit) {
  if (value === null || value === undefined) return "—";
  if (typeof value !== "number") return value;
  switch (unit) {
    case "usd": return value === 0 ? "$0" : `$${Math.abs(value) >= 1 ? decimals(value, 2) : Math.abs(value) >= 0.01 ? decimals(value, 3) : Number(value.toPrecision(2))}`;
    case "percent": { const percent = value * 100; return `${decimals(percent, Math.abs(percent - Math.round(percent)) < 1e-9 ? 0 : 1)}%`; }
    case "ratio": return `${decimals(value, 2)}×`;
    case "seconds": return `${decimals(value, Math.abs(value) < 10 ? 2 : 1)} s`;
    case "ms": return `${decimals(value, 1)} ms`;
    case "per_second": return `${decimals(value, 1)} /s`;
    default: return Number.isInteger(value) ? number(value) : decimals(value, Math.abs(value) < 10 ? 2 : Math.abs(value) < 100 ? 1 : 0);
  }
}

const numeric = (unit) => unit !== "text" && unit !== undefined;

// Text from meaning.py names the requirements it speaks to, as R-16: each becomes a link to it in the specification.
const SPEC = "https://contextwindowarchitecture.io/spec.html";
function cited(text) {
  return html`${String(text ?? "").split(/(R-\d+)/).map((part) => (/^R-\d+$/.test(part)
    ? html`<a href="${SPEC}#${part}" target="_blank" rel="noopener">${part}</a>` : part))}`;
}

// What the page's numbers have to do with CWA, beside what this run's values say.
function says(page) {
  return html`<div class="hair wide" style="margin-bottom: 40px;" data-tour="numbers-says">
    <div class="cell"><div class="label">In this run</div>
      ${page.reading.length ? html`<ul class="reading">${page.reading.map((line) => html`<li>${cited(line)}</li>`)}</ul>`
        : html`<div class="card-copy">This run has too little on this page to read anything from.</div>`}</div>
    <div class="cell"><div class="label">What this says about CWA</div><div class="card-copy says">${cited(page.says)}</div></div>
  </div>`;
}
// A table's columns: what a row is about, then a column of figures for each number or model. A table too wide for the
// page scrolls inside its panel.
const WIDE = 108;
const grid = (columns, first = 220) => `grid-template-columns: minmax(${first}px, 1.6fr) repeat(${columns}, minmax(96px, 1fr)); min-width: ${first + WIDE * columns}px;`;

// What a value rests on: the range it could have, and how many observations it was read from.
function rests(one, model) {
  const range = one.ranges?.[model];
  const n = one.n?.[model];
  return html`${range ? html`<span class="sub">${shown(range[0], one.unit)} to ${shown(range[1], one.unit)}</span>` : ""}${n !== undefined && one.values[model] !== null ? html`<span class="sub">of ${number(n)}</span>` : ""}`;
}

// The pills that lead from one page of numbers to the others.
function pages(run, numbers, here) {
  return html`<div class="pills" style="margin-bottom: 28px;">${numbers.pages.map((page) => html`
    <a class="pill" href="#/${run}/numbers/${page.id}"${page.id === here ? html` aria-current="page"` : ""}>${page.title}</a>`)}
    <a class="pill" href="#/${run}/numbers"${here ? "" : html` aria-current="page"`}>All numbers</a></div>`;
}

// A page's numbers: a row per model, a column per number. A column's heading sorts the models by it.
function byModel(numbers, page, sort) {
  const models = [...numbers.models];
  const sorted = page.numbers.find((one) => one.id === sort.by);
  if (sorted) {
    const value = (model) => sorted.values[model];
    const order = (a, b) => (typeof a === "number" ? a - b : String(a).localeCompare(String(b)));
    models.sort((a, b) => (value(a) === null) - (value(b) === null) || (sort.down ? order(value(b), value(a)) : order(value(a), value(b))));
  }
  return html`<div class="panel scroll"><div>
    <div class="row headrow" style="${grid(page.numbers.length)}"><span>Model</span>${page.numbers.map((one) => html`
      <button type="button" class="sort num" data-action="sort" data-value="${one.id}" aria-pressed="${one.id === sort.by}">${one.label}${one.id === sort.by ? (sort.down ? " ↓" : " ↑") : ""}</button>`)}</div>
    ${models.map((model) => html`<div class="row" style="${grid(page.numbers.length)}"><span class="fg">${model}</span>${page.numbers.map((one) => html`
      <span class="num fg">${shown(one.values[model], one.unit)}${rests(one, model)}</span>`)}</div>`)}
  </div></div>`;
}

// What each number says about CWA, and the formula behind it, said once under the table that holds them.
function how(page) {
  return html`<div class="label" style="margin: 36px 0 10px;">What each number says, and how it is computed</div>
    <div class="panel">${page.numbers.map((one) => html`<div class="row how"><span class="fg">${one.label}</span>
      <span><span class="means">${cited(one.means)}</span><span class="muted">${cited(one.how)}</span></span></div>`)}</div>`;
}

// A breakdown: its own columns, each with a unit. A column named for a model carries that model's values.
function breakdown(table) {
  const [first, ...rest] = table.columns;
  const texts = rest.filter((column) => !numeric(column.unit)).length;
  const columns = `grid-template-columns: minmax(240px, 1.6fr) ${rest.map((column) => (numeric(column.unit) ? "minmax(104px, 1fr)" : "minmax(180px, 1.4fr)")).join(" ")}; min-width: ${240 + 118 * (rest.length - texts) + 190 * texts}px;`;
  const cell = (row, column) => html`<span class="${numeric(column.unit) ? "num" : ""}${column === first ? " fg" : ""}">${shown(row[column.id], column.unit)}</span>`;
  return html`<h2 class="case" style="margin-top: 56px;">${table.title}</h2><p class="body">${table.how}</p>
    ${table.rows.length ? html`<div class="panel scroll"><div>
      <div class="row headrow" style="${columns}">${table.columns.map((column) => html`<span class="${numeric(column.unit) ? "num" : ""}">${column.label}</span>`)}</div>
      ${table.rows.map((row) => html`<div class="row" style="${columns}">${table.columns.map((column) => cell(row, column))}</div>`)}
    </div></div>` : html`<p class="body mono">Nothing to list in this run.</p>`}`;
}

// A chart of the page's numbers. charts.js draws it once the page is in the document; every value it shows is in a
// table below it, so the chart adds a way to see them and takes nothing away when it cannot be drawn.
function figure(chart) {
  return html`<figure class="chart" data-chart="${chart.id}">
    <figcaption><h2 class="case">${chart.title}</h2><p class="body">${cited(chart.how)}</p></figcaption>
    <div class="chart-legend"></div>
    <div class="chart-plot"></div>
    <p class="chart-note">${chart.values}</p>
  </figure>`;
}

// A figure about the whole run, not one model.
function totals(page) {
  if (!page.totals?.length) return "";
  return html`<div class="hair four" style="margin-bottom: 40px;">${page.totals.map((total) => html`<div class="cell">
    <div class="label">${total.label}</div><div class="big">${shown(total.value, total.unit)}${total.of !== undefined ? html`<span class="of"> / ${number(total.of)}</span>` : ""}</div>
    <div class="card-copy"><span class="means">${cited(total.means)}</span>${cited(total.how)}</div></div>`)}</div>`;
}

export function page(run, numbers, id, sort, file, lead = "") {
  const one = numbers.pages.find((candidate) => candidate.id === id);
  if (!one) return html`<section class="wrap head"><h1>No such page of numbers</h1>${pages(run, numbers, null)}</section>`;
  const rest = one.tables.filter((table) => !one.cards?.tables.includes(table.id));  // what the cards hold is not set out twice
  return html`
    <section class="wrap head">
      <div class="crumb"><a href="${opens(run)}">Run ${run}</a> / <a href="#/${run}/numbers">See the Numbers</a> / ${one.title}</div>
      <div class="kicker">Numbers · ${one.title}</div>
      <h1>${one.title}</h1>${lead}<p class="lede">${one.lede}</p>
      ${pages(run, numbers, id)}
    </section>
    <section class="band surface"><div class="wrap">
      ${says(one)}
      ${totals(one)}
    </div></section>
    ${one.charts?.length ? html`<section class="band"><div class="wrap charts" data-tour="numbers-chart">${one.charts.map(figure)}</div></section>` : ""}
    <section class="band surface"><div class="wrap">
      <div class="toolbar"><span class="label">${one.cards ? ordered(one) : "One row per model · a heading sorts by its column"}</span><span class="changed" aria-hidden="true"></span>
        <a class="mono" style="font-size: 12px;" href="${file}" target="_blank" rel="noopener">numbers.json →</a></div>
      <div data-tour="numbers-table">${one.cards ? cards(numbers, one) : byModel(numbers, one, sort)}</div>
      ${how(one)}
    </div></section>
    ${rest.length ? html`<section class="band"><div class="wrap" style="padding-top: 0;">${rest.map(breakdown)}</div></section>` : ""}`;
}

// What a page's cards are ordered by, which is the order its chart of models draws them in, where it has one.
function ordered(page) {
  const by = page.numbers.find((one) => one.id === page.cards.order);
  return `A card per model · ${by.label}, ${page.cards.down ? "highest" : "lowest"} first · open one for every number it has`;
}

// A page's models as cards, in the order its chart draws them. Closed, a card holds the few numbers most readers
// compare, set in columns so they still read down; open, every number by the question it answers, and the model's
// share of the page's tables, which nobody reads across fourteen models. Comparing is the chart's job.
function cards(numbers, page) {
  const spec = page.cards;
  const by = Object.fromEntries(page.numbers.map((one) => [one.id, one]));
  const value = (model) => by[spec.order].values[model];
  const models = [...numbers.models].sort((a, b) => (value(a) == null) - (value(b) == null) || (spec.down ? value(b) - value(a) : value(a) - value(b)));
  const find = (id) => page.tables.find((table) => table.id === id);
  const merged = new Set((spec.merge ?? []).flatMap((group) => Object.keys(group.columns)));
  const tables = spec.tables.filter((id) => !merged.has(id)).map(find).filter(Boolean);
  const columns = `--figures: ${spec.head.length};`;
  return html`<div class="mcards">
    <div class="mcard-heads" style="${columns}" aria-hidden="true"><span>Model</span>${spec.head.map((id) => html`<span class="num">${by[id].label}</span>`)}</div>
    ${models.map((model) => html`<details class="mcard" data-model="${model}">
      <summary style="${columns}"><span class="fg">${model}</span>${spec.head.map((id) => html`<span class="num fg"><span class="mlabel">${by[id].label}</span>${shown(by[id].values[model], by[id].unit)}</span>`)}</summary>
      <div class="mcard-body">
        ${spec.groups.map((group) => html`<div class="mgroup"><div class="label">${group.title}</div>${group.numbers.map((id) => html`
          <div class="mrow" title="${by[id].means}"><span>${by[id].label}</span><span class="num fg">${shown(by[id].values[model], by[id].unit)}${rests(by[id], model)}</span></div>`)}</div>`)}
        ${tables.map((table) => slice(table, model))}
        ${(spec.merge ?? []).map((group) => together(group, find, model))}
      </div>
    </details>`)}
  </div>`;
}

// A model's column of several tables about the same rows, as one list: a row each, a column a table.
function together(group, find, model) {
  const tables = Object.entries(group.columns).map(([id, label]) => [find(id), label]).filter(([table]) => table);
  if (!tables.length) return "";
  const [[first]] = tables, key = first.columns[0];
  const of = (table) => Object.fromEntries(table.rows.map((row) => [row[key.id], row]));
  const units = tables.map(([table]) => [of(table), table.columns.find((column) => column.id === model)]);
  if (units.some(([, column]) => !column)) return "";
  const template = `grid-template-columns: minmax(120px, 2fr) ${tables.map(() => "minmax(64px, 1fr)").join(" ")}; min-width: ${120 + 76 * tables.length}px;`;
  return html`<div class="mslice wide"><div class="label">${group.title}</div>
    <div class="mrow head" style="${template}"><span>${key.label}</span>${tables.map(([table, label]) => html`<span class="num" title="${table.how}">${label}</span>`)}</div>
    ${first.rows.map((row) => html`<div class="mrow" style="${template}"><span>${shown(row[key.id], key.unit)}</span>${units.map(([rows, column]) => html`
      <span class="num fg">${shown(rows[row[key.id]]?.[model], column.unit)}</span>`)}</div>`)}
  </div>`;
}

// A model's share of a table: its rows, where a column names the model, or its column, where each model has one.
function slice(table, model) {
  const long = table.columns.some((column) => column.id === "model");
  const columns = long ? table.columns.filter((column) => column.id !== "model") : [table.columns[0], table.columns.find((column) => column.id === model)];
  const rows = long ? table.rows.filter((row) => row.model === model) : table.rows;
  if (!rows.length || !columns.at(-1)) return "";
  // A model's one row is a list of what each column says of it: a row of nine columns would not fit a card.
  if (long && rows.length === 1) return html`<div class="mslice" title="${table.how}"><div class="label">${table.title}</div>
    ${columns.map((column) => html`<div class="mrow"><span>${column.label}</span><span class="${numeric(column.unit) ? "num fg" : "fg"}">${shown(rows[0][column.id], column.unit)}</span></div>`)}
  </div>`;
  // Every row as wide as the columns need, so a slice too wide for a phone scrolls inside its card with its columns aligned.
  const template = `grid-template-columns: minmax(110px, 1.4fr) ${columns.slice(1).map(() => "minmax(56px, 1fr)").join(" ")}; min-width: ${110 + 68 * (columns.length - 1)}px;`;
  const cell = (row, column) => html`<span class="${numeric(column.unit) ? "num fg" : ""}">${shown(row[column.id], column.unit)}</span>`;
  return html`<div class="mslice${long ? " wide" : ""}" title="${table.how}"><div class="label">${table.title}</div>
    ${long ? html`<div class="mrow head" style="${template}">${columns.map((column) => html`<span class="${numeric(column.unit) ? "num" : ""}">${column.label}</span>`)}</div>` : ""}
    ${rows.map((row) => html`<div class="mrow" style="${template}">${columns.map((column) => cell(row, column))}</div>`)}
  </div>`;
}

// Every number of the run: a row each, grouped by page, a column per model.
export function all(run, numbers, file) {
  const models = numbers.models;
  const count = numbers.pages.reduce((sum, one) => sum + one.numbers.length, 0);
  return html`
    <section class="wrap head">
      <div class="crumb"><a href="${opens(run)}">Run ${run}</a> / See the Numbers</div>
      <div class="kicker">Numbers · ${count} of them, for ${models.length === 1 ? "1 model" : `${models.length} models`}</div>
      <h1>All numbers</h1>
      <p class="lede">Everything this run measured, one row a number and one column a model. There is no single score: a model that is cheap may be slow, and one that passes every check may change its answer between repeats. Each group's page says how its numbers are computed and breaks them down.</p>
      ${pages(run, numbers, null)}
      <div class="meta"><span>graded <b>${numbers.graded}</b></span><span><a href="${file}" target="_blank" rel="noopener">numbers.json →</a></span></div>
    </section>
    <section class="band surface"><div class="wrap">
      <div class="panel scroll" data-tour="numbers-table"><div>
        <div class="row headrow" style="${grid(models.length, 280)}"><span>Number</span>${models.map((model) => html`<span class="num" title="${model}">${short(model)}</span>`)}</div>
        ${numbers.pages.map((one) => html`
          <a class="row group" href="#/${run}/numbers/${one.id}" style="${grid(models.length, 280)}"><span>${one.title} →</span></a>
          ${one.numbers.map((entry) => html`<div class="row" style="${grid(models.length, 280)}"><span class="fg" title="${entry.how}">${entry.label}</span>${models.map((model) => html`
            <span class="num fg">${shown(entry.values[model], entry.unit)}</span>`)}</div>`)}`)}
      </div></div>
    </div></section>`;
}

// A run graded before numbers.json existed has none: grading it again reads the same files and writes it.
export function missing(run) {
  return html`<section class="wrap head"><div class="kicker">Numbers</div><h1>No numbers yet</h1>
    <p class="lede">This run was graded before its numbers were computed. Grade it again from its files, with no model: uv run grade.py results/${run}</p></section>`;
}
