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

try:
    from src.config import load_config, BotConfig
    from src.signals import SignalEngine, SignalResult
    from src.polymarket import PolymarketTrader, MarketInfo
except ModuleNotFoundError:
    from config import load_config, BotConfig
    from signals import SignalEngine, SignalResult
    from polymarket import PolymarketTrader, MarketInfo

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


def make_countdown_bar(remaining: int, total: int = 300, width: int = 28) -> str:
    elapsed = total - remaining
    pct = elapsed / total
    filled = int(width * pct)
    empty = width - filled
    if pct < 0.33:
        color = "green"
    elif pct < 0.66:
        color = "yellow"
    else:
        color = "red"
    bar = f"[{'█' * filled}{'░' * empty}]"
    mins, secs = divmod(remaining, 60)
    return f"[{color}]{bar}[/{color}] [bold white]{mins:02d}:{secs:02d}[/bold white]"


def make_progress_bar(elapsed: int, total: int = 300, width: int = 28) -> str:
    pct = elapsed / total
    filled = int(width * pct)
    empty = width - filled
    if pct < 0.33:
        color = "green"
    elif pct < 0.66:
        color = "yellow"
    else:
        color = "red"
    bar = f"[{'█' * filled}{'░' * empty}]"
    mins, secs = divmod(total - elapsed, 60)
    return f"[{color}]{bar}[/{color}] [bold white]{mins:02d}:{secs:02d}[/bold white]"


def rsi_status(rsi: float, prev_rsi: float) -> tuple:
    if rsi < 30:
        return "OVERSOLD", "green", "↑"
    elif rsi < 35:
        return "DEEP BUY", "green", "↑"
    elif rsi < 40 and rsi > prev_rsi:
        return "BOUNCE UP", "green", "↑"
    elif rsi < 40:
        return "BUY ZONE", "yellow", "→"
    elif rsi <= 45:
        return "NEUTRAL-LOW", "dim", "→"
    elif rsi <= 55:
        return "NEUTRAL", "white", "→"
    elif rsi <= 60:
        return "NEUTRAL-HIGH", "dim", "→"
    elif rsi > 65 and rsi < prev_rsi:
        return "REJECT DOWN", "red", "↓"
    elif rsi > 60:
        return "SELL ZONE", "yellow", "→"
    else:
        return "OVERBOUGHT", "red", "↓"


def ema_trend(price: float, ema_fast: float, ema_slow: float) -> tuple:
    if price > ema_fast > ema_slow:
        diff = (ema_fast - ema_slow) / ema_slow * 100
        return f"BULLISH (+{diff:.3f}%)", "green", "🟢"
    elif price < ema_fast < ema_slow:
        diff = (ema_slow - ema_fast) / ema_slow * 100
        return f"BEARISH (-{diff:.3f}%)", "red", "🔴"
    elif ema_fast > ema_slow:
        return "CROSSING UP", "yellow", "🟡"
    else:
        return "CROSSING DOWN", "yellow", "🟡"


def signal_badge(direction: str, confidence: float) -> tuple:
    if direction == "UP" and confidence >= 0.7:
        return "🟢", "STRONG BUY", "green"
    elif direction == "UP" and confidence >= 0.6:
        return "🟢", "BUY", "green"
    elif direction == "DOWN" and confidence >= 0.7:
        return "🔴", "STRONG SELL", "red"
    elif direction == "DOWN" and confidence >= 0.6:
        return "🔴", "SELL", "red"
    elif direction in ("UP", "DOWN"):
        return "🟡", f"WEAK {direction}", "yellow"
    else:
        return "⚪", "NO SIGNAL", "white"


