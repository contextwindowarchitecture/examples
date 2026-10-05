// See the numbers: a run's numbers.json, a page per family and one table of everything. Nothing is computed here.
// metrics.py wrote every value with its label, its unit and the formula behind it, so one renderer draws every page:
// a number is one value per model, a table is a breakdown with columns of its own.

import { html, number } from "./html.js";

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

// The formula behind each number, said once under the table that holds them.
function how(page) {
  return html`<div class="label" style="margin: 36px 0 10px;">How each is computed</div>
    <div class="panel">${page.numbers.map((one) => html`<div class="row how"><span class="fg">${one.label}</span><span class="muted">${one.how}</span></div>`)}</div>`;
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

// A figure about the whole run, not one model.
function totals(page) {
  if (!page.totals?.length) return "";
  return html`<div class="hair four" style="margin-bottom: 40px;">${page.totals.map((total) => html`<div class="cell">
    <div class="label">${total.label}</div><div class="big">${shown(total.value, total.unit)}${total.of !== undefined ? html`<span class="of"> / ${number(total.of)}</span>` : ""}</div>
    <div class="card-copy">${total.how}</div></div>`)}</div>`;
}

export function page(run, numbers, id, sort, file) {
  const one = numbers.pages.find((candidate) => candidate.id === id);
  if (!one) return html`<section class="wrap head"><h1>No such page of numbers</h1>${pages(run, numbers, null)}</section>`;
  return html`
    <section class="wrap head">
      <div class="crumb"><a href="#/${run}">Run ${run}</a> / <a href="#/${run}/numbers">See the numbers</a> / ${one.title}</div>
      <div class="kicker">Numbers · ${one.title}</div>
      <h1>${one.title}</h1><p class="lede">${one.lede}</p>
      ${pages(run, numbers, id)}
    </section>
    <section class="band surface"><div class="wrap">
      ${totals(one)}
      <div class="toolbar"><span class="label">One row per model · a heading sorts by its column</span><span class="changed" aria-hidden="true"></span>
        <a class="mono" style="font-size: 12px;" href="${file}" target="_blank" rel="noopener">numbers.json →</a></div>
      <div data-tour="numbers-table">${byModel(numbers, one, sort)}</div>
      ${how(one)}
    </div></section>
    <section class="band"><div class="wrap" style="padding-top: 0;">${one.tables.map(breakdown)}</div></section>`;
}

// Every number of the run: a row each, grouped by page, a column per model.
export function all(run, numbers, file) {
  const models = numbers.models;
  const count = numbers.pages.reduce((sum, one) => sum + one.numbers.length, 0);
  return html`
    <section class="wrap head">
      <div class="crumb"><a href="#/${run}">Run ${run}</a> / See the numbers</div>
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
