"""
Polymarket BTC Up/Down 5-Minute Trading Bot

STRATEGY: EMA 9/21 Crossover + RSI 14 Bounce
"""
import os
import sys
import time
import logging
from typing import Optional
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# Rich UI Imports
# ------------------------------------------------------------------
try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
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

def make_bar(value: float, max_val: float = 100, width: int = 16, color: str = "green") -> str:
    filled = int(width * min(value, max_val) / max_val)
    empty = width - filled
    bar = f"[{'█' * filled}{'░' * empty}]"
    return f"[{color}]{bar}[/{color}] {value:.1f}"

def make_countdown_bar(remaining: int, total: int = 300, width: int = 20) -> str:
    elapsed = total - remaining
    pct = elapsed / total
    filled = int(width * pct)
    empty = width - filled
    if pct < 0.5:
        color = "green"
    elif pct < 0.8:
        color = "yellow"
    else:
        color = "red"
    bar = f"[{'█' * filled}{'░' * empty}]"
    mins, secs = divmod(remaining, 60)
    return f"[{color}]{bar}[/{color}] [bold]{mins:02d}:{secs:02d}[/bold]"

def rsi_gauge(rsi: float) -> str:
    if rsi < 30:
        return f"[cyan]◄───[/cyan] [green]{rsi:.1f}[/green] [cyan]───►[/cyan] [bold green]OVERSOLD[/bold green]"
    elif rsi < 40:
        return f"[cyan]◄───[/cyan] [yellow]{rsi:.1f}[/yellow] [cyan]───►[/cyan] [bold yellow]BUY ZONE[/bold yellow]"
    elif rsi < 45:
        return f"[cyan]◄───[/cyan] [dim]{rsi:.1f}[/dim] [cyan]───►[/cyan] NEUTRAL-LOW"
    elif rsi <= 55:
        return f"[cyan]◄───[/cyan] [white]{rsi:.1f}[/white] [cyan]───►[/cyan] NEUTRAL"
    elif rsi <= 60:
        return f"[cyan]◄───[/cyan] [dim]{rsi:.1f}[/dim] [cyan]───►[/cyan] NEUTRAL-HIGH"
    elif rsi <= 65:
        return f"[cyan]◄───[/cyan] [yellow]{rsi:.1f}[/yellow] [cyan]───►[/cyan] [bold yellow]SELL ZONE[/bold yellow]"
    else:
        return f"[cyan]◄───[/cyan] [red]{rsi:.1f}[/red] [cyan]───►[/cyan] [bold red]OVERBOUGHT[/bold red]"

def ema_status(price: float, ema_fast: float, ema_slow: float) -> tuple:
    if price > ema_fast > ema_slow:
        diff = (ema_fast - ema_slow) / ema_slow * 100
        return f"BULLISH +{diff:.3f}%", "green", "🟢"
    elif price < ema_fast < ema_slow:
        diff = (ema_slow - ema_fast) / ema_slow * 100
        return f"BEARISH -{diff:.3f}%", "red", "🔴"
    elif ema_fast > ema_slow:
        return "CROSSING UP", "yellow", "🟡"
    else:
        return "CROSSING DOWN", "yellow", "🟡"

def format_badge(direction: str, confidence: float) -> tuple:
    if direction == "UP" and confidence >= 0.7:
        return "🟢 STRONG BUY", "green"
    elif direction == "UP" and confidence >= 0.6:
        return "🟢 BUY", "green"
    elif direction == "DOWN" and confidence >= 0.7:
        return "🔴 STRONG SELL", "red"
    elif direction == "DOWN" and confidence >= 0.6:
        return "🔴 SELL", "red"
    elif direction in ("UP", "DOWN"):
        return f"🟡 WEAK {direction}", "yellow"
    else:
        return "⚪ NO SIGNAL", "white"

# ==================================================================
# RENDERERS
# ==================================================================

