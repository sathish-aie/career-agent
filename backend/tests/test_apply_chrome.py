import subprocess
from pathlib import Path

import pytest

from career_agent.apply import agent as agent_mod
from career_agent.apply import ats as ats_apply
from career_agent.apply import chrome
from career_agent.apply.chrome import chrome_command


def test_chrome_command_flags():
    cmd = chrome_command("C:/chrome.exe", Path("C:/prof"), port=9223)
    assert cmd[0] == "C:/chrome.exe"
    assert "--remote-debugging-port=9223" in cmd
    assert any(a.startswith("--user-data-dir=") and a.endswith("prof") for a in cmd)
    for flag in ("--no-first-run", "--deny-permission-prompts",
                 "--use-fake-ui-for-media-stream", "--disable-notifications",
                 "--disable-session-crashed-bubble", "--password-store=basic"):
        assert flag in cmd
    assert "--headless=new" not in cmd
    assert "--headless=new" in chrome_command("c", Path("p"), headless=True)


def test_chrome_keeps_rendering_while_its_window_is_covered():
    """Playwright's click/hover/drag wait for the target to be stable across
    animation frames, and Chrome throttles animation frames in a window it
    considers occluded or backgrounded. The live runs of 2026-10-02 saw every
    click time out as "unstable" on two Greenhouse forms while fill and
    keyboard kept working, and the keyboard fallback cost $13 on one form.
    Playwright passes these flags itself when it launches the browser; this
    launcher must too, since the agent's window sits behind the operator's."""
    cmd = chrome_command("C:/chrome.exe", Path("C:/prof"))
    for flag in ("--disable-backgrounding-occluded-windows",
                 "--disable-renderer-backgrounding",
                 "--disable-background-timer-throttling"):
        assert flag in cmd, flag


def test_a_bogus_chrome_path_override_is_refused(monkeypatch, tmp_path):
    """get_chrome_path() returned $CHROME_PATH unchecked, so a typo passed
    ats.preflight() and the launch failure landed downstream as
    agent_error/held_unknown -- exactly the class preflight exists to catch
    before any application row is written."""
    monkeypatch.setenv("CHROME_PATH", str(tmp_path / "nope" / "chrome.exe"))
    with pytest.raises(RuntimeError, match="CHROME_PATH"):
        chrome.get_chrome_path()


def test_a_real_chrome_path_override_is_used(monkeypatch, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("CHROME_PATH", str(exe))
    assert chrome.get_chrome_path() == str(exe)


def test_preflight_reports_a_bad_override_as_a_precondition(monkeypatch, tmp_path):
    """preflight() must turn it into PreconditionError, the one failure that
    writes no row at all."""
    monkeypatch.setenv("CHROME_PATH", str(tmp_path / "nope.exe"))
    monkeypatch.setattr(agent_mod, "require_binaries", lambda: None)
    with pytest.raises(agent_mod.PreconditionError, match="CHROME_PATH"):
        ats_apply.preflight()


def test_ensure_profile_returns_an_absolute_path(tmp_path, monkeypatch):
    """A relative --user-data-dir makes Chrome hand the launch to an already
    running session ("Opening in existing browser session") and drop the CDP
    port, so the agent gets no browser. Seen live on 2026-09-13."""
    from career_agent.apply import chrome
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prof" / "Default").mkdir(parents=True)  # already cloned: no copy
    monkeypatch.setattr(chrome, "PROFILE_DIR", Path("prof"))
    assert chrome.ensure_profile().is_absolute()


def test_a_profile_folder_from_the_environment_is_used_as_it_is(tmp_path, monkeypatch):
    """CHROME_PROFILE_DIR: a folder the human chose (and may already be signed
    in on) is never cloned into."""
    everyday = tmp_path / "User Data"
    (everyday / "Default").mkdir(parents=True)
    (everyday / "Default" / "Cookies").write_text("theirs", encoding="utf-8")
    monkeypatch.setattr(chrome, "_user_profile_source", lambda: everyday)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHROME_PROFILE_DIR", "agent profile")

    got = chrome.ensure_profile()

    assert got == (tmp_path / "agent profile").resolve() and got.is_dir()
    assert list(got.iterdir()) == []


@pytest.mark.parametrize("inside", ["", "Default"])
def test_chromes_own_profile_folder_is_refused_before_any_run(tmp_path, monkeypatch, inside):
    """Chrome ignores --remote-debugging-port on its default data folder (since
    v136): the agent would get no browser. preflight reports it, the one
    failure that writes no row."""
    everyday = tmp_path / "User Data"
    (everyday / "Default").mkdir(parents=True)
    monkeypatch.setattr(chrome, "_user_profile_source", lambda: everyday)
    monkeypatch.setenv("CHROME_PROFILE_DIR", str(everyday / inside))
    with pytest.raises(RuntimeError, match="CHROME_PROFILE_DIR"):
        chrome.ensure_profile()
    monkeypatch.setattr(agent_mod, "require_binaries", lambda: None)
    monkeypatch.setattr(chrome, "get_chrome_path", lambda: "chrome.exe")
    with pytest.raises(agent_mod.PreconditionError, match="CHROME_PROFILE_DIR"):
        ats_apply.preflight()


class _Chrome:
    pid = 4242

    def __init__(self, closes: bool):
        self.closes, self.waits = closes, []

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if not self.closes:
            raise subprocess.TimeoutExpired("chrome", timeout)
        return 0


@pytest.mark.parametrize("closes", [True, False])
def test_cleanup_asks_chrome_to_close_and_force_kills_only_what_is_left(monkeypatch, closes):
    """A force kill skips Chrome's shutdown, and with it the write of the
    cookies a human just signed in for: the next run would be signed out again."""
    calls = []
    monkeypatch.setattr(chrome.platform, "system", lambda: "Windows")
    monkeypatch.setattr(chrome.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    proc = _Chrome(closes)

    chrome.cleanup(proc)

    assert calls[0] == ["taskkill", "/PID", "4242"] and proc.waits == [chrome.CLOSE_WAIT_S]
    assert calls[1:] == ([] if closes else [["taskkill", "/F", "/T", "/PID", "4242"]])


def test_saved_passwords_are_never_cloned_into_the_agent_profile():
    """M-4: the agent's Chrome must not carry the user's saved passwords
    (Login Data is Chrome's password store, in the profile's Default dir)."""
    import shutil
    ignore = shutil.ignore_patterns(*chrome._SKIP_ON_CLONE)
    names = ["Login Data", "Login Data-journal", "Login Data For Account",
             "Login Data For Account-journal", "Cookies", "Preferences"]
    assert ignore("Default", names) == {"Login Data", "Login Data-journal",
                                        "Login Data For Account",
                                        "Login Data For Account-journal"}
