"""
Polymarket BTC Up/Down 5-Minute Trading Bot

Flow:
1. SCANNING: Analyze BTC momentum -> find valid signal
2. ENTRY: Place FOK market order on Polymarket (Up/Down token)
3. MONITORING: Wait for market resolution
4. REDEEM: Auto cash out winning positions -> back to SCANNING
"""
import os
import sys
import time
import logging
from typing import Optional
from datetime import datetime

# ------------------------------------------------------------------
# Rich UI Imports
# ------------------------------------------------------------------
try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("[ERROR] rich not installed. Run: pip install rich")
    sys.exit(1)

console = Console()

# ------------------------------------------------------------------
# Polymarket / Config Imports
# ------------------------------------------------------------------
try:
    from src.config import load_config, BotConfig
    from src.signals import SignalEngine, SignalResult
    from src.polymarket import PolymarketTrader, MarketInfo
except ModuleNotFoundError:
    from config import load_config, BotConfig
    from signals import SignalEngine, SignalResult
    from polymarket import PolymarketTrader, MarketInfo

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ==================================================================
# UI HELPERS
# ==================================================================

def make_countdown_bar(remaining: int, total: int = 300, width: int = 28) -> str:
    elapsed = total - remaining
    filled = int(width * elapsed / total)
    bar = "█" * filled + "░" * (width - filled)
    mins, secs = divmod(remaining, 60)
    return f"[{bar}] {mins:02d}:{secs:02d}"

def make_progress_bar(elapsed: int, total: int = 300, width: int = 28) -> str:
    filled = int(width * elapsed / total)
    bar = "█" * filled + "░" * (width - filled)
    mins, secs = divmod(total - elapsed, 60)
    return f"[{bar}] {mins:02d}:{secs:02d}"

def format_signal_style(direction: str, confidence: float) -> tuple:
    if direction == "UP" and confidence >= 0.6:
        return "🟢", "BULLISH SIGNAL", "green"
    elif direction == "DOWN" and confidence >= 0.6:
        return "🔴", "BEARISH SIGNAL", "red"
    elif direction in ("UP", "DOWN") and confidence < 0.6:
        return "🟡", f"WEAK {direction}", "yellow"
    else:
        return "⚪", "NO SIGNAL", "white"

# ==================================================================
# DASHBOARD RENDERERS
# ==================================================================

def render_scan_dashboard(
    balance: float,
    signal: SignalResult,
    market: Optional[MarketInfo],
    next_epoch: int
) -> Panel:
    now = int(time.time())
    seconds_to_next = max(0, next_epoch - now)
    
    sig_emoji, sig_text, sig_color = format_signal_style(signal.direction, signal.confidence)
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="bold cyan", width=18)
    table.add_column("value", style="white")
    
    table.add_row("💰 Balance", f"[bold green]${balance:.2f}[/bold green] USDC")
    table.add_row("📡 Source", "Binance API (Yahoo Fallback)")
    table.add_row("")
    table.add_row("📊 Direction", f"[{sig_color}]{signal.direction}[/{sig_color}]")
    table.add_row("🎯 Confidence", f"{signal.confidence*100:.1f}%")
    table.add_row("📈 RSI", f"{signal.rsi:.1f}")
    table.add_row("📉 EMA Slope", f"{signal.ema_slope:+.4f}%")
    table.add_row("📊 Window Δ", f"{signal.window_delta_pct:+.4f}%")
    table.add_row("")
    
    if market:
        table.add_row("🎰 Market", f"[dim]{market.slug}[/dim]")
        table.add_row("💵 UP Price", f"[green]{market.up_price:.4f}[/green]")
        table.add_row("💵 DOWN Price", f"[red]{market.down_price:.4f}[/red]")
        table.add_row("🔒 Resolved", "[bold red]YES[/bold red]" if market.resolved else "[bold green]NO[/bold green]")
    else:
        table.add_row("🎰 Market", "[dim]Waiting for next window...[/dim]")
    
    table.add_row("")
    countdown = make_countdown_bar(seconds_to_next, 300)
    table.add_row("⏳ Next Window", f"[bold yellow]{countdown}[/bold yellow]")
    
    header = Text("🤖  POLYMARKET BTC 5M BOT  •  SCANNING MARKET", style="bold white on blue")
    sep = Text("─" * 62, style="dim")
    footer = Text(f"{sig_emoji}  {sig_text}  •  {datetime.now().strftime('%H:%M:%S')}", style=f"bold {sig_color}")
    
    content = Group(header, sep, table, sep, footer)
    
    return Panel(
        content,
        border_style="blue",
        box=box.ROUNDED,
        padding=(1, 2),
        title="[bold blue]SCAN MODE[/bold blue]",
        title_align="left"
    )


