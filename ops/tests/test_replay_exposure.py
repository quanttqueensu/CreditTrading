"""ops/replay_exposure: recorded runs through today's gate 8, read from the records alone."""
import json

from ops import replay_exposure as rx

SPEC_P = {"max_gross_stress": 1.8, "max_gross_usd": 260_000.0}


def _send_day(tmp_path, *, live_equity, refusals, refit=False):
    """A send sized at the cap on 100,000 from flat (so it ADDS gross), sent on
    `live_equity`; `refit` records a send-time re-fit, as bp_shortfall = scale does."""
    day = tmp_path / "2026-01-07"
    (day / "runs").mkdir(parents=True)
    orders = [{"symbol": "AAA", "side": "buy", "qty": 9000, "leg": 1,
               "client_order_id": "cef-20260107-AAA-1", "current": 0, "target": 9000,
               "est_price": 10.0, "reason": "t", "time_in_force": "day"},
              {"symbol": "BBB", "side": "sell", "qty": 4500, "leg": 1,
               "client_order_id": "cef-20260107-BBB-1", "current": 0, "target": -4500,
               "est_price": 20.0, "reason": "t", "time_in_force": "day"}]
    (day / "plan.json").write_text(json.dumps({"equity": 100_000.0, "orders": orders,
                                               "closes": {"AAA": 10.0, "BBB": 20.0}}))
    (day / "runs" / "20260107T205201Z-run.json").write_text(json.dumps({
        "phase": "send", "exit": {"code": 11, "name": "REFUSED"}, "positions": {},
        "refusals": refusals,
        **({"bp_scale_at_send": {"kept": 1.0, "binding": None}} if refit else {}),
        "account": {"equity": live_equity, "buying_power": 1e9, "maintenance_margin": 0.0,
                    "long_market_value": 0.0, "short_market_value": 0.0}}))
    return tmp_path


THEN = [{"gate": "exposure", "detail": "projected gross $180,000.00 > max_gross_stress "
                                       "1.8 x equity $99,900.00"}]


def test_a_send_refused_then_on_live_equity_is_scaled_and_passes_now(tmp_path):
    """With a recorded re-fit (bp_shortfall = scale, prod's setting) the adding plan is
    scaled to 1.8 x the lower of sized and live equity (team lead 2026-10-11) and passes."""
    rows, every = rx.replay(_send_day(tmp_path, live_equity=99_900.0, refusals=THEN,
                                      refit=True), SPEC_P)
    (r,) = rows
    assert r["then"] and r["now"] == []
    assert r["refit"] == "max_gross_stress (on the lower of sized and live equity)"
    assert round(r["old_headroom"]) == -180                 # 1.8 x 99,900 - 180,000
    assert r["sized"] == 100_000.0 and r["after"] == 180_000.0
    assert every == {("2026-01-07", "send", "exposure"): 1}


def test_without_a_refit_an_adding_plan_past_the_live_cap_is_still_refused(tmp_path):
    rows, _ = rx.replay(_send_day(tmp_path, live_equity=99_900.0, refusals=THEN), SPEC_P)
    (r,) = rows
    assert len(r["now"]) == 1 and "live equity" in r["now"][0]


def test_a_record_missing_a_field_is_skipped_and_says_which(tmp_path):
    state = _send_day(tmp_path, live_equity=100_000.0, refusals=[])
    f = next((state / "2026-01-07" / "runs").glob("*.json"))
    rec = json.loads(f.read_text())
    del rec["account"]["buying_power"]
    f.write_text(json.dumps(rec))
    (r,) = rx.replay(state, SPEC_P)[0]
    assert r["skipped"] == "account lacks ['buying_power']"
