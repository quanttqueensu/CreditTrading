"""The prod installer builds prod from a tag and nothing else, and touches nothing else.

Each test pins one promise from `install_prod`'s docstring. They are the kind
that rot silently: a later edit that seeds data by symlink, renders a template
from the working tree instead of the tag, or writes a plist while launchd still
runs the old one would pass every other check in this repo.

Hermetic throughout. A whole fake world is built under tmp_path: a "dev" repo
with its origin a local bare repo (git over a file path opens no socket, so the
root conftest's netguard stays in force), a fake home whose ~/Library and
~/prod are tmp directories, a fake /etc/localtime symlink, and a stub for
launchctl (the conftest forbids every mutating launchctl verb in tests anyway).
The real templates are copied into the fake repo, so the checks run against the
templates that will ship.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from quantt.deploy import install_prod as ip

REAL_REPO = Path(ip.__file__).resolve().parents[2]
SENTINEL = "sentinel-secret-that-must-never-be-read"
NOW = dt.datetime(2026, 9, 28, 20, 0, tzinfo=dt.timezone.utc)
GITC = ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
        "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def git(*args, cwd):
    r = subprocess.run(["git", *GITC, *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class FakeLaunchctl:
    """Records calls. `loaded` names labels `print` reports as loaded."""

    def __init__(self, loaded=()):
        self.loaded = set(loaded)
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        rc = 0
        if args[0] == "print":
            rc = 0 if args[1].rsplit("/", 1)[1] in self.loaded else 113
        return subprocess.CompletedProcess(args, rc, "", "")

    def verbs(self):
        return [c[0] for c in self.calls]


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.layout = ip.Layout(self.home)
        self.dev = tmp / "dev"
        self.origin = tmp / "origin.git"
        self.localtime = tmp / "localtime"
        self.set_tz("America/New_York")
        self.keys = tmp / "keys & stuff" / "alpaca.env"
        self.keys.parent.mkdir()
        self.keys.write_text(f"ALPACA_CEF_SECRET_KEY={SENTINEL}\n")
        os.chmod(self.keys, 0o600)
        self.launchctl = FakeLaunchctl()
        self._make_repo()

    def set_tz(self, zone):
        if self.localtime.is_symlink():
            self.localtime.unlink()
        os.symlink(f"/var/db/timezone/zoneinfo/{zone}", self.localtime)

    def _make_repo(self):
        d = self.dev
        d.mkdir()
        git("init", "-q", "-b", "main", cwd=d)
        (d / ".gitignore").write_text("/data/\n")
        for rel in ip.REQUIRED_AT_TAG:
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(f"# stub {rel}\n")
        for job in ip.JOBS:
            (d / job.template).parent.mkdir(parents=True, exist_ok=True)
            (d / job.template).write_text((REAL_REPO / job.template).read_text())
        (d / "data" / "cef").mkdir(parents=True)
        for name in ip.SEED_FILES + ip.SEED_WRITE_ONLY:
            (d / "data" / "cef" / name).write_bytes(f"dev bytes of {name}".encode())
        (d / "data" / "cef" / "cef_borrow.csv").write_text("not read by the live path")
        git("add", "-A", cwd=d)
        git("commit", "-q", "-m", "v1", cwd=d)
        git("tag", "-a", "v1", "-m", "release v1", cwd=d)
        subprocess.run(["git", "clone", "-q", "--bare", str(d), str(self.origin)],
                       check=True, capture_output=True)
        git("remote", "add", "origin", str(self.origin), cwd=d)

    def commit_and_tag(self, tag, change, push=True):
        change(self.dev)
        git("add", "-A", cwd=self.dev)
        git("commit", "-q", "-m", tag, cwd=self.dev)
        git("tag", "-a", tag, "-m", tag, cwd=self.dev)
        if push:
            git("push", "-q", "origin", "main", tag, cwd=self.dev)

    def tag_commit(self, tag):
        return git("rev-parse", f"{tag}^{{commit}}", cwd=self.dev)

    def run(self, *extra, tag="v1", env_file=None, capsys=None):
        argv = ["--tag", tag, "--env-file", str(env_file or self.keys), *extra]
        rc = ip.main(argv, layout=self.layout, dev_repo=self.dev,
                     localtime=self.localtime, launchctl=self.launchctl, now_utc=NOW)
        out = capsys.readouterr().out if capsys else ""
        return rc, out

    def plist(self, job_index=0):
        return plistlib.loads(self.layout.plist_path(ip.JOBS[job_index]).read_bytes())


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture
def no_reading_keys(world, monkeypatch):
    """Any open() of the key file fails the test. The installer may stat it only."""
    real_open = io.open
    target = os.path.realpath(world.keys)

    def guarded(file, *a, **kw):
        if isinstance(file, (str, bytes, os.PathLike)) and \
                os.path.realpath(os.fsdecode(file)) == target:
            raise AssertionError(f"installer opened the key file {file}")
        return real_open(file, *a, **kw)
    monkeypatch.setattr(io, "open", guarded)
    monkeypatch.setattr("builtins.open", guarded)


# -- dry run ----------------------------------------------------------------

def test_dry_run_writes_nothing_and_shows_the_plists(world, capsys, no_reading_keys):
    rc, out = world.run(capsys=capsys)
    assert rc == 0, out
    assert not world.layout.prod_dir.exists()
    assert not world.layout.state_dir.exists()
    assert not world.layout.agents_dir.exists()
    assert "WOULD 1. git clone" in out and "DOING" not in out
    assert out.count("<key>Label</key>") == 2
    assert "DRY RUN: nothing was written" in out
    assert [v for v in world.launchctl.verbs() if v != "print"] == []


# -- apply ------------------------------------------------------------------

def test_apply_builds_prod_at_the_tag(world, capsys, no_reading_keys):
    rc, out = world.run("--apply", capsys=capsys)
    assert rc == 0, out
    prod = world.layout.prod_dir
    assert git("rev-parse", "HEAD", cwd=prod) == world.tag_commit("v1")
    # detached, not on a branch: prod follows tags, never a moving branch
    r = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=prod,
                       capture_output=True)
    assert r.returncode != 0
    assert git("status", "--porcelain", cwd=prod) == ""
    assert world.layout.log_dir.is_dir()
    assert oct(world.layout.state_dir.stat().st_mode & 0o777) == "0o700"


def test_apply_seeds_only_the_files_the_live_path_reads(world, capsys):
    world.run("--apply", capsys=capsys)
    data = world.layout.prod_dir / "data" / "cef"
    assert sorted(p.name for p in data.iterdir()) == sorted(ip.SEED_FILES)
    for name in ip.SEED_FILES:
        assert not (data / name).is_symlink()
        assert (data / name).read_bytes() == (world.dev / "data/cef" / name).read_bytes()


def test_rendered_plists_are_dry_by_default_and_complete(world, capsys, no_reading_keys):
    world.run("--apply", capsys=capsys)
    py = str(Path(sys.executable))
    sess, ver = world.plist(0), world.plist(1)
    for d, sub in ((sess, "run"), (ver, "verify")):
        assert d["ProgramArguments"] == [py, "-m", "quantt.session", sub, "--book", "cef"]
        assert d["WorkingDirectory"] == str(world.layout.prod_dir)
        env = d["EnvironmentVariables"]
        assert env["DRY_RUN"] == "1"
        assert env["QUANTT_STATE_DIR"] == str(world.layout.state_dir)
        assert env["QUANTT_ENV_FILE"] == str(world.keys)      # '&' survived XML
        assert env["PATH"].split(":")[0] == str(Path(py).parent)
        assert d["StandardOutPath"].startswith(str(world.layout.log_dir))
        assert d["RunAtLoad"] is False
    when = lambda d: sorted((x["Weekday"], x["Hour"], x["Minute"])
                            for x in d["StartCalendarInterval"])
    assert when(sess) == sorted((w, h, m) for w in range(1, 6) for h, m in ((8, 30), (12, 0)))
    assert when(ver) == [(w, 17, 30) for w in range(1, 6)]
    for p in world.layout.agents_dir.iterdir():
        assert SENTINEL not in p.read_text()


def test_armed_renders_dry_run_zero_and_warns(world, capsys):
    rc, out = world.run("--apply", "--armed", capsys=capsys)
    assert rc == 0
    assert world.plist(0)["EnvironmentVariables"]["DRY_RUN"] == "0"
    assert world.plist(1)["EnvironmentVariables"]["DRY_RUN"] == "0"
    assert "ARMED" in out and "AUTO_ARMED" in out


def test_reinstall_without_armed_disarms(world, capsys):
    world.run("--apply", "--armed", capsys=capsys)
    rc, out = world.run("--apply", capsys=capsys)
    assert rc == 0
    assert world.plist(0)["EnvironmentVariables"]["DRY_RUN"] == "1"
    assert "replacing DRY_RUN=0" in out


def test_without_load_launchd_is_only_asked_read_only_questions(world, capsys):
    world.run("--apply", capsys=capsys)
    assert set(world.launchctl.verbs()) == {"print"}


def test_load_bootstraps_both_jobs(world, capsys):
    rc, _ = world.run("--apply", "--load", capsys=capsys)
    assert rc == 0
    boots = [c for c in world.launchctl.calls if c[0] == "bootstrap"]
    assert [Path(c[2]).name for c in boots] == [f"{j.label}.plist" for j in ip.JOBS]
    assert all(c[1] == f"gui/{os.getuid()}" for c in boots)
    assert "bootout" not in world.launchctl.verbs()


def test_load_reloads_a_loaded_job(world, capsys):
    world.run("--apply", capsys=capsys)
    world.launchctl = FakeLaunchctl(loaded=[j.label for j in ip.JOBS])
    rc, _ = world.run("--apply", "--load", "--armed", capsys=capsys)
    assert rc == 0
    v = world.launchctl.verbs()
    assert v.count("bootout") == 2 and v.count("bootstrap") == 2
    assert v.index("bootout") < v.index("bootstrap")


def test_changed_plist_for_a_loaded_job_without_load_is_refused(world, capsys):
    """Else the file says DRY_RUN=1 while launchd still runs DRY_RUN=0."""
    world.run("--apply", "--armed", capsys=capsys)
    world.launchctl = FakeLaunchctl(loaded=[ip.JOBS[0].label])
    rc, out = world.run("--apply", capsys=capsys)
    assert rc == 2 and "is loaded in launchd" in out
    assert world.plist(0)["EnvironmentVariables"]["DRY_RUN"] == "0"


def test_unchanged_plist_for_a_loaded_job_needs_no_reload(world, capsys):
    world.run("--apply", capsys=capsys)
    world.launchctl = FakeLaunchctl(loaded=[j.label for j in ip.JOBS])
    rc, out = world.run("--apply", capsys=capsys)
    assert rc == 0, out


def test_load_requires_apply(world, capsys):
    with pytest.raises(SystemExit):
        world.run("--load", capsys=capsys)


def test_other_launch_agents_are_untouched(world, capsys):
    agents = world.layout.agents_dir
    agents.mkdir(parents=True)
    old = agents / "com.quantt.verify.cef.plist"
    old.write_text("retired IBKR job")
    world.run("--apply", capsys=capsys)
    assert old.read_text() == "retired IBKR job"
    assert sorted(p.name for p in agents.iterdir()) == sorted(
        [old.name] + [f"{j.label}.plist" for j in ip.JOBS])


# -- update -----------------------------------------------------------------

def test_update_moves_to_the_new_tag_and_keeps_prods_panels(world, capsys):
    world.run("--apply", capsys=capsys)
    panel = world.layout.prod_dir / "data" / "cef" / ip.SEED_FILES[0]
    panel.write_bytes(b"prod appended newer rows")
    world.commit_and_tag("v2", lambda d: (d / "ops/halt.py").write_text("# v2\n"))
    rc, out = world.run("--apply", tag="v2", capsys=capsys)
    assert rc == 0, out
    assert git("rev-parse", "HEAD", cwd=world.layout.prod_dir) == world.tag_commit("v2")
    assert panel.read_bytes() == b"prod appended newer rows"
    assert "leave " in out and "untouched" in out


@pytest.mark.parametrize("dirty", ["modified", "untracked"])
def test_dirty_prod_clone_is_refused(world, capsys, dirty):
    world.run("--apply", capsys=capsys)
    prod = world.layout.prod_dir
    if dirty == "modified":
        (prod / "ops/halt.py").write_text("# hand edit in prod\n")
    else:
        (prod / "ops/stray.txt").write_text("x")
    world.commit_and_tag("v2", lambda d: (d / "ops/halt.py").write_text("# v2\n"))
    rc, out = world.run("--apply", tag="v2", capsys=capsys)
    assert rc == 2 and "local modifications" in out
    assert git("rev-parse", "HEAD", cwd=prod) == world.tag_commit("v1")


def test_prod_dir_that_is_not_a_clone_is_refused(world, capsys):
    world.layout.prod_dir.mkdir(parents=True)
    rc, out = world.run("--apply", capsys=capsys)
    assert rc == 2 and "not a git clone" in out


def test_clone_of_another_origin_is_refused(world, capsys):
    world.run("--apply", capsys=capsys)
    git("remote", "set-url", "origin", "/elsewhere.git", cwd=world.layout.prod_dir)
    rc, out = world.run("--apply", capsys=capsys)
    assert rc == 2 and "not of this repo's origin" in out


# -- the tag ----------------------------------------------------------------

def test_tag_not_pushed_is_refused(world, capsys):
    world.commit_and_tag("v2", lambda d: (d / "ops/halt.py").write_text("# v2\n"),
                         push=False)
    rc, out = world.run(tag="v2", capsys=capsys)
    assert rc == 2 and "not on origin" in out


def test_tag_that_moved_is_refused(world, capsys):
    (world.dev / "ops/halt.py").write_text("# moved\n")
    git("commit", "-qam", "moved", cwd=world.dev)
    git("tag", "-f", "-a", "v1", "-m", "moved", cwd=world.dev)
    rc, out = world.run(capsys=capsys)
    assert rc == 2 and "must not move" in out


def test_tag_without_the_session_package_is_refused(world, capsys):
    world.commit_and_tag("v2", lambda d: (d / "quantt/session/__main__.py").unlink())
    rc, out = world.run("--apply", tag="v2", capsys=capsys)
    assert rc == 2 and "quantt/session/__main__.py" in out
    assert not world.layout.prod_dir.exists()


def test_template_is_read_at_the_tag_and_checked(world, capsys):
    """An edited schedule at the tag is refused, even if the working tree is fine."""
    rel = ip.JOBS[0].template

    def edit(d):
        t = (d / rel).read_text()
        (d / rel).write_text(t.replace("<integer>30</integer>", "<integer>45</integer>", 1))
    world.commit_and_tag("v2", edit)
    (world.dev / rel).write_text((REAL_REPO / rel).read_text())   # tree restored, tag not
    rc, out = world.run(tag="v2", capsys=capsys)
    assert rc == 2 and "StartCalendarInterval" in out


def test_bad_tag_name_is_refused(world, capsys):
    rc, out = world.run(tag="v1^{}", capsys=capsys)
    assert rc == 2 and "not a plain tag name" in out


# -- the key file -----------------------------------------------------------

def test_missing_env_file_is_refused(world, capsys):
    rc, out = world.run(env_file=world.tmp / "nope.env", capsys=capsys)
    assert rc == 2 and "does not exist" in out


def test_relative_env_file_is_refused(world, capsys):
    rc, out = world.run(env_file=Path("config/.env"), capsys=capsys)
    assert rc == 2 and "absolute" in out


def test_loose_env_file_mode_warns(world, capsys, no_reading_keys):
    os.chmod(world.keys, 0o644)
    rc, out = world.run(capsys=capsys)
    assert rc == 0 and "WARNING" in out and "0o644" in out


def test_private_env_file_does_not_warn(world, capsys):
    rc, out = world.run(capsys=capsys)
    assert rc == 0 and "WARNING" not in out


def test_env_file_under_downloads_warns(world, capsys):
    f = world.home / "Downloads" / "repo" / "config" / ".env"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    os.chmod(f, 0o600)
    rc, out = world.run(env_file=f, capsys=capsys)
    assert rc == 0 and "privacy-protected" in out


def test_env_file_inside_prod_is_refused(world, capsys):
    world.run("--apply", capsys=capsys)
    f = world.layout.prod_dir / "keys.env"
    f.write_text("x")
    os.chmod(f, 0o600)
    rc, out = world.run(env_file=f, capsys=capsys)
    assert rc == 2 and "inside the prod clone" in out


# -- timezone ---------------------------------------------------------------

def test_non_new_york_zone_is_refused(world, capsys):
    world.set_tz("America/Toronto")
    rc, out = world.run(capsys=capsys)
    assert rc == 2 and "America/Toronto" in out and "--accept-timezone" in out


def test_equivalent_zone_accepted_only_when_named(world, capsys):
    world.set_tz("America/Toronto")
    rc, out = world.run("--accept-timezone", "America/Toronto", capsys=capsys)
    assert rc == 0, out
    assert "accepted by --accept-timezone" in out


def test_accept_timezone_must_name_the_measured_zone(world, capsys):
    world.set_tz("America/Toronto")
    rc, out = world.run("--accept-timezone", "America/Detroit", capsys=capsys)
    assert rc == 2 and "does not match" in out


def test_non_equivalent_zone_is_refused_even_when_named(world, capsys):
    world.set_tz("America/Chicago")
    rc, out = world.run("--accept-timezone", "America/Chicago", capsys=capsys)
    assert rc == 2 and "differs from America/New_York" in out


def test_offset_check_catches_a_dst_difference():
    # Toronto keeps New York's offsets; Phoenix (no DST) matches New York's
    # standard-time offset in winter only, so a check sampling one date could pass it.
    assert ip.offset_mismatches("America/Toronto", NOW, 24 * 731) == []
    assert ip.offset_mismatches("America/Phoenix", NOW, 24 * 731) != []


# -- the old prod -----------------------------------------------------------

def test_layout_on_the_retired_prod_is_refused(world, capsys):
    class OnOldProd(ip.Layout):
        @property
        def prod_dir(self):
            return self.home / "prod" / "quantt"          # same dir as QUANTT on APFS
    world.layout = OnOldProd(world.home)
    rc, out = world.run(capsys=capsys)
    assert rc == 2 and "retired IBKR prod" in out


def test_default_layout_is_not_the_retired_prod():
    lay = ip.Layout(Path("/Users/x"))
    assert lay.prod_dir == Path("/Users/x/prod/quantt-alpaca")
    assert not ip._under(lay.prod_dir, lay.old_prod)


# -- rendering --------------------------------------------------------------

def test_missing_placeholder_value_raises():
    with pytest.raises(ip.InstallRefused, match="ENV_FILE"):
        ip.render("<string>${ENV_FILE}</string>", {"PYTHON": "/x"})


def test_values_are_xml_escaped():
    assert ip.render("<string>${A}</string>", {"A": "a & <b>"}) == \
        "<string>a &amp; &lt;b&gt;</string>"


def test_real_templates_render_and_pass_their_checks(tmp_path):
    lay = ip.Layout(tmp_path)
    py = Path(sys.executable)
    env = ip.expected_env("1", lay, tmp_path / "k.env", py)
    for job in ip.JOBS:
        text = ip.render((REAL_REPO / job.template).read_text(),
                         {"TAG": "vX", "PYTHON": py, "PROD_DIR": lay.prod_dir,
                          "DRY_RUN": "1", "STATE_DIR": lay.state_dir,
                          "ENV_FILE": tmp_path / "k.env", "PATH": env["PATH"],
                          "LOG_DIR": lay.log_dir})
        ip.check_rendered(text, job, python=py, layout=lay, env=env)


# -- drift guards -----------------------------------------------------------

def test_seed_files_match_the_live_code():
    """SEED_FILES was found by reading the sleeve and fetch_daily. If either
    starts naming another data file, this fails and the list is decided again."""
    named = set()
    for rel in ("src/deploy/sleeves/cef_discount.py", "scripts/cef/fetch_daily.py"):
        named |= set(re.findall(r"[A-Za-z0-9_]+\.(?:parquet|csv)",
                                (REAL_REPO / rel).read_text()))
    assert named == set(ip.SEED_FILES) | set(ip.SEED_WRITE_ONLY)


def test_installer_has_no_broker_or_session_import():
    import ast
    tree = ast.parse(Path(ip.__file__).read_text())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    assert not {m for m in mods if m.startswith(("quantt", "requests", "dotenv", "src"))}
