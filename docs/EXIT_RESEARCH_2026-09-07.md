# When to leave a trade — a systematic study of exit for the CEF book

**2026-09-07.** Reproduce: `scripts/cef/exit_study.py`.

---

## 0. The finding, before the argument

**Optimal holding period shortens as conviction rises.** Measured on 27 years,
net of a realistic round trip, the argmax of expected-return-per-unit-time is:

| entry \|z\| | optimal hold | net bp/day @30bp RT | n (non-overlapping) |
|---|---:|---:|---:|
| 0.5 – 1.0 | 60d | **+0.02** | 1,140 |
| 1.0 – 1.5 | 60d | +0.38 | 1,129 |
| 1.5 – 2.0 | **8d** | +2.31 | 909 |
| 2.0 – 2.5 | **5d** | +6.01 | 624 |
| 2.5 – 4.0 | **2d** | +12.31 | 375 |

This is the opposite of "hold your best ideas longest", and it is economically
right: a large dislocation converges *fast* in absolute terms at the same κ, so
it is harvested and released; a small one needs weeks merely to clear the spread.

**And a stop-loss destroys value here.** Conditioning on how a position moved in
the 5 days before the decision, forward 21-day trade return:

| since entry | n | forward | t |
|---|---:|---:|---:|
| **adverse, \|z\| widened >0.5** | 9,661 | **+63.9bp** | **9.39** |
| adverse, \|z\| widened | 16,568 | +39.5bp | 9.70 |
| favourable, \|z\| narrowed | 13,567 | +38.8bp | 8.65 |
| favourable, \|z\| narrowed >0.5 | 4,154 | +70.3bp | 6.23 |

The positions that went against us have the **highest** forward return of any
group. A stop-loss cuts exactly those. This is the defining property of a mean-
reverting book and it is why Leung & Li's stop-loss variant is the wrong member
of that family for us.

---

## 1. What we do now, and why it is not an exit rule

The sleeve has an entry rule (cross-sectional z), and since 2026-09-06 a
rebalance rule (the no-trade band). **It has no exit rule.** A position closes
only as a side effect of its target weight decaying. The holding period is
therefore an *output* of the signal, not a decision anyone made — currently
about 12 business days on average, uniform across every name and every level of
conviction.

The table in §0 says that uniform holding period is wrong at both ends: too
short for the low-conviction majority and roughly 6× too long for the strongest
signals.

---

## 2. The theory, and which paper actually applies

