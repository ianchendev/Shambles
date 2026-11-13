"""Must every real machine pass before this change can merge?

Reads changed paths, one per line, on standard input and the list of paths
that matter from the file named as the first argument. Prints the changed
paths that matter and exits 0 if there are any, 1 if there are none, and 2 if
the question could not be answered. The workflow treats 2 as "yes".

Kept as a file of its own, and free of anything but the standard library, so
that the unit suite can check the rule the workflow applies.
"""

import sys


def load(path):
    """The entries of the list: directories end in "/", the rest are files."""
    with open(path, encoding="utf-8") as handle:
        lines = (line.strip() for line in handle)
        return [line for line in lines if line and not line.startswith("#")]


def matters(changed, entries):
    """Whether one changed path falls under any entry."""
    return any(changed.startswith(entry) if entry.endswith("/")
               else changed == entry for entry in entries)


def relevant(changed_paths, entries):
    return [path for path in changed_paths if matters(path, entries)]


def main(argv):
    try:
        entries = load(argv[1])
    except (OSError, IndexError, UnicodeDecodeError) as exc:
        print(f"cannot read the list of paths: {exc}", file=sys.stderr)
        return 2
    if not entries:
        print("the list of paths is empty", file=sys.stderr)
        return 2
    changed = [line.strip() for line in sys.stdin if line.strip()]
    hits = relevant(changed, entries)
    for path in hits:
        print(path)
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
