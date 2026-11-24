"""scripts/data/team_data.py against an in-memory bucket: no network, no credentials.

What matters is what the analysts' copy can never become: a mix of two pushes, a
file of theirs silently replaced, or a write outside data/.
"""
import io
import json
from pathlib import Path

import pytest

from scripts.data import team_data as T


class _NoSuchKey(Exception):
    pass


class FakeClient:
    """The five S3 calls team_data makes, on a dict. Records the order of writes."""

    class exceptions:
        NoSuchKey = _NoSuchKey

    def __init__(self):
        self.store, self.writes = {}, []

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise _NoSuchKey(Key)
        return {"Body": io.BytesIO(self.store[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.store[Key] = Body
        self.writes.append(Key)

    def upload_file(self, Filename, Bucket, Key):
        self.store[Key] = Path(Filename).read_bytes()
        self.writes.append(Key)

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.store[Key])

    def list_objects_v2(self, Bucket, Prefix, Delimiter, ContinuationToken=None):
        """One "folder" per page, so the pagination is exercised."""
        subs = sorted({Prefix + k[len(Prefix):].split(Delimiter)[0] + Delimiter
                       for k in self.store if k.startswith(Prefix) and Delimiter in k[len(Prefix):]})
        i = int(ContinuationToken or 0)
        page = {"CommonPrefixes": [{"Prefix": p} for p in subs[i:i + 1]], "IsTruncated": i + 1 < len(subs)}
        if page["IsTruncated"]:
            page["NextContinuationToken"] = str(i + 1)
        return page


def _tree(root: Path, files: dict) -> Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return root


@pytest.fixture
def src(tmp_path):
    return _tree(tmp_path / "src", {"cef/prices.parquet": b"P1", "cef/nav.parquet": b"N1",
                                    "etf.parquet.pre-20261011.bak": b"old",
                                    ".DS_Store": b"x", "cef/.hidden": b"x"})


def test_push_without_go_sends_nothing(src):
    c = FakeClient()
    T.push(c, "b", src, go=False)
    assert c.writes == []


def test_push_skips_backups_and_dotfiles_and_writes_the_manifest_last(src):
    c = FakeClient()
    T.push(c, "b", src, go=True)
    assert c.writes[-1] == T.MANIFEST_KEY
    assert sorted(c.writes[:-1]) == ["team-data/cef/nav.parquet", "team-data/cef/prices.parquet"]
    paths = [e["path"] for e in json.loads(c.store[T.MANIFEST_KEY])["files"]]
    assert paths == ["cef/nav.parquet", "cef/prices.parquet"]


def test_a_second_push_uploads_only_what_changed(src):
    c = FakeClient()
    T.push(c, "b", src, go=True)
    (src / "cef/nav.parquet").write_bytes(b"N2")
    c.writes.clear()
    T.push(c, "b", src, go=True)
    assert c.writes == ["team-data/cef/nav.parquet", T.MANIFEST_KEY]


def test_pull_reproduces_the_pushed_files(src, tmp_path):
    c = FakeClient()
    T.push(c, "b", src, go=True)
    dst = tmp_path / "dst"
    assert T.pull(c, "b", dst, overwrite=False) == 2
    assert (dst / "cef/prices.parquet").read_bytes() == b"P1"
    assert not (dst / ".DS_Store").exists()
    assert T.pull(c, "b", dst, overwrite=False) == 0       # identical: nothing to do


def test_pull_refuses_to_overwrite_a_different_file_and_downloads_nothing(src, tmp_path):
    c = FakeClient()
    T.push(c, "b", src, go=True)
    dst = _tree(tmp_path / "dst", {"cef/nav.parquet": b"MINE"})
    with pytest.raises(T.TeamDataError, match="cef/nav.parquet"):
        T.pull(c, "b", dst, overwrite=False)
    assert (dst / "cef/nav.parquet").read_bytes() == b"MINE"
    assert not (dst / "cef/prices.parquet").exists()
    T.pull(c, "b", dst, overwrite=True)
    assert (dst / "cef/nav.parquet").read_bytes() == b"N1"


def test_pull_raises_when_a_file_does_not_match_its_checksum(src, tmp_path):
    c = FakeClient()
    T.push(c, "b", src, go=True)
    c.store["team-data/cef/prices.parquet"] = b"half a push"
    with pytest.raises(T.TeamDataError, match="checksum"):
        T.pull(c, "b", tmp_path / "dst", overwrite=False)
    assert not list((tmp_path / "dst").rglob("*.part"))


@pytest.mark.parametrize("bad", ["../escape.parquet", "/etc/passwd", "cef/../../x"])
def test_pull_never_writes_outside_data(tmp_path, bad):
    c = FakeClient()
    c.store[T.MANIFEST_KEY] = json.dumps(
        {"pushed_at": "t", "files": [{"path": bad, "bytes": 1, "sha256": "0"}]}).encode()
    with pytest.raises(T.TeamDataError, match="outside data/"):
        T.pull(c, "b", tmp_path / "dst", overwrite=False)


def test_pull_before_any_push_says_so(tmp_path):
    with pytest.raises(T.TeamDataError, match="nothing has been pushed"):
        T.pull(FakeClient(), "b", tmp_path / "dst", overwrite=False)


# ---- research handoffs (team lead, 2026-11-24): one folder per name, under team-research/

def test_a_handoff_has_its_own_prefix_and_manifest_and_never_touches_the_team_copy(src, tmp_path):
    c = FakeClient()
    T.push(c, "b", src, go=True)
    team_manifest = c.store[T.MANIFEST_KEY]
    h = _tree(tmp_path / "h", {"books.csv": b"B", "regime.py": b"R", ".DS_Store": b"x"})
    c.writes.clear()
    T.push(c, "b", h, go=True, prefix=T.handoff_prefix("regime_overlay_2026-11-24"))
    assert c.writes == ["team-research/regime_overlay_2026-11-24/books.csv",
                        "team-research/regime_overlay_2026-11-24/regime.py",
                        "team-research/regime_overlay_2026-11-24/MANIFEST.json"]
    assert c.store[T.MANIFEST_KEY] == team_manifest
    dst = tmp_path / "pulled"
    assert T.pull(c, "b", dst, overwrite=False, prefix=T.handoff_prefix("regime_overlay_2026-11-24")) == 2
    assert (dst / "books.csv").read_bytes() == b"B"
    assert sorted(p.name for p in dst.iterdir()) == ["books.csv", "regime.py"]


def test_handoffs_lists_every_name_across_pages(tmp_path):
    c = FakeClient()
    for n in ("b_two", "a_one", "c_three"):
        T.push(c, "b", _tree(tmp_path / n, {"x.csv": n.encode()}), go=True, prefix=T.handoff_prefix(n))
    T.push(c, "b", _tree(tmp_path / "d", {"cef/p.parquet": b"P"}), go=True)   # the team copy is not a handoff
    assert T.list_handoffs(c, "b") == ["a_one", "b_two", "c_three"]


@pytest.mark.parametrize("bad", ["", ".", "..", "../team-data", "a/b", "-x", ".hidden", "a b", "x\\y"])
def test_a_handoff_name_is_one_safe_segment(bad):
    with pytest.raises(T.TeamDataError, match="handoff name"):
        T.handoff_prefix(bad)


def test_a_handoff_pull_never_writes_outside_its_folder(tmp_path):
    c = FakeClient()
    pre = T.handoff_prefix("h")
    c.store[pre + "MANIFEST.json"] = json.dumps(
        {"pushed_at": "t", "files": [{"path": "../escape.csv", "bytes": 1, "sha256": "0"}]}).encode()
    with pytest.raises(T.TeamDataError, match="would write outside"):
        T.pull(c, "b", tmp_path / "h", overwrite=False, prefix=pre)
    assert not (tmp_path / "escape.csv").exists()


def test_a_handoff_never_pushed_says_so(tmp_path):
    with pytest.raises(T.TeamDataError, match="team-research/h/MANIFEST.json"):
        T.pull(FakeClient(), "b", tmp_path / "h", overwrite=False, prefix=T.handoff_prefix("h"))


@pytest.mark.parametrize("argv", [
    ["push", "--handoff", "h"],                       # a handoff push must name its folder
    ["push", "--from", "/tmp/x"],                     # --from without a handoff would replace the team copy
    ["push", "--handoff", "../x", "--from", "/tmp/x"],
    ["pull", "--into", "/tmp/x"],                     # --into is for handoffs only
    ["pull", "--handoff", "h", "--into", "relative/dir"],
])
def test_the_command_line_refuses_before_it_opens_a_client(argv, monkeypatch):
    def no_client():
        raise AssertionError("make_client called")
    monkeypatch.setattr(T, "make_client", no_client)
    with pytest.raises(SystemExit) as e:
        T.main(argv)
    assert e.value.code == 2


def test_the_command_line_pulls_a_handoff_into_quantt_research_by_default(monkeypatch, tmp_path):
    c = FakeClient()
    T.push(c, "b", _tree(tmp_path / "src", {"x.csv": b"X"}), go=True, prefix=T.handoff_prefix("h1"))
    monkeypatch.setattr(T, "make_client", lambda: (c, "b"))
    monkeypatch.setattr(T, "RESEARCH_HOME", tmp_path / "quantt_research")
    assert T.main(["pull", "--handoff", "h1"]) == 0
    assert (tmp_path / "quantt_research/h1/x.csv").read_bytes() == b"X"
