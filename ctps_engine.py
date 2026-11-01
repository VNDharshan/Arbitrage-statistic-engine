# """
# CTPS - Statistical Arbitrage Engine with Dynamic Cointegration
# and Z-Score Mean Reversion

# CoinGecko Demo API edition.
# Research and historical backtesting only; it does NOT place live trades.

# Install:
#     pip install requests pandas numpy scipy statsmodels scikit-learn matplotlib

# Windows PowerShell (set a NEW key; do not hard-code it):
#     $env:COINGECKO_API_KEY="YOUR_NEW_DEMO_KEY"
#     python ctps_coingecko_final.py

# Optional:
#     python ctps_coingecko_final.py --coins bitcoin ethereum binancecoin solana
#     python ctps_coingecko_final.py --days 90 --vs-currency usd

# CoinGecko coin IDs are used, not ticker symbols:
#     BTC=bitcoin, ETH=ethereum, BNB=binancecoin, SOL=solana,
#     XRP=ripple, ADA=cardano.

# Outputs are written to ./ctps_output/
# """

# from __future__ import annotations

# import argparse
# import itertools
# import os
# import sys
# import time
# from pathlib import Path
# from typing import Dict, List, Tuple

# import matplotlib
# matplotlib.use("Agg")
# import matplotlib.pyplot as plt
# import numpy as np
# import pandas as pd
# import requests
# from sklearn.cluster import KMeans
# from sklearn.preprocessing import StandardScaler
# from statsmodels.tsa.stattools import adfuller


# BASE_URL = "https://api.coingecko.com/api/v3"
# DEFAULT_COINS = [
#     "bitcoin", "ethereum", "binancecoin", "solana", "ripple", "cardano"
# ]


# def get_api_key() -> str:
#     key = os.getenv("COINGECKO_API_KEY", "").strip()
#     if not key:
#         raise RuntimeError(
#             "COINGECKO_API_KEY is not set.\n"
#             "PowerShell example:\n"
#             '$env:COINGECKO_API_KEY="YOUR_NEW_DEMO_KEY"\n'
#             "Then run this program in the same PowerShell window."
#         )
#     return key


# def fetch_coin_prices(
#     session: requests.Session,
#     coin_id: str,
#     vs_currency: str,
#     days: int,
#     api_key: str,
#     timeout: int = 30,
# ) -> pd.Series:
#     """Fetch CoinGecko market-chart prices. No key is stored in this file."""
#     url = f"{BASE_URL}/coins/{coin_id}/market_chart"
#     # CoinGecko Demo authentication: use the documented query parameter.
#     # This is an alternative to the x-cg-demo-api-key header and helps
#     # diagnose environments/proxies that may strip custom request headers.
#     headers = {"accept": "application/json"}
#     params = {
#         "vs_currency": vs_currency.lower(),
#         "days": str(days),
#         "x_cg_demo_api_key": api_key,
#     }

#     last_error = None
#     for attempt in range(4):
#         try:
#             response = session.get(
#                 url, headers=headers, params=params, timeout=timeout
#             )
#             if response.status_code == 429 or response.status_code >= 500:
#                 wait = min(2 ** attempt * 3, 30)
#                 last_error = (
#                     f"HTTP {response.status_code}: {response.text[:300]}"
#                 )
#                 if attempt < 3:
#                     print(f"  API busy; retrying in {wait}s...")
#                     time.sleep(wait)
#                     continue
#             if response.status_code != 200:
#                 raise RuntimeError(
#                     f"CoinGecko error for '{coin_id}' "
#                     f"(HTTP {response.status_code}): {response.text[:500]}"
#                 )

#             payload = response.json()
#             price_rows = payload.get("prices", [])
#             if not price_rows:
#                 raise RuntimeError(
#                     f"No price history returned for '{coin_id}'. "
#                     "Check the coin ID and Demo API access."
#                 )

#             frame = pd.DataFrame(price_rows, columns=["timestamp_ms", "price"])
#             frame["timestamp"] = pd.to_datetime(
#                 frame["timestamp_ms"], unit="ms", utc=True
#             )
#             frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
#             frame = frame.dropna(subset=["timestamp", "price"])
#             frame = frame.drop_duplicates("timestamp").set_index("timestamp")
#             series = frame["price"].sort_index()
#             series.name = coin_id
#             return series

