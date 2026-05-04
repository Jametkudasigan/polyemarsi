"""Polymarket API Client - Market Discovery & Trading"""
import requests
import json
import time
from typing import Dict, Optional, Tuple
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY, SELL
from config.settings import Config


class PolymarketClient:
    def __init__(self):
        self.gamma_api = Config.GAMMA_API
        self.data_api = Config.DATA_API
        self.session = requests.Session()
        self._clob: Optional[ClobClient] = None
        self._api_creds = None

    def init_clob(self):
        """Inisialisasi CLOB client dan auto-generate API credentials"""
        if self._clob is not None:
            return

        print("[Polymarket] Initializing CLOB client...")
        self._clob = ClobClient(
            Config.CLOB_HOST,
            key=Config.POLY_PRIVATE_KEY,
            chain_id=Config.CHAIN_ID,
            signature_type=Config.POLY_SIGNATURE_TYPE,
            funder=Config.POLY_PROXY_ADDRESS
        )

        # Auto generate atau derive API credentials dari private key
        print("[Polymarket] Deriving API credentials from private key...")
        self._api_creds = self._clob.create_or_derive_api_creds()
        self._clob.set_api_creds(self._api_creds)
        print("[Polymarket] API credentials derived successfully!")

    def get_balance(self) -> float:
        """Get USDC balance di Polymarket"""
        if self._clob is None:
            self.init_clob()
        try:
            bal = self._clob.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            return int(bal["balance"]) / 1e6
        except Exception as e:
            print(f"[Balance Error] {e}")
            return 0.0

    def discover_market(self, epoch: int) -> Optional[Dict]:
        """Discover BTC Up/Down 5m market dari Gamma API"""
        slug = f"btc-updown-5m-{epoch}"
        url = f"{self.gamma_api}/events"

        # Coba beberapa offset karena market kadang tidak tepat di boundary
        offsets = [0, -300, 300]

        for offset in offsets:
            test_epoch = epoch + offset
            test_slug = f"btc-updown-5m-{test_epoch}"
            try:
                resp = self.session.get(url, params={"slug": test_slug}, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not data or len(data) == 0:
                    continue

                event = data[0]
                market = event.get("markets", [{}])[0]
                if not market:
                    continue

                token_ids = json.loads(market.get("clobTokenIds", "[]"))
                outcomes = json.loads(market.get("outcomes", "[]"))
                outcome_prices = json.loads(market.get("outcomePrices", "[]"))

                up_idx = outcomes.index("Up") if "Up" in outcomes else -1
                down_idx = outcomes.index("Down") if "Down" in outcomes else -1

                if up_idx == -1 or down_idx == -1 or len(token_ids) < 2:
                    continue

                return {
                    "epoch": test_epoch,
                    "slug": test_slug,
                    "condition_id": market.get("conditionId"),
                    "market_id": market.get("id"),
                    "question": event.get("title", ""),
                    "up_token_id": token_ids[up_idx],
                    "down_token_id": token_ids[down_idx],
                    "up_price": float(outcome_prices[up_idx]) if up_idx < len(outcome_prices) else 0.5,
                    "down_price": float(outcome_prices[down_idx]) if down_idx < len(outcome_prices) else 0.5,
                    "end_time": market.get("endDate"),
                    "url": f"https://polymarket.com/event/{test_slug}",
                }
            except Exception as e:
                continue

        return None

    def get_odds(self, token_id: str) -> float:
        """Get midpoint price untuk token (odds)"""
        if self._clob is None:
            self.init_clob()
        try:
            mid = self._clob.get_midpoint(token_id)
            return float(mid.get("mid", 0.5))
        except Exception as e:
            return 0.5

    def place_market_order(self, token_id: str, amount: float, side: str) -> Dict:
        """Place FOK market order"""
        if self._clob is None:
            self.init_clob()

        side_const = BUY if side.upper() == "BUY" else SELL

        mo = MarketOrderArgs(
            token_id=token_id,
            amount=amount,
            side=side_const,
            order_type=OrderType.FOK
        )

        signed = self._clob.create_market_order(mo)
        resp = self._clob.post_order(signed, OrderType.FOK)
        return resp

    def check_market_resolved(self, slug: str) -> Tuple[bool, Optional[str]]:
        """Check apakah market sudah resolved dan winner"""
        url = f"{self.gamma_api}/events"
        try:
            resp = self.session.get(url, params={"slug": slug}, timeout=10)
            if resp.status_code != 200:
                return False, None
            data = resp.json()
            if not data:
                return False, None

            event = data[0]
            market = event.get("markets", [{}])[0]

            if market.get("closed", False) or market.get("resolved", False):
                winner = None
                outcome_prices = json.loads(market.get("outcomePrices", "[]"))
                outcomes = json.loads(market.get("outcomes", "[]"))
                for i, price in enumerate(outcome_prices):
                    if float(price) >= 0.99:
                        winner = outcomes[i] if i < len(outcomes) else None
                        break
                return True, winner

            return False, None
        except Exception as e:
            return False, None
