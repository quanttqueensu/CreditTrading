"""The account's base currency is CAD (staging on the VM, 2026-11-26): buying power and net liquidation are
converted with IBKR's OWN ExchangeRate for USD, its direction checked against IBKR's own ledger, and a
missing, non-finite or contradicted rate refuses. The figures are the probe's shape, not market claims."""
from __future__ import annotations

import io
import json

from quantt.broker import ibkr as I
from quantt.twin import run
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_send import armed, world_and_books

NLV, BP = 1_006_590.13, 3_164_814.97
LEDGER = {"BASE": (1.0, NLV), "CAD": (1.0, NLV - 700_000.0), "USD": (1.40, 500_000.0)}   # 500k USD x 1.40 = 700k CAD


def cad_world(**kw):
    w = F.World()
    w.base, w.nlv, w.bp = "CAD", NLV, BP
    for k, v in kw.items():
        setattr(w, k, v)
    return w


def summary(w):
    return I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT), mode="read", ib_module=F.stub_module(w),
                        sleep=lambda s: None).connect().account_summary()


def test_a_cad_account_with_the_usd_rate_row_converts_with_it():
    s = summary(cad_world(ledger=LEDGER))
    fx = s["fx"]
    assert fx["source"] == "accountSummary" and fx["base_per_usd"] == 1.40 and fx["tag"] == "ExchangeRate"
    assert fx["direction_check"].startswith("consistent")
    assert abs(s["usd_per_base"] - 1 / 1.40) < 1e-12                        # USD = CAD / rate


def test_the_subscription_row_is_used_when_the_summary_has_none_and_the_direction_is_unverified():
    s = summary(cad_world(usd_rate=1.40))
    assert s["fx"]["source"] == "accountValues" and s["fx"]["direction_check"].startswith("UNVERIFIED")
    assert abs(s["usd_per_base"] - 1 / 1.40) < 1e-12


def test_a_missing_nonfinite_or_contradicted_rate_gives_no_rate():
    assert summary(cad_world())["usd_per_base"] is None
    assert summary(cad_world(ledger={"USD": (float("nan"), 1.0)}))["usd_per_base"] is None
    assert summary(cad_world(ledger={"USD": (float("inf"), 1.0)}))["usd_per_base"] is None
    inverted = {**LEDGER, "USD": (1 / 1.40, 500_000.0)}                     # USD per CAD: the wrong way round
    s = summary(cad_world(ledger=inverted))
    assert s["usd_per_base"] is None and s["fx"]["direction_check"].startswith("CONTRADICTS")


def test_the_send_passes_buying_power_in_a_cad_account_and_records_the_rate(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.base, w.nlv, w.bp, w.ledger = "CAD", NLV, BP, LEDGER
    assert run.send(d) == run.EXIT_SENT, out.getvalue()
    send = run.started_send_record(st["twin"] / "2026-11-27")
    bp = send["buying_power"]
    assert bp["fx"]["base_per_usd"] == 1.40 and bp["fx"]["currency"] == "USD" and bp["fx"]["tag"] == "ExchangeRate"
    assert abs(bp["buying_power_usd"] - BP / 1.40) < 0.01


def test_the_send_refuses_when_the_row_is_missing(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.base, w.nlv, w.bp = "CAD", NLV, BP
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    rec_ = run.latest_send_record(st["twin"] / "2026-11-27")
    assert any(r["gate"] == "buying_power" and "no usable USD exchange rate" in r["detail"] for r in rec_["refusals"])


def test_the_nlv_check_converts_the_cad_net_liquidation_with_the_rate(tmp_path):
    import datetime as dt
    from quantt.twin import verify
    new, pnl = {"sleeves": {}}, {"cef": 0.0}
    summ = {"net_liquidation": NLV, "base_currency": "CAD", "usd_per_base": 1 / 1.40, "fx": {}}
    first = verify._nlv(tmp_path, summ, new, pnl, 0.0, 0, dt.date(2026, 11, 27))
    assert first["residual_usd"] is None and abs(first["net_liquidation_usd"] - NLV / 1.40) < 0.01
    later = {**summ, "net_liquidation": NLV + 1_400.0}                     # +1,400 CAD = +1,000 USD, no P&L
    r = verify._nlv(tmp_path, later, new, pnl, 0.0, 0, dt.date(2026, 11, 30))
    assert abs(r["residual_usd"] - 1_000.0) < 0.01
    none = verify._nlv(tmp_path, {**summ, "usd_per_base": None}, new, pnl, 0.0, 0, dt.date(2026, 12, 1))
    assert none["residual_usd"] is None and "UNMEASURED" in none["why"]


def test_the_probe_prints_the_rate_rows_and_never_the_account(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    w.base, w.nlv, w.bp, w.ledger = "CAD", NLV, BP, LEDGER
    d.out = io.StringIO()
    assert run.probe(d) == 0
    text = d.out.getvalue()
    assert "PROBE ExchangeRate rows: accountSummary BASE 1.0; accountSummary CAD 1.0; accountSummary USD 1.4" in text
    assert F.ACCOUNT not in text
    g = json.loads((st["twin"] / "status.json").read_text())["gateway"]
    assert g["fx"]["base_per_usd"] == 1.40 and g["fx"]["source"] == "accountSummary"
