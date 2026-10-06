# AGENTS.md

Instructions for coding agents and contributors working in `examples`, the runnable example applications for the Context Window Architecture (CWA) draft specification. Each example is code an adopter could copy. It shows an application building its context through CWA, not a demonstration of CWA's internals. That is [assembler-demo](https://github.com/contextwindowarchitecture/assembler-demo)'s job.

## Layout

Each example is a numbered folder (`01-docs-qa/`, `02-...`) and its own `uv` project, with its own README, tests and committed scenarios. Later examples build on earlier ones: an example's README says which one it extends and what the diff adds.

`bench/` is the benchmark harness, not an example: its own `uv` project, standard library only, that runs the examples' command lines against models on OpenRouter and changes nothing they send. Its README is its design and its manual, and `expectations.toml` says what each 01–04 scenario must show.

## Commands

Run these inside an example's folder:

```sh
uv sync                        # install, with the assembler pinned to its draft-release tag
uv run pytest                  # the example's suite; must pass before every commit
uv run scenarios.py --check    # fail when a committed scenario differs from what the code builds now
uv run scenarios.py --write    # rebuild the committed scenarios after an intended change, then review the diff
```

Inside `bench/`:

```sh
uv run pytest                                # the harness's suite: no model, no network; must pass before every commit
uv run --env-file .env plan.py               # what a run would do and cost; sends nothing
uv run --env-file .env run.py                # a run, into results/; spends money, so only when asked
uv run grade.py results/<run-id>             # grade a run again from its files
uv run serve.py                              # the viewer, at http://127.0.0.1:8765/
```

From the repository root:

```sh
python3 -m unittest discover -s scripts                    # the pin check's own tests
python3 scripts/assembler_pin.py                           # every example pins the same assembler tag and commit
python3 scripts/assembler_pin.py --release <tag> --remote  # before tagging: they pin <tag>, as it points now
```

## Rules

- **Depend on a released assembler, never a sibling checkout.** An example pins `contextwindowarchitecture-assembler` to a tag of [assembler-python](https://github.com/contextwindowarchitecture/assembler-python) through `[tool.uv.sources]`. A reader runs `uv sync` and has everything. Every example pins the same tag and locks the same commit; `scripts/assembler_pin.py` fails CI otherwise. Move the pin in every example at once, in its own `build:` commit, with the regenerated scenarios and their diff explained in the body.
- **Never assemble in example code.** Admission, fitting and rendering belong to the assembler. An example produces items, freezes a snapshot, calls `assemble()` and sends what comes back. If an example needs behavior the assembler lacks, the spec changes first, in the [specification repository](https://github.com/contextwindowarchitecture/contextwindowarchitecture).
- **Never patch an assembler's output.** The payload goes to the model as it comes back. A refused assembly has no payload and never reaches a model.
- **Committed scenarios are reviewed expectations.** `scenarios.py --write` regenerates them. Read the diff of every `snapshot.json`, `trace.json` and `payload.json` it changes before committing, and say in the commit body why the context changed.
- **Readable first.** Flat files, a short focal function per file, and comments that explain a CWA decision where it happens. A reader should be able to diff `before.py` and `after.py` in their head.
- **No credentials in the repository.** Providers read their keys from the environment or `.env` (gitignored). The suite never calls a model. bench reads its OpenRouter key from `bench/.env`, hands the examples a dummy one, and never writes the real one.
- **A benchmark run spends money.** Run `bench/run.py` only when asked, after `plan.py` has shown what it would cost. A change to `expectations.toml` or the checks after reading a run's results tunes them to that run: say so in the commit body.

## Test-driven development

Behavior changes follow red → green → refactor. Write the smallest failing test, watch it fail for the reason you expect, make it pass, then clean up with the suite green. Before claiming a test protects something, break the code on purpose and watch the test fail, then restore it by copying the file back, never with `git checkout` or `git restore`.

## Commits

- **Commit unasked at each green step.** One behavior, or one refactor, per commit. Every commit passes the suite of every example it touches.
- **Conventional Commits 1.0.0, signed off.** `git commit -s` with `type(scope): summary` in the imperative mood, lower case, no trailing period, at most 72 characters. Types: `feat`, `fix`, `test`, `refactor`, `docs`, `build`, `ci`, `chore`. Scopes: the example's folder name without its number (`docs-qa`), `bench` for the benchmark harness in `bench/`, or `repo` and `ci` for shared files. Don't add `Co-Authored-By` trailers.
- **Never push, and never tag.** The remote is `origin` (https://github.com/contextwindowarchitecture/examples). The maintainer publishes commits and pushes tags. A tag starts `release.yml`, which releases only when every example pins assembler-python at that same tag (the README's Releases section).
- **The changelog is generated** from the commit history by git-cliff (`cliff.toml`). Never edit `CHANGELOG.md` by hand.
- Stage paths explicitly. Never commit `.venv/`, `runs/`, `.env`, `bench/results/` or anything under `.claude/`.

## Documentation

A commit that changes behavior also updates the README that describes it. Use Mermaid diagrams wherever a flow reads faster as a picture, and check that each one parses with Mermaid 12 before committing.
