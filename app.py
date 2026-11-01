from __future__ import annotations

import io
import json
import math
import os
import threading
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_from_directory

import ctps_engine as engine

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "ctps_output"
app = Flask(__name__)
run_lock = threading.Lock()
state = {"running": False, "last_error": None, "last_summary": None, "last_log": "No run yet."}


def clean_value(value):
    if value is None:
        return None
    if isinstance(value, (float,)) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return clean_value(value.item())
    return value


def frame_records(frame: pd.DataFrame, limit: int = 500):
    data = frame.tail(limit).copy()
    data.index = data.index.astype(str)
    data = data.replace([float("inf"), float("-inf")], pd.NA)
    data = data.astype(object).where(pd.notna(data), None)
    return [{"date": idx, **{k: clean_value(v) for k, v in row.items()}}
            for idx, row in data.iterrows()]


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    return jsonify(state)


@app.post("/api/run")
def api_run():
    if run_lock.locked():
        return jsonify({"ok": False, "error": "A backtest is already running."}), 409
    payload = request.get_json(silent=True) or {}
    try:
        coins = [x.strip().lower() for x in payload.get("coins", ["bitcoin", "ethereum", "binancecoin", "solana", "ripple", "cardano"]) if x.strip()]
        days = int(payload.get("days", 365))
        hedge_window = int(payload.get("hedge_window", 60))
        z_window = int(payload.get("z_window", 30))
        entry_z = float(payload.get("entry_z", 2.0))
        exit_z = float(payload.get("exit_z", 0.5))
        fee = float(payload.get("fee", 0.001))
        slippage = float(payload.get("slippage", 0.0005))
        adf_cutoff = float(payload.get("adf_cutoff", 0.05))
        min_corr = float(payload.get("min_correlation", 0.50))
        if len(coins) < 2 or len(set(coins)) != len(coins):
            raise ValueError("Enter at least two unique CoinGecko coin IDs.")
        if not 90 <= days <= 3650:
            raise ValueError("Days must be between 90 and 3650.")
        if hedge_window < 10 or z_window < 5:
            raise ValueError("Hedge window must be >=10 and Z-score window >=5.")
        if entry_z <= exit_z or exit_z < 0:
            raise ValueError("Entry Z must be greater than exit Z, and exit Z cannot be negative.")
        if not 0 <= adf_cutoff <= 1 or not 0 <= min_corr <= 1:
            raise ValueError("ADF cutoff and minimum correlation must be between 0 and 1.")
        if fee < 0 or slippage < 0:
            raise ValueError("Estimated costs cannot be negative.")
        api_key = engine.get_api_key()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    with run_lock:
        state.update(running=True, last_error=None, last_log="Starting historical data download…")
        log = io.StringIO()
        try:
            with redirect_stdout(log):
                prices = engine.download_market_data(coins, "usd", days, api_key)
                coin_y, coin_x, ranking = engine.select_pair(prices, min_correlation=min_corr)
                backtest, summary = engine.run_backtest(
                    prices=prices, coin_y=coin_y, coin_x=coin_x,
                    hedge_window=hedge_window, z_window=z_window,
                    entry_z=entry_z, exit_z=exit_z, fee=fee,
                    slippage=slippage, adf_cutoff=adf_cutoff,
                )
                engine.save_results(prices, backtest, ranking, summary, OUTPUT_DIR)
            state["last_summary"] = summary
            state["last_log"] = log.getvalue()
            state["last_error"] = None
            return jsonify({
                "ok": True,
                "summary": summary,
                "ranking": frame_records(ranking, 100),
                "series": frame_records(backtest[["zscore", "equity", "signal", "position", "hedge_ratio"]], 500),
                "log": log.getvalue(),
                "warning": "This is an in-sample research backtest. Pair selection and the ADF gate use the same full history; this can create selection bias. Results are estimates, not evidence of a reliable trading edge."
            })
        except Exception as exc:
            state["last_error"] = str(exc)
            state["last_log"] = log.getvalue()
            return jsonify({"ok": False, "error": str(exc), "log": log.getvalue()}), 500
        finally:
            state["running"] = False


@app.get("/api/file/<path:filename>")
def get_output_file(filename):
    allowed = {"summary.txt", "prices.csv", "backtest.csv", "pair_ranking.csv", "equity_curve.png", "zscore.png"}
    if filename not in allowed or not (OUTPUT_DIR / filename).is_file():
        return jsonify({"error": "File not found. Run a backtest first."}), 404
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=filename.endswith((".csv", ".txt")))


if __name__ == "__main__":
    print("CTPS dashboard: http://127.0.0.1:5000")
    print("Set COINGECKO_API_KEY in this PowerShell session before starting.")
    app.run(host="127.0.0.1", port=5000, debug=False)

