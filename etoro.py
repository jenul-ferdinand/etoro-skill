#!/usr/bin/env python3
"""Read-only eToro account and market data, with instrument IDs resolved to
tickers. Keys come from $ETORO_API_KEY and $ETORO_USER_KEY, or from
~/.config/etoro-skill/.env, which survives skill and plugin updates. Amounts
are USD; prices are in each instrument's own currency.

  etoro.py               balance, 24h move, weights and holdings by ticker
  etoro.py positions     every open position (lot) on its own row
  etoro.py ids ID...     tickers, names and sectors for instrument IDs
  etoro.py get PATH      raw GET of an /api/v1 PATH, printed as JSON
  etoro.py --test        self-check
"""

import json
import os
import sys
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from math import isclose
from operator import itemgetter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://public-api.etoro.com/api/v1"
CGT_CUT = "2027-07-01"  # AU 50% CGT discount stops for later gain


def keys() -> dict[str, str]:
    env = dict(os.environ)
    dotenv = Path.home() / ".config" / "etoro-skill" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.lstrip().startswith("#"):
                env.setdefault(k.strip(), v.strip().strip("\"'"))
    try:
        return {
            "x-api-key": env["ETORO_API_KEY"],
            "x-user-key": env["ETORO_USER_KEY"],
        }
    except KeyError as e:
        sys.exit(f"etoro.py: {e.args[0]} is not set (env or {dotenv})")


def get(path: str):
    """GET an /api/v1 path. Only GET exists here: this skill never trades."""
    headers = {
        **keys(),
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "etoro-skill",
    }
    try:
        with urlopen(Request(BASE + path, headers=headers), timeout=20) as r:
            return json.load(r)
    except HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        sys.exit(f"etoro.py: GET {path} -> HTTP {e.code}: {body}")
    except URLError as e:
        sys.exit(f"etoro.py: GET {path} failed: {e.reason}")


