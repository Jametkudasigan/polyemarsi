"""
Technical analysis engine for BTC 5m prediction.
Uses Binance API as primary, Yahoo Finance as fallback.

STRATEGY: EMA 9/21 Crossover + RSI 14 Bounce
🟢 BUY: Price > EMA21, EMA9 > EMA21, RSI turun ke 35-40 lalu mantul naik
🔴 SELL: Price < EMA21, EMA9 < EMA21, RSI naik ke 60-65 lalu turun
"""
import logging
from typing import Optional
from dataclasses import dataclass

import requests
import numpy as np
import pandas as pd

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

@dataclass
class SignalResult:
    direction: str
    confidence: float
    ema_fast: float
    ema_slow: float
    rsi: float
    prev_rsi: float
    price: float
    analysis: str

class SignalEngine:
    def __init__(self, ema_fast: int = 9, ema_slow: int = 21, rsi_period: int = 14, atr_period: int = 14):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.atr_period = atr_period

    def _fetch_binance_klines(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 200) -> pd.DataFrame:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
        ])

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        return df

    def _fetch_yahoo_fallback(self, symbol: str = "BTC-USD", period: str = "1d", interval: str = "1m") -> pd.DataFrame:
        if not YF_AVAILABLE:
            raise ImportError("yfinance not installed")

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            raise ValueError("Yahoo Finance returned empty data")

        df = df.reset_index()
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df["open_time"] = df["Datetime"]
        return df

    def fetch_data(self) -> pd.DataFrame:
        try:
            df = self._fetch_binance_klines()
            logger.info("Binance data loaded | %d candles", len(df))
            return df
        except Exception as e:
            logger.warning("Binance failed (%s), trying Yahoo Finance...", str(e))
            try:
                df = self._fetch_yahoo_fallback()
                logger.info("Yahoo Finance fallback loaded | %d candles", len(df))
                return df
            except Exception as e2:
                logger.error("Both failed: %s", str(e2))
                raise

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def analyze(self) -> SignalResult:
        """
        🟢 BUY:  Price > EMA21, EMA9 > EMA21, RSI turun 35-40 lalu mantul naik
        🔴 SELL: Price < EMA21, EMA9 < EMA21, RSI naik 60-65 lalu turun
        """
        df = self.fetch_data()

        # Indicators
        df["ema_fast"] = self.calculate_ema(df["close"], self.ema_fast)
        df["ema_slow"] = self.calculate_ema(df["close"], self.ema_slow)
        df["rsi"] = self.calculate_rsi(df["close"], self.rsi_period)

        # 3 candle terakhir
        c_now = df.iloc[-1]
        c_prev = df.iloc[-2]
        c_prev2 = df.iloc[-3]

        price = c_now["close"]
        ema_f = c_now["ema_fast"]
        ema_s = c_now["ema_slow"]
        rsi = c_now["rsi"]
        prev_rsi = c_prev["rsi"]
        prev2_rsi = c_prev2["rsi"]

        # Trend
        trend_up = price > ema_s and ema_f > ema_s
        trend_down = price < ema_s and ema_f < ema_s

        # RSI Bounce Detection
        rsi_bounce_buy = (
            prev_rsi < 40 and
            rsi > prev_rsi and
            prev2_rsi > prev_rsi
        )

        rsi_bounce_sell = (
            prev_rsi > 60 and
            rsi < prev_rsi and
            prev2_rsi < prev_rsi
        )

        # Candle direction
        candle_up = c_now["close"] > c_now["open"]
        candle_down = c_now["close"] < c_now["open"]

        # Decision
        direction = "NEUTRAL"
        confidence = 0.0
        analysis_parts = []

        if trend_up:
            analysis_parts.append(f"Trend UP | EMA{self.ema_fast}({ema_f:.2f}) > EMA{self.ema_slow}({ema_s:.2f})")

            if rsi_bounce_buy and candle_up:
                direction = "UP"
                depth = max(0, 40 - prev_rsi)
                strength = rsi - prev_rsi
                confidence = min(0.95, 0.6 + (depth * 0.01) + (strength * 0.02))
                analysis_parts.append(f"RSI bounce {prev_rsi:.1f} -> {rsi:.1f} | Candle UP")
            elif rsi_bounce_buy and not candle_up:
                analysis_parts.append(f"RSI bounce detected but candle belum naik | wait")
            else:
                analysis_parts.append(f"RSI {rsi:.1f} (prev {prev_rsi:.1f}) | Waiting bounce 35-40")

        elif trend_down:
            analysis_parts.append(f"Trend DOWN | EMA{self.ema_fast}({ema_f:.2f}) < EMA{self.ema_slow}({ema_s:.2f})")

            if rsi_bounce_sell and candle_down:
                direction = "DOWN"
                height = max(0, prev_rsi - 60)
                strength = prev_rsi - rsi
                confidence = min(0.95, 0.6 + (height * 0.01) + (strength * 0.02))
                analysis_parts.append(f"RSI reject {prev_rsi:.1f} -> {rsi:.1f} | Candle DOWN")
            elif rsi_bounce_sell and not candle_down:
                analysis_parts.append(f"RSI reject detected but candle belum turun | wait")
            else:
                analysis_parts.append(f"RSI {rsi:.1f} (prev {prev_rsi:.1f}) | Waiting reject 60-65")
        else:
            analysis_parts.append(
                f"Sideways | Price {price:.2f} vs EMA{self.ema_slow} {ema_s:.2f} | EMA{self.ema_fast} {ema_f:.2f}"
            )

        analysis = " | ".join(analysis_parts)
        logger.info("ANALYSIS: %s | Confidence: %.2f | %s", direction, confidence, analysis)

        return SignalResult(
            direction=direction,
            confidence=confidence,
            ema_fast=ema_f,
            ema_slow=ema_s,
            rsi=rsi,
            prev_rsi=prev_rsi,
            price=price,
            analysis=analysis
        )
