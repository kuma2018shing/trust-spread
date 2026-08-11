"""Snapshot P2P order books and compute the trust spread.

The advertised top-of-book rate in a P2P market is frequently posted by a
merchant with no completed orders. This records the whole visible book, then
computes what a trade actually clears at once you restrict yourself to
merchants with a track record -- and walks the book at real ticket sizes
rather than quoting the touch.

    python collect.py --fiat ZAR KES --out ../data

Writes one row per (fiat, side, snapshot) to data/spreads.csv and the raw
book to data/books/<fiat>_<side>_<ts>.csv, both append-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
UA = "Mozilla/5.0 (compatible; trust-spread/0.1; +https://github.com/kuma2018shing)"

# A merchant is "proven" only if BOTH hold. Deliberately conservative: the
# whole point is to measure the rate you can actually rely on, and a lenient
# filter would quietly reintroduce the thing being measured.
MIN_ORDERS = 20
MIN_COMPLETION = 90.0

# Ticket sizes to price the book at, in fiat units.
TICKETS = {
    "ZAR": [1_000, 5_000, 20_000],
    "KES": [5_000, 25_000, 100_000],
    "NGN": [50_000, 250_000, 1_000_000],
    "GHS": [500, 2_500, 10_000],
    "UGX": [200_000, 1_000_000, 4_000_000],
}
DEFAULT_TICKETS = [1_000, 5_000, 20_000]


@dataclass
class Ad:
    price: float
    available: float        # surplusAmount, in USDT
    min_fiat: float
    max_fiat: float
    orders: int
    completion: float       # percent
    positive: float         # percent
    merchant_age_days: float
    pro: bool
    nick: str

    @property
    def proven(self) -> bool:
        return self.orders >= MIN_ORDERS and self.completion >= MIN_COMPLETION


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_page(fiat: str, side: str, page: int, rows: int = 20) -> list[dict]:
    body = json.dumps({
        "page": page, "rows": rows, "asset": "USDT", "tradeType": side,
        "fiat": fiat, "payTypes": [], "countries": [],
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read()).get("data") or []


def fetch_book(fiat: str, side: str, max_pages: int = 5) -> list[Ad]:
    """Walk several pages so depth at size is real rather than top-of-book."""
    out: list[Ad] = []
    now = datetime.now(timezone.utc).timestamp()
    for page in range(1, max_pages + 1):
        for attempt in range(3):
            try:
                rows = fetch_page(fiat, side, page)
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                if attempt == 2:
                    print(f"    {fiat}/{side} page {page}: giving up ({e})")
                    rows = []
                else:
                    time.sleep(1.5 * (attempt + 1))
        if not rows:
            break
        for x in rows:
            adv, m = x["adv"], x["advertiser"]
            reg = _f(m.get("registrationTime"))
            out.append(Ad(
                price=_f(adv.get("price")),
                available=_f(adv.get("surplusAmount")),
                min_fiat=_f(adv.get("minSingleTransAmount")),
                max_fiat=_f(adv.get("maxSingleTransAmount")),
                orders=int(_f(m.get("monthOrderCount"))),
                completion=_f(m.get("monthFinishRate")) * 100,
                positive=_f(m.get("positiveRate")) * 100,
                merchant_age_days=round((now - reg / 1000) / 86400, 1) if reg else 0.0,
                pro=bool(m.get("proMerchant")),
                nick=str(m.get("nickName") or "")[:40],
            ))
        time.sleep(0.7)          # be a polite client
    return out


def walk_book(ads: list[Ad], side: str, ticket: float) -> float | None:
    """Volume-weighted rate to fill `ticket` fiat, best price first.

    Returns None if the visible book cannot fill the ticket -- which is itself
    a finding, so it is recorded rather than silently zero-filled.
    """
    # BUY ads = you buy USDT, you want the LOWEST price. SELL = highest.
    ordered = sorted(ads, key=lambda a: a.price, reverse=(side == "SELL"))
    remaining, cost = ticket, 0.0
    for a in ordered:
        if a.price <= 0 or remaining <= 0:
            continue
        # honour the merchant's own per-order limits
        if a.min_fiat and remaining < a.min_fiat:
            continue
        depth_fiat = a.available * a.price
        if a.max_fiat:
            depth_fiat = min(depth_fiat, a.max_fiat)
        take = min(remaining, depth_fiat)
        if take <= 0:
            continue
        cost += take / a.price          # USDT acquired/sold
        remaining -= take
    if remaining > 0.01 * ticket:
        return None
    return round(ticket / cost, 6) if cost else None


def snapshot(fiat: str, side: str, out_dir: Path) -> dict | None:
    ads = fetch_book(fiat, side)
    if not ads:
        print(f"  {fiat}/{side}: no ads (market not served here?)")
        return None

    proven = [a for a in ads if a.proven]
    best = max(ads, key=lambda a: a.price) if side == "SELL" else min(ads, key=lambda a: a.price)
    best_proven = (max(proven, key=lambda a: a.price) if side == "SELL"
                   else min(proven, key=lambda a: a.price)) if proven else None

    ts = datetime.now(timezone.utc)
    row = {
        "ts": ts.isoformat(timespec="seconds"),
        "fiat": fiat, "side": side,
        "ads": len(ads), "proven_ads": len(proven),
        "sticker": best.price,
        "sticker_orders": best.orders,
        "sticker_completion": round(best.completion, 1),
        "proven": best_proven.price if best_proven else "",
        "trust_spread_pct": (round((best.price / best_proven.price - 1) * 100, 3)
                             if best_proven and best_proven.price else ""),
    }
    for t in TICKETS.get(fiat, DEFAULT_TICKETS):
        row[f"realized_{t}"] = walk_book(proven, side, t) or ""

    # raw book, so every published number can be re-derived later
    books = out_dir / "books"
    books.mkdir(parents=True, exist_ok=True)
    bp = books / f"{fiat}_{side}_{ts.strftime('%Y%m%dT%H%M%SZ')}.csv"
    with bp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(ads[0]).keys()) + ["proven"])
        w.writeheader()
        for a in ads:
            w.writerow({**asdict(a), "proven": a.proven})

    ts_txt = row["trust_spread_pct"]
    print(f"  {fiat}/{side}: {len(ads)} ads ({len(proven)} proven)  "
          f"sticker {best.price}  proven {row['proven'] or 'n/a'}  "
          f"spread {ts_txt if ts_txt != '' else 'n/a'}%")
    return row


def append_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            existing = next(csv.reader(f), [])
        cols = existing + [c for c in cols if c not in existing]
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fiat", nargs="+", default=["ZAR", "KES"])
    ap.add_argument("--sides", nargs="+", default=["BUY", "SELL"])
    ap.add_argument("--out", default="../data")
    a = ap.parse_args()

    out = Path(a.out).resolve()
    print(f"trust-spread collector  {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    rows = []
    for fiat in a.fiat:
        for side in a.sides:
            r = snapshot(fiat, side, out)
            if r:
                rows.append(r)
    append_csv(out / "spreads.csv", rows)
    print(f"appended {len(rows)} rows -> {out / 'spreads.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
