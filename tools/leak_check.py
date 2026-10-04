"""Leak check for a public repository.

Blocks a commit or push that would publish secrets or private material.
Two layers of rules:

  1. Generic rules (in this file, public): API keys, private keys, licence-style
     keys, real IP addresses, .env / .ini / office / image files, config blocks.
  2. Private terms (in `.leakcheck-private.txt`, gitignored, never published):
     machine names, key fragments, company paths — things that would themselves
     leak if written into a public rule file.

Usage:
  python tools/leak_check.py --staged          # pre-commit: what is about to be committed
  python tools/leak_check.py --push            # pre-push: every commit about to be pushed (refs on stdin)
  python tools/leak_check.py --tree HEAD       # any revision's full tree

Exit code 0 = clean, 1 = blocked.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRIVATE_TERMS_FILE = REPO / ".leakcheck-private.txt"
ZERO_SHA = "0" * 40

# Files that must never be published, whatever their content.
BLOCKED_FILE_PATTERNS = [
    r"(^|/)\.env$",                      # real env file (.env.example is fine)
    r"\.ini$",                           # scanner / app configs
    r"\.(docx?|xlsx?|pptx?|pdf)$",       # internal documents and reports
    r"\.(tif|tiff)$",                    # raw scanner images
    r"\.(db|sqlite3?)$",                 # conversation databases
    r"\.(pem|key|pfx|p12)$",             # key material
    r"(^|/)\.leakcheck-private\.txt$",   # the private term list itself
    r"(^|/)journal/",                    # private learning log
    r"(^|/)\.sync-private\.txt$",       # private sync rewrite rules
]

# Content that must never be published.
BLOCKED_CONTENT_PATTERNS = [
    ("API key", r"\bsk-[A-Za-z0-9]{20,}"),
    ("private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("licence-style key", r"(?im)^\s*key\s*=\s*[0-9A-F]{8,}"),
    ("filled-in API key", r"(?m)^\s*[A-Z_]*API_KEY\s*=\s*(?!your_|<|$)\S{12,}"),  # env-file style, upper case
    ("scanner config section", r"(?m)^\[(Controller|Camera|Stage|Lens|Setup)\]\s*$"),
    ("Windows user path", r"(?i)\b[A-Z]:\\Users\\[^\\\s]+"),
]

# Real IP addresses — loopback / any / documentation ranges are allowed.
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ALLOWED_IP_PREFIXES = ("127.", "0.0.0.0", "192.0.2.", "198.51.100.", "203.0.113.")


def git(*args, stdin=None):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          input=stdin, check=True).stdout


def private_terms():
    if not PRIVATE_TERMS_FILE.exists():
        return []
    lines = PRIVATE_TERMS_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def check_file(path, data, terms):
    """Return a list of problems for one file."""
    problems = []
    for pat in BLOCKED_FILE_PATTERNS:
        if re.search(pat, path, re.IGNORECASE):
            problems.append(f"{path}: file type/name is never published ({pat})")
            return problems
    if b"\0" in data[:8000]:          # binary: name rules only
        return problems
    text = data.decode("utf-8", errors="replace")
    for label, pat in BLOCKED_CONTENT_PATTERNS:
        for m in re.finditer(pat, text):
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"{path}:{line}: {label}")
    for m in IP_RE.finditer(text):
        ip = m.group(0)
        if all(0 <= int(p) <= 255 for p in ip.split(".")) and not ip.startswith(ALLOWED_IP_PREFIXES):
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"{path}:{line}: real IP address")
    lowered = text.lower()
    for term in terms:
        idx = lowered.find(term.lower())
        if idx != -1:
            line = text.count("\n", 0, idx) + 1
            # Never print the private term itself.
            problems.append(f"{path}:{line}: private term #{terms.index(term) + 1}")
    for term in terms:              # a private term in the file NAME too
        if term.lower() in path.lower():
            problems.append(f"{path}: private term #{terms.index(term) + 1} in file name")
    return problems


def staged_files():
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode()
    for path in filter(None, names.split("\0")):
        yield path, git("show", f":{path}")


def commit_files(rev):
    """Files added or changed by one commit (whole tree for a root commit)."""
    names = git("diff-tree", "--root", "--no-commit-id", "-r", "--name-only",
                "--diff-filter=ACMR", "-z", rev).decode()
    for path in filter(None, names.split("\0")):
        yield path, git("show", f"{rev}:{path}")


def tree_files(rev):
    names = git("ls-tree", "-r", "--name-only", "-z", rev).decode()
    for path in filter(None, names.split("\0")):
        yield path, git("show", f"{rev}:{path}")


def pushed_commits(stdin_text):
    """Commits about to be pushed, from the pre-push hook's stdin."""
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == ZERO_SHA:        # branch deletion
            continue
        rng = local_sha if remote_sha == ZERO_SHA else f"{remote_sha}..{local_sha}"
        extra = ["--not", "--remotes"] if remote_sha == ZERO_SHA else []
        yield from git("rev-list", rng, *extra).decode().split()


def main():
    args = sys.argv[1:]
    terms = private_terms()
    if not terms:
        print("leak_check: WARNING - no private term list (.leakcheck-private.txt); "
              "only generic rules apply.")

    if args[:1] == ["--staged"]:
        files = list(staged_files())
    elif args[:1] == ["--push"]:
        files = [f for c in pushed_commits(sys.stdin.read()) for f in commit_files(c)]
    elif args[:1] == ["--tree"] and len(args) == 2:
        files = list(tree_files(args[1]))
    else:
        print(__doc__)
        return 2

    problems = [p for path, data in files for p in check_file(path, data, terms)]
    if problems:
        print("leak_check: BLOCKED - this would publish private material:")
        for p in problems:
            print("  -", p)
        print("Remove or rewrite these, then try again. Do not bypass this check.")
        return 1
    print(f"leak_check: clean ({len(files)} file(s) checked, {len(terms)} private term(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
