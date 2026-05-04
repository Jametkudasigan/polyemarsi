"""Terminal UI dengan Rich"""
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.layout import Layout
from rich.console import Console, Group
from rich.text import Text
from rich.align import Align
from typing import Dict, Optional
from src.utils import format_time_left, format_usd, now_iso, seconds_to_next_5m, seconds_since_5m_start

console = Console()


class BotUI:
    def __init__(self):
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3)
        )
        self.layout["main"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=1)
        )

    def _header(self, state: str, mode: str) -> Panel:
        """Header dengan status bot"""
        mode_style = "green" if mode == "LIVE" else "yellow"
        text = Text()
        text.append("🤖 POLYMARKET BTC 5M BOT ", style="bold cyan")
        text.append(f"| State: ", style="white")
        text.append(f"{state}", style="bold magenta")
        text.append(f" | Mode: ", style="white")
        text.append(f"{mode}", style=f"bold {mode_style}")
        text.append(f" | {now_iso()}", style="dim")
        return Panel(Align.center(text), border_style="cyan", title="[bold blue]Automation Bot[/bold blue]")

    def _scanning_panel(self, data: Dict) -> Panel:
        """Panel untuk state SCANNING"""
        seconds_next = seconds_to_next_5m()
        seconds_passed = seconds_since_5m_start()

        # Countdown progress
        progress = Progress(
            TextColumn("[bold cyan]⏳ Next Window[/bold cyan]"),
            BarColumn(bar_width=40, complete_style="green", finished_style="bold green"),
            TextColumn("[bold]{task.percentage:.0f}%"),
            TextColumn("[{task.fields[time_left]}]"),
            expand=False
        )
        task = progress.add_task("countdown", total=300, completed=seconds_passed, time_left=format_time_left(seconds_next))

        # Indicator table
        ind_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        ind_table.add_column("Indicator", style="bold")
        ind_table.add_column("Value", justify="right")
        ind_table.add_column("Signal", justify="center")

        ind = data.get("indicators", {})
        details = ind.get("details", {})

        signal = ind.get("signal", "NEUTRAL")
        signal_color = {"BUY": "green", "SELL": "red", "NEUTRAL": "yellow"}.get(signal, "white")

        ind_table.add_row("Price", f"${details.get('price', 0):,.2f}", "")
        ind_table.add_row("EMA 9", f"{details.get('ema9', 0):,.2f}", "")
        ind_table.add_row("EMA 21", f"{details.get('ema21', 0):,.2f}", "")
        ind_table.add_row("RSI 14", f"{details.get('rsi', 0):.2f}", "")
        ind_table.add_row("Confidence", f"{details.get('confidence', 0):.0%}", f"[{signal_color}]{signal}[/{signal_color}]")

        # Market info
        market = data.get("market", {})
        market_table = Table(show_header=False, box=None, padding=(0, 1))
        market_table.add_column("Key", style="bold dim")
        market_table.add_column("Value")
        market_table.add_row("Slug", market.get("slug", "-"))
        market_table.add_row("Up Odds", f"${market.get('up_price', 0):.3f}")
        market_table.add_row("Down Odds", f"${market.get('down_price', 0):.3f}")

        content = Group(
            Align.center(progress),
            "",
            Panel(ind_table, title="[bold]Technical Analysis[/bold]", border_style="blue"),
            Panel(market_table, title="[bold]Market Discovery[/bold]", border_style="blue"),
        )

        return Panel(content, title="[bold yellow]🔍 SCANNING MARKET[/bold yellow]", border_style="yellow")

    def _position_panel(self, data: Dict) -> Panel:
        """Panel untuk state POSITION"""
        pos = data.get("position", {})
        market = data.get("market", {})

        # Time elapsed in position
        elapsed = data.get("elapsed_seconds", 0)
        remaining = max(0, 300 - elapsed)

        progress = Progress(
            TextColumn("[bold magenta]⏱️ Position Time[/bold magenta]"),
            BarColumn(bar_width=40, complete_style="green", finished_style="bold red"),
            TextColumn("[bold]{task.percentage:.0f}%"),
            TextColumn("[{task.fields[time_left]} remaining]"),
            expand=False
        )
        task = progress.add_task("position", total=300, completed=elapsed, time_left=format_time_left(remaining))

        pos_table = Table(show_header=False, box=None, padding=(0, 2))
        pos_table.add_column("Key", style="bold cyan")
        pos_table.add_column("Value", style="bold white")

        side = pos.get("side", "-")
        side_color = "green" if side == "UP" else "red"

        pos_table.add_row("Amount Entry", format_usd(pos.get("amount", 0)))
        pos_table.add_row("Direction", f"[{side_color}]{'Buy YES (Up)' if side == 'UP' else 'Buy NO (Down)'}[/{side_color}]")
        pos_table.add_row("Entry Odds", f"${pos.get('entry_odds', 0):.3f}")
        pos_table.add_row("Potential PnL", f"{'+' if side == 'UP' else '-'}${pos.get('amount', 0):.2f}")

        link = market.get("url", "-")

        content = Group(
            Align.center(progress),
            "",
            Panel(pos_table, title="[bold]Position Details[/bold]", border_style="magenta"),
            Panel(f"[link={link}]{link}[/link]", title="[bold]Market Link[/bold]", border_style="blue"),
        )

        return Panel(content, title="[bold magenta]📊 MONITORING POSITION[/bold magenta]", border_style="magenta")

    def _stats_panel(self, stats: Dict, balance: float) -> Panel:
        """Panel statistik trading"""
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        pnl = stats.get("total_pnl", 0)
        pnl_color = "green" if pnl >= 0 else "red"

        table.add_row("Balance", f"[bold cyan]{format_usd(balance)}[/bold cyan]")
        table.add_row("Wins", f"[bold green]{stats['wins']}[/bold green]")
        table.add_row("Losses", f"[bold red]{stats['losses']}[/bold red]")
        table.add_row("Win Rate", f"{stats['win_rate']:.1f}%")
        table.add_row("Total PnL", f"[bold {pnl_color}]{format_usd(pnl)}[/bold {pnl_color}]")
        table.add_row("Total Trades", str(stats["total_trades"]))

        return Panel(table, title="[bold green]💰 Performance[/bold green]", border_style="green")

    def _logs_panel(self, logs: list) -> Panel:
        """Panel log terakhir"""
        text = Text()
        for log in logs[-8:]:
            text.append(f"• {log}\n", style="dim")
        return Panel(text, title="[bold]📝 Logs[/bold]", border_style="dim")

    def render(self, state: str, data: Dict, stats: Dict, balance: float, logs: list, mode: str) -> Layout:
        """Render full UI"""
        self.layout["header"].update(self._header(state, mode))

        if state == "SCANNING":
            self.layout["left"].update(self._scanning_panel(data))
        elif state in ["ENTERING", "POSITION", "REDEEMING"]:
            self.layout["left"].update(self._position_panel(data))
        else:
            self.layout["left"].update(Panel("[dim]Waiting...[/dim]", border_style="dim"))

        right_content = Group(
            self._stats_panel(stats, balance),
            self._logs_panel(logs)
        )
        self.layout["right"].update(right_content)

        # Footer
        footer_text = Text()
        footer_text.append("Strategy: ", style="bold")
        footer_text.append("EMA9/21 + RSI14 | ", style="dim")
        footer_text.append("Odds Filter: ", style="bold")
        footer_text.append("0.45-0.55 | ", style="dim")
        footer_text.append("Max Entry: ", style="bold")
        footer_text.append(f"${data.get('max_entry', 1.0)} | ", style="dim")
        footer_text.append("Press Ctrl+C to exit", style="bold red")
        self.layout["footer"].update(Panel(Align.center(footer_text), border_style="dim"))

        return self.layout
