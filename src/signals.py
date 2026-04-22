"""
Technical analysis engine for BTC 5m prediction.
Uses Binance API as primary, Yahoo Finance as fallback.
"""
import logging
import time
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
    direction: str  # "UP" or "DOWN"
    confidence: float  # 0.0 - 1.0
    ema_slope: float
    rsi: float
    momentum: float
    window_delta_pct: float
    entry_price: float
    analysis: str

class SignalEngine:
    def __init__(self, ema_period: int = 50, rsi_period: int = 14, atr_period: int = 14):
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self._klines_cache: Optional[pd.DataFrame] = None
        self._cache_time = 0

    def _fetch_binance_klines(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 200) -> pd.DataFrame:
        """Fetch 1-minute klines from Binance."""
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
        """Fetch BTC data from Yahoo Finance as fallback."""
        if not YF_AVAILABLE:
            raise ImportError("yfinance not installed. Install with: pip install yfinance")

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            raise ValueError("Yahoo Finance returned empty data")

        df = df.reset_index()
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df["open_time"] = df["Datetime"]
        return df

    def fetch_data(self) -> pd.DataFrame:
        """Fetch data with Binance primary, Yahoo fallback."""
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
                logger.error("Both Binance and Yahoo Finance failed: %s", str(e2))
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

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    def analyze(self) -> SignalResult:
        """
        Main analysis pipeline:
        1. Trend (EMA 50)
        2. Timing (RSI pullback)
        3. Confirmation (Momentum + Structure)
        4. Filter (EMA slope, candle strength, RSI zone, break structure)
        """
        df = self.fetch_data()

        # Indicators
        df["ema50"] = self.calculate_ema(df["close"], self.ema_period)
        df["rsi"] = self.calculate_rsi(df["close"], self.rsi_period)
        df["atr"] = self.calculate_atr(df, self.atr_period)

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        price = latest["close"]
        ema = latest["ema50"]
        rsi = latest["rsi"]

        # EMA slope (last 5 candles)
        ema_slope = (df["ema50"].iloc[-1] - df["ema50"].iloc[-5]) / df["ema50"].iloc[-5] * 100

        # Window delta (current vs window open - for 5m markets)
        window_open = df["open"].iloc[-5]  # approx 5m ago
        window_delta_pct = (price - window_open) / window_open * 100

        # Momentum: last candle body / ATR
        candle_body = abs(latest["close"] - latest["open"])
        atr_val = latest["atr"] if latest["atr"] != 0 else 1e-9
        momentum = candle_body / atr_val

        # Break structure: close above/below previous high/low
        prev_high = prev["high"]
        prev_low = prev["low"]
        break_up = latest["close"] > prev_high
        break_down = latest["close"] < prev_low

        # Trend Direction
        trend_up = price > ema
        trend_down = price < ema

        # Timing (RSI Pullback)
        rsi_pullback_buy = trend_up and rsi < 50
        rsi_pullback_sell = trend_down and rsi > 50

        # Filters
        ema_clear = abs(ema_slope) > 0.01
        strong_candle = momentum > 0.3

        if rsi < 40:
            rsi_zone = "oversold"
        elif rsi > 60:
            rsi_zone = "overbought"
        else:
            rsi_zone = "noise"

        structure_break = break_up or break_down

        # Decision
        direction = "NEUTRAL"
        confidence = 0.0
        analysis_parts = []

        if trend_up and ema_clear:
            analysis_parts.append(f"Trend UP | EMA slope {ema_slope:+.4f}%")
            if rsi_pullback_buy and strong_candle and structure_break and break_up:
                direction = "UP"
                confidence = min(0.95, 0.5 + abs(window_delta_pct) * 10 + momentum * 0.1)
                analysis_parts.append(f"RSI pullback {rsi:.1f} | Momentum {momentum:.2f} | Break UP")
            elif rsi_zone == "oversold" and break_up:
                direction = "UP"
                confidence = 0.6
                analysis_parts.append(f"RSI oversold {rsi:.1f} | Break UP")

        elif trend_down and ema_clear:
            analysis_parts.append(f"Trend DOWN | EMA slope {ema_slope:+.4f}%")
            if rsi_pullback_sell and strong_candle and structure_break and break_down:
                direction = "DOWN"
                confidence = min(0.95, 0.5 + abs(window_delta_pct) * 10 + momentum * 0.1)
                analysis_parts.append(f"RSI pullback {rsi:.1f} | Momentum {momentum:.2f} | Break DOWN")
            elif rsi_zone == "overbought" and break_down:
                direction = "DOWN"
                confidence = 0.6
                analysis_parts.append(f"RSI overbought {rsi:.1f} | Break DOWN")
        else:
            analysis_parts.append(f"Sideways/unclear | EMA slope {ema_slope:+.4f}% | RSI {rsi:.1f}")

        analysis = " | ".join(analysis_parts)

        logger.info("ANALYSIS: %s | Confidence: %.2f | %s", direction, confidence, analysis)

        return SignalResult(
            direction=direction,
            confidence=confidence,
            ema_slope=ema_slope,
            rsi=rsi,
            momentum=momentum,
            window_delta_pct=window_delta_pct,
            entry_price=price,
            analysis=analysis
        )