def tickers(ids) -> dict[int, tuple[str, str, str]]:
    """id -> (ticker, name, sector) for these instrument IDs. The sector is
    the industry for stocks and the asset type (ETF, Crypto...) otherwise."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    types = {
        t["instrumentTypeID"]: t["instrumentTypeDescription"]
        for t in get("/market-data/instrument-types")["instrumentTypes"]
    }
    industries = {
        i["industryID"]: i["industryName"]
        for i in get("/market-data/stocks-industries")["stocksIndustries"]
    }
    q = ",".join(map(str, ids))
    data = get(f"/market-data/instruments?instrumentIds={q}")
    out = {}
    for d in data["instrumentDisplayDatas"]:
        sector = types.get(d["instrumentTypeID"], "?")
        if sector == "Stocks":
            sector = industries.get(d.get("stocksIndustryID"), sector)
        out[d["instrumentID"]] = (
            d["symbolFull"],
            d["instrumentDisplayName"],
            sector,
        )
    return out


def positions(cp: dict) -> list[dict]:
    """Open positions, own and copied (mirror) ones."""
    return cp["positions"] + [p for m in cp["mirrors"] for p in m["positions"]]


def upnl(p: dict) -> dict:
    return p.get("unrealizedPnL") or {}


def group(ps: list[dict], key) -> list[dict]:
    """Sum positions sharing key(p) into rows, largest value first."""
    rows: dict = {}
    for p in ps:
        r = rows.setdefault(
            key(p),
            {
                "id": p["instrumentID"],
                "short": not p["isBuy"],
                "lev": p["leverage"],
                "since": p["openDateTime"],
                "lots": 0,
                "units": 0.0,
                "cost": 0.0,
                "invested": 0.0,
                "pnl": 0.0,
                "div": 0.0,
                "fees": 0.0,
                "price": None,
            },
        )
        r["lots"] += 1
        r["units"] += p["units"]
        r["cost"] += p["units"] * p["openRate"]
        r["invested"] += p["amount"]
        r["pnl"] += upnl(p).get("pnL", 0)
        r["div"] -= p.get("totalFees", 0)
        r["fees"] += p.get("totalExternalFees", 0)
        r["fees"] += p.get("totalExternalTaxes", 0)
        r["price"] = upnl(p).get("closeRate", r["price"])
        r["since"] = min(r["since"], p["openDateTime"])
    out = list(rows.values())
    for r in out:
        r["value"] = r["invested"] + r["pnl"]
        r["net"] = r["pnl"] + r["div"] - r["fees"]
        r["avg"] = r["cost"] / r["units"] if r["units"] else None
    return sorted(out, key=lambda r: -r["value"])


def pct(a: float, b: float) -> str:
    return f"{a / b:+.1%}" if b else "-"


def cgt_date(opened: str) -> str:
    """First sale date that counts as held over 12 months (Australian CGT,
    US long-term): the day after the UTC open date, a year on."""
    d = date.fromisoformat(opened[:10]) + timedelta(days=1)
    try:
        return d.replace(year=d.year + 1).isoformat()
    except ValueError:
        return date(d.year + 1, 3, 1).isoformat()


def table(rows: list[dict], equity: float, names: dict, by_lot: bool) -> str:
    cols = "ticker name lots since units avg-open price invested value P/L"
    head = "{:<16}{:<26}{:>5} {:<11}{:>12}{:>11}{:>11}{:>12}{:>12}{:>11}"
    tail = f"{'P/L%':>8}{'net':>11}{'24h':>10}{'weight':>8}"
    cgt = "  1y+ from" if by_lot else ""
    lines = [head.format(*cols.split()) + tail + cgt]
    for r in rows:
        ticker, name, _ = names.get(r["id"], (str(r["id"]), "?", "?"))
        flags = (" short" if r["short"] else "") + (
            f" x{r['lev']}" if r["lev"] != 1 else ""
        )
        avg, price = r["avg"], r["price"]
        d24 = f"{r['24h']:+,.2f}" if "24h" in r else "-"
        when = cgt_date(r["since"])
        lines.append(
            head.format(
                ticker + flags,
                name[:25],
                r["lots"],
                r["since"][:10],
                f"{r['units']:.4f}",
                f"{avg:,.2f}" if avg else "-",
                f"{price:,.2f}" if price else "-",
                f"{r['invested']:,.2f}",
                f"{r['value']:,.2f}",
                f"{r['pnl']:+,.2f}",
            )
            + f"{pct(r['pnl'], r['invested']):>8}"
            + f"{r['net']:>+11,.2f}"
            + f"{d24:>10}"
            + f"{r['value'] / equity:>8.1%}"
            + (f"  {when}{'*' if when >= CGT_CUT else ''}" if by_lot else "")
        )
    today = datetime.now(UTC).date().isoformat()
    if by_lot and (today >= CGT_CUT or any(x.endswith("*") for x in lines)):
        lines.append(
            f"* 1y+ date on or after {CGT_CUT}: Australia's 50% CGT discount"
            " only covers gain accrued before that date"
        )
    return "\n".join(lines)


def report(cp: dict, agg: dict, names: dict, by_lot: bool) -> str:
    """cp from /trading/info/real/pnl, agg from the aggregate portfolio."""
    t = agg["accountTotals"]
    equity, cash = t["accountTotalValue"], t["accountAvailableCash"]
    invested, pnl = t["accountTotalUsedMargin"], t["accountCurrentPnl"]
    if by_lot:
        key = itemgetter("positionID")
    else:
        key = itemgetter("instrumentID", "isBuy", "leverage")
    rows = group(positions(cp), key)
    daily = {a["instrumentId"]: a for a in agg["instrumentAggregates"]}
    for r in rows:
        a = daily.get(r["id"], {})
        units = -r["units"] if r["short"] else r["units"]
        if isclose(a.get("netUnits", 0), units):
            r["24h"] = a["dailyGainAccountCurrency"]
    div = sum(r["div"] for r in rows)
    fees = sum(r["fees"] for r in rows)
    net = pnl + div - fees
    w = Counter(cash=cash)
    for r in rows:
        w[names.get(r["id"], ("", "", "?"))[2]] += r["value"]
    shares = (f"{k} {v / equity:.1%}" for k, v in w.most_common())
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"eToro account (USD), {now}\n"
        f"equity {equity:,.2f} | cash {cash:,.2f} | invested {invested:,.2f}"
        f" | unrealized P/L {pnl:+,.2f} ({pct(pnl, invested)})"
        f" | 24h {t['dailyGainAccountCurrency']:+,.2f}"
        f" ({t['dailyGainAccountCurrencyPercent']:+.1f}%)\n"
        f"dividends/overnight {div:+,.2f} | fees/taxes {-fees:+,.2f}"
        f" | net P/L {net:+,.2f} ({pct(net, invested)})"
        f" | {len(positions(cp))} positions, {len(cp['mirrors'])} copied traders"
        f", {len(cp['orders']) + len(cp['ordersForOpen'])} pending orders\n"
        f"weights: {' | '.join(shares) if equity else '-'}\n\n"
        + table(rows, equity, names, by_lot)
    )


def test() -> None:
    def pos(pid, iid, units, rate, amount, pnl, close, buy=True):
        return {
            "positionID": pid,
            "instrumentID": iid,
            "isBuy": buy,
            "leverage": 1,
            "units": units,
            "openRate": rate,
            "amount": amount,
            "openDateTime": f"2026-01-0{pid}T00:00:00Z",
            "unrealizedPnL": {"pnL": pnl, "closeRate": close},
            "totalFees": -0.5,
            "totalExternalFees": 2.0,
            "totalExternalTaxes": 0.5,
        }

    cp = {
        "positions": [
            pos(1, 7, 1.0, 50.0, 50.0, 10.0, 60.0),
            pos(2, 7, 1.0, 70.0, 70.0, -10.0, 60.0),
            pos(3, 9, 2.0, 10.0, 20.0, 5.0, 12.5),
        ],
        "mirrors": [{"positions": [pos(4, 9, 1.0, 10.0, 10.0, 1.0, 11.0)]}],
        "orders": [{}],
        "ordersForOpen": [{}, {}],
    }
    rows = group(positions(cp), lambda p: p["instrumentID"])
    amd = next(r for r in rows if r["id"] == 7)
    assert (amd["lots"], amd["units"], amd["avg"]) == (2, 2.0, 60.0)
    assert (amd["value"], amd["since"]) == (120.0, "2026-01-01T00:00:00Z")
    assert (amd["div"], amd["fees"], amd["net"]) == (1.0, 5.0, -4.0)
    assert [r["id"] for r in rows] == [7, 9]
    lots = group(positions(cp), lambda p: p["positionID"])
    assert len(lots) == 4 and sum(r["value"] for r in lots) == 156.0
    assert pct(0, 0) == "-" and pct(1, 4) == "+25.0%"
    agg = {
        "accountTotals": {
            "accountTotalValue": 200.0,
            "accountAvailableCash": 44.0,
            "accountTotalUsedMargin": 150.0,
            "accountCurrentPnl": 6.0,
            "dailyGainAccountCurrency": 3.5,
            "dailyGainAccountCurrencyPercent": 1.78,
        },
        "instrumentAggregates": [
            {"instrumentId": i, "netUnits": 2.0, "dailyGainAccountCurrency": g}
            for i, g in ((7, 3.0), (9, 0.5))
        ],
    }
    global get
    get = {
        "/market-data/instrument-types": {
            "instrumentTypes": [
                {"instrumentTypeID": i, "instrumentTypeDescription": n}
                for i, n in ((5, "Stocks"), (6, "ETF"))
            ]
        },
        "/market-data/stocks-industries": {
            "stocksIndustries": [{"industryID": 8, "industryName": "Tech"}]
        },
        "/market-data/instruments?instrumentIds=7,9": {
            "instrumentDisplayDatas": [
                {
                    "instrumentID": i,
                    "symbolFull": s,
                    "instrumentDisplayName": n,
                    "instrumentTypeID": t,
                    "stocksIndustryID": 8,
                }
                for i, s, n, t in (
                    (7, "AAA", "Alpha", 5),
                    (9, "BBB", "Beta", 6),
                )
            ]
        },
    }.__getitem__
    names = tickers([9, 7, 7])
    assert names == {7: ("AAA", "Alpha", "Tech"), 9: ("BBB", "Beta", "ETF")}

    def cells(by_lot):
        out = report(cp, agg, names, by_lot).splitlines()
        return out, [c.split() for c in out if c[:3] in ("AAA", "BBB")]

    out, (aaa, bbb) = cells(False)
    assert out[1].startswith("equity 200.00 | cash 44.00 | invested 150.00")
    assert out[1].endswith("| 24h +3.50 (+1.8%)")
    assert out[2].startswith("dividends/overnight +2.00 | fees/taxes -10.00")
    assert "| net P/L -2.00 (-1.3%) |" in out[2]
    assert out[3] == "weights: Tech 60.0% | cash 22.0% | ETF 18.0%"
    assert (aaa[11], aaa[12], bbb[12]) == ("-4.00", "+3.00", "-")
    _, lots = cells(True)
    assert [c[12] for c in lots] == ["-", "-", "+0.50", "-"]
    assert [c[14] for c in lots] == [f"2027-01-0{d}" for d in (2, 3, 4, 5)]
    global CGT_CUT
    CGT_CUT = "9999-12-31"
    assert not cells(True)[0][-1].startswith("*")
    CGT_CUT = "2027-01-04"
    out, lots = cells(True)
    assert [c[14][10:] for c in lots] == ["", "", "*", "*"]
    assert out[-1].startswith("* 1y+ date on or after 2027-01-04:")
    for opened, first in (
        ("2026-03-05", "2027-03-06"),
        ("2027-02-28", "2028-03-01"),
        ("2028-02-28", "2029-03-01"),
        ("2028-02-29", "2029-03-01"),
        ("2026-12-31", "2028-01-01"),
    ):
        assert cgt_date(opened + "T20:00:00Z") == first, opened
    print("ok")


def main() -> None:
    args = sys.argv[1:]
    match args:
        case ["--test"]:
            test()
        case [] | ["positions"]:
            cp = get("/trading/info/real/pnl")["clientPortfolio"]
            cut = datetime.now(UTC) - timedelta(days=1)
            agg = get(
                "/trading/info/aggregate-portfolio?pnlLevel=DailyPnl"
                f"&dailyCutoffUtc={cut:%Y-%m-%dT%H:%M:%SZ}"
            )
            names = tickers(p["instrumentID"] for p in positions(cp))
            print(report(cp, agg, names, by_lot=bool(args)))
        case ["ids", *ids] if ids and all(i.isdigit() for i in ids):
            names = tickers(ids)
            for i in ids:
                print(i, *names.get(int(i), ("?", "not found")), sep="\t")
        case ["get", path] if path.startswith("/"):
            print(json.dumps(get(path), separators=(",", ":")))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main()
