"""
Configuration loader for Polymarket BTC 5m Bot.
Auto-derives CLOB API credentials from private key.
"""
import os
import logging
from dataclasses import dataclass
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

@dataclass
class BotConfig:
    # Wallet
    private_key: str
    proxy_address: str

    # Relayer (optional - for gasless redemption)
    relayer_api_key: str | None
    relayer_api_key_address: str | None

    # RPC fallback (if relayer not configured)
    polygon_rpc: str | None

    # Trading
    max_entry_usdc: float
    min_entry_usdc: float
    odds_min: float
    odds_max: float

    # Strategy
    ema_period: int
    rsi_period: int
    atr_period: int

    # Behavior
    scan_interval: int
    position_check_interval: int
    deadline_seconds: int

def load_config(env_path: str = ".env") -> BotConfig:
    load_dotenv(env_path)

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS", "")

    if not private_key or not proxy_address:
        raise ValueError("POLYMARKET_PRIVATE_KEY and POLYMARKET_PROXY_ADDRESS are required in .env")

    # Normalize private key
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    return BotConfig(
        private_key=private_key,
        proxy_address=proxy_address.lower(),
        relayer_api_key=os.getenv("POLYMARKET_RELAYER_API_KEY") or None,
        relayer_api_key_address=os.getenv("POLYMARKET_RELAYER_API_KEY_ADDRESS") or None,
        polygon_rpc=os.getenv("POLYGON_RPC") or None,
        max_entry_usdc=float(os.getenv("MAX_ENTRY_USDC", "1.0")),
        min_entry_usdc=float(os.getenv("MIN_ENTRY_USDC", "1.0")),
        odds_min=float(os.getenv("ODDS_MIN", "0.45")),
        odds_max=float(os.getenv("ODDS_MAX", "0.55")),
        ema_period=int(os.getenv("EMA_PERIOD", "50")),
        rsi_period=int(os.getenv("RSI_PERIOD", "14")),
        atr_period=int(os.getenv("ATR_PERIOD", "14")),
        scan_interval=int(os.getenv("SCAN_INTERVAL_SECONDS", "10")),
        position_check_interval=int(os.getenv("POSITION_CHECK_INTERVAL_SECONDS", "30")),
        deadline_seconds=int(os.getenv("DEADLINE_SECONDS", "180")),
    )
