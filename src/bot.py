"""
Polymarket BTC Up/Down 5-Minute Trading Bot

STRATEGY: EMA 9/21 Crossover + RSI 14 Bounce
🟢 BUY:  Price > EMA21, EMA9 > EMA21, RSI turun ke 35-40 lalu mantul naik
🔴 SELL: Price < EMA21, EMA9 < EMA21, RSI naik ke 60-65 lalu turun
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
    from rich.layout import Layout
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

def make_bar(value: float, max_val: float = 100, width: int = 20, color: str = "green") -> str:
    filled = int(width * min(value, max_val) / max_val)
    empty = width - filled
    bar = f"[{'█' * filled}{'░' * empty}]"
    return f"[{color}]{bar}[/{color}] {value:.1f}"

def make_countdown_bar(remaining: int, total: int = 300, width: int = 24) -> str:
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
    return f"[{color}]{bar}[/{color}] [bold white]{mins:02d}:{secs:02d}[/bold white]"

def rsi_gauge(rsi: float) -> str:
    if rsi < 30:
        return f"[bold cyan]◄─── {rsi:.1f} ───►[/bold cyan] [green]OVERSOLD[/green]"
    elif rsi < 40:
        return f"[bold cyan]◄─── {rsi:.1f} ───►[/bold cyan] [yellow]BUY ZONE[/yellow]"
    elif rsi < 45:
        return f"[bold cyan]◄─── {rsi:.1f} ───►[/bold cyan] [dim]NEUTRAL-LOW[/dim]"
    elif rsi <= 55:
        return f"[bold cyan]◄─── {rsi:.1f} ───►[/bold cyan] [dim]NEUTRAL[/dim]"
    elif rsi <= 60:
        return f"[bold cyan]◄─── {rsi:.1f} ───►[/bold cyan] [dim]NEUTRAL-HIGH[/dim]"
    elif rsi <= 65:
        return f"[bold cyan]◄─── {rsi:.1f} ───►[/bold cyan] [yellow]SELL ZONE[/yellow]"
    else:
        return f"[bold cyan]◄─── {rsi:.1f} ───►[/bold cyan] [red]OVERBOUGHT[/red]"

def ema_status(price: float, ema_fast: float, ema_slow: float) -> tuple:
    if price > ema_fast > ema_slow:
        diff_pct = (ema_fast - ema_slow) / ema_slow * 100
        return f"BULLISH [green]+{diff_pct:.3f}%[/green]", "green", "🟢"
    elif price < ema_fast < ema_slow:
        diff_pct = (ema_slow - ema_fast) / ema_slow * 100
        return f"BEARISH [red]-{diff_pct:.3f}%[/red]", "red", "🔴"
    elif ema_fast > ema_slow:
        return "CROSSING UP", "yellow", "🟡"
    else:
        return "CROSSING DOWN", "yellow", "🟡"

def format_signal_badge(direction: str, confidence: float) -> tuple:
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
# DASHBOARD RENDERERS
# ==================================================================

def render_header(state: str, runtime: str) -> Panel:
    state_colors = {"SCANNING": "blue", "IN_POSITION": "green", "ERROR": "red"}
    color = state_colors.get(state, "white")
    text = Text()
    text.append("🤖  ", style="bold")
    text.append("POLYMARKET BTC 5M BOT", style="bold white")
    text.append("   │   ", style="dim")
    text.append(f"State: ", style="dim")
    text.append(f"{state}", style=f"bold {color}")
    text.append("   │   ", style="dim")
    text.append(f"Runtime: {runtime}", style="dim")
    return Panel(text, border_style=color, box=box.ROUNDED, padding=(0, 2))

def render_market_panel(market: Optional[MarketInfo], next_epoch: int) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("k", style="bold cyan", width=14)
    table.add_column("v")
    now = int(time.time())
    seconds_to_next = max(0, next_epoch - now)
    if market:
        table.add_row("🎰 Slug", f"[dim]{market.slug}[/dim]")
        table.add_row("💵 UP", f"[green bold]{market.up_price:.4f}[/green bold]")
        table.add_row("💵 DOWN", f"[red bold]{market.down_price:.4f}[/red bold]")
        table.add_row("🔒 Status", "[red]RESOLVED[/red]" if market.resolved else "[green]ACTIVE[/green]")
        if market.outcome:
            table.add_row("🏆 Winner", f"[bold]{market.outcome}[/bold]")
    else:
        table.add_row("🎰 Status", "[dim]Waiting...[/dim]")
    table.add_row("⏳ Next", make_countdown_bar(seconds_to_next, 300))
    return Panel(table, title="[bold]MARKET[/bold]", border_style="blue", box=box.ROUNDED, padding=(0, 1))

def render_signal_panel(signal: SignalResult) -> Panel:
    badge, badge_color = format_signal_badge(signal.direction, signal.confidence)
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("k", style="bold cyan", width=14)
    table.add_column("v")
    table.add_row("📊 Signal", f"[bold {badge_color}]{badge}[/bold {badge_color}]")
    table.add_row("🎯 Confidence", make_bar(signal.confidence * 100, 100, 18, badge_color))
    table.add_row("")
    ema_text, ema_color, ema_emoji = ema_status(signal.price, signal.ema_fast, signal.ema_slow)
    table.add_row(f"{ema_emoji} EMA Trend", f"[{ema_color}]{ema_text}[/{ema_color}]")
    table.add_row("📈 EMA 9", f"{signal.ema_fast:.2f}")
    table.add_row("📉 EMA 21", f"{signal.ema_slow:.2f}")
    table.add_row("💰 Price", f"{signal.price:.2f}")
    table.add_row("")
    table.add_row("📈 RSI 14", rsi_gauge(signal.rsi))
    table.add_row("📊 Prev RSI", f"{signal.prev_rsi:.1f}")
    table.add_row("")
    table.add_row("💡 Analysis", f"[dim]{signal.analysis}[/dim]")
    border = badge_color if signal.direction in ("UP", "DOWN") else "white"
    return Panel(table, title="[bold]SIGNAL[/bold]", border_style=border, box=box.ROUNDED, padding=(0, 1))

def render_account_panel(balance: float, wins: int, losses: int, total_pnl: float) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("k", style="bold cyan", width=14)
    table.add_column("v")
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    pnl_color = "green" if total_pnl >= 0 else "red"
    pnl_sign = "+" if total_pnl >= 0 else ""
    table.add_row("💰 Balance", f"[bold green]${balance:.2f}[/bold green] USDC")
    table.add_row("")
    table.add_row("📈 Wins", f"[green]{wins}[/green]")
    table.add_row("📉 Losses", f"[red]{losses}[/red]")
    table.add_row("📊 Win Rate", f"[bold]{win_rate:.1f}%[/bold]")
    table.add_row("💵 Total PnL", f"[bold {pnl_color}]{pnl_sign}${total_pnl:.2f}[/{pnl_color}]")
    return Panel(table, title="[bold]ACCOUNT[/bold]", border_style="green", box=box.ROUNDED, padding=(0, 1))

def render_position_panel(market: MarketInfo, entry_side: str, entry_amount: float, entry_price: float) -> Panel:
    now = int(time.time())
    entered_epoch = int(market.slug.split("-")[-1])
    window_end = entered_epoch + 300
    remaining = max(0, window_end - now)
    elapsed = 300 - remaining
    side_color = "green" if entry_side == "UP" else "red"
    side_emoji = "🟢" if entry_side == "UP" else "🔴"
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("k", style="bold cyan", width=14)
    table.add_column("v")
    table.add_row(f"{side_emoji} Side", f"[bold {side_color}]{entry_side}[/{side_color}]")
    table.add_row("💵 Amount", f"[bold]${entry_amount:.2f}[/bold] USDC")
    table.add_row("💵 Entry", f"{entry_price:.4f}")
    table.add_row("🎰 Market", f"[dim]{market.slug}[/dim]")
    table.add_row("")
    table.add_row("⏳ Window", make_countdown_bar(remaining, 300))
    mins, secs = divmod(remaining, 60)
    table.add_row("⏱️  Remaining", f"[bold]{mins:02d}:{secs:02d}[/bold]")
    return Panel(table, title="[bold]POSITION[/bold]", border_style=side_color, box=box.ROUNDED, padding=(0, 1))

def render_footer(last_update: str) -> Panel:
    text = Text(f"⏱️  Last Update: {last_update}  │  Press Ctrl+C to stop", style="dim")
    return Panel(text, border_style="dim", box=box.ROUNDED, padding=(0, 1))

def render_scan_layout(balance, signal, market, next_epoch, wins, losses, total_pnl, runtime):
    layout = Layout()
    header = render_header("SCANNING", runtime)
    body = Layout()
    body.split_row(
        Layout(render_market_panel(market, next_epoch), name="market", ratio=1),
        Layout(render_signal_panel(signal), name="signal", ratio=1),
        Layout(render_account_panel(balance, wins, losses, total_pnl), name="account", ratio=1),
    )
    footer = render_footer(datetime.now().strftime("%H:%M:%S"))
    layout.split_column(
        Layout(header, size=3),
        Layout(body, ratio=1),
        Layout(footer, size=3),
    )
    return layout

def render_monitor_layout(balance, market, entry_side, entry_amount, entry_price, wins, losses, total_pnl, runtime):
    layout = Layout()
    header = render_header("IN_POSITION", runtime)
    body = Layout()
    body.split_row(
        Layout(render_position_panel(market, entry_side, entry_amount, entry_price), name="position", ratio=1),
        Layout(render_account_panel(balance, wins, losses, total_pnl), name="account", ratio=1),
    )
    footer = render_footer(datetime.now().strftime("%H:%M:%S"))
    layout.split_column(
        Layout(header, size=3),
        Layout(body, ratio=1),
        Layout(footer, size=3),
    )
    return layout

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

    def _build_scan_layout(self):
        return render_scan_layout(
            self._last_balance,
            self._last_signal or SignalResult("NEUTRAL", 0, 0, 0, 50, 50, 0, "Loading..."),
            self._last_market,
            self._last_next_epoch,
            self._wins,
            self._losses,
            self._total_pnl,
            self._get_runtime()
        )

    def _build_monitor_layout(self):
        if not self.current_market:
            return self._build_scan_layout()
        return render_monitor_layout(
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
            console.print(f"[bold green]✅ POSITION ENTERED SUCCESSFULLY[/bold green]\n")
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
                console.print(f"\n[bold green]🎉 WIN | Profit: ${profit:.2f} | Winner: {refreshed.outcome}[/bold green]")
            else:
                self._losses += 1
                self._total_pnl -= self.entry_amount
                console.print(f"\n[bold red]💀 LOSS | -${self.entry_amount:.2f} | Winner: {refreshed.outcome}[/bold red]")
            return True
        now = int(time.time())
        window_end = entered_epoch + 300
        if now > window_end + 300:
            console.print("[yellow]Assuming resolution complete[/yellow]")
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
            "[dim]Strategy: EMA 9/21 Crossover + RSI 14 Bounce[/dim]",
            border_style="blue",
            box=box.DOUBLE,
            padding=(1, 4)
        ))
        console.print(f"[dim]Proxy: {self.config.proxy_address[:20]}...[/dim]\n")
        self._last_balance = self.trader.get_usdc_balance()
        try:
            self._last_signal = self.signal_engine.analyze()
        except:
            self._last_signal = SignalResult("NEUTRAL", 0, 0, 0, 50, 50, 0, "Loading...")
        self._last_next_epoch = self.get_next_5m_epoch()
        self._last_market = self.trader.discover_btc_5m_market(self.get_current_5m_epoch())
        with Live(self._build_scan_layout(), refresh_per_second=1, console=console, screen=False) as live:
            self._live = live
            while True:
                try:
                    if self.state == "SCANNING":
                        self.trader.redeem_all_positions()
                        valid = self.scan()
                        live.update(self._build_scan_layout())
                        if valid:
                            live.stop()
                            self._live = None
                            success = self.enter_position()
                            if success:
                                live = Live(self._build_monitor_layout(), refresh_per_second=1, console=console, screen=False)
                                live.start()
                                self._live = live
                            else:
                                live = Live(self._build_scan_layout(), refresh_per_second=1, console=console, screen=False)
                                live.start()
                                self._live = live
                                time.sleep(self.config.scan_interval)
                        else:
                            time.sleep(self.config.scan_interval)
                    elif self.state == "IN_POSITION":
                        resolved = self.monitor_position()
                        if self._live:
                            self._live.update(self._build_monitor_layout())
                        if resolved:
                            if self._live:
                                self._live.stop()
                                self._live = None
                            self.redeem_and_reset()
                            live = Live(self._build_scan_layout(), refresh_per_second=1, console=console, screen=False)
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
                    console.print("\n[bold yellow]👋 Bot stopped by user[/bold yellow]")
                    break
                except Exception as e:
                    if self._live:
                        self._live.stop()
                    console.print(f"[bold red]⚠️  Error: {e}[/bold red]")
                    time.sleep(10)
                    live = Live(self._build_scan_layout(), refresh_per_second=1, console=console, screen=False)
                    live.start()
                    self._live = live

def main():
    config = load_config()
    bot = BTC5mBot(config)
    bot.run()

if __name__ == "__main__":
    main()
