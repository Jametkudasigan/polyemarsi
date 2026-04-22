"""
Polymarket BTC Up/Down 5-Minute Trading Bot

Flow:
1. SCANNING: Analyze BTC momentum -> find valid signal
2. ENTRY: Place FOK market order on Polymarket (Up/Down token)
3. MONITORING: Wait for market resolution
4. REDEEM: Auto cash out winning positions -> back to SCANNING

Dashboard always shows:
- USDC balance (funder address)
- Signal from Binance/Yahoo
- Current BTC 5m market being scanned
"""
import os
import sys
import time
import json
import logging
import math
from datetime import datetime
from typing import Optional

from colorama import init, Fore, Style

from src.config import load_config, BotConfig
from src.signals import SignalEngine, SignalResult
from src.polymarket import PolymarketTrader, MarketInfo

init(autoreset=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def print_banner():
    print(Fore.CYAN + """
============================================================
     POLYMARKET BTC 5-MINUTE TRADING BOT
     Strategy: EMA50 + RSI Pullback + Momentum Confirmation
============================================================
""" + Style.RESET_ALL)

def print_scan_dashboard(balance: float, signal: SignalResult, market: Optional[MarketInfo]):
    """Print scanning mode dashboard."""
    print("\n" + "-" * 60)
    print(Fore.YELLOW + "MODE: SCANNING MARKET" + Style.RESET_ALL)
    print("-" * 60)
    print(f"Balance (Funder):     ${balance:.2f} USDC")
    print(f"Signal Source:        {signal.analysis.split(' | ')[0] if signal else 'Loading...'}")
    print(f"   Confidence:           {signal.confidence*100:.1f}%" if signal else "")
    print(f"   RSI:                  {signal.rsi:.1f}" if signal else "")
    print(f"   EMA Slope:            {signal.ema_slope:+.4f}%" if signal else "")
    print(f"   Window Delta:         {signal.window_delta_pct:+.4f}%" if signal else "")

    if market:
        print(f"Market:               {market.slug}")
        print(f"   Up Price:             {market.up_price:.4f}")
        print(f"   Down Price:           {market.down_price:.4f}")
        print(f"   Resolved:             {'YES' if market.resolved else 'NO'}")
    else:
        print(f"Market:               Waiting for next 5m window...")
    print("-" * 60)

def print_position_dashboard(balance: float, market: MarketInfo, entry_side: str, entry_amount: float):
    """Print position monitoring dashboard."""
    print("\n" + "-" * 60)
    print(Fore.GREEN + "MODE: MONITORING POSITION" + Style.RESET_ALL)
    print("-" * 60)
    print(f"Balance (Funder):     ${balance:.2f} USDC")
    print(f"Market:               {market.slug}")
    side_color = Fore.GREEN if entry_side == "UP" else Fore.RED
    print(f"Entry Side:           {side_color}{entry_side}{Style.RESET_ALL}")
    print(f"Entry Amount:         ${entry_amount:.2f} USDC")
    print(f"Window Closes:        ~{300 - (int(time.time()) % 300)}s remaining")
    print("-" * 60)

class BTC5mBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.signal_engine = SignalEngine(
            ema_period=config.ema_period,
            rsi_period=config.rsi_period,
            atr_period=config.atr_period
        )
        self.trader = PolymarketTrader(
            private_key=config.private_key,
            proxy_address=config.proxy_address,
            relayer_api_key=config.relayer_api_key,
            relayer_api_key_address=config.relayer_api_key_address
        )

        self.state = "SCANNING"
        self.current_market: Optional[MarketInfo] = None
        self.entry_side: Optional[str] = None
        self.entry_amount: float = 0.0
        self.entry_price: float = 0.0

    def get_current_5m_epoch(self) -> int:
        now = int(time.time())
        return (now // 300) * 300

    def get_next_5m_epoch(self) -> int:
        now = int(time.time())
        return ((now // 300) + 1) * 300

    def seconds_to_next_window(self) -> int:
        now = int(time.time())
        next_window = self.get_next_5m_epoch()
        return next_window - now

    def scan(self) -> bool:
        """
        Scanning phase:
        1. Check balance
        2. Fetch signal from Binance/Yahoo
        3. Discover current BTC 5m market
        4. Check odds filter (0.45 - 0.55)
        5. If valid -> return True (ready to enter)
        """
        balance = self.trader.get_usdc_balance()

        try:
            signal = self.signal_engine.analyze()
        except Exception as e:
            logger.error("Signal analysis failed: %s", e)
            signal = SignalResult("NEUTRAL", 0, 0, 50, 0, 0, 0, "Error")

        epoch = self.get_current_5m_epoch()
        market = self.trader.discover_btc_5m_market(epoch)

        print_scan_dashboard(balance, signal, market)

        if balance < self.config.min_entry_usdc:
            logger.warning("Insufficient balance: $%.2f < $%.2f min", balance, self.config.min_entry_usdc)
            return False

        if not market or market.resolved:
            logger.info("No active market for epoch %d", epoch)
            return False

        seconds_remaining = 300 - (int(time.time()) % 300)
        if seconds_remaining < 30:
            logger.info("Too close to window close (%ds), waiting for next window", seconds_remaining)
            return False

        # Strategy Validation
        if signal.direction not in ("UP", "DOWN"):
            logger.info("Signal direction unclear: %s", signal.direction)
            return False

        if signal.confidence < 0.6:
            logger.info("Confidence too low: %.2f < 0.6", signal.confidence)
            return False

        # Odds Filter
        target_token = market.up_token_id if signal.direction == "UP" else market.down_token_id
        current_price = market.up_price if signal.direction == "UP" else market.down_price

        if not (self.config.odds_min <= current_price <= self.config.odds_max):
            logger.info("Odds filter: price %.4f outside range [%.2f - %.2f]",
                       current_price, self.config.odds_min, self.config.odds_max)
            return False

        logger.info("VALID SIGNAL | Direction: %s | Price: %.4f | Confidence: %.2f",
                   signal.direction, current_price, signal.confidence)

        self.current_market = market
        self.entry_side = signal.direction
        self.entry_price = current_price
        return True

    def enter_position(self) -> bool:
        if not self.current_market or not self.entry_side:
            return False

        amount = min(self.config.max_entry_usdc, self.config.min_entry_usdc)
        amount = max(amount, 1.0)

        token_id = (self.current_market.up_token_id if self.entry_side == "UP"
                   else self.current_market.down_token_id)

        logger.info("ENTERING POSITION | Side: %s | Amount: $%.2f | Token: %s",
                   self.entry_side, amount, token_id[:16])

        resp = self.trader.place_market_order(token_id, amount, "BUY")

        if resp and resp.get("success"):
            self.entry_amount = amount
            self.state = "IN_POSITION"
            logger.info("POSITION ENTERED")
            return True
        else:
            logger.error("Entry failed: %s", resp)
            self.state = "SCANNING"
            return False

    def monitor_position(self) -> bool:
        if not self.current_market:
            return False

        balance = self.trader.get_usdc_balance()
        print_position_dashboard(balance, self.current_market, self.entry_side or "UNKNOWN", self.entry_amount)

        entered_epoch = int(self.current_market.slug.split("-")[-1])

        refreshed = self.trader.discover_btc_5m_market(entered_epoch)
        if refreshed and refreshed.resolved:
            self.current_market = refreshed
            logger.info("MARKET RESOLVED | Winner: %s", refreshed.outcome)
            return True

        now = int(time.time())
        window_end = entered_epoch + 300
        if now > window_end + 60:
            if now > window_end + 300:
                logger.info("Assuming resolution complete")
                return True

        return False

    def redeem_and_reset(self):
        logger.info("Redeeming positions...")
        redeemed = self.trader.redeem_all_positions()

        if redeemed > 0:
            new_balance = self.trader.get_usdc_balance()
            logger.info("New balance: $%.2f USDC", new_balance)

        self.state = "SCANNING"
        self.current_market = None
        self.entry_side = None
        self.entry_amount = 0.0
        self.entry_price = 0.0

        logger.info("Reset to SCANNING mode")

    def run(self):
        print_banner()
        logger.info("Bot starting... Proxy: %s", self.config.proxy_address[:20])

        while True:
            try:
                if self.state == "SCANNING":
                    self.trader.redeem_all_positions()

                    valid = self.scan()
                    if valid:
                        success = self.enter_position()
                        if not success:
                            time.sleep(self.config.scan_interval)
                    else:
                        time.sleep(self.config.scan_interval)

                elif self.state == "IN_POSITION":
                    resolved = self.monitor_position()
                    if resolved:
                        self.redeem_and_reset()
                    else:
                        time.sleep(self.config.position_check_interval)

                else:
                    self.state = "SCANNING"
                    time.sleep(5)

            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error("Main loop error: %s", e)
                time.sleep(10)

def main():
    config = load_config()
    bot = BTC5mBot(config)
    bot.run()

if __name__ == "__main__":
    main()