def render_scan_dashboard(
    balance: float,
    signal: SignalResult,
    market: Optional[MarketInfo],
    next_epoch: int,
    wins: int,
    losses: int,
    total_pnl: float,
    runtime: str
) -> Panel:
    now = int(time.time())
    seconds_to_next = max(0, next_epoch - now)
    
    sig_emoji, sig_text, sig_color = signal_badge(signal.direction, signal.confidence)
    rsi_label, rsi_color, rsi_arrow = rsi_status(signal.rsi, signal.prev_rsi)
    ema_label, ema_color, ema_emoji = ema_trend(signal.price, signal.ema_fast, signal.ema_slow)
    
    total_trades = wins + losses
    wr = (wins / total_trades * 100) if total_trades > 0 else 0
    pnl_color = "green" if total_pnl >= 0 else "red"
    pnl_sign = "+" if total_pnl >= 0 else ""
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("icon", style="bold", width=3)
    table.add_column("key", style="bold cyan", width=20)
    table.add_column("value")
    
    table.add_row("", "", "")
    table.add_row("🤖", "BOT", Text.assemble("POLYMARKET BTC 5M BOT", ("  |  ", "dim"), (f"Runtime: {runtime}", "dim"), style="bold white"))
    table.add_row("", "Mode", Text("SCANNING MARKET", style="bold blue"))
    table.add_row("", "", "")
    table.add_row("", "", Text("-" * 55, style="dim"))
    table.add_row("", "", "")
    
    table.add_row("💰", "Balance", Text(f"${balance:.2f} USDC", style="bold green"))
    table.add_row("📈", "Wins", Text(str(wins), style="green"))
    table.add_row("📉", "Losses", Text(str(losses), style="red"))
    table.add_row("📊", "Win Rate", Text.assemble((f"{wr:.1f}%", "bold"), (f"  ({total_trades} trades)", "dim")))
    table.add_row("💵", "Total PnL", Text(f"{pnl_sign}${total_pnl:.2f}", style=f"bold {pnl_color}"))
    table.add_row("", "", "")
    table.add_row("", "", Text("-" * 55, style="dim"))
    table.add_row("", "", "")
    
    table.add_row("📡", "Source", Text("Binance API (Yahoo Fallback)", style="dim"))
    table.add_row("📊", "Direction", Text(signal.direction, style=f"bold {sig_color}"))
    table.add_row("🎯", "Confidence", Text(f"{signal.confidence*100:.1f}%", style=f"bold {sig_color}"))
    table.add_row("", "", "")
    
    table.add_row(f"{ema_emoji}", "EMA Trend", Text(ema_label, style=ema_color))
    table.add_row("📈", "EMA 9", Text(f"{signal.ema_fast:.2f}"))
    table.add_row("📉", "EMA 21", Text(f"{signal.ema_slow:.2f}"))
    table.add_row("💰", "Price", Text(f"{signal.price:.2f}"))
    table.add_row("", "", "")
    
    table.add_row("📈", "RSI 14", Text.assemble((f"{signal.rsi:.1f} {rsi_arrow}", f"bold {rsi_color}"), (f"  (prev: {signal.prev_rsi:.1f})", "dim")))
    table.add_row("📊", "RSI Status", Text(rsi_label, style=rsi_color))
    table.add_row("", "", "")
    table.add_row("", "", Text("-" * 55, style="dim"))
    table.add_row("", "", "")
    
    if market:
        table.add_row("🎰", "Market", Text(market.slug, style="dim"))
        table.add_row("💵", "UP Price", Text(f"{market.up_price:.4f}", style="green bold"))
        table.add_row("💵", "DOWN Price", Text(f"{market.down_price:.4f}", style="red bold"))
        resolved_text = "YES" if market.resolved else "NO"
        resolved_style = "bold red" if market.resolved else "bold green"
        table.add_row("🔒", "Resolved", Text(resolved_text, style=resolved_style))
    else:
        table.add_row("🎰", "Market", Text("Waiting for next window...", style="dim"))
    
    table.add_row("", "", "")
    countdown = make_countdown_bar(seconds_to_next, 300)
    table.add_row("⏳", "Next Window", Text(countdown))
    table.add_row("", "", "")
    table.add_row("", "", Text("-" * 55, style="dim"))
    table.add_row("", "", "")
    table.add_row(f"{sig_emoji}", "Status", Text.assemble((sig_text, f"bold {sig_color}"), (f"  •  {datetime.now().strftime('%H:%M:%S')}", "dim")))
    table.add_row("", "", "")
    
    return Panel(
        table,
        border_style="blue",
        box=box.ROUNDED,
        padding=(0, 2),
        title="[bold blue]SCAN MODE[/bold blue]",
        title_align="left",
        subtitle=f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        subtitle_align="right"
    )


