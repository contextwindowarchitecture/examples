// Everything the viewer shows is read from results/: index.json, each run's summary.json, and the job files the
// summary names. Nothing is computed that grade.py did not write, except counts over the summary's checks.

const cache = new Map();

export function json(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(path).then((response) => {
      if (!response.ok) throw new Error(`${path}: ${response.status}`);
      return response.json();
    }));
  }
  return cache.get(path);
}

export const index = () => json("../results/index.json");
export const summary = (run) => json(`../results/${run}/summary.json`);
export const file = (run, path) => json(`../results/${run}/${path}`);
export const href = (run, path) => `../results/${run}/${path}`;

// One assembly: its trace, its snapshot, and the snapshot's items by id.
export async function assembly(run, folder) {
  const [trace, snapshot] = await Promise.all([file(run, `${folder}/trace.json`), file(run, `${folder}/snapshot.json`)]);
  const items = new Map(snapshot.batches.flatMap((batch) => batch.items.map((item) => [item.id, item])));
  return { folder, trace, snapshot, items };
}

// Checks passed of those graded, over results, for the checks a test picks.
export function tally(found, test) {
  let passed = 0, graded = 0;
  for (const check of found) {
    if (check.passed === null || !test(check)) continue;
    graded += 1;
    if (check.passed) passed += 1;
  }
  return [passed, graded];
}
