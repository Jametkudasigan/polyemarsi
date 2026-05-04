"""Binance API Client untuk fetch klines"""
import requests
import time
from typing import List, Dict, Optional
from config.settings import Config


class BinanceClient:
    def __init__(self):
        self.base_url = "https://api.binance.com"
        self.session = requests.Session()

    def get_klines(self, symbol: str = Config.SYMBOL, interval: str = Config.INTERVAL, 
                   limit: int = Config.KLINE_LIMIT) -> List[List]:
        """Fetch candlestick data dari Binance

        Returns list of candles:
        [timestamp, open, high, low, close, volume, close_time, quote_volume, 
         trades, taker_buy_base, taker_buy_quote, ignore]
        """
        url = f"{self.base_url}/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"[Binance Error] {e}")
            return []

    def get_current_price(self, symbol: str = Config.SYMBOL) -> Optional[float]:
        """Get harga BTC/USDT saat ini"""
        url = f"{self.base_url}/api/v3/ticker/price"
        try:
            resp = self.session.get(url, params={"symbol": symbol}, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            return float(data["price"])
        except Exception as e:
            print(f"[Binance Price Error] {e}")
            return None