def render_monitor_dashboard(
    balance: float,
    market: MarketInfo,
    entry_side: str,
    entry_amount: float,
    entry_price: float
) -> Panel:
    now = int(time.time())
    entered_epoch = int(market.slug.split("-")[-1])
    window_end = entered_epoch + 300
    remaining = max(0, window_end - now)
    elapsed = 300 - remaining
    
    side_color = "green" if entry_side == "UP" else "red"
    side_emoji = "🟢" if entry_side == "UP" else "🔴"
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="bold cyan", width=18)
    table.add_column("value", style="white")
    
    table.add_row("💰 Balance", f"[bold green]${balance:.2f}[/bold green] USDC")
    table.add_row("🎰 Market", f"[dim]{market.slug}[/dim]")
    table.add_row("")
    table.add_row(f"{side_emoji} Entry Side", f"[bold {side_color}]{entry_side}[/{side_color}]")
    table.add_row("💵 Entry Amount", f"[bold]${entry_amount:.2f}[/bold] USDC")
    table.add_row("💵 Entry Price", f"{entry_price:.4f}")
    table.add_row("")
    progress = make_progress_bar(elapsed, 300)
    mins, secs = divmod(remaining, 60)
    table.add_row("⏳ Window Close", f"[bold yellow]{progress}[/bold yellow]  ({mins:02d}:{secs:02d})")
    
    header = Text("🤖  POLYMARKET BTC 5M BOT  •  MONITORING POSITION", style="bold white on green")
    sep = Text("─" * 62, style="dim")
    footer = Text(f"{side_emoji}  POSITION OPEN  •  Waiting resolution...  •  {datetime.now().strftime('%H:%M:%S')}", style="bold green")
    
    content = Group(header, sep, table, sep, footer)
    
    return Panel(
        content,
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2),
        title="[bold green]MONITOR MODE[/bold green]",
        title_align="left"
    )


