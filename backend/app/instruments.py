from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


SECURITY_MASTER_URL = (
    "https://traderweb.icicidirect.com/Content/File/txtFile/ScripFile/StockScriptNew.csv"
)

# Current NIFTY 50 aliases provide a safe fallback if the daily master download
# is temporarily unavailable. The master file remains authoritative.
NSE_TO_BREEZE: dict[str, str] = {
    "ADANIENT": "ADAENT",
    "ADANIPORTS": "ADAPOR",
    "APOLLOHOSP": "APOHOS",
    "ASIANPAINT": "ASIPAI",
    "AXISBANK": "AXIBAN",
    "BAJAJ-AUTO": "BAAUTO",
    "BAJAJFINSV": "BAFINS",
    "BAJFINANCE": "BAJFI",
    "BEL": "BHAELE",
    "BHARTIARTL": "BHAAIR",
    "CIPLA": "CIPLA",
    "COALINDIA": "COALIN",
    "DRREDDY": "DRREDD",
    "EICHERMOT": "EICMOT",
    "ETERNAL": "ZOMLIM",
    "GRASIM": "GRASIM",
    "HCLTECH": "HCLTEC",
    "HDFCBANK": "HDFBAN",
    "HDFCLIFE": "HDFSTA",
    "HEROMOTOCO": "HERHON",
    "HINDALCO": "HINDAL",
    "HINDUNILVR": "HINLEV",
    "ICICIBANK": "ICIBAN",
    "INDUSINDBK": "INDBA",
    "INFY": "INFTEC",
    "ITC": "ITC",
    "JIOFIN": "JIOFIN",
    "JSWSTEEL": "JSWSTE",
    "KOTAKBANK": "KOTMAH",
    "LT": "LARTOU",
    "M&M": "MAHMAH",
    "MARUTI": "MARUTI",
    "NESTLEIND": "NESIND",
    "NTPC": "NTPC",
    "ONGC": "ONGC",
    "POWERGRID": "POWGRI",
    "RELIANCE": "RELIND",
    "SBILIFE": "SBILIF",
    "SBIN": "STABAN",
    "SHRIRAMFIN": "SHRTRA",
    "SUNPHARMA": "SUNPHA",
    "TATACONSUM": "TATGLO",
    "TATASTEEL": "TATSTE",
    "TCS": "TCS",
    "TECHM": "TECMAH",
    "TITAN": "TITIND",
    "TRENT": "TRENT",
    "ULTRACEMCO": "ULTCEM",
    "WIPRO": "WIPRO",
}


class InstrumentMapper:
    def __init__(self, cache_path: str):
        self.cache_path = Path(cache_path)
        self._nse_to_breeze = dict(NSE_TO_BREEZE)
        self._breeze_to_nse = {value: key for key, value in self._nse_to_breeze.items()}
        self._loaded_master = False

    def to_breeze(self, nse_symbol: str) -> str:
        symbol = nse_symbol.upper()
        if symbol not in self._nse_to_breeze:
            self._load_master()
        return self._nse_to_breeze.get(symbol, symbol)

    def to_nse(self, breeze_code: str | None) -> str | None:
        if not breeze_code:
            return breeze_code
        code = breeze_code.upper()
        if code not in self._breeze_to_nse:
            self._load_master()
        return self._breeze_to_nse.get(code, code)

    def _load_master(self) -> None:
        if self._loaded_master:
            return
        self._loaded_master = True
        try:
            path = self._fresh_cache() or self._download()
            self._read(path)
        except (OSError, requests.RequestException, csv.Error):
            # Existing aliases and identity mapping remain available. Breeze
            # will reject an unknown code rather than receive a guessed code.
            return

    def _fresh_cache(self) -> Path | None:
        if not self.cache_path.exists():
            return None
        modified = datetime.fromtimestamp(self.cache_path.stat().st_mtime, timezone.utc)
        if datetime.now(timezone.utc) - modified <= timedelta(hours=24):
            return self.cache_path
        return None

    def _download(self) -> Path:
        response = requests.get(SECURITY_MASTER_URL, timeout=20)
        response.raise_for_status()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_bytes(response.content)
        return self.cache_path

    def _read(self, path: Path) -> None:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if (
                    row.get("EC") != "NSE"
                    or row.get("SG") != "EQUITY"
                    or row.get("SR") != "EQ"
                ):
                    continue
                nse_symbol = (row.get("NS") or "").strip().upper()
                breeze_code = (row.get("SC") or "").strip().upper()
                if nse_symbol and breeze_code:
                    self._nse_to_breeze[nse_symbol] = breeze_code
                    self._breeze_to_nse[breeze_code] = nse_symbol
