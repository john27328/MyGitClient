from mygitclient.git.remotes import parse_remote_config


def test_parse_remote_config_reads_nul_delimited_keys_and_urls() -> None:
    output = (
        b"remote.origin.url\nhttps://github.com/octocat/Hello-World.git\0"
        b"remote.backup.url\ngit@example.invalid:team/project.git\0"
    )

    assert parse_remote_config(output) == (
        "https://github.com/octocat/Hello-World.git",
        "git@example.invalid:team/project.git",
    )
