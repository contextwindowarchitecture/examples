"""The assembler pin check, on examples written for each case, and on this repository's own examples.

    python3 -m unittest discover -s scripts
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import assembler_pin

SHA = "49b321e4f525d8c879934f28e1c316bb8fc33f6f"
OTHER = "0" * 40


def write(root: Path, name: str, *, tag: str = "draft-release", locked_tag: str | None = None,
          commit: str = SHA, source: str | None = None) -> None:
    folder = root / name
    folder.mkdir()
    pin = source or f'{{ git = "{assembler_pin.REPO}", tag = "{tag}" }}'
    (folder / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\n\n[tool.uv.sources]\ncontextwindowarchitecture-assembler = {pin}\n')
    (folder / "uv.lock").write_text(
        '[[package]]\nname = "contextwindowarchitecture-assembler"\nversion = "0.0.1"\n'
        f'source = {{ git = "{assembler_pin.REPO}?tag={locked_tag or tag}#{commit}" }}\n')


class Check(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def problems(self, **options: object) -> list[str]:
        return assembler_pin.check(assembler_pin.pins(self.root), **options)  # type: ignore[arg-type]

    def test_examples_that_agree_pass(self) -> None:
        write(self.root, "01-a")
        write(self.root, "02-b")
        self.assertEqual(self.problems(), [])

    def test_only_numbered_folders_are_examples(self) -> None:
        write(self.root, "01-a")
        bench = self.root / "bench"  # a project of the repository's own, such as the benchmark harness
        bench.mkdir()
        (bench / "pyproject.toml").write_text('[project]\nname = "bench"\n')
        (bench / "uv.lock").write_text('[[package]]\nname = "pytest"\nversion = "8.0.0"\n')
        self.assertEqual(self.problems(), [])

    def test_examples_on_different_tags_fail(self) -> None:
        write(self.root, "01-a")
        write(self.root, "02-b", tag="v0.1.0")
        self.assertIn("the examples pin different assembler tags", " ".join(self.problems()))

    def test_a_lock_for_another_tag_fails(self) -> None:
        write(self.root, "01-a", locked_tag="v0.1.0")
        self.assertIn("uv.lock resolves tag v0.1.0", " ".join(self.problems()))

    def test_locks_on_different_commits_fail(self) -> None:
        write(self.root, "01-a")
        write(self.root, "02-b", commit=OTHER)
        self.assertIn("lock different assembler commits", " ".join(self.problems()))

    def test_a_branch_or_path_pin_fails(self) -> None:
        write(self.root, "01-a", source=f'{{ git = "{assembler_pin.REPO}", branch = "main" }}')
        write(self.root, "02-b", source='{ path = "../../assembler-python" }')
        problems = " ".join(self.problems())
        self.assertIn("01-a pins the assembler without a tag", problems)
        self.assertIn("02-b pins the assembler without a tag", problems)

    def test_a_release_must_pin_its_own_tag(self) -> None:
        write(self.root, "01-a")
        self.assertEqual(self.problems(release="draft-release"), [])
        self.assertIn("pin draft-release, not the release tag v0.1.0", " ".join(self.problems(release="v0.1.0")))

    def test_a_moved_tag_fails_until_the_locks_follow_it(self) -> None:
        write(self.root, "01-a")
        self.assertEqual(self.problems(remote=lambda tag: SHA), [])
        problems = " ".join(self.problems(remote=lambda tag: OTHER))
        self.assertIn(f"now points to {OTHER[:7]}", problems)
        self.assertIn("uv lock --upgrade-package contextwindowarchitecture-assembler", problems)
        self.assertIn("does not exist", " ".join(self.problems(remote=lambda tag: None)))

    def test_no_examples_fails(self) -> None:
        self.assertEqual(self.problems(), ["no examples found"])

    def test_the_notes_name_the_tag_and_commit(self) -> None:
        write(self.root, "01-a")
        notes = assembler_pin.notes(assembler_pin.pins(self.root))
        self.assertIn(f"[assembler-python `draft-release`]({assembler_pin.REPO}/releases/tag/draft-release)", notes)
        self.assertIn(f"[`{SHA[:7]}`]({assembler_pin.REPO}/commit/{SHA})", notes)


class ThisRepository(unittest.TestCase):
    def test_every_example_here_pins_the_same_assembler(self) -> None:
        found = assembler_pin.pins(assembler_pin.ROOT)
        self.assertGreaterEqual(len(found), 5)
        self.assertEqual(assembler_pin.check(found), [])


if __name__ == "__main__":
    unittest.main()
