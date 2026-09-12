"""Measure the test count and the mutation table, and write them into the docs.

Never type a test count into a README. A README claiming a number nobody checked
is the first thing a reviewer catches, and a stale one is worse than none.

    python scripts/measure.py            # report the measured numbers
    python scripts/measure.py --write    # substitute them into README.md

The README carries paired markers and everything between them is generated:

    <!-- measured:tests -->    ... <!-- /measured:tests -->
    <!-- measured:mutations --> ... <!-- /measured:mutations -->

Nothing is measured, and nothing is written, while the house style check fails.
"""

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# The nine characters the house style bans. Built from code points and never
# written literally: a checker that contains the characters it bans reports
# itself on every clean run, and a check that always fails is a check people
# learn to skip.
BANNED = {
    chr(0x2014): "U+2014 em dash",
    chr(0x2013): "U+2013 en dash",
    chr(0x00B7): "U+00B7 middle dot",
    chr(0x2022): "U+2022 bullet",
    chr(0x2026): "U+2026 ellipsis",
    chr(0x2010): "U+2010 hyphen",
    chr(0x2012): "U+2012 figure dash",
    chr(0x2015): "U+2015 horizontal bar",
    chr(0x2212): "U+2212 minus sign",
}
TEXT_SUFFIXES = {".md", ".py", ".sh", ".svg", ".yaml", ".yml", ".txt", ".ini",
                 ".json", ".toml", ".cfg"}
TEXT_NAMES = {".gitignore", ".gitattributes", ".env.example", "LICENSE"}
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "artifacts", ".venv", "venv"}


def check_style(root=ROOT):
    """House style: a spaced hyphen is the only connector, three full stops
    the only ellipsis.

    Scans every text file in the repository for the nine banned characters and
    refuses to go on while any exist. Enforced here rather than remembered,
    because remembering has failed on every project in this line that relied
    on it. Returns the number of characters checked.
    """
    root = pathlib.Path(root)
    hits = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        if p.suffix not in TEXT_SUFFIXES and p.name not in TEXT_NAMES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.split("\n"), 1):
            for ch, name in BANNED.items():
                if ch in line:
                    hits.append("%s:%d  %s" % (p.relative_to(root).as_posix(), i, name))
    if hits:
        raise SystemExit(
            "house style: banned characters found, refusing to measure or write "
            "anything. Use a spaced hyphen as the connector and three full stops "
            "for an ellipsis:\n  " + "\n  ".join(hits)
        )
    return len(BANNED)


def measure_tests():
    """Run the suite and return (passed, skipped) as measured, not as claimed."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    m = re.search(r"(\d+) passed(?:, (\d+) skipped)?", out)
    if not m:
        raise SystemExit("could not read a result line from pytest:\n" + out[-2000:])
    if proc.returncode != 0:
        raise SystemExit("the suite is not green; refusing to write a number")
    return int(m.group(1)), int(m.group(2) or 0)


def measure_mutations():
    """Run the mutation pass and return its markdown table plus the count."""
    proc = subprocess.run(
        [sys.executable, "scripts/mutate.py", "--md"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "a mutation escaped; the table would be a lie:\n" + proc.stderr[-2000:]
        )
    table = proc.stdout.strip()
    # Drop the header and the separator, then count what is left. Counting by
    # prefix got this wrong once: the separator line "|---|---|" has no space
    # after the pipe, so it slipped past the filter and the slice ate a real
    # row instead.
    lines = [ln for ln in table.split("\n") if ln.strip()]
    return table, max(0, len(lines) - 2)


def substitute(text, name, body):
    open_tag = "<!-- measured:%s -->" % name
    close_tag = "<!-- /measured:%s -->" % name
    if open_tag not in text or close_tag not in text:
        raise SystemExit("README is missing the %s markers" % name)
    head = text.split(open_tag, 1)[0]
    tail = text.split(close_tag, 1)[1]
    return head + open_tag + "\n" + body + "\n" + close_tag + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    checked = check_style()
    print("  style      : clean (%d characters checked)" % checked)
    passed, skipped = measure_tests()
    table, n_mutations = measure_mutations()

    print("  tests      : %d passed, %d skipped" % (passed, skipped))
    print("  mutations  : %d, all caught" % n_mutations)

    if not args.write:
        return 0

    text = README.read_text(encoding="utf-8")
    line = ("`pytest tests/ -q` reports **%d passed, %d skipped**, and every one "
            "of the **%d** mutations below is caught." % (passed, skipped, n_mutations))
    text = substitute(text, "tests", line)
    text = substitute(text, "mutations", table)
    README.write_text(text, encoding="utf-8", newline="\n")
    # The README is now different from what was checked, so check it again.
    check_style()
    print("  README.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
