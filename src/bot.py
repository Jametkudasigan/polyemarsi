"""Main Bot Logic - State Machine with CLOB V2 Support"""
import time
import traceback
from typing import List
from datetime import datetime

from config.settings import Config
from src.utils import (
    get_current_5m_epoch, get_next_5m_epoch, seconds_to_next_5m, 
    seconds_since_5m_start, format_time_left, now_iso, get_4s_cycle_progress
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
        self.has_allowance = False

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

        # 4-second cycle tracking
        self.last_4s_tick = 0
        self.cycle_count = 0

        self._log("=" * 50)
        self._log("🚀 POLYMARKET BTC 5M BOT - CLOB V2")
        self._log(f"Mode: {self.mode} | Max Entry: ${Config.MAX_ENTRY}")
        self._log("=" * 50)

        # Init CLOB dan cek balance
        self._init_and_check_balance()

    def _log(self, msg: str):
        """Tambah log dengan timestamp"""
        ts = datetime.utcnow().strftime("%H:%M:%S")
        log_entry = f"[{ts}] {msg}"
        self.logs.append(log_entry)
        if len(self.logs) > 100:
            self.logs.pop(0)

    def _init_and_check_balance(self):
        """Inisialisasi CLOB dan cek balance + allowance"""
        try:
            self._log("[INIT] Connecting to Polymarket CLOB V2...")
            self.polymarket.init_clob()

            self._log("[INIT] Checking PolyUSD balance...")
            self.balance = self.polymarket.get_balance()
            self._log(f"[INIT] Balance: ${self.balance:.2f} PolyUSD")

            if self.balance <= 0:
                self._log("⚠️  WARNING: Balance $0 - Deposit PolyUSD ke wallet!")
                self._log("⚠️  Cara deposit: polymarket.com → Deposit → USDC → Convert ke PolyUSD")
            else:
                self._log("✅ Balance OK")

            self._log("[INIT] Checking token allowance...")
            self.has_allowance = self.polymarket.check_allowance()
            if self.has_allowance:
                self._log("✅ Allowance OK - Ready to trade")
            else:
                self._log("⚠️  Allowance belum di-set atau balance 0")
                self._log("⚠️  Untuk email wallet (type=1): allowance auto-set")
                self._log("⚠️  Untuk EOA wallet (type=0): perlu set manual via UI Polymarket")

        except Exception as e:
            self._log(f"❌ [INIT ERROR] {e}")
            self._log("Pastikan private key dan proxy address sudah benar di .env")

    def _update_balance(self):
        """Update balance periodically"""
        try:
            self.balance = self.polymarket.get_balance()
        except Exception:
            pass

    def _discover_market(self, epoch: int) -> bool:
        """Discover market untuk epoch tertentu"""
        self._log(f"🔍 Discovering market for epoch {epoch}...")
        market = self.polymarket.discover_market(epoch)
        if market:
            self.current_market = market
            self.ui_data["market"] = market
            self._log(f"✅ Market found: {market['slug']}")
            self._log(f"   Up Odds: ${market['up_price']:.3f} | Down Odds: ${market['down_price']:.3f}")
            return True
        else:
            self._log("⏳ Market not found, will retry next cycle...")
            return False

    def _analyze(self) -> dict:
        """Fetch data dan analisis indikator"""
        self._log("📡 Fetching Binance klines (BTCUSDT 1m)...")
        candles = self.binance.get_klines()
        if not candles or len(candles) < 25:
            self._log("❌ Insufficient candle data from Binance")
            return {"signal": "NEUTRAL", "confidence": 0}

        result = analyze_momentum(candles)
        self.ui_data["indicators"] = result

        signal = result["signal"]
        conf = result["confidence"]
        details = result.get("details", {})

        self._log(f"📊 Signal: {signal} | Confidence: {conf:.0%}")
        self._log(f"   Price: ${details.get('price', 0):,.2f} | EMA9: {details.get('ema9', 0):,.2f} | EMA21: {details.get('ema21', 0):,.2f} | RSI: {details.get('rsi', 0):.1f}")
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
        status = "PASS" if valid else "FAIL"
        self._log(f"🎲 Odds Check: ${odds:.3f} | Range: {Config.MIN_ODDS}-{Config.MAX_ODDS} | {status}")
        return valid

    def _enter_position(self, side: str):
        """Eksekusi entry ke Polymarket V2"""
        if not self.current_market:
            return False

        # Pre-flight checks
        if self.balance <= 0:
            self._log("❌ ENTRY BLOCKED: Balance $0 - Deposit PolyUSD dulu!")
            self._log("   polymarket.com → Deposit → USDC → Convert ke PolyUSD")
            return False

        if not self.has_allowance:
            self._log("❌ ENTRY BLOCKED: Token allowance belum di-set!")
            self._log("   Untuk email wallet: tunggu auto-deploy atau deposit dulu")
            self._log("   Untuk EOA wallet: set allowance manual di UI Polymarket")
            return False

        token_id = self.current_market["up_token_id"] if side == "BUY" else self.current_market["down_token_id"]
        odds = self.current_market.get("up_price" if side == "BUY" else "down_price", 0.5)
        direction = "UP" if side == "BUY" else "DOWN"

        self._log("=" * 40)
        self._log(f"🎯 EXECUTING ENTRY: {direction}")
        self._log(f"   Amount: ${Config.MAX_ENTRY}")
        self._log(f"   Odds: ${odds:.3f}")
        self._log(f"   Token: {token_id[:30]}...")
        self._log("=" * 40)

        if self.mode == "DRY_RUN":
            self._log("[DRY RUN] Order simulated - NO real transaction")
            success = True
        else:
            try:
                resp = self.polymarket.place_market_order(token_id, Config.MAX_ENTRY, "BUY")
                self._log(f"📨 Order Response: {json.dumps(resp, default=str)[:200]}")

                # Cek response
                if isinstance(resp, dict):
                    if resp.get("success"):
                        success = True
                        self._log("✅ Order placed successfully!")
                    elif "errorMsg" in resp and resp["errorMsg"]:
                        err = resp["errorMsg"]
                        self._log(f"❌ Order rejected: {err}")
                        if "order_version_mismatch" in err.lower():
                            self._log("🔴 CRITICAL: CLOB V1/V2 mismatch!")
                            self._log("   → Upgrade: pip install -U py-clob-client")
                            self._log("   → Pastikan pakai CLOB V2 endpoint")
                        elif "not enough balance" in err.lower():
                            self._log("🔴 CRITICAL: PolyUSD balance insufficient!")
                            self._log("   → Deposit USDC dan convert ke PolyUSD")
                        success = False
                    else:
                        success = True
                else:
                    success = bool(resp)

            except Exception as e:
                err_str = str(e)
                self._log(f"❌ Order exception: {err_str}")

                if "order_version_mismatch" in err_str.lower():
                    self._log("🔴 CLOB VERSION MISMATCH (V1 vs V2)")
                    self._log("   Solusi:")
                    self._log("   1. pip install -U py-clob-client")
                    self._log("   2. Restart bot")
                elif "not enough balance" in err_str.lower() or "allowance" in err_str.lower():
                    self._log("🔴 INSUFFICIENT BALANCE / ALLOWANCE")
                    self._log("   → Deposit PolyUSD ke wallet")
                    self._log("   → Cek token allowances")

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
            self._log(f"✅ POSITION OPENED: {direction} | ${Config.MAX_ENTRY}")

        return success

    def _check_resolution(self) -> tuple:
        """Check apakah market sudah resolved"""
        if not self.current_market:
            return False, None

        resolved, winner = self.polymarket.check_market_resolved(self.current_market["slug"])
        return resolved, winner

    def _redeem_and_close(self, winner: str):
        """Redeem position dan update stats"""
        self._log("=" * 40)
        self._log(f"🏁 MARKET RESOLVED! Winner: {winner}")
        self._log("=" * 40)

        self.positions.close_position(winner)
        stats = self.positions.get_stats()
        last_trade = self.positions.trades[-1] if self.positions.trades else {}
        pnl = last_trade.get("pnl", 0)
        result = last_trade.get("result", "UNKNOWN")

        if result == "WIN":
            self._log(f"🎉 WIN! PnL: +${pnl:.2f}")
        else:
            self._log(f"💸 LOSS! PnL: ${pnl:.2f}")

        self._log(f"📈 Stats → W/L: {stats['wins']}/{stats['losses']} | Total PnL: ${stats['total_pnl']:.2f} | WR: {stats['win_rate']:.1f}%")
        self._update_balance()

    def _should_tick(self) -> bool:
        """Check apakah sudah waktunya tick 4-detik baru"""
        current_tick = int(time.time()) // 4
        if current_tick != self.last_4s_tick:
            self.last_4s_tick = current_tick
            self.cycle_count += 1
            return True
        return False

    def run(self):
        """Main bot loop - refresh setiap 4 detik"""
        from rich.live import Live

        self._log("🤖 Bot starting...")
        self._log("⏳ Aligning to 4-second cycle...")

        # Align ke cycle 4 detik
        while True:
            if self._should_tick():
                break
            time.sleep(0.1)

        self._log("✅ Bot aligned. Running main loop.")

        with Live(self.ui.render(self.state, self.ui_data, self.positions.get_stats(), 
                                  self.balance, self.logs, self.mode), 
                  refresh_per_second=4, screen=True) as live:

            try:
                while True:
                    # Tunggu sampai tick 4-detik berikutnya
                    while not self._should_tick():
                        stats = self.positions.get_stats()
                        live.update(self.ui.render(self.state, self.ui_data, stats, 
                                                   self.balance, self.logs, self.mode))
                        time.sleep(0.25)

                    # ====== INI ADALAH 1 CYCLE 4 DETIK ======
                    self._log(f"--- Cycle #{self.cycle_count} | State: {self.state} ---")

                    # Update UI
                    stats = self.positions.get_stats()
                    live.update(self.ui.render(self.state, self.ui_data, stats, 
                                               self.balance, self.logs, self.mode))

                    # ===================== STATE MACHINE =====================

                    if self.state == "IDLE":
                        seconds_left = seconds_to_next_5m()
                        self._log(f"⏰ Next window in {seconds_left}s")

                        if seconds_left <= 30:
                            self.state = "SCANNING"
                            self.current_epoch = get_next_5m_epoch()
                            self._log(f"🚀 Approaching new window: epoch {self.current_epoch}")

                    elif self.state == "SCANNING":
                        seconds_passed = seconds_since_5m_start()
                        self.ui_data["elapsed_seconds"] = seconds_passed

                        # Discovery market jika belum
                        if not self.current_market or self.current_market.get("epoch") != get_current_5m_epoch():
                            found = self._discover_market(get_current_5m_epoch())
                            if not found:
                                continue

                        # Analisis setiap cycle (4 detik)
                        result = self._analyze()
                        signal = result["signal"]
                        confidence = result["confidence"]

                        # Apply filters
                        if signal in ["BUY", "SELL"] and confidence >= Config.CONFIDENCE_THRESHOLD:
                            if self._check_odds_filter(signal):
                                self.state = "ENTERING"
                                self._log("✅ ALL FILTERS PASSED → Proceeding to entry...")
                                continue
                            else:
                                self._log("⛔ Odds filter failed, continuing scan...")
                        else:
                            self._log(f"⏳ Signal: {signal} | Conf: {confidence:.0%} | Waiting for valid setup...")

                        # Jika sudah terlalu lama dalam window (> 3 menit), skip
                        if seconds_passed > 180:
                            self._log("⚠️ Window too old (>3min), skipping to next...")
                            self.state = "IDLE"
                            self.current_market = None

                    elif self.state == "ENTERING":
                        result = self._analyze()
                        signal = result["signal"]

                        if signal in ["BUY", "SELL"]:
                            success = self._enter_position(signal)
                            if success:
                                self.state = "POSITION"
                                self._log("📊 Now monitoring position until resolution...")
                            else:
                                self._log("❌ Entry failed, returning to scan...")
                                self.state = "SCANNING"
                        else:
                            self._log("⚠️ Signal lost during entry, aborting...")
                            self.state = "SCANNING"

                    elif self.state == "POSITION":
                        if self.entry_time:
                            elapsed = int(time.time() - self.entry_time)
                            self.ui_data["elapsed_seconds"] = elapsed

                        # Check resolution setiap cycle (4 detik)
                        resolved, winner = self._check_resolution()
                        if resolved:
                            self.state = "REDEEMING"
                            self.ui_data["winner"] = winner
                            self._log(f"🔔 Market resolved! Winner: {winner}")
                            continue
                        else:
                            self._log(f"📊 Position active | Elapsed: {self.ui_data['elapsed_seconds']}s | Waiting resolution...")

                        # Safety: jika sudah > 6 menit, force check lebih sering
                        if self.entry_time and (time.time() - self.entry_time) > 360:
                            self._log("⚠️ Force checking resolution after 6 minutes...")
                            resolved, winner = self._check_resolution()
                            if resolved:
                                self.state = "REDEEMING"
                                self.ui_data["winner"] = winner
                                continue

                    elif self.state == "REDEEMING":
                        winner = self.ui_data.get("winner")
                        self._redeem_and_close(winner)

                        # Reset untuk cycle berikutnya
                        self.state = "IDLE"
                        self.current_market = None
                        self.entry_time = None
                        self.ui_data["position"] = {}
                        self.ui_data["winner"] = None
                        self._log("🔄 Cycle complete. Returning to IDLE...")

            except KeyboardInterrupt:
                self._log("🛑 Bot stopped by user")
                raise
            except Exception as e:
                self._log(f"🔴 CRITICAL ERROR: {e}")
                self._log(traceback.format_exc())
                time.sleep(5)
