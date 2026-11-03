"""Print every table of REPORT.md from results.json (report only, 2026-11-03).

No number in the report is typed by hand: each table there is this script's
output for its section, pasted. Run third_rule.py first.

    python3 results/backtests/thin-third-rule-2026-11-03/tables.py > /dev/stdout
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
J = json.loads((HERE / "results.json").read_text())
COSTS = ("5", "15", "30")
WIN = ("2005-09", "2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+", "full")
FLIPS = ("instant", "deferred")
MAIN = ("hold", "flatten", "te4")


def f2(x, d=2):
    return "n/a" if x is None or x != x else f"{x:.{d}f}"


def pc(x, d=2, sign=False):
    if x is None or x != x:
        return "n/a"
    return f"{x * 100:+.{d}f}" if sign else f"{x * 100:.{d}f}"


def section(t):
    print(f"\n#### {t}\n")


def answer():
    section("A. which rule scored higher, gross ann % (instant / deferred)")
    T = J["table"]
    print("| window | hold | flatten | te4 | highest (instant) | highest (deferred) |")
    print("|---|---:|---:|---:|---|---|")
    for w in WIN[1:6]:
        cells, best = [], []
        for fl in FLIPS:
            v = {r: T[f"{r}/{fl}/{w}"]["ann"] for r in MAIN}
            best.append(max(v, key=v.get))
        for r in MAIN:
            cells.append(f"{pc(T[f'{r}/instant/{w}']['ann'])} / {pc(T[f'{r}/deferred/{w}']['ann'])}")
        print(f"| {w} | " + " | ".join(cells) + f" | {best[0]} | {best[1]} |")


def leaders():
    section("A2. the leading rule by metric (hold / flatten / te4); instant, then deferred")
    T = J["table"]
    mets = (("gross ann", lambda s: s["ann"]), ("SR", lambda s: s["sr"]),
            ("net @5", lambda s: s["net"]["5"]), ("net @15", lambda s: s["net"]["15"]),
            ("net @30", lambda s: s["net"]["30"]), ("maxDD (shallowest)", lambda s: s["maxdd"]),
            ("vol-matched ann", lambda s: s["vm"]["ann"]))
    print("| window | " + " | ".join(m for m, _ in mets) + " |")
    print("|---|" + "---|" * len(mets))
    for w in WIN[1:6]:
        cells = []
        for _, fn in mets:
            lead = []
            for fl in FLIPS:
                v = {r: fn(T[f"{r}/{fl}/{w}"]) for r in MAIN}
                lead.append(max(v, key=v.get))
            cells.append(" / ".join(lead))
        print(f"| {w} | " + " | ".join(cells) + " |")


def scoreboard(key="table", rules=MAIN, wins=WIN):
    section(f"B. scoreboard ({key}): gross headline; net = ann - turn x c (real-money view, labelled); no borrow")
    T = J[key]
    print("| window | rule | flips | SR | ann % | vol % | maxDD % | turn/yr | net %/yr @5 / @15 / @30 | BE bp | "
          "sign flips at | vol-matched ann % (net @15) |")
    print("|---|---|---|---:|---:|---:|---:|---:|---|---:|---|---|")
    for w in wins:
        for r in rules:
            for fl in FLIPS:
                s = T.get(f"{r}/{fl}/{w}")
                if s is None:
                    continue
                if s["flat"]:
                    print(f"| {w} | {r} | {fl} | flat: nothing held | | | | {s['turn']:.1f} | | | | |")
                    continue
                nets = " / ".join(pc(s["net"][c]) for c in COSTS)
                fl_ = f"{s['flip_bp']}bp" if s["flip_bp"] else "no"
                print(f"| {w} | {r} | {fl} | {s['sr']:.2f} | {pc(s['ann'])} | {pc(s['vol'])} | {pc(s['maxdd'], 1)} | "
                      f"{s['turn']:.1f} | {nets} | {s['be']:.1f} | {fl_} | {pc(s['vm']['ann'])} "
                      f"({pc(s['vm']['net']['15'])}) |")


def paired():
    section("C. paired daily difference te4 minus each rule, pp/yr (NW t)")
    P = J["paired_te4"]
    print("| window | - flatten, instant | - flatten, deferred | - hold, instant | - hold, deferred |")
    print("|---|---|---|---|---|")
    for w in WIN[1:]:
        cells = [f"{pc(P[f'{r}/{fl}/{w}']['pp'], sign=True)} ({f2(P[f'{r}/{fl}/{w}']['t'])})"
                 for r in ("flatten", "hold") for fl in FLIPS]
        print(f"| {w} | " + " | ".join(cells) + " |")


def net_gaps():
    section("D. te4 minus each rule after the cost grid, pp/yr (instant; from B), and where the sign flips")
    T = J["table"]
    print("| window | vs | gross | @5 | @15 | @30 | sign flips? |")
    print("|---|---|---:|---:|---:|---:|---|")
    for w in WIN[1:6]:
        for r in ("flatten", "hold"):
            a, b = T[f"te4/instant/{w}"], T[f"{r}/instant/{w}"]
            g = a["ann"] - b["ann"]
            n = [a["net"][c] - b["net"][c] for c in COSTS]
            fl = next((c for c, v in zip(COSTS, n) if (v > 0) != (g > 0)), None)
            print(f"| {w} | {r} | {pc(g, sign=True)} | " + " | ".join(pc(v, sign=True) for v in n)
                  + f" | {('yes, ' + fl + 'bp') if fl else 'no'} |")


def thin_only():
    section("E. gross on thin-decision earning days and on active ones, ann % of the window (instant / deferred)")
    X = J["thin_only"]
    print("| window | thin earning days | hold thin | hold active | flatten thin | flatten active | te4 thin | te4 active |")
    print("|---|---:|---|---|---|---|---|---|")
    for w in WIN[1:]:
        cells = []
        for r in MAIN:
            for k in ("thin", "active"):
                cells.append(f"{pc(X[f'{r}/instant/{w}'][k])} / {pc(X[f'{r}/deferred/{w}'][k])}")
        print(f"| {w} | {X[f'hold/instant/{w}']['thin_days']} | " + " | ".join(cells) + " |")


def turnover():
    section("F. turnover (H2) and the matched rows")
    T, C, M = J["table"], J["era_turnover_cv"], J["matched"]
    print("| window | hold | flatten | te4 | te4 vs flatten | te4 vs hold |")
    print("|---|---:|---:|---:|---:|---:|")
    for w in WIN[1:]:
        t = {r: T[f"{r}/instant/{w}"]["turn"] for r in MAIN}
        print(f"| {w} | {t['hold']:.1f} | {t['flatten']:.1f} | {t['te4']:.1f} | "
              f"{(t['te4'] / t['flatten'] - 1) * 100:+.0f}% | {(t['te4'] / t['hold'] - 1) * 100:+.0f}% |")
    print("\nera turnover sd/mean (H5, instant, over the eras each rule traded): "
          + "; ".join(f"{r} {C[r]['cv']:.2f} ({C[r]['n_eras']} eras)" for r in ("hold", "flatten", "te3", "te4", "te5")))
    print("\n| matched to | te4 band | te4 FIT turn | ref FIT turn | window | te4 SR / ann % / net @5, @15, @30 | ref SR / ann % / net @5, @15, @30 |")
    print("|---|---:|---:|---:|---|---|---|")
    for ref in ("flatten", "hold"):
        m = M[ref]
        for w in ("FIT <2023", "H13 2023+"):
            a, b = m[w]["te"], m[w]["ref"]
            print(f"| {ref} | {m['band']:.4f} | {m['matched_turn']:.2f} | {m['ref_turn']:.2f} | {w} (turn {a['turn']:.1f} "
                  f"vs {b['turn']:.1f}) | {a['sr']:.2f} / {pc(a['ann'])} / " + ", ".join(pc(a["net"][c]) for c in COSTS)
                  + f" | {b['sr']:.2f} / {pc(b['ann'])} / " + ", ".join(pc(b["net"][c]) for c in COSTS) + " |")


def plateau():
    section("G. the floor's plateau (H8): te3 / te4 / te5 minus flatten and minus hold, instant, pp/yr (NW t)")
    P, S, TT = J["plateau"], J["plateau_per_session"], J["traded_thin"]
    print("| window | te3 - flatten | te4 - flatten | te5 - flatten | te3 - hold | te4 - hold | te5 - hold |")
    print("|---|---|---|---|---|---|---|")
    for w in ("2005-09", "2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+"):
        cells = [f"{pc(P[f'te{f}-{r}/{w}']['pp'], sign=True)} ({f2(P[f'te{f}-{r}/{w}']['t'])})"
                 for r in ("flatten", "hold") for f in (3, 4, 5)]
        print(f"| {w} | " + " | ".join(cells) + " |")
    print("\n| floor | thin sessions traded (all / FIT eras 2005-09, 10-14, 15-19, 20-22 / 2023+) | FIT share | "
          "per unit share vs flatten | vs hold |")
    print("|---|---|---:|---:|---:|")
    for f in ("3", "4", "5"):
        t = TT[f]
        s = S[f]
        print(f"| {f} | {sum(t[w] for w in ('2005-09', '2010-14', '2015-19', '2020-22', '2023+'))} / {t['2005-09']}, "
              f"{t['2010-14']}, {t['2015-19']}, {t['2020-22']} / {t['2023+']} | {pc(s['share'], 1)}% | "
              f"{pc(s['flatten']['per_share'], sign=True)} | {pc(s['hold']['per_share'], sign=True)} |")


def concentration():
    section("H. concentration on thin sessions (book as decided, instant): mean / median / p90 / max [sessions]")
    C = J["concentration"]
    print("| rule | window | set | names held | max single-name abs weight | gross |")
    print("|---|---|---|---|---|---|")
    for r in ("te4", "hold"):
        for w in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+"):
            for s in ("thin", "active"):
                o = C.get(f"{r}/{s}/{w}")
                if o is None:
                    continue
                q = lambda d, k=2: "/".join(f"{d[x]:.{k}f}" for x in ("mean", "median", "p90", "max"))   # noqa: E731
                print(f"| {r} | {w} | {s} [{o['sessions']}] | {q(o['names'], 1)} | {q(o['maxw'], 3)} | {q(o['gross'], 3)} |")
    t = C["target_reduced"]
    print(f"\nte4 TARGET on the {t['sessions']} thin sessions it trades (count: {t['by_n']}): single-fund side on "
          f"{pc(t['single_name_side_share'], 1)}% (" + ", ".join(f"n={k}: {pc(v, 1)}%" for k, v in
                                                            t["single_name_side_share_by_n"].items())
          + f"); max abs weight median {t['maxw_median']:.3f}, p90 {t['maxw_p90']:.3f}; gross median "
          f"{t['gross_median']:.3f}; 0/0 rows {t['degenerate_zero_rows']}")


def leave_out():
    section("I. leave one name out (attribution), te4 minus flatten and minus hold, instant, pp/yr (NW t)")
    for ref in ("flatten", "hold"):
        L = J[f"leave_out_vs_{ref}"]
        ws = ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+")
        print(f"\nvs {ref}:\n")
        print("| left out | " + " | ".join(ws) + " |")
        print("|---|" + "---|" * len(ws))
        for k, row in L.items():
            print(f"| {k} | " + " | ".join(f"{pc(row[w]['pp'], sign=True)} ({f2(row[w]['t'])})" for w in ws) + " |")
    R = J["rebuilt"]
    print("\nrebuilt universes (targets, masks and books recomputed):\n")
    print("| without | thin sessions | below floor 4 | FIT te4 - flatten | FIT te4 - hold | 2015-19 te4 - flatten | "
          "H13 te4 - flatten |")
    print("|---|---:|---:|---|---|---|---|")
    for k, r in R.items():
        c = lambda w, x: f"{pc(r[w][x]['pp'], sign=True)} ({f2(r[w][x]['t'])})"      # noqa: E731
        print(f"| {k} | {r['thin']} | {r['below_floor']} | {c('FIT <2023', 'te4-flatten')} | {c('FIT <2023', 'te4-hold')} | "
              f"{c('2015-19', 'te4-flatten')} | {c('H13 2023+', 'te4-flatten')} |")


def borrow():
    section("J. borrow (charged nowhere else): break-even and the IBKR panel where it exists")
    B = J["borrow"]
    print("| vs | window | gross gap pp/yr | mean extra short weight | uniform fee that erases the gap |")
    print("|---|---|---:|---:|---:|")
    for k, v in B["breakeven"].items():
        ref, w = k.split("/")
        fee = f"{v['fee'] * 100:.1f}%/yr" if v["extra_short"] > 0 else "none (no extra short)"
        print(f"| {ref} | {w} | {pc(v['gap'], sign=True)} | {v['extra_short']:+.3f} | {fee} |")
    print("\n| measured window | borrow hold / flatten / te4 (%/yr of NAV) | te4 - flatten gross -> net | te4 - hold gross -> net |")
    print("|---|---|---|---|")
    for w, v in B["measured"].items():
        b = v["borrow"]
        print(f"| {w} | {pc(b['hold'])} / {pc(b['flatten'])} / {pc(b['te4'])} | {pc(v['gap']['flatten'], sign=True)} -> "
              f"{pc(v['net']['flatten'], sign=True)} | {pc(v['gap']['hold'], sign=True)} -> {pc(v['net']['hold'], sign=True)} |")
    print("\nFIT mean extra short weight by name: " + "; ".join(
        f"vs {ref}: " + ", ".join(f"{t} {x:+.3f}" for t, x in sorted(d.items(), key=lambda kv: -kv[1]))
        for ref, d in B["extra_by_name"].items()))


def attacks():
    section("K. attacks on te4's gap")
    A = J["attack"]
    print("| window | te4 thin ann % | eligible names | band residues | residue gross | price leg | distribution leg | "
          "beta to EW universe | alpha part (NW t) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for w in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+"):
        a, c = A["a_split"][w], A["c_legs_beta"][w]
        print(f"| {w} | {pc(a['thin'])} | {pc(a['elig'])} | {pc(a['resid'])} | {a['resid_gross']:.3f} | {pc(c['price'])} | "
              f"{pc(c['dist'])} | {c['beta']:+.3f} | {pc(c['alpha'])} ({f2(c['t'])}) |")
    print("\nby eligible count at the decision (ann % of the window; per thin earning day x 252; NW t) [days]:\n")
    print("| window | n = 4 | n = 5 |")
    print("|---|---|---|")
    for w in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+"):
        c = A["a_by_count"][w]
        print(f"| {w} | " + " | ".join(f"{pc(c[k]['ann'], sign=True)}; {pc(c[k]['per_day'], sign=True)}; t {f2(c[k]['t'])} "
                                       f"[{c[k]['days']}]" for k in ("4", "5")) + " |")
    print("\nstale-price signature, share of held name-days with a total return of exactly 0 (zero-volume share in "
          "brackets):\n")
    print("| window | thin, eligible | thin, residue | active, eligible | active, residue |")
    print("|---|---|---|---|---|")
    for w in ("2010-14", "2015-19", "2020-22", "FIT <2023", "H13 2023+"):
        b = A["b_stale"][w]
        print(f"| {w} | " + " | ".join(f"{pc(b[k]['zero'])}% ({pc(b[k]['vol0'])}%) [{b[k]['n']}]"
                                       for k in ("thin/elig", "thin/resid", "active/elig", "active/resid")) + " |")
    print("\n| vs | FIT stretches | run t | positive | sign-flip p | largest stretch (share) | best 10 days / total pp | "
          "t without them | bar N=52 / 53 / 54 | paired t | read_result (Sidak) |")
    print("|---|---:|---:|---|---|---|---|---:|---|---:|---|")
    for ref in ("flatten", "hold"):
        o = A[f"d_f_vs_{ref}"]
        bars = " / ".join(f"{o['bars'][n]['bar']:.3f}" for n in ("52", "53", "54"))
        rr = o["bars"]["53"]
        print(f"| {ref} | {o['runs']} | {o['t_runs']:.2f} | {o['positive']}/{o['runs']} | {o['p_signflip']:.4f} "
              f"({o['p_how']}) | {pc(o['largest'])}pp ({o['largest_share'] * 100:.0f}%; {o['largest_run'][0]}.."
              f"{o['largest_run'][1]}) | {pc(o['best10_pp'])} / {pc(o['total_pp'])} | {o['t_without_best10']:.2f} | "
              f"{bars} | {J['paired_te4'][f'{ref}/instant/FIT <2023']['t']:.2f} | {rr['read']}"
              + (f" [{pc(rr['lo'])}, {pc(rr['hi'])}]" if rr["lo"] is not None else "") + " |")


def control():
    section("L. direction control (H12): te4's thin-day P&L against random within-session reassignments, ann %")
    D = J["direction_control"]
    print("| window | te4 | null mean | null sd | null 95th pct | P(null >= te4) |")
    print("|---|---:|---:|---:|---:|---:|")
    for w, o in D.items():
        print(f"| {w} | {pc(o['actual'], sign=True)} | {pc(o['null_mean'], sign=True)} | {pc(o['null_sd'])} | "
              f"{pc(o['p95'], sign=True)} | {o['p_ge']:.3f} |")


def degenerate():
    section("M. the two degenerate sessions replayed with the sleeve's hold (PR #33 5.H), ann % harness -> sleeve")
    D = J["degenerate_replay"]
    print(f"dates: {D['dates']}\n")
    print("| book | 2020-22 | FIT | H13 |")
    print("|---|---|---|---|")
    for r in MAIN:
        for fl in FLIPS:
            o = D[f"{r}/{fl}"]
            print(f"| {r} {fl} | " + " | ".join(f"{pc(o[w]['harness'])} -> {pc(o[w]['sleeve'])}"
                                                for w in ("2020-22", "FIT <2023", "H13 2023+")) + " |")
    for ref in ("flatten", "hold"):
        for fl in FLIPS:
            o = D[f"te4-{ref}/{fl}"]
            print(f"| te4 - {ref} {fl}, under the replay | " + " | ".join(
                f"{pc(o[w]['pp'], sign=True)} ({f2(o[w]['t'])})" for w in ("2020-22", "FIT <2023", "H13 2023+")) + " |")


def forward():
    section("N. forward relevance")
    F = J["forward"]
    print("| year | sessions | n = 4 | n = 5 | n = 6 | n = 7 | n >= 8 | min |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for y, v in F["by_year"].items():
        print(f"| {y} | {v['sessions']} | {v['n=4']} | {v['n=5']} | {v['n=6']} | {v['n=7']} | {v['n>=8']} | {v['min']} |")
    s, m = F["since_last_thin"], F["margin"]
    print(f"\nsince the last thin session ({s['last_thin']}): {s['sessions']} sessions; 6 eligible on {s['n6']} (last "
          f"{s['last_n6']}), 7 on {s['n7']} (last {s['last_n7']}). On the {m['sessions']} sessions since 2023 with 6 or 7 "
          f"eligible, the least liquid eligible name's ADV / floor: min {m['ratio_min']:.2f}, p10 {m['ratio_p10']:.2f}, "
          f"median {m['ratio_median']:.2f}; most often marginal: {m['marginal_name']}")
    print("\n| HYPOTHETICAL [U]: on those sessions, drop the least liquid eligible names until | sessions | flatten "
          "closes a held book of gross (median) | te4 target cosine to the full target, median (p10) | te4 target gross "
          "(median) | te4 max abs weight median (p90) |")
    print("|---|---:|---:|---|---:|---|")
    for k, h in F["hypothetical"].items():
        print(f"| {k.replace('dip_to_', '')} remain | {m['sessions'] - len(h['skipped'])} | {h['live_held_gross_median']:.3f} | "
              f"{h['cos_median']:.2f} ({h['cos_p10']:.2f}) | {h['gross_median']:.3f} | {h['maxw_median']:.3f} "
              f"({h['maxw_p90']:.3f}) |")
    h = F["h13_thin"]
    print(f"\nthe 2023+ thin sessions ({h['first']}..{h['last']}, {h['days']} earning days): " + "; ".join(
        f"{r} {pc(h[r]['pp_on_thin_days'], sign=True)}pp, mean gross {h[r]['gross_mean']:.3f}" for r in MAIN))
    e = F["expected"]
    print(f"\nEXPECTED ANNUAL EFFECT [U] (unit book; at {e['tag']} the book is m = {e['m']} times the unit book):\n")
    print("| base | gap pp/yr (deferred) | share traded | per unit share (deferred) | forward share | gross unit "
          "(at m) | extra turnover cost @15bp, unit |")
    print("|---|---|---:|---|---|---|---:|")
    for b in e["bases"]:
        for sk, sv in e["shares"].items():
            g = b["per_share"] * sv
            print(f"| {b['window']} | {pc(b['gap'], sign=True)} ({pc(b['gap_deferred'], sign=True)}) | {pc(b['share'], 1)}% | "
                  f"{pc(b['per_share'], sign=True)} ({pc(b['per_share_deferred'], sign=True)}) | {sk}: {pc(sv, 1)}% | "
                  f"{pc(g, sign=True)} ({pc(g * e['m'], sign=True)}) | {pc(b['extra_turn_per_share'] * sv * 15 / 1e4)} |")


def checks():
    section("O. second methods")
    s = J["sleeve_check"]
    print(f"live sleeve on all {s['thin']} thin sessions (min_names lowered to 3 in memory): below the floor on "
          f"{s['below']}; traded on {s['traded']}; equal to the harness after the ceiling on {s['clean']} to "
          f"{s['max_abs_diff_clean']:.1e}; min-weight block acts on {s['minw_rows']} (by count {s['minw_by_n']}; at "
          f"floor 4: {s['minw_by_n_floor4']}), max abs weight difference there {s['max_abs_diff_minw']:.4f}")


if __name__ == "__main__":
    answer()
    leaders()
    scoreboard()
    paired()
    net_gaps()
    thin_only()
    turnover()
    scoreboard("table_plateau", ("te3", "te4", "te5"), ("2005-09", "2010-14", "2015-19", "2020-22", "FIT <2023",
                                                        "H13 2023+"))
    plateau()
    concentration()
    leave_out()
    borrow()
    attacks()
    control()
    degenerate()
    forward()
    checks()
