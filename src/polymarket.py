"""
Polymarket integration: market discovery, trading, balance, redemption.
Uses py-clob-client for orders and py-builder-relayer-client for gasless redemption.
"""
import os
import time
import json
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds, MarketOrderArgs, OrderType,
    BalanceAllowanceParams, AssetType
)
from py_clob_client.order_builder.constants import BUY, SELL

try:
    from py_builder_relayer_client.client import RelayClient
    from py_builder_relayer_client.models import RelayerTxType, OperationType, SafeTransaction
    RELAYER_AVAILABLE = True
except ImportError:
    RELAYER_AVAILABLE = False
    logging.warning("py-builder-relayer-client not installed. Redemption will need manual gas.")

try:
    from eth_abi import encode as eth_encode
    from eth_utils import keccak
    ETH_UTILS_AVAILABLE = True
except ImportError:
    ETH_UTILS_AVAILABLE = False

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Contract addresses on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

@dataclass
class MarketInfo:
    condition_id: str
    up_token_id: str
    down_token_id: str
    up_price: float
    down_price: float
    slug: str
    resolved: bool
    outcome: str | None

class PolymarketTrader:
    def __init__(self, private_key: str, proxy_address: str,
                 relayer_api_key: str | None = None,
                 relayer_api_key_address: str | None = None):
        self.private_key = private_key
        self.proxy_address = proxy_address.lower()
        self.relayer_api_key = relayer_api_key
        self.relayer_api_key_address = relayer_api_key_address

        # Initialize CLOB client (L1 auth)
        self._clob = ClobClient(
            host=CLOB_API,
            key=private_key,
            chain_id=137,
            signature_type=1,  # Proxy wallet (Magic/Email)
            funder=proxy_address
        )

        # Auto-derive or create API credentials (L2 auth)
        self._creds = self._clob.create_or_derive_api_creds()
        self._clob.set_api_creds(self._creds)
        logger.info("CLOB API credentials auto-derived")

        # Initialize relayer client if credentials provided
        self._relayer = None
        if relayer_api_key and relayer_api_key_address and RELAYER_AVAILABLE:
            self._relayer = RelayClient(
                "https://relayer-v2.polymarket.com",
                chain_id=137,
                private_key=private_key,
                relayer_api_key=relayer_api_key,
                relayer_api_key_address=relayer_api_key_address,
                relay_tx_type=RelayerTxType.PROXY
            )
            logger.info("Relayer client initialized (gasless)")

    # Balance
    def get_usdc_balance(self) -> float:
        """Get USDC balance in funder (proxy) wallet."""
        try:
            bal = self._clob.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            usdc = int(bal.get("balance", 0)) / 1e6
            logger.info("USDC Balance: $%.2f", usdc)
            return usdc
        except Exception as e:
            logger.error("Failed to get balance: %s", e)
            return 0.0

    # Market Discovery
    def discover_btc_5m_market(self, epoch_timestamp: int) -> Optional[MarketInfo]:
        """
        Discover BTC Up/Down 5m market by deterministic slug.
        Slug format: btc-updown-5m-{epochTimestamp}
        """
        slug = f"btc-updown-5m-{epoch_timestamp}"
        url = f"{GAMMA_API}/events?slug={slug}"

        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data or len(data) == 0:
                return None

            event = data[0]
            market = event.get("markets", [{}])[0]
            if not market:
                return None

            token_ids = json.loads(market.get("clobTokenIds", "[]"))
            outcomes = json.loads(market.get("outcomes", "[]"))
            prices = json.loads(market.get("outcomePrices", "[]"))

            up_idx = outcomes.index("Up") if "Up" in outcomes else -1
            down_idx = outcomes.index("Down") if "Down" in outcomes else -1

            if up_idx == -1 or down_idx == -1 or len(token_ids) < 2:
                logger.warning("Unexpected market structure: %s", outcomes)
                return None

            resolved = market.get("resolved", False)
            outcome = market.get("winner", None)

            return MarketInfo(
                condition_id=market.get("conditionId", ""),
                up_token_id=token_ids[up_idx],
                down_token_id=token_ids[down_idx],
                up_price=float(prices[up_idx]) if up_idx < len(prices) else 0.5,
                down_price=float(prices[down_idx]) if down_idx < len(prices) else 0.5,
                slug=slug,
                resolved=resolved,
                outcome=outcome
            )
        except Exception as e:
            logger.error("Market discovery failed: %s", e)
            return None

    def get_token_price(self, token_id: str) -> float:
        """Get best buy price for a token."""
        try:
            price_data = self._clob.get_price(token_id, side="BUY")
            return float(price_data.get("price", 0.5))
        except Exception as e:
            logger.warning("Price fetch failed for %s: %s", token_id[:12], e)
            return 0.5

    # Order Execution
    def place_market_order(self, token_id: str, amount_usdc: float, side: str) -> Optional[Dict[str, Any]]:
        """
        Place a FOK market order.
        side: "BUY" or "SELL"
        """
        try:
            side_const = BUY if side.upper() == "BUY" else SELL

            mo = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usdc,
                side=side_const,
                order_type=OrderType.FOK
            )

            signed = self._clob.create_market_order(mo)
            resp = self._clob.post_order(signed, OrderType.FOK)

            logger.info("Order placed | Token: %s | Side: %s | Amount: $%.2f | Status: %s",
                       token_id[:16], side, amount_usdc, resp.get("status", "unknown"))
            return resp
        except Exception as e:
            logger.error("Order placement failed: %s", e)
            return None

    # Position Monitoring
    def get_open_orders(self) -> list:
        """Get all open orders."""
        try:
            from py_clob_client.clob_types import OpenOrderParams
            return self._clob.get_orders(OpenOrderParams())
        except Exception as e:
            logger.error("Failed to get open orders: %s", e)
            return []

    def get_trades(self) -> list:
        """Get recent trades."""
        try:
            return self._clob.get_trades()
        except Exception as e:
            logger.error("Failed to get trades: %s", e)
            return []

    def get_positions(self) -> list:
        """Get current positions from Data API."""
        try:
            resp = requests.get(
                f"{DATA_API}/positions",
                params={"user": self.proxy_address, "sizeThreshold": 0},
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Failed to get positions: %s", e)
            return []

    # Redemption (Cash Out)
    def redeem_all_positions(self) -> int:
        """
        Auto-redeem all resolved positions.
        Uses relayer (gasless) if configured.
        Returns number of positions redeemed.
        """
        if not RELAYER_AVAILABLE or not self._relayer:
            logger.warning("Relayer not available. Skipping auto-redemption.")
            return 0

        if not ETH_UTILS_AVAILABLE:
            logger.error("eth-abi/eth-utils required for redemption.")
            return 0

        try:
            resp = requests.get(
                f"{DATA_API}/positions",
                params={"user": self.proxy_address, "redeemable": "true", "sizeThreshold": 0},
                timeout=15
            )
            resp.raise_for_status()
            positions = [p for p in resp.json() if float(p.get("size", 0)) > 0]

            if not positions:
                logger.info("No redeemable positions found")
                return 0

            logger.info("Found %d redeemable positions", len(positions))

            REDEEM_SELECTOR = keccak(text="redeemPositions(address,bytes32,bytes32,uint256[])")[:4]
            NEG_RISK_REDEEM_SELECTOR = keccak(text="redeemPositions(bytes32,uint256[])")[:4]

            redeemed = 0
            for pos in positions:
                cid = pos.get("conditionId", pos.get("condition_id", ""))
                if not cid:
                    continue
                if not cid.startswith("0x"):
                    cid = "0x" + cid

                neg_risk = pos.get("negativeRisk")
                condition_bytes = bytes.fromhex(cid[2:])

                try:
                    if neg_risk is True:
                        size_raw = int(float(pos.get("size", 0)) * 1e6)
                        outcome_index = int(pos.get("outcomeIndex", 0))
                        amounts = [0, 0]
                        amounts[outcome_index] = size_raw
                        args = eth_encode(["bytes32", "uint256[]"], [condition_bytes, amounts])
                        txn = SafeTransaction(
                            to=NEG_RISK_ADAPTER,
                            operation=OperationType.Call,
                            data="0x" + (NEG_RISK_REDEEM_SELECTOR + args).hex(),
                            value="0"
                        )
                    elif neg_risk is False:
                        args = eth_encode(
                            ["address", "bytes32", "bytes32", "uint256[]"],
                            [USDC_ADDRESS, b"\x00" * 32, condition_bytes, [1, 2]]
                        )
                        txn = SafeTransaction(
                            to=CTF_ADDRESS,
                            operation=OperationType.Call,
                            data="0x" + (REDEEM_SELECTOR + args).hex(),
                            value="0"
                        )
                    else:
                        continue

                    resp = self._relayer.execute([txn], f"redeem {cid[:12]}")
                    resp.wait()
                    redeemed += 1
                    logger.info("Redeemed: %s", pos.get("title", cid[:12]))

                except Exception as e:
                    logger.error("Failed to redeem %s: %s", cid[:12], e)

            logger.info("Redeemed %d/%d positions", redeemed, len(positions))
            return redeemed

        except Exception as e:
            logger.error("Redemption failed: %s", e)
            return 0