#         except requests.RequestException as exc:
#             last_error = str(exc)
#             if attempt < 3:
#                 wait = min(2 ** attempt * 3, 30)
#                 print(f"  Network error; retrying in {wait}s...")
#                 time.sleep(wait)

#     raise RuntimeError(
#         f"Could not download '{coin_id}'. Last error: {last_error}"
#     )


# def download_market_data(
#     coin_ids: List[str], vs_currency: str, days: int, api_key: str
# ) -> pd.DataFrame:
#     session = requests.Session()
#     series: Dict[str, pd.Series] = {}
#     failures = []

#     for i, coin_id in enumerate(coin_ids):
#         coin_id = coin_id.strip().lower()
#         print(f"Downloading {coin_id} ({i + 1}/{len(coin_ids)})...")
#         try:
#             series[coin_id] = fetch_coin_prices(
#                 session, coin_id, vs_currency, days, api_key
#             )
#             print(f"  received {len(series[coin_id])} price observations")
#         except Exception as exc:
#             failures.append(f"{coin_id}: {exc}")
#             print(f"  FAILED: {exc}")

#         # Avoid sending requests too quickly on the Demo plan.
#         if i < len(coin_ids) - 1:
#             time.sleep(2.2)

#     if len(series) < 2:
#         raise RuntimeError(
#             "At least two coins must download successfully.\n"
#             + "\n".join(failures)
#         )

#     # CoinGecko may return slightly different timestamps for each asset.
#     # Resample to daily closes so all assets share a common time index.
#     price_frame = pd.concat(series.values(), axis=1).sort_index()
#     daily = price_frame.resample("1D").last().ffill()
#     daily = daily.dropna(how="any")
#     daily = daily.loc[:, daily.nunique() > 1]

#     if daily.shape[1] < 2 or len(daily) < 60:
#         raise RuntimeError(
#             "Fewer than 60 overlapping daily observations were available. "
#             "Try a larger --days value or different coin IDs."
#         )

#     if failures:
#         print("\nSome coins were skipped:")
#         print("\n".join(failures))

#     return daily


# def select_pair(
#     prices: pd.DataFrame, min_correlation: float
# ) -> Tuple[str, str, pd.DataFrame]:
#     log_returns = np.log(prices).diff().dropna()

#     features = pd.DataFrame({
#         "mean_return": log_returns.mean(),
#         "volatility": log_returns.std(),
#         "skew": log_returns.skew(),
#     }).replace([np.inf, -np.inf], np.nan).dropna()

#     if len(features) < 2:
#         raise RuntimeError("Not enough valid assets for pair selection.")

#     n_clusters = min(3, len(features))
#     scaled = StandardScaler().fit_transform(features)
#     labels = KMeans(
#         n_clusters=n_clusters, random_state=42, n_init=10
#     ).fit_predict(scaled)
#     cluster = dict(zip(features.index, labels))

#     pairs = []
#     for a, b in itertools.combinations(features.index.tolist(), 2):
#         corr = float(log_returns[a].corr(log_returns[b]))
#         if abs(corr) >= min_correlation and cluster[a] == cluster[b]:
#             pairs.append((a, b, corr))

#     # Fallback: correlated pairs even if they are in different clusters.
#     if not pairs:
#         for a, b in itertools.combinations(features.index.tolist(), 2):
#             corr = float(log_returns[a].corr(log_returns[b]))
#             if abs(corr) >= min_correlation:
#                 pairs.append((a, b, corr))

#     if not pairs:
#         raise RuntimeError(
#             "No candidate pair passed the correlation threshold. "
#             "Try more coin IDs or lower --min-correlation."
#         )

#     results = []
#     best_pair = None
#     best_p = float("inf")

#     for a, b, corr in pairs:
#         # Regress log(b) on log(a); test the residual for stationarity.
#         log_a = np.log(prices[a])
#         log_b = np.log(prices[b])
#         beta = np.polyfit(log_a.to_numpy(), log_b.to_numpy(), 1)[0]
#         residual = log_b - beta * log_a
#         try:
#             pvalue = float(
#                 adfuller(residual.dropna(), regression="c", autolag="AIC")[1]
#             )
#         except Exception:
#             pvalue = 1.0

