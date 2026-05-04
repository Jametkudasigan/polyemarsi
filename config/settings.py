"""Konfigurasi bot - load dari .env"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Polymarket
    POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY", "").strip()
    POLY_PROXY_ADDRESS = os.getenv("POLY_PROXY_ADDRESS", "").strip()
    POLY_SIGNATURE_TYPE = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))

    # API Endpoints
    CLOB_HOST = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"
    DATA_API = "https://data-api.polymarket.com"
    CHAIN_ID = 137  # Polygon Mainnet

    # Polygon RPC
    POLYGON_RPC = os.getenv("POLYGON_RPC", "https://polygon-rpc.com")

    # Bot
    BOT_MODE = os.getenv("BOT_MODE", "DRY_RUN").upper()
    MAX_ENTRY = float(os.getenv("MAX_ENTRY", "1.0"))
    MIN_ODDS = float(os.getenv("MIN_ODDS", "0.45"))
    MAX_ODDS = float(os.getenv("MAX_ODDS", "0.55"))

    # Trading
    MARKET_SLUG_PREFIX = "btc-updown-5m"
    BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
    SYMBOL = "BTCUSDT"
    INTERVAL = "1m"
    KLINE_LIMIT = 50  # Cukup untuk EMA21 + RSI14

    # Risk
    CONFIDENCE_THRESHOLD = 0.6  # Minimal confidence untuk entry

    @classmethod
    def validate(cls):
        if not cls.POLY_PRIVATE_KEY:
            raise ValueError("POLY_PRIVATE_KEY wajib diisi di .env")
        if not cls.POLY_PROXY_ADDRESS:
            raise ValueError("POLY_PROXY_ADDRESS wajib diisi di .env")
        # Normalisasi private key
        if not cls.POLY_PRIVATE_KEY.startswith("0x"):
            cls.POLY_PRIVATE_KEY = "0x" + cls.POLY_PRIVATE_KEY
        return True
