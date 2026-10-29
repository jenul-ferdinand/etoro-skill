---
name: etoro
description: Read the user's live eToro account (cash, equity, holdings by ticker, cost basis, P/L, trade history) and eToro market data before answering. Use whenever the user mentions eToro, their portfolio, balance or holdings, a stock, ETF or crypto they own or are considering, or asks for investing thoughts.
---

# eToro

`etoro.py` (in this skill's directory) reads the eToro public API. It only sends GET requests and cannot place, change or close trades. The keys should be read-only, so eToro refuses trades even outside the script. If the user wants a trade, they do it in eToro.

## Before answering

Run `python3 <skill dir>/etoro.py` and base the answer on its output. It prints, in USD:

- equity, cash (available to trade), invested, unrealized P/L, and counts of positions, copied traders and pending orders
- one row per holding: ticker, lots, first buy date, units, average open price, current price, invested, value, P/L, P/L%, and weight (value / equity)

`etoro.py positions` prints one row per lot instead. Use it for questions about when or at what price something was bought.

Answer the question using the numbers: position size, concentration, cost basis, cash on hand. Don't paste the whole table back unless asked. The API has no fundamentals or news, so when the answer depends on those, search the web and say what you looked up.

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

HTTP 401 or 403 means the keys in `~/.config/etoro-skill/.env` are wrong or expired. Ask the user to generate new ones in eToro with Read permission for the Real environment, and update `ETORO_API_KEY` and `ETORO_USER_KEY`. A 403 with `InsufficientPermissions` is different: the key works but doesn't cover that endpoint, so skip it and don't suggest a Write key. `etoro.py get /me` lists the key's `scopes`, and a read-only key has only `:read` ones.
