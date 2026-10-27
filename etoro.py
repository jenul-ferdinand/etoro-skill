#!/usr/bin/env python3
"""Read-only eToro account and market data, with instrument IDs resolved to
tickers. Keys come from $ETORO_API_KEY and $ETORO_USER_KEY, or a .env file
next to this script. Amounts are USD.

  etoro.py               balance, equity and holdings grouped by ticker
  etoro.py positions     every open position (lot) on its own row
  etoro.py ids ID...     tickers and names for instrument IDs
  etoro.py get PATH      raw GET of an /api/v1 PATH, printed as JSON
  etoro.py --test        self-check
"""

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
BASE = "https://public-api.etoro.com/api/v1"


@cache
def keys() -> dict[str, str]:
    env = dict(os.environ)
    dotenv = HERE / ".env"
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


def tickers(ids) -> dict[int, tuple[str, str]]:
    """id -> (ticker, name) for these instrument IDs."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    # eToro rejects %2C-encoded commas, so the query is built by hand.
    # One request, batch by 100 if a portfolio outgrows that
    q = ",".join(map(str, ids))
    data = get(f"/market-data/instruments?instrumentIds={q}")
    return {
        d["instrumentID"]: (d["symbolFull"], d["instrumentDisplayName"])
        for d in data["instrumentDisplayDatas"]
    }


def positions(cp: dict) -> list[dict]:
    """Open positions, own and copied (mirror) ones."""
    return cp["positions"] + [p for m in cp["mirrors"] for p in m["positions"]]


def upnl(p: dict) -> dict:
    return p.get("unrealizedPnL") or {}


def totals(cp: dict) -> dict:
    """Cash, invested, unrealized P/L and equity, summed the way eToro's
    calculate-equity guide does it."""
    own = [
        o
        for o in cp["ordersForOpen"]
        if not (o.get("mirrorID") or o.get("mirrorId"))
    ]
    pending = sum(o["amount"] for o in own + cp["orders"])
    mirrors = cp["mirrors"]
    ps = positions(cp)
    cash = cp["credit"] - pending
    invested = (
        sum(p["amount"] for p in ps)
        + sum(
            m["availableAmount"] - m["closedPositionsNetProfit"]
            for m in mirrors
        )
        + pending
        + sum(o.get("totalExternalCosts", 0) for o in own)
    )
    pnl = sum(upnl(p).get("pnL", 0) for p in ps) + sum(
        m["closedPositionsNetProfit"] for m in mirrors
    )
    return {
        "cash": cash,
        "invested": invested,
        "pnl": pnl,
        "equity": cash + invested + pnl,
    }


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
                "price": None,
            },
        )
        r["lots"] += 1
        r["units"] += p["units"]
        r["cost"] += p["units"] * p["openRate"]
        r["invested"] += p["amount"]
        r["pnl"] += upnl(p).get("pnL", 0)
        r["price"] = upnl(p).get("closeRate", r["price"])
        r["since"] = min(r["since"], p["openDateTime"])
    out = list(rows.values())
    for r in out:
        r["value"] = r["invested"] + r["pnl"]
        r["avg"] = r["cost"] / r["units"] if r["units"] else None
    return sorted(out, key=lambda r: -r["value"])


def money(x: float, sign: bool = False) -> str:
    return f"{x:+,.2f}" if sign else f"{x:,.2f}"


def pct(a: float, b: float) -> str:
    return f"{a / b:+.1%}" if b else "-"


def table(rows: list[dict], equity: float) -> str:
    names = tickers(r["id"] for r in rows)
    cols = "ticker name lots since units avg-open price invested value P/L"
    head = "{:<16}{:<26}{:>5} {:<11}{:>12}{:>11}{:>11}{:>12}{:>12}{:>11}"
    lines = [head.format(*cols.split()) + f"{'P/L%':>8}{'weight':>8}"]
    for r in rows:
        ticker, name = names.get(r["id"], (str(r["id"]), "?"))
        flags = (" short" if r["short"] else "") + (
            f" x{r['lev']}" if r["lev"] != 1 else ""
        )
        avg, price = r["avg"], r["price"]
        lines.append(
            head.format(
                ticker + flags,
                name[:25],
                r["lots"],
                r["since"][:10],
                f"{r['units']:.4f}",
                f"{avg:,.2f}" if avg else "-",
                f"{price:,.2f}" if price else "-",
                money(r["invested"]),
                money(r["value"]),
                money(r["pnl"], sign=True),
            )
            + f"{pct(r['pnl'], r['invested']):>8}"
            + f"{r['value'] / equity:>8.1%}"
        )
    return "\n".join(lines)


def report(cp: dict, by_lot: bool) -> str:
    t = totals(cp)
    if by_lot:
        key = lambda p: p["positionID"]  # noqa: E731
    else:
        key = lambda p: (p["instrumentID"], p["isBuy"], p["leverage"])  # noqa: E731
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"eToro account (USD), {now}\n"
        f"equity {money(t['equity'])} | cash {money(t['cash'])}"
        f" | invested {money(t['invested'])}"
        f" | unrealized P/L {money(t['pnl'], sign=True)}"
        f" ({pct(t['pnl'], t['invested'])})"
        f" | {len(positions(cp))} positions, {len(cp['mirrors'])} copied traders"
        f", {len(cp['orders']) + len(cp['ordersForOpen'])} pending orders\n\n"
        + table(group(positions(cp), key), t["equity"])
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
        }

    cp = {
        "credit": 100.0,
        "positions": [
            pos(1, 7, 1.0, 50.0, 50.0, 10.0, 60.0),
            pos(2, 7, 1.0, 70.0, 70.0, -10.0, 60.0),
            pos(3, 9, 2.0, 10.0, 20.0, 5.0, 12.5),
        ],
        "mirrors": [
            {
                "availableAmount": 30.0,
                "closedPositionsNetProfit": 5.0,
                "positions": [pos(4, 9, 1.0, 10.0, 10.0, 1.0, 11.0)],
            }
        ],
        "orders": [{"amount": 15.0}],
        "ordersForOpen": [
            {"amount": 25.0, "mirrorID": 0, "totalExternalCosts": 1.0},
            {"amount": 99.0, "mirrorID": 3, "totalExternalCosts": 9.0},
        ],
    }
    t = totals(cp)
    assert t["cash"] == 100 - 25 - 15
    assert t["invested"] == 50 + 70 + 20 + 10 + (30 - 5) + 40 + 1
    assert t["pnl"] == 10 - 10 + 5 + 1 + 5
    assert t["equity"] == t["cash"] + t["invested"] + t["pnl"]
    rows = group(positions(cp), lambda p: p["instrumentID"])
    amd = next(r for r in rows if r["id"] == 7)
    assert (amd["lots"], amd["units"], amd["avg"]) == (2, 2.0, 60.0)
    assert (amd["value"], amd["since"]) == (120.0, "2026-01-01T00:00:00Z")
    assert [r["id"] for r in rows] == [7, 9]
    lots = group(positions(cp), lambda p: p["positionID"])
    assert len(lots) == 4 and sum(r["value"] for r in lots) == 156.0
    assert pct(0, 0) == "-" and pct(1, 4) == "+25.0%"
    print("ok")


def main() -> None:
    args = sys.argv[1:]
    match args:
        case ["--test"]:
            test()
        case [] | ["positions"]:
            cp = get("/trading/info/real/pnl")["clientPortfolio"]
            print(report(cp, by_lot=bool(args)))
        case ["ids", *ids] if ids and all(i.isdigit() for i in ids):
            names = tickers(ids)
            for i in ids:
                print(i, *names.get(int(i), ("?", "not found")), sep="\t")
        case ["get", path] if path.startswith("/"):
            print(json.dumps(get(path), indent=1))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main()
