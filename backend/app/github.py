import re
import shutil
import subprocess
from pathlib import Path

from app.config import REPOS_DIR

GITHUB_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


class GitHubUrlError(ValueError):
    pass


def parse_github_url(repo_url: str) -> tuple[str, str, str]:
    url = repo_url.strip()
    match = GITHUB_RE.match(url)
    if not match:
        raise GitHubUrlError(
            "Only public HTTPS GitHub URLs are supported (https://github.com/owner/repo)."
        )
    owner = match.group("owner")
    name = match.group("name")
    repo_id = f"{owner}__{name}"
    clone_url = f"https://github.com/{owner}/{name}.git"
    return repo_id, clone_url, name


def clone_repo(repo_url: str) -> tuple[str, Path]:
    repo_id, clone_url, _ = parse_github_url(repo_url)
    dest = REPOS_DIR / repo_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        err = (result.stderr or result.stdout or "git clone failed").strip()
        raise RuntimeError(err[:800])
    return repo_id, dest