def render_dashboard(
    state: str,
    balance: float,
    signal: SignalResult,
    market: Optional[MarketInfo],
    next_epoch: int,
    wins: int,
    losses: int,
    total_pnl: float,
    runtime: str,
    entry_side: Optional[str] = None,
    entry_amount: float = 0.0,
    entry_price: float = 0.0,
) -> Panel:
    """Render dashboard utama - 1 panel besar dengan table 3 kolom."""
    
    state_colors = {"SCANNING": "blue", "IN_POSITION": "green", "ERROR": "red"}
    sc = state_colors.get(state, "white")
    
    # Header
    header_text = Text()
    header_text.append("🤖 ", style="bold")
    header_text.append("POLYMARKET BTC 5M BOT", style="bold white")
    header_text.append("  │  ", style="dim")
    header_text.append(f"State: ", style="dim")
    header_text.append(f"{state}", style=f"bold {sc}")
    header_text.append("  │  ", style="dim")
    header_text.append(f"Runtime: {runtime}", style="dim")
    
    # Main Table (3 columns)
    main_table = Table(show_header=False, box=None, padding=(0, 1))
    main_table.add_column("col1", ratio=1)
    main_table.add_column("col2", ratio=1)
    main_table.add_column("col3", ratio=1)
    
    # ===== COL 1: MARKET =====
    t1 = Table(show_header=False, box=None, padding=(0, 0))
    t1.add_column("k", style="bold cyan", width=10)
    t1.add_column("v")
    
    now = int(time.time())
    sec_next = max(0, next_epoch - now)
    
    if market:
        t1.add_row("🎰 Slug", f"[dim]{market.slug}[/dim]")
        t1.add_row("💵 UP", f"[green bold]{market.up_price:.4f}[/green bold]")
        t1.add_row("💵 DOWN", f"[red bold]{market.down_price:.4f}[/red bold]")
        t1.add_row("🔒 Status", "[red]RESOLVED[/red]" if market.resolved else "[green]ACTIVE[/green]")
        if market.outcome:
            t1.add_row("🏆 Win", f"[bold]{market.outcome}[/bold]")
    else:
        t1.add_row("🎰 Status", "[dim]Waiting...[/dim]")
    
    t1.add_row("⏳ Next", make_countdown_bar(sec_next, 300))
    p1 = Panel(t1, title="[bold blue]📊 MARKET[/bold blue]", border_style="blue", box=box.ROUNDED, padding=(0, 1))
    
    # ===== COL 2: SIGNAL =====
    badge, bc = format_badge(signal.direction, signal.confidence)
    
    t2 = Table(show_header=False, box=None, padding=(0, 0))
    t2.add_column("k", style="bold cyan", width=10)
    t2.add_column("v")
    
    t2.add_row("📊 Signal", f"[bold {bc}]{badge}[/bold {bc}]")
    t2.add_row("🎯 Conf", make_bar(signal.confidence * 100, 100, 16, bc))
    t2.add_row("", "")
    
    ema_txt, ema_c, ema_e = ema_status(signal.price, signal.ema_fast, signal.ema_slow)
    t2.add_row(f"{ema_e} Trend", f"[{ema_c}]{ema_txt}[/{ema_c}]")
    t2.add_row("📈 EMA 9", f"{signal.ema_fast:.2f}")
    t2.add_row("📉 EMA 21", f"{signal.ema_slow:.2f}")
    t2.add_row("💰 Price", f"{signal.price:.2f}")
    t2.add_row("", "")
    t2.add_row("📈 RSI", rsi_gauge(signal.rsi))
    t2.add_row("📊 Prev", f"{signal.prev_rsi:.1f}")
    
    border_c = bc if signal.direction in ("UP", "DOWN") else "white"
    p2 = Panel(t2, title="[bold]📡 SIGNAL[/bold]", border_style=border_c, box=box.ROUNDED, padding=(0, 1))
    
    # ===== COL 3: ACCOUNT / POSITION =====
    t3 = Table(show_header=False, box=None, padding=(0, 0))
    t3.add_column("k", style="bold cyan", width=10)
    t3.add_column("v")
    
    t3.add_row("💰 Balance", f"[bold green]${balance:.2f}[/bold green]")
    t3.add_row("", "")
    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    pnl_c = "green" if total_pnl >= 0 else "red"
    pnl_s = "+" if total_pnl >= 0 else ""
    t3.add_row("📈 Wins", f"[green]{wins}[/green]")
    t3.add_row("📉 Losses", f"[red]{losses}[/red]")
    t3.add_row("📊 WR", f"[bold]{wr:.1f}%[/bold]")
    t3.add_row("💵 PnL", f"[bold {pnl_c}]{pnl_s}${total_pnl:.2f}[/{pnl_c}]")
    
    if state == "IN_POSITION" and entry_side:
        t3.add_row("", "")
        ec = "green" if entry_side == "UP" else "red"
        ee = "🟢" if entry_side == "UP" else "🔴"
        t3.add_row(f"{ee} Side", f"[bold {ec}]{entry_side}[/{ec}]")
        t3.add_row("💵 Entry", f"${entry_amount:.2f} @ {entry_price:.4f}")
        
        entered = int(market.slug.split("-")[-1]) if market else 0
        rem = max(0, entered + 300 - now)
        t3.add_row("⏳ Close", make_countdown_bar(rem, 300))
    
    p3 = Panel(t3, title="[bold green]💼 ACCOUNT[/bold green]", border_style="green", box=box.ROUNDED, padding=(0, 1))
    
    main_table.add_row(p1, p2, p3)
    
    # Footer
    footer = Text(f"⏱️  {datetime.now().strftime('%H:%M:%S')}  │  Ctrl+C to stop", style="dim")
    
    content = Group(header_text, Text("─" * 78, style="dim"), main_table, Text("─" * 78, style="dim"), footer)
    
    return Panel(
        content,
        border_style=sc,
        box=box.ROUNDED,
        padding=(1, 2),
        title=f"[bold {sc}]BTC 5M BOT[/bold {sc}]",
        title_align="center"
    )


