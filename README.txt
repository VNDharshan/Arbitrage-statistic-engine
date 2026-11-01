CTPS HTML DASHBOARD — WINDOWS SETUP
===================================

1) Extract this folder to a convenient location.
2) Open PowerShell in the extracted ctps_dashboard folder.
3) Install dependencies:
   py -m pip install -r requirements.txt

4) Set your NEW CoinGecko Demo API key in that same PowerShell window:
   $env:COINGECKO_API_KEY="YOUR_NEW_DEMO_KEY"
   Do not paste the key into HTML, Python source, screenshots, or chat.

5) Start the dashboard:
   py app.py

6) Open this address in your browser:
   http://127.0.0.1:5000

7) Configure the coins and model settings, then click Run historical backtest.
   CSV and summary downloads appear after a successful run.

IMPORTANT
---------
- Keep the PowerShell window open while using the dashboard.
- The dashboard is local to your computer (127.0.0.1).
- It downloads historical CoinGecko data and runs the existing Python engine.
- It does not connect to an exchange or place orders.
- Existing model limitations remain: full-sample pair selection and ADF testing
  can introduce selection bias. Treat results as an academic demonstration,
  not proof of a profitable strategy. A walk-forward evaluation is a needed
  next methodological improvement.
- If the CoinGecko key was previously exposed, revoke it and use a replacement.
