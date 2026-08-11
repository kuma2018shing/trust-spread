# Trust spread

**Everyone advertises their rate. Nobody publishes what you actually get.**

In a peer-to-peer crypto market the best-advertised rate is often posted by a
merchant who has never completed a trade. This project records the whole
visible order book twice an hour and publishes the gap between the rate on the
board and the rate you can actually rely on.

We call that gap the **trust spread**.

> ⚠️ **Early.** Collection started 11 August 2026. Everything below is a
> hypothesis from a small number of snapshots, not a finding. Nothing here is
> a rate you should trade on, and none of it is financial advice.

---

## The first snapshot

South African rand, USDT, sell side — 11 August 2026:

| price | orders | completion |
|---|---|---|
| **18.00** | **0** | **0.0%** |
| 16.64 | 41 | 65.1% |
| **16.62** | **247** | **95.8%** |

The top of the board belongs to a merchant with **zero completed orders**. The
best rate from a merchant with a real track record is **8.3% worse**.

That matters because the headline case for stablecoin remittances is *"save
around 6% versus a traditional operator."* If the trust spread is routinely
larger than the saving, the comparison everyone quotes is being made against a
rate that cannot actually be reached.

## Two things worth testing

Both come from single snapshots. Both need weeks of data before they mean
anything.

**1. The spread may be one-sided.** In the first snapshot it was ~0% on the buy
side and 8.3% (ZAR) / 3.9% (KES) on the sell side. If that persists, the bait
sits where people **cash out** — which is what someone receiving a remittance
does.

**2. Small tickets may pay more.** Walking the proven book, R1,000 cleared at
17.15 while R20,000 cleared at 17.02 — smaller orders can't reach merchants
with high minimums.

## Method

Twice an hour, for each currency and side, we page through the visible book and
record every ad: price, available depth, per-order limits, and the merchant's
order count, completion rate, positive rating and account age.

A merchant is **proven** only if they clear both:

- **≥ 20** completed orders in the trailing month
- **≥ 90%** completion rate

Deliberately conservative. A lenient filter would quietly reintroduce the exact
thing being measured.

From that we compute:

| Metric | Meaning |
|---|---|
| **Sticker** | Top of book — the number everyone quotes |
| **Proven** | Best rate from a merchant clearing the filter |
| **Trust spread** | The gap between them |
| **Realized @ size** | Volume-weighted rate to fill a real ticket, proven merchants only, honouring each merchant's own limits |

If the visible book cannot fill a ticket, that is recorded as blank rather than
zero-filled — a book that can't fill an order is itself a result.

**Every raw book is committed**, so any number published here can be
re-derived from the data it came from rather than taken on trust. That is the
whole point.

## Coverage

| Currency | Status |
|---|---|
| ZAR — South Africa | live |
| KES — Kenya | live |
| NGN — Nigeria | **not available** on this venue; needs another source |
| GHS, UGX | planned |

## Data

```
data/spreads.csv           one row per currency/side/snapshot
data/books/<f>_<s>_<ts>.csv  the full book behind every row
```

## Running it

Standard library only — no dependencies, no install.

```bash
python collector/collect.py --fiat ZAR KES --out data
```

## Limitations

- **One venue.** Binance P2P only. Cross-venue coverage is needed before any
  claim about "the market" is safe.
- **Advertised depth is not guaranteed depth.** `surplusAmount` is what the
  merchant claims is available.
- **The filter is a choice.** 20 orders and 90% completion are defensible, not
  derived. Sensitivity to those thresholds needs testing and publishing.
- **No ground truth yet.** These are book-derived estimates. Until they are
  checked against real completed transactions, they are a model of what you
  would get, not a record of what anyone did get.
- **Short history.** Days, not months.

## Licence

Data and code released for public use. No warranty. Not financial advice.
