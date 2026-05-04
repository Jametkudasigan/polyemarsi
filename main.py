#!/usr/bin/env python3
"""
Polymarket BTC Up/Down 5-Minute Trading Bot
============================================
Strategy: EMA 9/21 + RSI 14 dengan Odds Filter 0.45-0.55

Setup:
1. cp .env.example .env
2. Isi POLY_PRIVATE_KEY dan POLY_PROXY_ADDRESS
3. pip install -r requirements.txt
4. python main.py

Arsitektur:
[Private Key / EOA]
        ↓ (sign)
[Proxy Wallet / Smart Contract]
        ↓ (execute)
[Polymarket CLOB / Relayer API]
"""
import sys
from src.bot import PolymarketBot


def main():
    print("=" * 60)
    print("  POLYMARKET BTC 5M BOT")
    print("  Strategy: EMA+RSI | Gasless via CLOB")
    print("=" * 60)
    print()

    try:
        bot = PolymarketBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n\nBot stopped gracefully.")
        sys.exit(0)
    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