#         results.append({
#             "coin_y": b,
#             "coin_x": a,
#             "return_correlation": corr,
#             "residual_adf_pvalue": pvalue,
#             "same_cluster": cluster[a] == cluster[b],
#         })
#         if pvalue < best_p:
#             best_p = pvalue
#             best_pair = (b, a)

#     ranking = pd.DataFrame(results).sort_values(
#         "residual_adf_pvalue"
#     ).reset_index(drop=True)

#     if best_pair is None:
#         raise RuntimeError("Pair selection failed.")
#     return best_pair[0], best_pair[1], ranking


# def estimate_half_life(spread: pd.Series) -> float:
#     clean = spread.dropna()
#     lagged = clean.shift(1)
#     delta = clean.diff()
#     aligned = pd.concat(
#         [delta.rename("delta"), lagged.rename("lagged")], axis=1
#     ).dropna()

#     if len(aligned) < 20:
#         return float("inf")

#     slope = np.polyfit(
#         aligned["lagged"].to_numpy(),
#         aligned["delta"].to_numpy(),
#         1,
#     )[0]
#     if slope >= 0:
#         return float("inf")

#     half_life = -np.log(2) / slope
#     return float(half_life) if np.isfinite(half_life) else float("inf")


# def run_backtest(
#     prices: pd.DataFrame,
#     coin_y: str,
#     coin_x: str,
#     hedge_window: int,
#     z_window: int,
#     entry_z: float,
#     exit_z: float,
#     fee: float,
#     slippage: float,
#     adf_cutoff: float,
# ) -> Tuple[pd.DataFrame, dict]:
#     log_y = np.log(prices[coin_y])
#     log_x = np.log(prices[coin_x])

#     # Rolling hedge ratio: only trailing observations are used.
#     beta = (
#         log_y.rolling(hedge_window).cov(log_x)
#         / log_x.rolling(hedge_window).var()
#     ).replace([np.inf, -np.inf], np.nan)

#     spread = log_y - beta * log_x
#     rolling_mean = spread.rolling(z_window).mean()
#     rolling_std = spread.rolling(z_window).std(ddof=1)
#     zscore = (spread - rolling_mean) / rolling_std.replace(0, np.nan)

#     sample = spread.dropna()
#     adf_pvalue = float(
#         adfuller(sample, regression="c", autolag="AIC")[1]
#     )
#     half_life = estimate_half_life(spread)

#     data = pd.DataFrame({
#         "price_y": prices[coin_y],
#         "price_x": prices[coin_x],
#         "hedge_ratio": beta,
#         "spread": spread,
#         "zscore": zscore,
#     }).dropna().copy()

#     # Mean-reversion state machine.
#     position = 0
#     positions = []
#     for z in data["zscore"]:
#         if position == 0:
#             if z <= -entry_z:
#                 position = 1       # Long spread
#             elif z >= entry_z:
#                 position = -1      # Short spread
#         elif position == 1 and z >= -exit_z:
#             position = 0
#         elif position == -1 and z <= exit_z:
#             position = 0
#         positions.append(position)

#     data["signal"] = positions
#     # Shift by one daily observation to avoid trading on the signal bar.
#     data["position"] = data["signal"].shift(1).fillna(0)

#     # Approximate hedged log-return P&L.
#     y_ret = np.log(data["price_y"]).diff()
#     x_ret = np.log(data["price_x"]).diff()
#     hedge_lag = data["hedge_ratio"].shift(1)
#     data["gross_return"] = (
#         data["position"] * (y_ret - hedge_lag * x_ret)
#     )

#     # Approximate costs on changes in both legs' exposure.
#     turnover = data["position"].diff().abs()
#     if len(turnover):
#         turnover.iloc[0] = abs(data["position"].iloc[0])
#     cost_per_leg = fee + slippage
#     exposure = 1 + hedge_lag.abs().fillna(0)
#     data["transaction_cost"] = turnover * cost_per_leg * exposure
#     data["net_return"] = (
#         data["gross_return"].fillna(0)
#         - data["transaction_cost"].fillna(0)
#     )