# ==================================================================
# BOT CLASS
# ==================================================================

class BTC5mBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.signal_engine = SignalEngine(
            ema_fast=config.ema_fast,
            ema_slow=config.ema_slow,
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
        
        self._live: Optional[Live] = None
        self._last_balance: float = 0.0
        self._last_signal: Optional[SignalResult] = None
        self._last_market: Optional[MarketInfo] = None
        self._last_next_epoch: int = 0
        
        self._wins: int = 0
        self._losses: int = 0
        self._total_pnl: float = 0.0
        self._start_time: float = time.time()
    
    def get_current_5m_epoch(self) -> int:
        now = int(time.time())
        return (now // 300) * 300
    
    def get_next_5m_epoch(self) -> int:
        now = int(time.time())
        return ((now // 300) + 1) * 300
    
    def _get_runtime(self) -> str:
        elapsed = int(time.time() - self._start_time)
        return str(timedelta(seconds=elapsed))
    
    def _build_panel(self) -> Panel:
        return render_dashboard(
            self.state,
            self._last_balance,
            self._last_signal or SignalResult("NEUTRAL", 0, 0, 0, 50, 50, 0, "Loading..."),
            self._last_market,
            self._last_next_epoch,
            self._wins,
            self._losses,
            self._total_pnl,
            self._get_runtime(),
            self.entry_side,
            self.entry_amount,
            self.entry_price,
        )
    
    def scan(self) -> bool:
        self._last_balance = self.trader.get_usdc_balance()
        
        try:
            signal = self.signal_engine.analyze()
        except Exception as e:
            signal = SignalResult("NEUTRAL", 0, 0, 0, 50, 50, 0, f"Error: {e}")
        
        self._last_signal = signal
        
        epoch = self.get_current_5m_epoch()
        self._last_next_epoch = self.get_next_5m_epoch()
        market = self.trader.discover_btc_5m_market(epoch)
        self._last_market = market
        
        if self._last_balance < self.config.min_entry_usdc:
            return False
        
        if not market or market.resolved:
            return False
        
        seconds_remaining = 300 - (int(time.time()) % 300)
        if seconds_remaining < 30:
            return False
        
        if signal.direction not in ("UP", "DOWN"):
            return False
        
        if signal.confidence < 0.6:
            return False
        
        target_price = market.up_price if signal.direction == "UP" else market.down_price
        if not (self.config.odds_min <= target_price <= self.config.odds_max):
            return False
        
        self.current_market = market
        self.entry_side = signal.direction
        self.entry_price = target_price
        
        console.print(f"\n[bold green]✅ VALID SIGNAL | {signal.direction} @ {target_price:.4f} | Confidence: {signal.confidence:.0%}[/bold green]")
        
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
            console.print(f"[bold green]✅ POSITION ENTERED[/bold green]\n")
            return True
        else:
            console.print(f"[bold red]❌ ENTRY FAILED: {resp}[/bold red]\n")
            self.state = "SCANNING"
            return False
    
    def monitor_position(self) -> bool:
        if not self.current_market:
            return False
        
        self._last_balance = self.trader.get_usdc_balance()
        
        entered_epoch = int(self.current_market.slug.split("-")[-1])
        
        refreshed = self.trader.discover_btc_5m_market(entered_epoch)
        if refreshed and refreshed.resolved:
            self.current_market = refreshed
            
            won = (refreshed.outcome == "Up" and self.entry_side == "UP") or \
                  (refreshed.outcome == "Down" and self.entry_side == "DOWN")
            
            if won:
                profit = self.entry_amount * (1 - self.entry_price) / self.entry_price
                self._wins += 1
                self._total_pnl += profit
                console.print(f"\n[bold green]🎉 WIN | +${profit:.2f} | {refreshed.outcome}[/bold green]")
            else:
                self._losses += 1
                self._total_pnl -= self.entry_amount
                console.print(f"\n[bold red]💀 LOSS | -${self.entry_amount:.2f} | {refreshed.outcome}[/bold red]")
            
            return True
        
        now = int(time.time())
        window_end = entered_epoch + 300
        if now > window_end + 300:
            console.print("[yellow]Resolution timeout[/yellow]")
            return True
        
        return False
    
    def redeem_and_reset(self):
        console.print("[bold cyan]💰 Redeeming...[/bold cyan]")
        redeemed = self.trader.redeem_all_positions()
        
        if redeemed > 0:
            new_balance = self.trader.get_usdc_balance()
            console.print(f"[bold green]💰 Balance: ${new_balance:.2f}[/bold green]")
        
        self.state = "SCANNING"
        self.current_market = None
        self.entry_side = None
        self.entry_amount = 0.0
        self.entry_price = 0.0
        
        console.print("[bold blue]🔄 SCANNING[/bold blue]\n")
    
    def run(self):
        """Main loop dengan Rich Live - 1 panel yang di-refresh."""
        
        # Init data
        self._last_balance = self.trader.get_usdc_balance()
        try:
            self._last_signal = self.signal_engine.analyze()
        except:
            self._last_signal = SignalResult("NEUTRAL", 0, 0, 0, 50, 50, 0, "Loading...")
        self._last_next_epoch = self.get_next_5m_epoch()
        self._last_market = self.trader.discover_btc_5m_market(self.get_current_5m_epoch())
        
        # Live display
        with Live(self._build_panel(), refresh_per_second=2, console=console, screen=False) as live:
            self._live = live
            
            while True:
                try:
                    if self.state == "SCANNING":
                        self.trader.redeem_all_positions()
                        valid = self.scan()
                        
                        live.update(self._build_panel())
                        
                        if valid:
                            live.stop()
                            self._live = None
                            
                            success = self.enter_position()
                            
                            live = Live(self._build_panel(), refresh_per_second=2, console=console, screen=False)
                            live.start()
                            self._live = live
                            
                            if not success:
                                time.sleep(self.config.scan_interval)
                        else:
                            time.sleep(self.config.scan_interval)
                    
                    elif self.state == "IN_POSITION":
                        resolved = self.monitor_position()
                        
                        live.update(self._build_panel())
                        
                        if resolved:
                            live.stop()
                            self._live = None
                            
                            self.redeem_and_reset()
                            
                            live = Live(self._build_panel(), refresh_per_second=2, console=console, screen=False)
                            live.start()
                            self._live = live
                        else:
                            time.sleep(self.config.position_check_interval)
                    
                    else:
                        self.state = "SCANNING"
                        time.sleep(5)
                        
                except KeyboardInterrupt:
                    if self._live:
                        self._live.stop()
                    console.print("\n[bold yellow]👋 Stopped[/bold yellow]")
                    break
                except Exception as e:
                    if self._live:
                        self._live.stop()
                    console.print(f"[bold red]⚠️  Error: {e}[/bold red]")
                    time.sleep(10)
                    live = Live(self._build_panel(), refresh_per_second=2, console=console, screen=False)
                    live.start()
                    self._live = live


def main():
    config = load_config()
    bot = BTC5mBot(config)
    bot.run()


if __name__ == "__main__":
    main()
