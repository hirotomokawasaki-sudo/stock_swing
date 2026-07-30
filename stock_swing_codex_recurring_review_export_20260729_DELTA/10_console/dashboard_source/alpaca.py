"""Alpaca Trading API client and account configuration loading.

Accounts are configured in .env as ACCOUNT_<n>_API_KEY / ACCOUNT_<n>_SECRET_KEY
blocks (see .env.example). Keys never leave the server process.
"""

import os
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

load_dotenv()

LIVE_URL = "https://api.alpaca.markets"
PAPER_URL = "https://paper-api.alpaca.markets"

# UI label -> (Alpaca period, bar timeframe)
PERIODS = {
    "1D": ("1D", "5Min"),
    "1W": ("1W", "15Min"),
    "1M": ("1M", "1D"),
    "3M": ("3M", "1D"),
    "1Y": ("1A", "1D"),
    "All": ("all", "1D"),
}


@dataclass(frozen=True)
class Account:
    idx: int
    name: str
    key: str
    secret: str
    paper: bool

    @property
    def base_url(self) -> str:
        return PAPER_URL if self.paper else LIVE_URL


def load_accounts() -> list[Account]:
    accounts = []
    i = 1
    while True:
        key = os.getenv(f"ACCOUNT_{i}_API_KEY", "").strip()
        secret = os.getenv(f"ACCOUNT_{i}_SECRET_KEY", "").strip()
        if not key or not secret:
            break
        name = os.getenv(f"ACCOUNT_{i}_NAME", f"Account {i}").strip()
        paper = os.getenv(f"ACCOUNT_{i}_PAPER", "true").strip().lower() in ("1", "true", "yes")
        accounts.append(Account(i, name, key, secret, paper))
        i += 1
    return accounts


def demo_mode() -> bool:
    forced = os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")
    return forced or not load_accounts()


def _get(acct: Account, path: str, params: dict | None = None):
    resp = requests.get(
        acct.base_url + path,
        params=params,
        timeout=15,
        headers={
            "APCA-API-KEY-ID": acct.key,
            "APCA-API-SECRET-KEY": acct.secret,
        },
    )
    resp.raise_for_status()
    return resp.json()


def get_account(acct: Account) -> dict:
    return _get(acct, "/v2/account")


def get_history(acct: Account, period_label: str) -> dict:
    period, timeframe = PERIODS[period_label]
    return _get(
        acct,
        "/v2/account/portfolio/history",
        {"period": period, "timeframe": timeframe, "intraday_reporting": "market_hours"},
    )


def get_positions(acct: Account) -> list[dict]:
    return _get(acct, "/v2/positions")


def get_orders(acct: Account, limit: int = 25) -> list[dict]:
    return _get(acct, "/v2/orders", {"status": "all", "limit": limit, "direction": "desc"})


def get_clock(acct: Account) -> dict:
    return _get(acct, "/v2/clock")