#     # Do not present the strategy as active if the residual ADF test fails.
#     if adf_pvalue > adf_cutoff:
#         data["position"] = 0.0
#         data["signal"] = 0.0
#         data["gross_return"] = 0.0
#         data["transaction_cost"] = 0.0
#         data["net_return"] = 0.0

#     data["equity"] = (1 + data["net_return"]).cumprod()
#     drawdown = data["equity"] / data["equity"].cummax() - 1

#     daily_vol = data["net_return"].std(ddof=1)
#     sharpe = (
#         np.sqrt(365) * data["net_return"].mean() / daily_vol
#         if daily_vol and np.isfinite(daily_vol) else 0.0
#     )

#     summary = {
#         "coin_y": coin_y,
#         "coin_x": coin_x,
#         "observations": int(len(data)),
#         "adf_pvalue": adf_pvalue,
#         "adf_gate_passed": bool(adf_pvalue <= adf_cutoff),
#         "ou_half_life_days_approx": half_life,
#         "total_return_pct": float((data["equity"].iloc[-1] - 1) * 100),
#         "annualized_sharpe_approx": float(sharpe),
#         "max_drawdown_pct": float(drawdown.min() * 100),
#         "position_changes": int(
#             data["position"].diff().fillna(data["position"]).abs().gt(0).sum()
#         ),
#         "fee_rate_per_leg": fee,
#         "slippage_rate_per_leg": slippage,
#         "entry_z": entry_z,
#         "exit_z": exit_z,
#     }
#     return data, summary


# def save_results(
#     prices: pd.DataFrame,
#     backtest: pd.DataFrame,
#     ranking: pd.DataFrame,
#     summary: dict,
#     output_dir: Path,
# ) -> None:
#     output_dir.mkdir(parents=True, exist_ok=True)
#     prices.to_csv(output_dir / "prices.csv")
#     backtest.to_csv(output_dir / "backtest.csv", index_label="date")
#     ranking.to_csv(output_dir / "pair_ranking.csv", index=False)

#     fig, ax = plt.subplots(figsize=(11, 5))
#     ax.plot(backtest.index, backtest["equity"], label="Strategy equity")
#     ax.set_title("CTPS - Equity Curve (estimated costs included)")
#     ax.set_xlabel("Date")
#     ax.set_ylabel("Growth of 1 unit")
#     ax.grid(True, alpha=0.3)
#     ax.legend()
#     fig.tight_layout()
#     fig.savefig(output_dir / "equity_curve.png", dpi=160)
#     plt.close(fig)

#     fig, ax = plt.subplots(figsize=(11, 4))
#     ax.plot(backtest.index, backtest["zscore"], label="Rolling Z-score")
#     ax.axhline(summary["entry_z"], linestyle="--", label="Entry threshold")
#     ax.axhline(-summary["entry_z"], linestyle="--")
#     ax.axhline(summary["exit_z"], linestyle=":", label="Exit threshold")
#     ax.axhline(-summary["exit_z"], linestyle=":")
#     ax.axhline(0, linewidth=0.8)
#     ax.set_title("Spread Z-score")
#     ax.set_xlabel("Date")
#     ax.set_ylabel("Z-score")
#     ax.grid(True, alpha=0.3)
#     ax.legend()
#     fig.tight_layout()
#     fig.savefig(output_dir / "zscore.png", dpi=160)
#     plt.close(fig)

#     lines = [
#         "CTPS - CoinGecko Statistical Arbitrage Backtest",
#         "=" * 48,
#         f"Y coin: {summary['coin_y']}",
#         f"X coin: {summary['coin_x']}",
#         f"Observations: {summary['observations']}",
#         f"ADF p-value: {summary['adf_pvalue']:.6f}",
#         f"ADF gate passed: {summary['adf_gate_passed']}",
#         f"OU half-life (approx. days): {summary['ou_half_life_days_approx']:.3f}",
#         f"Total return: {summary['total_return_pct']:.3f}%",
#         f"Annualized Sharpe (approx.): {summary['annualized_sharpe_approx']:.3f}",
#         f"Maximum drawdown: {summary['max_drawdown_pct']:.3f}%",
#         f"Position changes: {summary['position_changes']}",
#         f"Fee per leg: {summary['fee_rate_per_leg']:.5f}",
#         f"Slippage per leg: {summary['slippage_rate_per_leg']:.5f}",
#         "",
#         "Research/backtesting only. No live orders are placed.",
#         "Backtest returns, hedge P&L, fees and slippage are approximations.",
#         "Full-sample pair selection and ADF testing can introduce selection bias.",
#         "Use walk-forward and out-of-sample tests before drawing conclusions.",
#     ]
#     (output_dir / "summary.txt").write_text(
#         "\n".join(lines), encoding="utf-8"
#     )


