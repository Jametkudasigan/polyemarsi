"""Main Bot Logic - State Machine"""
import time
import traceback
from typing import List
from datetime import datetime

from config.settings import Config
from src.utils import (
    get_current_5m_epoch, get_next_5m_epoch, seconds_to_next_5m, 
    seconds_since_5m_start, format_time_left, now_iso
)
from src.binance_client import BinanceClient
from src.polymarket_client import PolymarketClient
from src.indicators import analyze_momentum
from src.position_manager import PositionManager
from src.ui import BotUI


class PolymarketBot:
    STATES = ["IDLE", "SCANNING", "ENTERING", "POSITION", "REDEEMING"]

    def __init__(self):
        Config.validate()
        self.state = "IDLE"
        self.mode = Config.BOT_MODE
        self.binance = BinanceClient()
        self.polymarket = PolymarketClient()
        self.positions = PositionManager()
        self.ui = BotUI()
        self.logs: List[str] = []
        self.balance = 0.0

        # Data untuk UI
        self.ui_data = {
            "indicators": {},
            "market": {},
            "position": {},
            "elapsed_seconds": 0,
            "max_entry": Config.MAX_ENTRY,
        }

        # Market tracking
        self.current_epoch = 0
        self.current_market = None
        self.entry_time = None

        self._log(f"Bot initialized | Mode: {self.mode}")
        self._log("Loading balance...")
        try:
            self.balance = self.polymarket.get_balance()
            self._log(f"Balance: ${self.balance:.2f}")
        except Exception as e:
            self._log(f"Balance check failed: {e}")

    def _log(self, msg: str):
        """Tambah log dengan timestamp"""
        ts = datetime.utcnow().strftime("%H:%M:%S")
        log_entry = f"[{ts}] {msg}"
        self.logs.append(log_entry)
        if len(self.logs) > 50:
            self.logs.pop(0)

    def _update_balance(self):
        """Update balance periodically"""
        try:
            self.balance = self.polymarket.get_balance()
        except Exception:
            pass

    def _discover_market(self, epoch: int) -> bool:
        """Discover market untuk epoch tertentu"""
        self._log(f"Discovering market for epoch {epoch}...")
        market = self.polymarket.discover_market(epoch)
        if market:
            self.current_market = market
            self.ui_data["market"] = market
            self._log(f"Market found: {market['slug']}")
            self._log(f"Up: ${market['up_price']:.3f} | Down: ${market['down_price']:.3f}")
            return True
        else:
            self._log("Market not found, will retry...")
            return False

    def _analyze(self) -> dict:
        """Fetch data dan analisis indikator"""
        self._log("Fetching Binance klines...")
        candles = self.binance.get_klines()
        if not candles or len(candles) < 25:
            self._log("Insufficient candle data")
            return {"signal": "NEUTRAL", "confidence": 0}

        result = analyze_momentum(candles)
        self.ui_data["indicators"] = result

        signal = result["signal"]
        conf = result["confidence"]
        details = result.get("details", {})

        self._log(f"Signal: {signal} | Confidence: {conf:.0%} | RSI: {details.get('rsi', 0):.1f}")
        return result

    def _check_odds_filter(self, side: str) -> bool:
        """Check apakah odds masuk range 0.45-0.55"""
        if not self.current_market:
            return False

        if side == "BUY":  # UP
            odds = self.current_market.get("up_price", 0.5)
        else:  # SELL -> DOWN
            odds = self.current_market.get("down_price", 0.5)

        valid = Config.MIN_ODDS <= odds <= Config.MAX_ODDS
        self._log(f"Odds check: ${odds:.3f} | Filter {Config.MIN_ODDS}-{Config.MAX_ODDS} | {'PASS' if valid else 'FAIL'}")
        return valid

    def _enter_position(self, side: str):
        """Eksekusi entry ke Polymarket"""
        if not self.current_market:
            return False

        token_id = self.current_market["up_token_id"] if side == "BUY" else self.current_market["down_token_id"]
        odds = self.current_market.get("up_price" if side == "BUY" else "down_price", 0.5)
        direction = "UP" if side == "BUY" else "DOWN"

        self._log(f"ENTERING {direction} | Amount: ${Config.MAX_ENTRY} | Odds: ${odds:.3f}")

        if self.mode == "DRY_RUN":
            self._log("[DRY RUN] Order simulated")
            success = True
        else:
            try:
                resp = self.polymarket.place_market_order(token_id, Config.MAX_ENTRY, "BUY")
                self._log(f"Order response: {resp}")
                success = resp.get("success", False) if isinstance(resp, dict) else True
            except Exception as e:
                self._log(f"Order failed: {e}")
                success = False

        if success:
            self.positions.open_position(
                market=self.current_market,
                side=direction,
                amount=Config.MAX_ENTRY,
                entry_odds=odds,
                token_id=token_id
            )
            self.entry_time = time.time()
            self.ui_data["position"] = self.positions.current_position
            self._log(f"Position opened: {direction}")

        return success

    def _check_resolution(self) -> tuple:
        """Check apakah market sudah resolved"""
        if not self.current_market:
            return False, None

        resolved, winner = self.polymarket.check_market_resolved(self.current_market["slug"])
        return resolved, winner

    def _redeem_and_close(self, winner: str):
        """Redeem position dan update stats"""
        self._log(f"Market resolved! Winner: {winner}")
        self.positions.close_position(winner)
        stats = self.positions.get_stats()
        self._log(f"Trade closed | PnL: ${stats['total_pnl']:.2f} | W/L: {stats['wins']}/{stats['losses']}")
        self._update_balance()

    def run(self):
        """Main bot loop"""
        from rich.live import Live

        self._log("Bot starting...")

        with Live(self.ui.render(self.state, self.ui_data, self.positions.get_stats(), 
                                  self.balance, self.logs, self.mode), 
                  refresh_per_second=1, screen=True) as live:

            try:
                while True:
                    # Update UI setiap detik
                    stats = self.positions.get_stats()
                    live.update(self.ui.render(self.state, self.ui_data, stats, 
                                               self.balance, self.logs, self.mode))

                    # ===================== STATE MACHINE =====================

                    if self.state == "IDLE":
                        # Tunggu sampai dekat window baru (kurang dari 30 detik)
                        seconds_left = seconds_to_next_5m()

                        if seconds_left <= 30:
                            self.state = "SCANNING"
                            self.current_epoch = get_next_5m_epoch()
                            self._log(f"Approaching new window: {self.current_epoch}")

                        time.sleep(1)

                    elif self.state == "SCANNING":
                        seconds_passed = seconds_since_5m_start()

                        # Discovery market jika belum
                        if not self.current_market or self.current_market.get("epoch") != get_current_5m_epoch():
                            found = self._discover_market(get_current_5m_epoch())
                            if not found:
                                time.sleep(3)
                                continue

                        # Update countdown
                        self.ui_data["elapsed_seconds"] = seconds_passed

                        # Analisis setiap 5 detik (untuk mengurangi spam)
                        if seconds_passed % 5 == 0 or seconds_passed < 5:
                            result = self._analyze()
                            signal = result["signal"]
                            confidence = result["confidence"]

                            # Apply filters
                            if signal in ["BUY", "SELL"] and confidence >= Config.CONFIDENCE_THRESHOLD:
                                if self._check_odds_filter(signal):
                                    self.state = "ENTERING"
                                    self._log("All filters passed! Entering position...")
                                    continue
                                else:
                                    self._log("Odds filter failed, skipping...")

                            # Jika sudah terlalu lama dalam window (> 3 menit), skip
                            if seconds_passed > 180:
                                self._log("Window too old, waiting for next...")
                                self.state = "IDLE"
                                self.current_market = None

                        time.sleep(1)

                    elif self.state == "ENTERING":
                        result = self._analyze()
                        signal = result["signal"]

                        if signal in ["BUY", "SELL"]:
                            success = self._enter_position(signal)
                            if success:
                                self.state = "POSITION"
                            else:
                                self._log("Entry failed, returning to scan...")
                                self.state = "SCANNING"
                        else:
                            self._log("Signal lost during entry, aborting...")
                            self.state = "SCANNING"

                        time.sleep(1)

                    elif self.state == "POSITION":
                        if self.entry_time:
                            elapsed = int(time.time() - self.entry_time)
                            self.ui_data["elapsed_seconds"] = elapsed

                        # Check resolution setiap 10 detik
                        if int(time.time()) % 10 == 0:
                            resolved, winner = self._check_resolution()
                            if resolved:
                                self.state = "REDEEMING"
                                self.ui_data["winner"] = winner
                                continue

                        # Safety: jika sudah > 6 menit, force check
                        if self.entry_time and (time.time() - self.entry_time) > 360:
                            self._log("Force checking resolution after 6 minutes...")
                            resolved, winner = self._check_resolution()
                            if resolved:
                                self.state = "REDEEMING"
                                self.ui_data["winner"] = winner
                                continue
                            else:
                                self._log("Market not resolved yet, waiting...")

                        time.sleep(1)

                    elif self.state == "REDEEMING":
                        winner = self.ui_data.get("winner")
                        self._redeem_and_close(winner)

                        # Reset untuk cycle berikutnya
                        self.state = "IDLE"
                        self.current_market = None
                        self.entry_time = None
                        self.ui_data["position"] = {}
                        self.ui_data["winner"] = None
                        self._log("Cycle complete. Returning to scan...")
                        time.sleep(5)

            except KeyboardInterrupt:
                self._log("Bot stopped by user")
                raise
            except Exception as e:
                self._log(f"CRITICAL ERROR: {e}")
                self._log(traceback.format_exc())
                time.sleep(5)
