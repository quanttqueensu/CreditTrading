"""The builder's provenance: every figure carries a footer naming its sources, commit and
data last date; the manifest lists every output with its inputs' sha256; an uncommitted
input is refused unless --allow-dirty; a missing input is PENDING, never faked.

Everything runs against a throwaway git repository in tmp_path with synthetic files, so
the test says nothing about the market and touches nothing in this repository.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from scripts.report import build_pack as bp
from scripts.report.common import PackError, sha256_file


def _repo(tmp: Path) -> Path:
    r = tmp / "repo"
    (r / "results" / "report").mkdir(parents=True)
    (r / "results" / "x.json").write_text(json.dumps({"v": 1}))
    env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), *env, "commit", "-q", "-m", "init"], check=True)
    return r


def test_footer_and_manifest_record_provenance(tmp_path):
    r = _repo(tmp_path)
    b = bp.Build(repo=r)
    b._current = []
    p = b.file("results/x.json")
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    b.save_fig(fig, "FX_test", "a test figure", ["results/x.json"], "2022-12-30")
    texts = [t.get_text() for t in fig.texts]
    assert any("results/x.json" in t and b.short in t and "2022-12-30" in t for t in texts)
    out = r / "results" / "report" / "figures" / "FX_test.png"
    assert out.exists()
    rec = b.outputs[0]
    assert rec["inputs"] == ["results/x.json"] and rec["sha256"] == sha256_file(out)
    assert b.inputs["results/x.json"] == {"sha256": sha256_file(p), "committed": True}
    b.save_table(pd.DataFrame({"a": [1]}), "TX_test", "a test table", ["results/x.json"], "2022-12-30")
    assert {o["id"] for o in b.outputs} == {"FX_test", "TX_test"}


def test_uncommitted_input_is_refused_unless_allowed(tmp_path):
    r = _repo(tmp_path)
    (r / "results" / "x.json").write_text(json.dumps({"v": 2}))          # dirty
    with pytest.raises(PackError, match="not committed"):
        bp.Build(repo=r).file("results/x.json")
    b = bp.Build(repo=r, allow_dirty=True)
    b.file("results/x.json")
    assert b.inputs["results/x.json"]["committed"] is False
    fig, _ = plt.subplots()
    b.save_fig(fig, "FX", "t", ["results/x.json"], "2022-12-30")
    assert any("UNCOMMITTED INPUT" in t.get_text() for t in fig.texts)


def test_missing_input_is_pending_not_faked(tmp_path):
    b = bp.Build(repo=_repo(tmp_path))
    with pytest.raises(bp.Pending, match="needs-this"):
        b.file("results/absent.json", needs="needs-this")
    assert b.outputs == []


def test_markdown_table_reader_takes_the_named_section():
    text = ("## Components\n\n| component | USD |\n|---|---:|\n| hold (q) | −667.27 |\n| fill (x) | −308.71 (−5.5bp) |"
            "\n\nNotes\n\n## Other\n\n| a | b |\n|---|---|\n| z | 1 |\n")
    df = bp._md_table(text, "Components")
    assert list(df.iloc[:, 0]) == ["hold (q)", "fill (x)"]
    assert bp._usd(df.iloc[1, 1]) == -308.71
