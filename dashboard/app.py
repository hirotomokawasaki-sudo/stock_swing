"""Alpaca multi-account monitoring dashboard.

Run with:  streamlit run app.py
Teammates on the same network reach it at http://<your-lan-ip>:8501
"""

import datetime as dt
import os
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

import alpaca
import charts
import demo

NY = ZoneInfo("America/New_York")
PERIOD_LABELS = list(alpaca.PERIODS.keys())

st.set_page_config(page_title="Alpaca Accounts Dashboard", page_icon="📈", layout="wide")

DEMO = alpaca.demo_mode()

if DEMO:
    ACCOUNTS = [alpaca.Account(i, demo.DEMO_NAMES[i], "", "", True) for i in (1, 2, 3)]
else:
    ACCOUNTS = alpaca.load_accounts()

COLOR_BY_NAME = {a.name: charts.SERIES_COLORS[(a.idx - 1) % len(charts.SERIES_COLORS)]
                 for a in ACCOUNTS}
COLOR_BY_NAME["Total"] = charts.TOTAL_COLOR


# ---------------------------------------------------------------- data layer

@st.cache_data(ttl=30, show_spinner=False)
def cached_summary(acct: alpaca.Account) -> dict:
    return demo.demo_summary(acct.idx) if DEMO else alpaca.get_account(acct)


@st.cache_data(ttl=30, show_spinner=False)
def cached_history(acct: alpaca.Account, period: str) -> dict:
    return demo.demo_history(acct.idx, period) if DEMO else alpaca.get_history(acct, period)


@st.cache_data(ttl=30, show_spinner=False)
def cached_positions(acct: alpaca.Account) -> list[dict]:
    return demo.demo_positions(acct.idx) if DEMO else alpaca.get_positions(acct)


@st.cache_data(ttl=30, show_spinner=False)
def cached_orders(acct: alpaca.Account) -> list[dict]:
    return demo.demo_orders(acct.idx) if DEMO else alpaca.get_orders(acct)


@st.cache_data(ttl=30, show_spinner=False)
def cached_clock(acct: alpaca.Account) -> dict:
    return demo.demo_clock() if DEMO else alpaca.get_clock(acct)


def history_series(acct: alpaca.Account, period: str) -> pd.Series:
    raw = cached_history(acct, period)
    ts = raw.get("timestamp") or []
    eq = raw.get("equity") or []
    pairs = [(t, e) for t, e in zip(ts, eq) if e not in (None, 0)]
    if not pairs:
        return pd.Series(dtype=float, name=acct.name)
    idx = pd.to_datetime([p[0] for p in pairs], unit="s", utc=True).tz_convert(NY)
    return pd.Series([p[1] for p in pairs], index=idx, name=acct.name)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def period_return(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] == 0:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


# ---------------------------------------------------------------- formatting

