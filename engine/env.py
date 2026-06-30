import os


def load_dotenv(path: str = ".env") -> int:
    """Load KEY=VALUE lines from a .env file into os.environ.

    Uses setdefault semantics: a key already present in the real environment
    (exported, set by cron/systemd, etc.) ALWAYS wins over the file — so the
    operator-set live key is never clobbered by .env. Missing file is a no-op.
    Returns the number of keys actually set.

    # ponytail: ~15-line stdlib loader; reach for python-dotenv only if we ever
    # need interpolation / multiline / export-prefix parsing.
    """
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")          # split on FIRST '=' only
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]                         # strip matching surrounding quotes
            if key and key not in os.environ:           # real env wins
                os.environ[key] = val
                n += 1
    return n
