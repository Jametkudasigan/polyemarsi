"""Utility functions"""
import time
from datetime import datetime, timezone


def get_current_5m_epoch() -> int:
    """Hitung epoch timestamp yang align ke boundary 5 menit"""
    now_sec = int(time.time())
    return (now_sec // 300) * 300


def get_next_5m_epoch() -> int:
    """Hitung epoch timestamp 5 menit berikutnya"""
    return get_current_5m_epoch() + 300


def epoch_to_slug(epoch: int) -> str:
    """Generate Polymarket slug dari epoch"""
    return f"btc-updown-5m-{epoch}"


def seconds_to_next_5m() -> int:
    """Sisa detik sampai 5-menit boundary berikutnya"""
    now_sec = int(time.time())
    next_epoch = ((now_sec // 300) + 1) * 300
    return next_epoch - now_sec


def seconds_since_5m_start() -> int:
    """Berapa detik sudah berlalu dari start 5-menit boundary"""
    now_sec = int(time.time())
    current_epoch = (now_sec // 300) * 300
    return now_sec - current_epoch


def format_time_left(seconds: int) -> str:
    """Format detik ke MM:SS"""
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def format_usd(value: float) -> str:
    """Format USD dengan warna indicator"""
    return f"${value:.2f}"


def now_iso() -> str:
    """Timestamp ISO format"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_4s_cycle_progress() -> tuple:
    """Hitung progress 4-detik cycle untuk UI refresh
    Returns: (elapsed_seconds, remaining_seconds, percentage)
    """
    now_ms = time.time()
    cycle_start = (int(now_ms) // 4) * 4
    elapsed = now_ms - cycle_start
    remaining = 4 - elapsed
    pct = (elapsed / 4) * 100
    return elapsed, remaining, pct
