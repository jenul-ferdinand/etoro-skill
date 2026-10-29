---
name: etoro
description: Read the user's live eToro account (cash, equity, holdings by ticker, cost basis, P/L, trade history) and eToro market data before answering. Use whenever the user mentions eToro, their portfolio, balance or holdings, a stock, ETF or crypto they own or are considering, or asks for investing thoughts.
---

# eToro

`etoro.py` (in this skill's directory) reads the eToro public API. It only sends GET requests and cannot place, change or close trades. If the user wants a trade, they do it in eToro.

## Before answering

Run `python3 <skill dir>/etoro.py` and base the answer on its output. Amounts are USD, but avg-open and price are in the instrument's own currency (GBX for London stocks, for example). It prints:

- equity, cash (available to trade), invested, unrealized P/L, and the 24h change (a rolling 24 hours, not since the last close)
- dividends/overnight (dividends minus overnight fees, which only leveraged and short positions pay), fees/taxes (ticket fees, stamp duty), net P/L (unrealized P/L after both), and counts of positions, copied traders and pending orders
- weights: the share of equity by industry for stocks, by asset type for the rest (ETF, Crypto), and cash
- one row per holding: ticker, lots, first buy date, units, average open price, current price, invested, value, P/L, P/L%, net (P/L after dividends and fees), 24h, and weight (value / equity). 24h shows `-` when the row isn't the instrument's whole own holding: copied positions, a long/short or leverage split, or one lot of several.

`etoro.py positions` prints one row per lot instead, ending with `1y+ from`: the first sale date that counts as held over 12 months, which US long-term gains and Australia's 50% CGT discount both use. A `*` marks a date on or after 1 July 2027, from when Australia's 50% discount covers only gain accrued before that day (a 2026–27 Budget change). Use it for questions about when or at what price something was bought. Dates are UTC. In Australia a trade during US hours falls on the next local day, so if the user's tax office counts the local date, the real date can be a day later.

Answer the question using the numbers: net P/L for total return, 24h for "today", weights for concentration, cost basis, cash on hand. Don't paste the whole table back unless asked. The API has no fundamentals or news, so when the answer depends on those, search the web and say what you looked up.

## Market data

`etoro.py get PATH` prints any GET under `https://public-api.etoro.com/api/v1` as JSON. `etoro.py ids ID...` turns instrument IDs (as in trade history) into tickers.

| Need | PATH |
|---|---|
| Instrument ID, price and % changes for a ticker | `/market-data/search?fields=instrumentId,internalSymbolFull,displayname,currentRate,dailyPriceChange,weeklyPriceChange,monthlyPriceChange&internalSymbolFull=TSLA` |
| Search by name | the same, with `displayname=Tesla` in place of `internalSymbolFull` |
| Live bid/ask | `/market-data/instruments/rates?instrumentIds=1111,1002` (max 100 IDs) |
| Price candles | `/market-data/instruments/1111/history/candles/desc/OneDay/30` (interval `OneMinute` to `FourHours`, `OneDay`, `OneWeek`; up to 1000) |
| Closed trades | `/trading/info/trade/history?minDate=2026-01-01&pageSize=50` (each call looks back under a year) |

Search returns the stock first, then variants like `TSLA.24-7` and options. Use the plain ticker. The `*PriceChange` fields are percents (0.22 means 0.22%).

Rate limits: 60 requests a minute for account endpoints and 120 for market data. Batch IDs into one call where the endpoint allows it.

The full docs index is `https://api-portal.etoro.com/_llms/core-api.txt`. Read it with a web fetch tool, since curl gets a Cloudflare challenge page.

## Errors

HTTP 401 or 403 means the keys in `~/.config/etoro-skill/.env` are wrong or expired. Ask the user to generate new ones in eToro and update `ETORO_API_KEY` and `ETORO_USER_KEY`.
