from app.chunking import chunk_text
from app.github import GitHubUrlError, parse_github_url


def test_parse_github_url():
    repo_id, clone_url, name = parse_github_url("https://github.com/pallets/flask")
    assert repo_id == "pallets__flask"
    assert clone_url == "https://github.com/pallets/flask.git"
    assert name == "flask"


def test_parse_github_git_suffix():
    repo_id, _, _ = parse_github_url("https://github.com/octocat/Hello-World.git")
    assert repo_id == "octocat__Hello-World"


def test_reject_non_github():
    try:
        parse_github_url("https://gitlab.com/foo/bar")
        assert False, "expected error"
    except GitHubUrlError:
        pass


def test_chunk_keeps_line_numbers():
    text = "\n".join(f"line-{i}" for i in range(1, 21))
    chunks = chunk_text("src/a.py", text)
    assert chunks
    assert chunks[0].start_line == 1
    assert chunks[0].path == "src/a.py"
    assert "line-1" in chunks[0].text
