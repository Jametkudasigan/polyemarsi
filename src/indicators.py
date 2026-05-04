"""Technical Indicators: EMA & RSI"""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple


def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return np.array([])
    multiplier = 2.0 / (period + 1)
    ema = np.zeros_like(prices)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = (prices[i] * multiplier) + (ema[i-1] * (1 - multiplier))
    return ema


def calculate_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Calculate RSI (Relative Strength Index)"""
    if len(prices) < period + 1:
        return np.array([])
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.zeros_like(prices)
    avg_loss = np.zeros_like(prices)

    # Initial averages
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    # Smoothed averages
    for i in range(period + 1, len(prices)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period

    rs = np.where(avg_loss == 0, 0, avg_gain / avg_loss)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def analyze_momentum(candles: List[List]) -> Dict:
    """
    Analisis momentum dari candlestick Binance.
    Candle format: [timestamp, open, high, low, close, volume, ...]

    Returns:
        signal: 'BUY' | 'SELL' | 'NEUTRAL'
        confidence: 0.0 - 1.0
        details: dict dengan nilai indikator
    """
    if len(candles) < 25:
        return {"signal": "NEUTRAL", "confidence": 0.0, "details": {"error": "Insufficient data"}}

    closes = np.array([float(c[4]) for c in candles])
    opens = np.array([float(c[1]) for c in candles])
    highs = np.array([float(c[2]) for c in candles])
    lows = np.array([float(c[3]) for c in candles])

    # Calculate indicators
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    rsi = calculate_rsi(closes, 14)

    if len(ema9) < 2 or len(ema21) < 2 or len(rsi) < 2:
        return {"signal": "NEUTRAL", "confidence": 0.0, "details": {"error": "Indicator calc failed"}}

    current_price = closes[-1]
    prev_price = closes[-2]
    current_ema9 = ema9[-1]
    current_ema21 = ema21[-1]
    prev_ema9 = ema9[-2]
    prev_ema21 = ema21[-2]
    current_rsi = rsi[-1]
    prev_rsi = rsi[-2]

    details = {
        "price": current_price,
        "ema9": round(current_ema9, 2),
        "ema21": round(current_ema21, 2),
        "rsi": round(current_rsi, 2),
        "prev_rsi": round(prev_rsi, 2),
        "candle_count": len(candles),
    }

    signal = "NEUTRAL"
    confidence = 0.0

    # ===================== BUY SETUP =====================
    # Harga di atas EMA 21
    # EMA 9 di atas EMA 21
    # RSI 14 turun ke 30-45 lalu mantul naik
    # Entry pas candle mulai naik lagi
    buy_conditions = [
        current_price > current_ema21,           # Harga di atas EMA21
        current_ema9 > current_ema21,             # EMA9 di atas EMA21
        prev_ema9 <= prev_ema21 and current_ema9 > current_ema21,  # Crossover atau sustain
    ]

    # RSI bounce: sebelumnya di 30-45, sekarang naik
    rsi_bounce_buy = (30 <= prev_rsi <= 55) and (current_rsi > prev_rsi) and (current_rsi >= 35)

    # Candle mulai naik
    candle_rising = current_price > prev_price

    if all(buy_conditions) and rsi_bounce_buy and candle_rising:
        signal = "BUY"
        # Confidence dari depth RSI + strength bounce
        rsi_strength = min((current_rsi - 30) / 25, 1.0)  # Normalized 30-55
        ema_strength = min((current_ema9 - current_ema21) / (current_ema21 * 0.002), 1.0)
        confidence = min(0.5 + (rsi_strength * 0.3) + (ema_strength * 0.2), 1.0)

    # ===================== SELL SETUP =====================
    # Harga di bawah EMA 21
    # EMA 9 di bawah EMA 21
    # RSI 14 naik ke 55-70 lalu turun
    # Entry pas candle mulai turun lagi
    sell_conditions = [
        current_price < current_ema21,            # Harga di bawah EMA21
        current_ema9 < current_ema21,              # EMA9 di bawah EMA21
        prev_ema9 >= prev_ema21 and current_ema9 < current_ema21,  # Crossover atau sustain
    ]

    # RSI drop: sebelumnya di 55-70, sekarang turun
    rsi_drop_sell = (55 <= prev_rsi <= 75) and (current_rsi < prev_rsi) and (current_rsi <= 65)

    # Candle mulai turun
    candle_falling = current_price < prev_price

    if all(sell_conditions) and rsi_drop_sell and candle_falling:
        signal = "SELL"
        rsi_strength = min((70 - current_rsi) / 20, 1.0)
        ema_strength = min((current_ema21 - current_ema9) / (current_ema21 * 0.002), 1.0)
        confidence = min(0.5 + (rsi_strength * 0.3) + (ema_strength * 0.2), 1.0)

    details["signal"] = signal
    details["confidence"] = round(confidence, 2)

    return {
        "signal": signal,
        "confidence": confidence,
        "details": details
    }