def render_monitor_dashboard(
    balance: float,
    market: MarketInfo,
    entry_side: str,
    entry_amount: float,
    entry_price: float,
    wins: int,
    losses: int,
    total_pnl: float,
    runtime: str
) -> Panel:
    now = int(time.time())
    entered_epoch = int(market.slug.split("-")[-1])
    window_end = entered_epoch + 300
    remaining = max(0, window_end - now)
    elapsed = 300 - remaining
    
    side_color = "green" if entry_side == "UP" else "red"
    side_emoji = "🟢" if entry_side == "UP" else "🔴"
    
    total_trades = wins + losses
    wr = (wins / total_trades * 100) if total_trades > 0 else 0
    pnl_color = "green" if total_pnl >= 0 else "red"
    pnl_sign = "+" if total_pnl >= 0 else ""
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("icon", style="bold", width=3)
    table.add_column("key", style="bold cyan", width=20)
    table.add_column("value")
    
    table.add_row("", "", "")
    table.add_row("🤖", "BOT", Text.assemble("POLYMARKET BTC 5M BOT", ("  |  ", "dim"), (f"Runtime: {runtime}", "dim"), style="bold white"))
    table.add_row("", "Mode", Text("MONITORING POSITION", style="bold green"))
    table.add_row("", "", "")
    table.add_row("", "", Text("-" * 55, style="dim"))
    table.add_row("", "", "")
    
    table.add_row("💰", "Balance", Text(f"${balance:.2f} USDC", style="bold green"))
    table.add_row("📈", "Wins", Text(str(wins), style="green"))
    table.add_row("📉", "Losses", Text(str(losses), style="red"))
    table.add_row("📊", "Win Rate", Text(f"{wr:.1f}%", style="bold"))
    table.add_row("💵", "Total PnL", Text(f"{pnl_sign}${total_pnl:.2f}", style=f"bold {pnl_color}"))
    table.add_row("", "", "")
    table.add_row("", "", Text("-" * 55, style="dim"))
    table.add_row("", "", "")
    
    table.add_row(f"{side_emoji}", "Entry Side", Text(entry_side, style=f"bold {side_color}"))
    table.add_row("💵", "Entry Amount", Text(f"${entry_amount:.2f} USDC", style="bold"))
    table.add_row("💵", "Entry Price", Text(f"{entry_price:.4f}"))
    table.add_row("🎰", "Market", Text(market.slug, style="dim"))
    table.add_row("", "", "")
    
    progress = make_progress_bar(elapsed, 300)
    table.add_row("⏳", "Window Close", Text(progress))
    mins, secs = divmod(remaining, 60)
    table.add_row("⏱️ ", "Remaining", Text(f"{mins:02d}:{secs:02d}", style="bold"))
    table.add_row("", "", "")
    table.add_row("", "", Text("-" * 55, style="dim"))
    table.add_row("", "", "")
    table.add_row(f"{side_emoji}", "Status", Text.assemble(("POSITION OPEN", f"bold {side_color}"), (f"  •  Waiting resolution...  •  {datetime.now().strftime('%H:%M:%S')}", "dim")))
    table.add_row("", "", "")
    
    return Panel(
        table,
        border_style="green",
        box=box.ROUNDED,
        padding=(0, 2),
        title="[bold green]MONITOR MODE[/bold green]",
        title_align="left",
        subtitle=f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        subtitle_align="right"
    )


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
    
    def _build_scan_panel(self) -> Panel:
        return render_scan_dashboard(
            self._last_balance,
            self._last_signal or SignalResult("NEUTRAL", 0, 0, 0, 50, 50, 0, "Loading..."),
            self._last_market,
            self._last_next_epoch,
            self._wins,
            self._losses,
            self._total_pnl,
            self._get_runtime()
        )
    
    def _build_monitor_panel(self) -> Panel:
        if not self.current_market:
            return self._build_scan_panel()
        return render_monitor_dashboard(
            self._last_balance,
            self.current_market,
            self.entry_side or "UNKNOWN",
            self.entry_amount,
            self.entry_price,
            self._wins,
            self._losses,
            self._total_pnl,
            self._get_runtime()
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
        self._last_balance = self.trader.get_usdc_balance()
        try:
            self._last_signal = self.signal_engine.analyze()
        except:
            self._last_signal = SignalResult("NEUTRAL", 0, 0, 0, 50, 50, 0, "Loading...")
        self._last_next_epoch = self.get_next_5m_epoch()
        self._last_market = self.trader.discover_btc_5m_market(self.get_current_5m_epoch())
        
        with Live(self._build_scan_panel(), refresh_per_second=2, console=console, screen=False) as live:
            self._live = live
            
            while True:
                try:
                    if self.state == "SCANNING":
                        self.trader.redeem_all_positions()
                        valid = self.scan()
                        
                        live.update(self._build_scan_panel())
                        
                        if valid:
                            live.stop()
                            self._live = None
                            
                            success = self.enter_position()
                            
                            live = Live(self._build_monitor_panel(), refresh_per_second=2, console=console, screen=False)
                            live.start()
                            self._live = live
                            
                            if not success:
                                time.sleep(self.config.scan_interval)
                        else:
                            time.sleep(self.config.scan_interval)
                    
                    elif self.state == "IN_POSITION":
                        resolved = self.monitor_position()
                        
                        live.update(self._build_monitor_panel())
                        
                        if resolved:
                            live.stop()
                            self._live = None
                            
                            self.redeem_and_reset()
                            
                            live = Live(self._build_scan_panel(), refresh_per_second=2, console=console, screen=False)
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
                    live = Live(self._build_scan_panel(), refresh_per_second=2, console=console, screen=False)
                    live.start()
                    self._live = live


def main():
    config = load_config()
    bot = BTC5mBot(config)
    bot.run()


if __name__ == "__main__":
    main()
