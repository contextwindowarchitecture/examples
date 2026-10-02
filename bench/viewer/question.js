// A case's question as a reader sees it. Most are one line; 03's pasted-log cases paste 45 lines of delivery log
// into theirs, and a question that long would stretch every page and row it heads.

import { html, number, plural } from "./html.js";

// A block the application wrapped in a tag when it put pasted text into the question: <pasted_log>…</pasted_log>.
const BLOCK = /<([a-z_]+)>\n?([\s\S]*?)\n?<\/\1>/g;

// A question is long when it holds a line break or runs past 200 characters.
export const long = (text) => text.includes("\n") || text.length > 200;

const lines = (text) => text.split("\n").length;
const named = (tag) => tag.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

// A long question's first sentence, then what follows it in order: prose, and each block pasted into it.
// Prose that is itself long is shown as a block too.
export function parts(question) {
  if (!long(question)) return { title: question, rest: [] };
  const title = /^[^\n]*?[.?!](?=\s|$)/.exec(question)?.[0] ?? question.split("\n")[0];
  // A first sentence that is itself long heads the page cut short, and the whole question goes under it.
  if (long(title)) return { title: `${title.slice(0, 120).replace(/\s+\S*$/, "")}…`, rest: [{ label: "The whole question", text: question }] };
  const remainder = question.slice(title.length);
  const rest = [];
  const prose = (text) => {
    const trimmed = text.trim();
    if (trimmed) rest.push(long(trimmed) ? { label: "The rest of the question", text: trimmed } : { text: trimmed });
  };
  let at = 0;
  for (const match of remainder.matchAll(BLOCK)) {
    prose(remainder.slice(at, match.index));
    rest.push({ label: named(match[1]), text: match[2] });
    at = match.index + match[0].length;
  }
  prose(remainder.slice(at));
  return { title, rest };
}

// The question in a list's cell: a long one shows about four lines and scrolls, and says how much there is.
export function cell(question) {
  if (!long(question)) return html`<span class="question">${question}</span>`;
  return html`<span class="clamped"><span class="question">${question}</span>
    <span class="label">${plural(lines(question), "line")} · ${number(question.length)} characters · scroll for the rest</span></span>`;
}

// The question heading a page: its first sentence is the heading, and what follows it goes under the heading, each
// pasted block in a panel of its own that scrolls. When prose follows a block, it is what the user asked of it.
export function asked(question, { small = false } = {}) {
  const { title, rest } = parts(question);
  const more = rest.map((part, n) => part.label
    ? html`<div class="panel pasted"><div class="panel-head"><span>${part.label} · ${plural(lines(part.text), "line")}</span><span>${number(part.text.length)} characters</span></div>
        <pre class="raw" tabindex="0" aria-label="${part.label}">${part.text}</pre></div>`
    : html`<p class="${n === rest.length - 1 && rest.some((other) => other.label) ? "ask" : ""}">${part.text}</p>`);
  return { title, more: rest.length ? html`<div class="asked${small ? " small" : ""}">${more}</div>` : "" };
}