# ==================================================================
# BOT CLASS
# ==================================================================

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
    
    def scan(self) -> bool:
        balance = self.trader.get_usdc_balance()
        
        try:
            signal = self.signal_engine.analyze()
        except Exception as e:
            signal = SignalResult("NEUTRAL", 0, 0, 50, 0, 0, 0, f"Error: {e}")
        
        epoch = self.get_current_5m_epoch()
        next_epoch = self.get_next_5m_epoch()
        market = self.trader.discover_btc_5m_market(epoch)
        
        panel = render_scan_dashboard(balance, signal, market, next_epoch)
        console.print(panel)
        
        if balance < self.config.min_entry_usdc:
            console.print("[dim]Insufficient balance, waiting...[/dim]\n")
            return False
        
        if not market or market.resolved:
            console.print("[dim]No active market, waiting...[/dim]\n")
            return False
        
        seconds_remaining = 300 - (int(time.time()) % 300)
        if seconds_remaining < 30:
            console.print("[yellow]Too close to window close, waiting next...[/yellow]\n")
            return False
        
        if signal.direction not in ("UP", "DOWN"):
            return False
        
        if signal.confidence < 0.6:
            return False
        
        target_price = market.up_price if signal.direction == "UP" else market.down_price
        if not (self.config.odds_min <= target_price <= self.config.odds_max):
            console.print(f"[yellow]Odds filter: {target_price:.4f} outside range[/yellow]\n")
            return False
        
        console.print(f"[bold green]✅ VALID SIGNAL | {signal.direction} @ {target_price:.4f} | Confidence: {signal.confidence:.0%}[/bold green]\n")
        
        self.current_market = market
        self.entry_side = signal.direction
        self.entry_price = target_price
        return True
    
    def enter_position(self) -> bool:
        if not self.current_market or not self.entry_side:
            return False
        
        amount = min(self.config.max_entry_usdc, self.config.min_entry_usdc)
        amount = max(amount, 1.0)
        
        token_id = (self.current_market.up_token_id if self.entry_side == "UP"
                   else self.current_market.down_token_id)
        
        console.print(f"[bold cyan]🚀 ENTERING {self.entry_side} | ${amount:.2f} @ {self.entry_price:.4f}[/bold cyan]")
        
        resp = self.trader.place_market_order(token_id, amount, "BUY")
        
        if resp and resp.get("success"):
            self.entry_amount = amount
            self.state = "IN_POSITION"
            console.print(f"[bold green]✅ POSITION ENTERED SUCCESSFULLY[/bold green]\n")
            return True
        else:
            console.print(f"[bold red]❌ ENTRY FAILED: {resp}[/bold red]\n")
            self.state = "SCANNING"
            return False
    
    def monitor_position(self) -> bool:
        if not self.current_market:
            return False
        
        balance = self.trader.get_usdc_balance()
        
        panel = render_monitor_dashboard(
            balance, self.current_market,
            self.entry_side or "UNKNOWN",
            self.entry_amount,
            self.entry_price
        )
        console.print(panel)
        
        entered_epoch = int(self.current_market.slug.split("-")[-1])
        
        refreshed = self.trader.discover_btc_5m_market(entered_epoch)
        if refreshed and refreshed.resolved:
            self.current_market = refreshed
            console.print(f"[bold green]🎉 MARKET RESOLVED | Winner: {refreshed.outcome}[/bold green]\n")
            return True
        
        now = int(time.time())
        window_end = entered_epoch + 300
        if now > window_end + 300:
            console.print("[yellow]Assuming resolution complete[/yellow]\n")
            return True
        
        return False
    
    def redeem_and_reset(self):
        console.print("[bold cyan]💰 Redeeming positions...[/bold cyan]")
        redeemed = self.trader.redeem_all_positions()
        
        if redeemed > 0:
            new_balance = self.trader.get_usdc_balance()
            console.print(f"[bold green]💰 New Balance: ${new_balance:.2f} USDC[/bold green]")
        
        self.state = "SCANNING"
        self.current_market = None
        self.entry_side = None
        self.entry_amount = 0.0
        self.entry_price = 0.0
        
        console.print("[bold blue]🔄 Back to SCANNING[/bold blue]\n")
    
    def run(self):
        console.print(Panel(
            "[bold white]POLYMARKET BTC 5-MINUTE TRADING BOT[/bold white]\n"
            "[dim]Strategy: EMA50 + RSI Pullback + Momentum Confirmation[/dim]",
            border_style="blue",
            box=box.DOUBLE,
            padding=(1, 4)
        ))
        console.print(f"[dim]Proxy: {self.config.proxy_address[:20]}...[/dim]\n")
        
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
                console.print("\n[bold yellow]👋 Bot stopped by user[/bold yellow]")
                break
            except Exception as e:
                console.print(f"[bold red]⚠️  Error: {e}[/bold red]")
                time.sleep(10)


def main():
    config = load_config()
    bot = BTC5mBot(config)
    bot.run()


if __name__ == "__main__":
    main()
