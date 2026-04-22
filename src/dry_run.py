"""
Dry-run mode: Test strategy without placing real orders.
Simulates entry and tracks hypothetical PnL.
"""
import time
import logging
from datetime import datetime

from colorama import init, Fore, Style
from src.config import load_config
from src.signals import SignalEngine
from src.polymarket import PolymarketTrader

init(autoreset=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

def main():
    config = load_config()
    engine = SignalEngine(ema_period=config.ema_period, rsi_period=config.rsi_period)
    trader = PolymarketTrader(
        private_key=config.private_key,
        proxy_address=config.proxy_address
    )

    bankroll = 100.0
    wins = 0
    losses = 0

    print(Fore.CYAN + "\nDRY RUN MODE - No real trades will be placed\n" + Style.RESET_ALL)

    while True:
        try:
            epoch = (int(time.time()) // 300) * 300

            signal = engine.analyze()
            market = trader.discover_btc_5m_market(epoch)
            balance = trader.get_usdc_balance()

            print(f"\nReal Balance: ${balance:.2f} | Simulated Bankroll: ${bankroll:.2f}")
            print(f"Signal: {signal.direction} | Confidence: {signal.confidence:.2f}")

            if market:
                print(f"Market: {market.slug}")
                print(f"   Up: {market.up_price:.4f} | Down: {market.down_price:.4f}")

            if signal.direction in ("UP", "DOWN") and signal.confidence >= 0.6 and market:
                target_price = market.up_price if signal.direction == "UP" else market.down_price

                if config.odds_min <= target_price <= config.odds_max:
                    entry = min(config.max_entry_usdc, bankroll * 0.01)
                    print(Fore.GREEN + f"\nSIMULATED ENTRY: {signal.direction} @ ${target_price:.4f} | Amount: ${entry:.2f}" + Style.RESET_ALL)

                    time.sleep(10)

                    refreshed = trader.discover_btc_5m_market(epoch)
                    if refreshed and refreshed.resolved:
                        won = (refreshed.outcome == "Up" and signal.direction == "UP") or \
                              (refreshed.outcome == "Down" and signal.direction == "DOWN")

                        if won:
                            profit = entry * (1 - target_price) / target_price
                            bankroll += profit
                            wins += 1
                            print(Fore.GREEN + f"WIN | Profit: ${profit:.2f} | Bankroll: ${bankroll:.2f}" + Style.RESET_ALL)
                        else:
                            bankroll -= entry
                            losses += 1
                            print(Fore.RED + f"LOSS | -${entry:.2f} | Bankroll: ${bankroll:.2f}" + Style.RESET_ALL)

                        print(f"Win Rate: {wins}/{wins+losses} ({wins/(wins+losses)*100:.1f}%)")

            time.sleep(config.scan_interval)

        except KeyboardInterrupt:
            print("\nDry run stopped")
            break
        except Exception as e:
            logger.error("Error: %s", e)
            time.sleep(10)

if __name__ == "__main__":
    main()