For a mean-reverting spread under proportional cost, the object to maximise is
**expected return per unit time**, not expected return
([Bertram 2010](https://www.sciencedirect.com/science/article/abs/pii/S0378437110001019)).
Bertram writes trade length and return as first-passage times of an OU process
and solves for entry/exit levels in closed form. The two objectives have
different maxima: holding longer always accumulates more convergence, but the
*rate* falls, and capital in a decayed position is capital not earning.

Our own data shows the gap starkly. At \|z\| ∈ [2.5,4.0): cumulative return peaks
at **h = 34d (134.1bp)**, but return per unit time peaks at **h = 2d**. Holding to
34 days earns four times as much in total and roughly a tenth as much per day.

**Cost is what makes this a real decision.** Ignoring it, the per-unit-time
optimum collapses to h = 1 for every conviction bucket — which at 16–27bp/day
gross against a 20–30bp round trip is how a book loses money quickly. Every
number in §0 is net of the round trip, and the optimum moves out by 1–2 orders
of magnitude in the low-conviction buckets when it is included.

[Leung & Li (2015)](https://arxiv.org/abs/1411.5062) solve the *double* stopping
problem — when to enter and when to liquidate — for an OU spread with
transaction costs and a stop-loss, and prove the entry region is a bounded
interval strictly above the stop-loss, with a higher stop-loss forcing a lower
optimal take-profit. Their machinery is right; **their stop-loss is empirically
wrong for this book**, per §0. The correct reading of their result for us is the
limiting case L → −∞, where the take-profit boundary is highest.

**Not applicable:** Almgren–Chriss (nothing to schedule at <1% participation) and
Gârleanu–Pedersen's quadratic-cost form (we pay proportional half-spread, not
impact). Both are already ruled out in `docs/PLAN.md` §6 for the same reasons.

---

## 3. Horizons — what is physically available

The user asks for intraday, daily, weekly and longer. The binding constraint is
not appetite, it is **when NAV exists**.

| horizon | available? | why |
|---|---|---|
| **Intraday entry** | **No** | The signal is price − NAV and a fund's NAV does not exist until after the close. There is no intraday discount to compute. This is structural, not a data gap. |
| **Intraday exit** | **Yes, and it is the only intraday edge we have** | Price moves all day against a *known* prior NAV. A position that converges intraday has earned its move without any new information. See §5. |
| **Daily / 2–8 day** | Yes | Where the high-conviction alpha lives (§0). |
| **Weekly–monthly (21–60d)** | Yes | Where the low-conviction alpha lives, and the only horizon at which \|z\| < 1.5 is worth holding at all. |
| **Quarterly+ / catalyst** | Yes, but it is a different trade | §4. |

The asymmetry is the important part: **we cannot enter intraday but we can exit
intraday.** Exit is a decision about a position we already hold, priced off a NAV
we already know.

---

## 4. Market structure — the exits that are not statistical

Three CEF-specific mechanisms close a discount for reasons the OU model does not
contain. They matter because they are *dated*, which makes them the one place a
long horizon is justified.

**Tax-loss selling and the January reversal.** Municipal-bond CEFs are held
overwhelmingly by tax-sensitive individuals. Starks, Yong & Zheng (2006, JF)
document a January effect in exactly this universe and tie it directly to
prior-year-end tax-loss selling, with abnormal January returns correlated to
year-end volume ([study](https://www.bus.umich.edu/pdf/mitsui/workshopdocs/ZhengJanuaryEffect.pdf);
[revisited 2024](https://onlinelibrary.wiley.com/doi/abs/10.1111/jfir.12384)).
**Six of our seventeen names are Nuveen munis.** A December widening in a muni
CEF is therefore not a random OU excursion — it has a known seasonal cause and a
known reversal window, and it argues for *extending* the hold through year-end
rather than exiting on the drawdown.

**Activism — the discrete exit.** Saba, Karpus and Bulldog run campaigns whose
usual settlement is a tender offer at or near NAV
([ICI 2025](https://www.ici.org/files/2025/cef-activism.pdf);
[Dividend.com](https://www.dividend.com/closed-end-funds-channel/rising-tide-of-cef-activism/)).
A fund at a 10% discount tendering at a 2% discount hands holders an instant 8%.
This is a **jump exit**: the discount does not revert, it gaps. It is strictly
good for our long leg and strictly bad for our short leg, and nothing in the
sleeve knows a campaign exists. Saba paused its UK campaign for three years in
May 2026 ([CNBC](https://www.cnbc.com/2026/05/07/saba-capital-herald-investment-trust-deal-activism-pause.html)),
so the intensity is time-varying and currently lower.

**Distribution cycles.** These funds pay monthly. The ex-date mechanically moves
price and not NAV, which injects a sawtooth into the discount that is not
dislocation. `docs/PLAN.md` §6 records two failed attempts to use distribution
data as a *signal*; using it as an **exit blackout** is a different and untested
question.

---

## 5. What to build

### 5.1 Conviction-dependent holding period — the main recommendation

The naive reading of §0 is "only trade \|z\| > 1.5". **That is wrong and the repo
already measured why**: every \|z\| threshold above zero *lowers* portfolio Sharpe
(0.81 → 0.40 → 0.29 → 0.27, `docs/PLAN.md` §3.1). Filtering on conviction
destroys breadth, and with BR_eff already 1.17–2.24 of 17 names we cannot afford
to lose names.

Per-name alpha and portfolio Sharpe are different objects. The resolution is to
keep every name and vary the **holding period** instead:

$$b_i \;=\; b_0 \cdot \left(\frac{h^*(|z_i|)}{\bar h}\right)^{1/3}$$

A wide band (long hold, rarely touched) for low conviction; a narrow band (short
hold, actively harvested) for high conviction. The exponent is the same cube-root
law that set the current 4.8% width, so this is one parameter, not a new model.

This is expressible in the existing sleeve — `band_width` becomes a vector rather
than a scalar — and it is the only proposal here that changes the live book.

### 5.2 Intraday exit on convergence

The one intraday edge available (§3). A position whose *price* has converged
toward the last published NAV has captured its move; the remaining expected
return is smaller and the position is now cheap to exit. Requires intraday
quotes, which **this account does not have** — error 10089, delayed data only.
That is a subscription, not research.

### 5.3 Do not build a stop-loss

§0 settles it: n = 26,229, t = 9.39, and the adverse bucket has the *highest*
forward return. This also matches the standing instruction not to add rules that
decide killing — here that instruction is not merely a preference, it is the
profit-maximising choice.

### 5.4 Calendar overlay — flagged, not recommended yet

The muni January reversal is well documented and six of our names qualify. But
`docs/PLAN.md` records two failures already built on seasonal/distribution data,
and this would be a third pass at the same class. It should be pre-registered
with a specific December/January window and tested **once**, on the 27 untouched
names, not swept.

---

## 6. Honest limits

1. **These are per-name statistics, not portfolio results.** They say what a
   position earns; they do not say what the book earns, because the book is
   cross-sectional and dollar-neutral. §5.1 is the only proposal that has been
   reasoned through to portfolio level, and it has not yet been backtested.
2. **Non-overlapping sampling shrinks n hard** — 375 entries in the top bucket
   over 27 years. The t-stats at long horizons in that bucket are ~2, and the
   cumulative return is non-monotonic in h (a dip at 13–21d, a peak at 34d) which
   is very likely noise. Do not read the shape too finely.
3. **The round trip is assumed, not measured.** Everything keys off 30bp. We have
   *one* MOC session on record at 2.8bp and one abandoned-method session at
   120.6bp. If the true cost is near 10bp the optimal holds shorten sharply
   (see the c=10bp column); if it is 40bp the lowest bucket stops being tradeable
   at any horizon.
4. **Survivorship.** Only funds alive today are in the panel.

---

## Sources

- [Bertram (2010), *Analytic solutions for optimal statistical arbitrage trading*, Physica A](https://www.sciencedirect.com/science/article/abs/pii/S0378437110001019)
- [Leung & Li (2015), *Optimal Mean Reversion Trading with Transaction Costs and Stop-Loss Exit*, IJTAF](https://arxiv.org/abs/1411.5062)
- [Starks, Yong & Zheng, *Tax-Loss Selling and the January Effect: Evidence from Municipal Bond Closed-End Funds*](https://www.bus.umich.edu/pdf/mitsui/workshopdocs/ZhengJanuaryEffect.pdf)
- [Carrion & Zhang (2024), *Tax-Loss Selling and the January Effect Revisited*, J. Financial Research](https://onlinelibrary.wiley.com/doi/abs/10.1111/jfir.12384)
- [ICI (2025), *Closed-End Fund Activism*](https://www.ici.org/files/2025/cef-activism.pdf)
- [Dividend.com, *Tender Offers, Lawsuits, and Mergers: The Rising Tide of CEF Activism*](https://www.dividend.com/closed-end-funds-channel/rising-tide-of-cef-activism/)
- [CNBC (2026-05-07), *Saba pauses UK fund activism*](https://www.cnbc.com/2026/05/07/saba-capital-herald-investment-trust-deal-activism-pause.html)
