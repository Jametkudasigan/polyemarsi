"""Position Manager - Track trades, PNL, history"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from config.settings import Config

DATA_FILE = "data/trades.json"


class PositionManager:
    def __init__(self):
        self.trades: List[Dict] = []
        self.current_position: Optional[Dict] = None
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.load_history()

    def load_history(self):
        """Load trade history dari file"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    self.trades = json.load(f)
                self._recalculate_stats()
            except Exception:
                self.trades = []

    def save_history(self):
        """Save trade history ke file"""
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(self.trades, f, indent=2)

    def _recalculate_stats(self):
        """Recalculate win/loss/pnl dari history"""
        self.wins = sum(1 for t in self.trades if t.get("pnl", 0) > 0)
        self.losses = sum(1 for t in self.trades if t.get("pnl", 0) <= 0)
        self.total_pnl = sum(t.get("pnl", 0) for t in self.trades)

    def open_position(self, market: Dict, side: str, amount: float, 
                      entry_odds: float, token_id: str):
        """Buka posisi baru"""
        self.current_position = {
            "id": len(self.trades) + 1,
            "epoch": market["epoch"],
            "slug": market["slug"],
            "market_url": market["url"],
            "side": side,  # 'UP' atau 'DOWN'
            "amount": amount,
            "entry_odds": entry_odds,
            "token_id": token_id,
            "entry_time": datetime.utcnow().isoformat(),
            "status": "OPEN",
            "pnl": 0.0,
            "result": None,
        }

    def close_position(self, winner: Optional[str]):
        """Tutup posisi dan hitung PNL"""
        if self.current_position is None:
            return

        pos = self.current_position
        pos["exit_time"] = datetime.utcnow().isoformat()
        pos["status"] = "CLOSED"
        pos["winner"] = winner

        # Hitung PNL
        # Jika winner sesuai side: profit = amount / entry_odds - amount
        # Simplified: bought shares at entry_odds, worth $1 if win
        if winner and winner.lower() == pos["side"].lower():
            # Win: shares bought = amount / entry_odds, each worth $1
            shares = pos["amount"] / pos["entry_odds"]
            gross = shares * 1.0
            # Approximate fee 2%
            fee = gross * 0.02
            pos["pnl"] = round((gross - fee) - pos["amount"], 4)
            pos["result"] = "WIN"
            self.wins += 1
        else:
            # Loss: full amount lost
            pos["pnl"] = round(-pos["amount"], 4)
            pos["result"] = "LOSS"
            self.losses += 1

        self.total_pnl += pos["pnl"]
        self.trades.append(pos)
        self.save_history()
        self.current_position = None

    def get_stats(self) -> Dict:
        """Get trading stats"""
        total = self.wins + self.losses
        win_rate = (self.wins / total * 100) if total > 0 else 0
        return {
            "wins": self.wins,
            "losses": self.losses,
            "total_trades": total,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(self.total_pnl, 4),
            "current_position": self.current_position,
        }
