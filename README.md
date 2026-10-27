<p align="center">
  <img alt="eToro Agent Skill" src=".github/banner.png" />
</p>

Ask your AI agent about your investments and it reads your live [eToro](https://www.etoro.com) account first: cash, equity, every holding by ticker with cost basis and P/L, plus prices and trade history.

It's an [Agent Skill](https://agentskills.io), so it works with Claude Code, Codex, and any other agent that loads skills. It's read-only: `etoro.py` only sends GET requests to the [eToro public API](https://api-portal.etoro.com) and can't trade.

## Setup

1. Generate a public API key and a user key in eToro (your account must be verified). See the [API portal](https://api-portal.etoro.com).
2. Copy `.env.example` to `.env` next to `etoro.py` (it's gitignored) and fill in the keys, or export `ETORO_API_KEY` and `ETORO_USER_KEY`.
3. Install the skill:
   ```sh
   npx skills add jenul-ferdinand/etoro-skill -g
   ```

## Usage

```sh
python3 etoro.py              # balance, equity, holdings by ticker
python3 etoro.py positions    # one row per lot
python3 etoro.py ids 1002     # instrument ID -> ticker
python3 etoro.py get /market-data/instruments/rates?instrumentIds=1002
python3 etoro.py --test       # self-check
```

Python 3.11+, standard library only. Unofficial and not affiliated with eToro. MIT licensed.
