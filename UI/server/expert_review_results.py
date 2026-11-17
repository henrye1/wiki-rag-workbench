"""Read the expert review files the reviewers sent back, with the KEY file, and write Expert_Review_<run>_RESULTS.xlsx:
how often the reviewers agree with the judge (for the wiki's answers and the RAG answers separately), their preferred
answers, and the wiki − RAG coverage gap from their grades beside the judge's. Reads only; the files are not changed.

Run from UI/server:
    .venv/bin/python expert_review_results.py <KEY.xlsx> <Reviewer1.xlsx> [<Reviewer2.xlsx> ...] [-o <RESULTS.xlsx>]
Without -o the results are written next to the KEY file."""
import argparse
import pathlib
import re
import sys

from app.expert_review import ReviewError, results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("key", type=pathlib.Path, help="the KEY file (Expert_Review_<run>_KEY.xlsx)")
    p.add_argument("returned", type=pathlib.Path, nargs="+", help="the reviewers' returned files")
    p.add_argument("-o", "--out", type=pathlib.Path, help="where to write the results (default: next to the KEY file)")
    a = p.parse_args()
    m = re.match(r"Expert_Review_(.+)_KEY\.xlsx$", a.key.name)
    out = a.out or a.key.with_name(f"Expert_Review_{m.group(1) if m else 'run'}_RESULTS.xlsx")
    if out.resolve() in {x.resolve() for x in [a.key, *a.returned]}:
        print("The results would overwrite one of the files read; choose another -o", file=sys.stderr)
        return 2
    try:
        blob = results(a.key.read_bytes(), [f.read_bytes() for f in a.returned])
    except (ReviewError, KeyError) as e:
        print(f"Not read: {e}", file=sys.stderr)
        return 1
    out.write_bytes(blob)
    print(f"Written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
