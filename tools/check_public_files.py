"""Check versioned content for private deployment files and operator identifiers."""

from pathlib import Path
import re
import subprocess
import sys


RULES = {
    "AWS account identifier": re.compile(r"(?<!\d)\d{12}(?!\d)"),
    "tax or personal identifier": re.compile(r"(?<!\d)\d{11}(?!\d)"),
    "personal home directory": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    "deployment RDS endpoint": re.compile(r"[\w-]+\.[\w.-]+\.rds\.amazonaws\.com"),
    "email address": re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[A-Za-z]{2,}"),
}
EXAMPLE_ACCOUNTS = {"000000000000", "111111111111", "123456789012"}
EXAMPLE_DOMAINS = {"example.com", "example.net", "example.org", "example.invalid"}


def findings(path: str, content: str) -> list[tuple[int, str]]:
    if (path == "cdk.local.json" or path.startswith(".private/")
            or path.endswith(("_RESULT.json", "_VALIDATION.json", ".pem", ".key", ".dump"))
            or Path(path).name in {".env", "deploy_key", "credentials", "DEPLOY_PROGRESS_LOG.md"}):
        return [(1, "private deployment file")]
    result = []
    for number, line in enumerate(content.splitlines(), 1):
        for label, pattern in RULES.items():
            for match in pattern.finditer(line):
                value = match.group()
                if label == "AWS account identifier" and value in EXAMPLE_ACCOUNTS:
                    continue
                if label == "email address":
                    domain = value.rsplit("@", 1)[1].lower()
                    if domain in EXAMPLE_DOMAINS or domain.endswith(".example.invalid"):
                        continue
                result.append((number, label))
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    failed = False
    for name in paths:
        if not name or not (root / name).is_file():
            continue
        try:
            content = (root / name).read_text()
        except UnicodeDecodeError:
            continue
        for number, label in findings(name, content):
            print(f"{name}:{number}: {label}")
            failed = True
    if not failed:
        print("Versioned content passed the public-file privacy checks.")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