def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def signed_money(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"


def pct(x: float) -> str:
    return f"{x:+.2%}"


# ------------------------------------------------------------------ auth

def check_password() -> bool:
    expected = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if not expected or st.session_state.get("authed"):
        return True
    st.title("Alpaca Accounts Dashboard")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in") :
            if pw == expected:
                st.session_state["authed"] = True
                st.rerun()
            st.error("Wrong password.")
    return False


# ------------------------------------------------------------------ views

def render_header(view: str):
    left, right = st.columns([3, 1])
    with left:
        st.title(view if view != "Overview" else "Alpaca Accounts Dashboard")
    with right:
        try:
            clock = cached_clock(ACCOUNTS[0])
            status = "🟢 Market open" if clock.get("is_open") else "⚪ Market closed"
        except Exception:
            status = "⚪ Market status unavailable"
        st.markdown(
            f"<div style='text-align:right; padding-top: 1.4rem; color:#52514e'>{status}<br>"
            f"<span style='color:#898781; font-size:0.8rem'>updated "
            f"{dt.datetime.now(tz=NY):%H:%M:%S} ET · refreshes every 60s</span></div>",
            unsafe_allow_html=True,
        )
    if DEMO:
        st.warning("Demo mode — no Alpaca keys found in `.env` (or `DEMO_MODE=true`). "
                   "Showing generated data. Copy `.env.example` to `.env` and add your keys.")


def render_overview(period: str):
    summaries, errors = {}, {}
    for acct in ACCOUNTS:
        try:
            summaries[acct.name] = cached_summary(acct)
        except requests.RequestException as e:
            errors[acct.name] = str(e)

    cols = st.columns(len(ACCOUNTS))
    for col, acct in zip(cols, ACCOUNTS):
        with col:
            s = summaries.get(acct.name)
            if s is None:
                st.metric(acct.name, "—")
                continue
            equity = float(s["equity"])
            last = float(s.get("last_equity") or equity)
            day_pl = equity - last
            day_pct = day_pl / last if last else 0.0
            badge = " · paper" if acct.paper else " · live"
            st.metric(f"{acct.name}{badge}", money(equity),
                      delta=f"{signed_money(day_pl)} ({pct(day_pct)}) today")

    for name, err in errors.items():
        st.error(f"{name}: request failed — {err}")

    series = {}
    for acct in ACCOUNTS:
        try:
            s = history_series(acct, period)
            if not s.empty:
                series[acct.name] = s
        except requests.RequestException as e:
            st.error(f"{acct.name}: history failed — {e}")
    if not series:
        st.info("No equity history available yet.")
        return

    df = pd.concat(series.values(), axis=1).sort_index().ffill()

    if len(df.columns) > 1:
        st.subheader("Total equity — all accounts")
        total = df.sum(axis=1).to_frame("Total")
        fig = charts.equity_figure(total, COLOR_BY_NAME, height=320, baseline=3_000_000)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.subheader("Equity by agent")
    fig = charts.equity_figure(df, COLOR_BY_NAME, baseline=1_000_000)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    with st.expander("Data table"):
        table = df.copy()
        if len(df.columns) > 1:
            table["Total"] = table.sum(axis=1)
        table.index = table.index.strftime("%Y-%m-%d %H:%M")
        st.dataframe(table.style.format("${:,.2f}"), width="stretch")

    st.subheader(f"Trend stats — {period}")
    rows = []
    for acct in ACCOUNTS:
        s = summaries.get(acct.name)
        eq_series = series.get(acct.name, pd.Series(dtype=float))
        if s is None:
            continue
        equity = float(s["equity"])
        last = float(s.get("last_equity") or equity)
        rows.append({
            "Account": acct.name,
            "Mode": "paper" if acct.paper else "live",
            "Equity": equity,
            "Day P/L": equity - last,
            f"{period} return": period_return(eq_series),
            f"{period} max drawdown": max_drawdown(eq_series),
            "Cash": float(s.get("cash") or 0),
            "Buying power": float(s.get("buying_power") or 0),
            "Status": s.get("status", "?"),
        })
    if rows:
        stats = pd.DataFrame(rows)
        st.dataframe(
            stats,
            width="stretch", hide_index=True,
            column_config={
                "Equity": st.column_config.NumberColumn(format="dollar"),
                "Day P/L": st.column_config.NumberColumn(format="dollar"),
                f"{period} return": st.column_config.NumberColumn(format="percent"),
                f"{period} max drawdown": st.column_config.NumberColumn(format="percent"),
                "Cash": st.column_config.NumberColumn(format="dollar"),
                "Buying power": st.column_config.NumberColumn(format="dollar"),
            },
        )


def render_account(acct: alpaca.Account, period: str):
    try:
        s = cached_summary(acct)
    except requests.RequestException as e:
        st.error(f"Could not load account — {e}")
        return

    equity = float(s["equity"])
    last = float(s.get("last_equity") or equity)
    day_pl = equity - last
    cash = float(s.get("cash") or 0)
    long_mv = float(s.get("long_market_value") or 0)
    short_mv = abs(float(s.get("short_market_value") or 0))

    try:
        eq_series = history_series(acct, period)
    except requests.RequestException as e:
        eq_series = pd.Series(dtype=float, name=acct.name)
        st.error(f"History failed — {e}")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Equity", money(equity), delta=f"{signed_money(day_pl)} today")
    m2.metric(f"{period} return", pct(period_return(eq_series)))
    m3.metric(f"{period} max drawdown", f"{max_drawdown(eq_series):.2%}")
    m4.metric("Cash", money(cash))
    m5.metric("Buying power", money(float(s.get("buying_power") or 0)))

    flags = []
    if s.get("pattern_day_trader"):
        flags.append("⚠️ pattern day trader")
    if s.get("status", "ACTIVE") != "ACTIVE":
        flags.append(f"⚠️ account status: {s['status']}")
    if flags:
        st.warning(" · ".join(flags))

    st.subheader("Equity history")
    if eq_series.empty:
        st.info("No equity history for this period.")
    else:
        fig = charts.equity_figure(eq_series.to_frame(), COLOR_BY_NAME)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        with st.expander("Data table"):
            table = eq_series.to_frame()
            table.index = table.index.strftime("%Y-%m-%d %H:%M")
            st.dataframe(table.style.format("${:,.2f}"), width="stretch")

    st.subheader("Allocation")
    labels, values = ["Cash", "Long positions"], [max(cash, 0), long_mv]
    colors = ["#9ec5f4", COLOR_BY_NAME[acct.name]]
    if short_mv:
        labels.append("Short positions")
        values.append(short_mv)
        colors.append("#e34948")
    fig = charts.allocation_figure(labels, values, colors)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    left, right = st.columns(2)
    with left:
        st.subheader("Open positions")
        try:
            positions = cached_positions(acct)
        except requests.RequestException as e:
            positions = []
            st.error(f"Positions failed — {e}")
        if positions:
            pdf = pd.DataFrame([{
                "Symbol": p["symbol"],
                "Side": p.get("side", ""),
                "Qty": float(p["qty"]),
                "Avg entry": float(p["avg_entry_price"]),
                "Price": float(p.get("current_price") or 0),
                "Market value": float(p.get("market_value") or 0),
                "Unrealized P/L": float(p.get("unrealized_pl") or 0),
                "P/L %": float(p.get("unrealized_plpc") or 0),
            } for p in positions]).sort_values("Market value", ascending=False)
            st.dataframe(
                pdf, width="stretch", hide_index=True,
                column_config={
                    "Avg entry": st.column_config.NumberColumn(format="dollar"),
                    "Price": st.column_config.NumberColumn(format="dollar"),
                    "Market value": st.column_config.NumberColumn(format="dollar"),
                    "Unrealized P/L": st.column_config.NumberColumn(format="dollar"),
                    "P/L %": st.column_config.NumberColumn(format="percent"),
                },
            )
        else:
            st.caption("No open positions.")
    with right:
        st.subheader("Recent orders")
        try:
            orders = cached_orders(acct)
        except requests.RequestException as e:
            orders = []
            st.error(f"Orders failed — {e}")
        if orders:
            odf = pd.DataFrame([{
                "Submitted": pd.to_datetime(o["submitted_at"]).tz_convert(NY).strftime("%m-%d %H:%M"),
                "Symbol": o["symbol"],
                "Side": o["side"],
                "Qty": o.get("qty") or o.get("notional") or "",
                "Type": o.get("type", ""),
                "Status": o.get("status", ""),
                "Fill price": float(o["filled_avg_price"]) if o.get("filled_avg_price") else None,
            } for o in orders])
            st.dataframe(
                odf, width="stretch", hide_index=True,
                column_config={"Fill price": st.column_config.NumberColumn(format="dollar")},
            )
        else:
            st.caption("No recent orders.")


# ------------------------------------------------------------------- main

@st.fragment(run_every="60s")
def main_view():
    view = st.session_state.get("view", "Overview")
    period = st.session_state.get("period", "1M")
    render_header(view)
    if view == "Overview":
        render_overview(period)
    else:
        acct = next((a for a in ACCOUNTS if a.name == view), None)
        if acct is None:
            render_overview(period)
        else:
            render_account(acct, period)


if not check_password():
    st.stop()

if not ACCOUNTS:
    st.error("No accounts configured. Copy `.env.example` to `.env` and add your Alpaca keys.")
    st.stop()

with st.sidebar:
    st.markdown("### View")
    st.radio("View", ["Overview"] + [a.name for a in ACCOUNTS],
             key="view", label_visibility="collapsed")
    st.markdown("### Period")
    st.radio("Period", PERIOD_LABELS, index=PERIOD_LABELS.index("1M"),
             key="period", horizontal=True, label_visibility="collapsed")
    if st.button("Refresh now", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Data auto-refreshes every 60 s (30 s API cache).")

main_view()
