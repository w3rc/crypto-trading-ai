import os
from engine.env import load_dotenv


def test_loads_key_value(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("FOO_BAR_TEST=hello\n")
    monkeypatch.delenv("FOO_BAR_TEST", raising=False)
    assert load_dotenv(str(env)) == 1
    assert os.environ["FOO_BAR_TEST"] == "hello"


def test_does_not_override_existing_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("FOO_BAR_TEST=fromfile\n")
    monkeypatch.setenv("FOO_BAR_TEST", "fromenv")
    load_dotenv(str(env))
    assert os.environ["FOO_BAR_TEST"] == "fromenv"        # real env wins (setdefault semantics)


def test_missing_file_is_noop(tmp_path):
    assert load_dotenv(str(tmp_path / "nope.env")) == 0


def test_skips_comments_blanks_and_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nA_TEST=1\nB_TEST="quoted value"\nC_TEST=has=equals\n')
    for k in ("A_TEST", "B_TEST", "C_TEST"):
        monkeypatch.delenv(k, raising=False)
    load_dotenv(str(env))
    assert os.environ["A_TEST"] == "1"
    assert os.environ["B_TEST"] == "quoted value"          # surrounding quotes stripped
    assert os.environ["C_TEST"] == "has=equals"            # split on first '=' only
