from mygitclient.github import first_github_remote, github_remote


def test_github_remote_accepts_https_and_scp_ssh_urls() -> None:
    https = github_remote("https://github.com/octocat/Hello-World.git")
    ssh = github_remote("git@github.com:octocat/Hello-World.git")

    assert https is not None and https.full_name == "octocat/Hello-World"
    assert ssh == https


def test_github_remote_rejects_other_hosts_and_first_finds_github() -> None:
    assert github_remote("https://gitlab.com/octocat/Hello-World.git") is None
    assert first_github_remote(
        ("ssh://example.invalid/team/repository.git", "ssh://git@github.com/team/project.git")
    ) == github_remote("https://github.com/team/project")
