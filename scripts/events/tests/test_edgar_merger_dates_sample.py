"""`edgar_merger_dates.date_deals(sample=...)` (added 2026-10-19 for E1's DG-E1-2) is a no-op by
default: with no sample it reads `crsp_sample()` exactly as before; with one, it never does.
Fakes only; no EDGAR, no CRSP."""
import pandas as pd
import pytest

from scripts.events import edgar_merger_dates as emd


class _Called(Exception):
    pass


def _fakes(monkeypatch):
    names = pd.DataFrame(columns=["cik", "company", "first", "last", "tok"])
    idx = pd.DataFrame(columns=["cik", "company", "form", "date_filed", "accession"])
    monkeypatch.setattr(emd, "name_table", lambda client, today: (names, idx))

    def boom():
        raise _Called
    monkeypatch.setattr(emd, "crsp_sample", boom)


def test_default_reads_crsp_sample(monkeypatch):
    _fakes(monkeypatch)
    with pytest.raises(_Called):
        emd.date_deals(None, None)


def test_a_given_sample_is_used_instead(monkeypatch):
    _fakes(monkeypatch)
    try:
        emd.date_deals(None, None, sample=pd.DataFrame(columns=["permno", "ticker", "comnam", "nwperm",
                                                                "a_ticker", "a_comnam", "dlstdt"]))
    except _Called:
        pytest.fail("crsp_sample() was called although a sample was given")
    except Exception:
        pass   # an empty sample has nothing to date; only the source of the sample is under test
