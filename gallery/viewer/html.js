// Markup from data. Answers are model output, so every value is escaped unless it is already markup built here.

class Markup {
  constructor(text) { this.text = text; }
  toString() { return this.text; }
}

export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((value, i) => { out += render(value) + strings[i + 1]; });
  return new Markup(out);
}

function render(value) {
  if (value instanceof Markup) return value.text;
  if (Array.isArray(value)) return value.map(render).join("");
  if (value === null || value === undefined || value === false) return "";
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export const number = (n) => (n ?? 0).toLocaleString("en-US");
export const dollars = (n) => `$${(n ?? 0).toFixed(2)}`;
export const seconds = (ms) => (ms === null || ms === undefined ? "—" : `${(ms / 1000).toFixed(1)} s`);
// Where a run opens: what CWA decided for it, the run in one page.
export const opens = (run) => `#/${run}/numbers/decisions`;
export const plural = (n, noun, many = `${noun}s`) => `${number(n)} ${n === 1 ? noun : many}`;

// A count of checks passed of those graded, in the foreground, or the accent when one failed.
export function count(name, [passed, graded]) {
  return html`<span class="${passed < graded ? "fail" : "pass"}">${name} ${passed}/${graded}</span>`;
}
