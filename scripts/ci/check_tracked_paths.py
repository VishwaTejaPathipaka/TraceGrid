"""Fail when the Git index includes local credentials or runtime output."""

from fnmatch import fnmatchcase
from pathlib import PurePosixPath
import subprocess
import sys


DIRECTORIES = {
    ".aws", ".ssh", ".cache", ".pytest_cache", ".tracegrid-mail", ".venv", "__pycache__",
    "dist", "node_modules", "playwright-report", "test-results", "venv",
}
FILENAMES = (
    ".env", ".env.*", ".pgpass", "pgpass.conf", ".netrc", "_netrc", ".npmrc", ".pypirc",
    ".git-credentials", "credentials", "credentials.*", "secrets.json", "id_rsa", "id_dsa",
    "id_ecdsa", "id_ed25519", "*.pem", "*.key", "*.p12", "*.pfx", "*.dump", "*.dump.*",
    "*.backup", "*.backup.*", "*.sql", "*.sql.gz", "*.db", "*.db-*", "*.sqlite", "*.sqlite-*",
    "*.sqlite3", "*.sqlite3-*", "*.log", "*.tmp", "*.pyc",
)
IGNORE_PROBES = (
    ".env", "frontend/.env.production", "pgpass.conf", ".ssh/id_ed25519", ".netrc",
    ".npmrc", ".pypirc", ".git-credentials", "client.key", "snapshot.dump",
    "snapshot.sql", "local.sqlite3-wal", ".tracegrid-mail/fixture.eml",
    ".venv/bin/python", "frontend/node_modules/pkg/index.js", "frontend/dist/index.html",
    "frontend/test-results/trace.zip", "server.log",
)


def sensitive(path):
    *parents, name = PurePosixPath(path.casefold()).parts
    return bool(DIRECTORIES.intersection(parents)) or any(
        fnmatchcase(name, pattern) for pattern in FILENAMES
    )


def main():
    files = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0")
    forbidden = {path for path in files if path and sensitive(path)}
    for path in sorted(forbidden):
        print(f"Sensitive or generated file is tracked: {path!r}", file=sys.stderr)

    for probe in IGNORE_PROBES:
        check = subprocess.run(["git", "check-ignore", "-q", "--no-index", "--", probe], check=False)
        if check.returncode != 0:
            print(f"Missing Git ignore rule for {probe!r}", file=sys.stderr)
            return 1

    if forbidden:
        return 1
    print("Tracked path and Git ignore checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