# def parse_args() -> argparse.Namespace:
#     parser = argparse.ArgumentParser(
#         description="CTPS statistical arbitrage research engine using CoinGecko."
#     )
#     parser.add_argument(
#         "--coins", nargs="+", default=DEFAULT_COINS,
#         help="CoinGecko IDs, e.g. bitcoin ethereum solana",
#     )
#     parser.add_argument("--vs-currency", default="usd")
#     parser.add_argument("--days", type=int, default=365)
#     parser.add_argument("--hedge-window", type=int, default=60)
#     parser.add_argument("--z-window", type=int, default=30)
#     parser.add_argument("--entry-z", type=float, default=2.0)
#     parser.add_argument("--exit-z", type=float, default=0.5)
#     parser.add_argument("--fee", type=float, default=0.001,
#                         help="Estimated fee per leg; 0.001 = 0.1%%")
#     parser.add_argument("--slippage", type=float, default=0.0005,
#                         help="Estimated slippage per leg; 0.0005 = 0.05%%")
#     parser.add_argument("--adf-cutoff", type=float, default=0.05)
#     parser.add_argument("--min-correlation", type=float, default=0.50)
#     parser.add_argument("--output-dir", default="ctps_output")
#     return parser.parse_args()


# def main() -> None:
#     args = parse_args()

#     if args.days < 90:
#         raise SystemExit(
#             "Use at least 90 days so the project has enough daily observations."
#         )
#     if args.hedge_window < 10 or args.z_window < 5:
#         raise SystemExit("Use hedge-window >= 10 and z-window >= 5.")
#     if args.entry_z <= args.exit_z or args.exit_z < 0:
#         raise SystemExit("entry-z must be greater than exit-z >= 0.")
#     if not 0 <= args.adf_cutoff <= 1:
#         raise SystemExit("adf-cutoff must be between 0 and 1.")

#     api_key = get_api_key()

#     print("\nCTPS Statistical Arbitrage Engine")
#     print("--------------------------------")
#     print("Data provider: CoinGecko Demo API")
#     print("Mode: historical research/backtesting only")
#     print("API key: loaded from environment variable (not displayed)\n")

#     prices = download_market_data(
#         args.coins, args.vs_currency, args.days, api_key
#     )
#     print(f"\nSynchronized daily dataset: {prices.shape[0]} rows x {prices.shape[1]} coins")

#     coin_y, coin_x, ranking = select_pair(
#         prices, min_correlation=args.min_correlation
#     )
#     print("\nPair ranking:")
#     print(ranking.to_string(index=False))
#     print(f"\nSelected pair: {coin_y} against {coin_x}")

#     backtest, summary = run_backtest(
#         prices=prices,
#         coin_y=coin_y,
#         coin_x=coin_x,
#         hedge_window=args.hedge_window,
#         z_window=args.z_window,
#         entry_z=args.entry_z,
#         exit_z=args.exit_z,
#         fee=args.fee,
#         slippage=args.slippage,
#         adf_cutoff=args.adf_cutoff,
#     )

#     output_dir = Path(args.output_dir)
#     save_results(prices, backtest, ranking, summary, output_dir)

#     print("\nBacktest summary")
#     print("----------------")
#     for key, value in summary.items():
#         print(f"{key}: {value}")
#     print(f"\nOutput folder: {output_dir.resolve()}")
#     print("No live orders were placed.")


# if __name__ == "__main__":
#     try:
#         main()
#     except KeyboardInterrupt:
#         print("\nStopped by user.")
#         sys.exit(130)
#     except Exception as exc:
#         print(f"\nPROJECT ERROR: {exc}", file=sys.stderr)
#         sys.exit(1)

