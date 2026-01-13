"""Modern Polymarket Trading Bot UI.

A redesigned interface with:
- Central chat feed for bot activity
- Market browser in top-right
- Paper trading support
- Insider trading detection
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from functools import partial

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from config_manager import MarketPolicy, SimulatorConfig, ensure_config, load_config, save_config
from engine import AllocationEngine, compute_g
from notification_manager import NotificationManager, NotificationType, Notification
from paper_trader import PaperTrader, PaperPosition, PaperTrade, TradeAction
from insider_detector import InsiderDetector, InsiderAlert, AlertSeverity, analyze_order_book_for_large_orders
from polymarket_api import (
    PolymarketAPIError,
    build_market_snapshot,
    extract_slug,
    fetch_market,
    fetch_order_book,
    get_outcome_descriptor,
    list_outcomes,
    resolve_reference,
    compute_resolution_days,
)
from runtime_state import (
    FreezeStatus,
    MarketState,
    RuntimeState,
    parse_volume,
    extract_parent_event,
    _now,
    _now_iso,
)
from ui_components import (
    Colors,
    MessageType,
    ChatMessage,
    ChatFeed,
    MarketCard,
    StatCard,
    AlertBadge,
    ModernButton,
    SearchEntry,
    configure_dark_theme,
)


# Paths
CONFIG_PATH = Path("config.yaml")
RUNTIME_PATH = Path("runtime_state.json")
PAPER_PATH = Path("paper_portfolio.json")
NOTIFICATIONS_PATH = Path("notifications.json")
INSIDER_PATH = Path("insider_alerts.json")

DEFAULT_BUDGET = 10000.0


def format_currency(value: float) -> str:
    if value >= 0:
        return f"${value:,.2f}"
    return f"-${abs(value):,.2f}"


def format_pct(value: float) -> str:
    if value >= 0:
        return f"+{value:.2f}%"
    return f"{value:.2f}%"


class AddMarketDialog(simpledialog.Dialog):
    """Dialog for adding a market by URL or slug."""
    
    def __init__(self, parent: tk.Widget, title: str = "Add Market"):
        self.market_data: Optional[Dict] = None
        self.selected_outcome: Optional[str] = None
        super().__init__(parent, title=title)
    
    def body(self, master: tk.Widget) -> tk.Widget:
        master.configure(bg=Colors.BG_DARK)
        
        # URL input
        tk.Label(
            master,
            text="Enter Polymarket URL or market slug:",
            font=("Segoe UI", 10),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
        ).pack(anchor="w", padx=10, pady=(10, 5))
        
        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(
            master,
            textvariable=self.url_var,
            font=("Segoe UI", 10),
            width=50,
            bg=Colors.BG_INPUT,
            fg=Colors.TEXT_PRIMARY,
            insertbackground=Colors.TEXT_PRIMARY,
        )
        self.url_entry.pack(fill=tk.X, padx=10, pady=5)
        
        # Fetch button
        fetch_btn = tk.Button(
            master,
            text="Fetch Market",
            command=self._fetch_market,
            bg=Colors.PRIMARY,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            cursor="hand2",
        )
        fetch_btn.pack(pady=10)
        
        # Market info display
        self.info_frame = tk.Frame(master, bg=Colors.BG_DARK)
        self.info_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.info_var = tk.StringVar(value="Enter a URL above and click Fetch")
        tk.Label(
            self.info_frame,
            textvariable=self.info_var,
            font=("Segoe UI", 9),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_SECONDARY,
            wraplength=400,
            justify=tk.LEFT,
        ).pack(anchor="w")
        
        # Outcome selection
        self.outcome_frame = tk.Frame(master, bg=Colors.BG_DARK)
        self.outcome_frame.pack(fill=tk.X, padx=10, pady=5)
        
        return self.url_entry
    
    def _fetch_market(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a URL or slug")
            return
        
        try:
            slug = extract_slug(url)
            ref_type, metadata = resolve_reference(slug)
            
            if ref_type == "event":
                # Get first market from event
                markets = metadata.get("markets", [])
                if not markets:
                    messagebox.showerror("Error", "No markets found in this event")
                    return
                metadata = markets[0]
                slug = metadata.get("slug") or str(metadata.get("id"))
                metadata = fetch_market(slug)
            
            self.market_data = metadata
            
            # Show market info
            question = metadata.get("question", "Unknown")
            end_date = metadata.get("endDate", "Unknown")
            
            try:
                days = compute_resolution_days(end_date)
                days_str = f"{days:.1f} days"
            except Exception:
                days_str = "Unknown"
            
            self.info_var.set(
                f"Question: {question}\n"
                f"Resolution: {days_str}\n"
                f"Select an outcome below:"
            )
            
            # Show outcome options
            for widget in self.outcome_frame.winfo_children():
                widget.destroy()
            
            try:
                outcomes = list_outcomes(metadata)
                self.outcome_var = tk.StringVar(value=outcomes[0].name if outcomes else "")
                
                for outcome in outcomes:
                    price_str = f" (${outcome.last_price:.3f})" if outcome.last_price else ""
                    rb = tk.Radiobutton(
                        self.outcome_frame,
                        text=f"{outcome.name}{price_str}",
                        variable=self.outcome_var,
                        value=outcome.name,
                        bg=Colors.BG_DARK,
                        fg=Colors.TEXT_PRIMARY,
                        selectcolor=Colors.BG_MEDIUM,
                        activebackground=Colors.BG_DARK,
                        activeforeground=Colors.TEXT_PRIMARY,
                        font=("Segoe UI", 10),
                    )
                    rb.pack(anchor="w")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to get outcomes: {e}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch market: {e}")
    
    def buttonbox(self) -> None:
        box = tk.Frame(self, bg=Colors.BG_DARK)
        box.pack(fill=tk.X, pady=10)
        
        tk.Button(
            box,
            text="Add Market",
            command=self.ok,
            bg=Colors.SUCCESS,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            width=12,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(10, 5))
        
        tk.Button(
            box,
            text="Cancel",
            command=self.cancel,
            bg=Colors.BG_LIGHT,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            width=12,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=5)
    
    def validate(self) -> bool:
        if not self.market_data:
            messagebox.showerror("Error", "Please fetch a market first")
            return False
        if hasattr(self, 'outcome_var'):
            self.selected_outcome = self.outcome_var.get()
        return True
    
    def apply(self) -> None:
        self.result = (self.market_data, self.selected_outcome)


class PaperTradeDialog(simpledialog.Dialog):
    """Dialog for executing a paper trade."""
    
    def __init__(
        self,
        parent: tk.Widget,
        market_id: str,
        question: str,
        outcome: str,
        current_price: float,
        order_book: Dict,
        position: Optional[PaperPosition] = None,
    ):
        self.market_id = market_id
        self.question = question
        self.outcome = outcome
        self.current_price = current_price
        self.order_book = order_book
        self.position = position
        self.trade_result: Optional[Tuple[str, float, float]] = None  # (action, shares, price)
        
        super().__init__(parent, title="Paper Trade")
    
    def body(self, master: tk.Widget) -> tk.Widget:
        master.configure(bg=Colors.BG_DARK)
        
        # Market info
        tk.Label(
            master,
            text=self.question[:60] + "..." if len(self.question) > 60 else self.question,
            font=("Segoe UI", 11, "bold"),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            wraplength=350,
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        tk.Label(
            master,
            text=f"Outcome: {self.outcome}  |  Price: ${self.current_price:.3f}",
            font=("Segoe UI", 10),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_SECONDARY,
        ).pack(anchor="w", padx=15, pady=(0, 10))
        
        # Current position
        if self.position:
            pos_frame = tk.Frame(master, bg=Colors.BG_CARD)
            pos_frame.pack(fill=tk.X, padx=15, pady=5)
            
            tk.Label(
                pos_frame,
                text=f"Current Position: {self.position.shares:.2f} shares @ ${self.position.average_price:.3f}",
                font=("Segoe UI", 10),
                bg=Colors.BG_CARD,
                fg=Colors.TEXT_PRIMARY,
                padx=10,
                pady=8,
            ).pack(anchor="w")
            
            pnl_color = Colors.PROFIT if self.position.unrealized_pnl >= 0 else Colors.LOSS
            tk.Label(
                pos_frame,
                text=f"Unrealized P&L: {format_currency(self.position.unrealized_pnl)} ({self.position.unrealized_pnl_pct:.1f}%)",
                font=("Segoe UI", 10),
                bg=Colors.BG_CARD,
                fg=pnl_color,
                padx=10,
                pady=(0, 8),
            ).pack(anchor="w")
        
        # Trade type
        type_frame = tk.Frame(master, bg=Colors.BG_DARK)
        type_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.trade_type = tk.StringVar(value="buy")
        
        tk.Radiobutton(
            type_frame,
            text="Buy",
            variable=self.trade_type,
            value="buy",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            selectcolor=Colors.BG_MEDIUM,
            activebackground=Colors.BG_DARK,
            font=("Segoe UI", 10),
            command=self._update_preview,
        ).pack(side=tk.LEFT, padx=(0, 20))
        
        tk.Radiobutton(
            type_frame,
            text="Sell",
            variable=self.trade_type,
            value="sell",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            selectcolor=Colors.BG_MEDIUM,
            activebackground=Colors.BG_DARK,
            font=("Segoe UI", 10),
            state=tk.NORMAL if self.position else tk.DISABLED,
            command=self._update_preview,
        ).pack(side=tk.LEFT)
        
        # Amount input
        amount_frame = tk.Frame(master, bg=Colors.BG_DARK)
        amount_frame.pack(fill=tk.X, padx=15, pady=5)
        
        tk.Label(
            amount_frame,
            text="Amount ($):",
            font=("Segoe UI", 10),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        self.amount_var = tk.StringVar(value="100")
        self.amount_entry = tk.Entry(
            amount_frame,
            textvariable=self.amount_var,
            font=("Segoe UI", 10),
            width=15,
            bg=Colors.BG_INPUT,
            fg=Colors.TEXT_PRIMARY,
            insertbackground=Colors.TEXT_PRIMARY,
        )
        self.amount_entry.pack(side=tk.LEFT, padx=10)
        self.amount_var.trace_add("write", lambda *_: self._update_preview())
        
        # Preview
        self.preview_var = tk.StringVar(value="")
        tk.Label(
            master,
            textvariable=self.preview_var,
            font=("Segoe UI", 10),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_SECONDARY,
            wraplength=350,
        ).pack(anchor="w", padx=15, pady=10)
        
        self._update_preview()
        return self.amount_entry
    
    def _update_preview(self) -> None:
        try:
            amount = float(self.amount_var.get())
        except ValueError:
            self.preview_var.set("Enter a valid amount")
            return
        
        if self.trade_type.get() == "buy":
            asks = self.order_book.get("asks", [])
            if asks:
                best_ask = asks[0][0]
                shares = amount / best_ask
                self.preview_var.set(f"Preview: Buy ~{shares:.2f} shares at ~${best_ask:.3f}")
            else:
                self.preview_var.set("No asks available")
        else:
            if self.position:
                bids = self.order_book.get("bids", [])
                if bids:
                    best_bid = bids[0][0]
                    shares_to_sell = min(amount / best_bid, self.position.shares)
                    proceeds = shares_to_sell * best_bid
                    self.preview_var.set(f"Preview: Sell ~{shares_to_sell:.2f} shares for ~${proceeds:.2f}")
                else:
                    self.preview_var.set("No bids available")
            else:
                self.preview_var.set("No position to sell")
    
    def buttonbox(self) -> None:
        box = tk.Frame(self, bg=Colors.BG_DARK)
        box.pack(fill=tk.X, pady=10)
        
        tk.Button(
            box,
            text="Execute Trade",
            command=self.ok,
            bg=Colors.SUCCESS,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            width=14,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(15, 5))
        
        tk.Button(
            box,
            text="Cancel",
            command=self.cancel,
            bg=Colors.BG_LIGHT,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            width=10,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=5)
    
    def validate(self) -> bool:
        try:
            amount = float(self.amount_var.get())
            if amount <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive amount")
            return False
        return True
    
    def apply(self) -> None:
        amount = float(self.amount_var.get())
        action = self.trade_type.get()
        
        if action == "buy":
            asks = self.order_book.get("asks", [])
            price = asks[0][0] if asks else self.current_price
            shares = amount / price
        else:
            bids = self.order_book.get("bids", [])
            price = bids[0][0] if bids else self.current_price
            shares = min(amount / price, self.position.shares if self.position else 0)
        
        self.result = (action, shares, price)


class ModernTradingApp(tk.Tk):
    """Modern Polymarket Trading Bot UI."""
    
    def __init__(self):
        super().__init__()
        
        self.title("Polymarket Trading Bot")
        self.geometry("1400x900")
        self.configure(bg=Colors.BG_DARK)
        self.minsize(1200, 700)
        
        # Apply theme
        self.style = configure_dark_theme(self)
        
        # Initialize components
        self.config = ensure_config(CONFIG_PATH)
        self.notifications = NotificationManager(NOTIFICATIONS_PATH)
        self.paper_trader = PaperTrader(PAPER_PATH, initial_capital=DEFAULT_BUDGET)
        self.insider_detector = InsiderDetector(storage_path=INSIDER_PATH)
        
        # Runtime state (for live/dry-run mode)
        self.state: Optional[RuntimeState] = None
        if RUNTIME_PATH.exists():
            try:
                self.state = RuntimeState.load(RUNTIME_PATH)
            except Exception:
                pass
        
        # Trading mode
        self.trading_mode = tk.StringVar(value="paper")  # paper, dry_run, live
        self.is_polling = False
        self.poll_interval = 30  # seconds
        
        # Market data cache
        self.markets: Dict[str, Dict] = {}  # market_key -> market data
        
        # Setup listeners
        self.notifications.add_listener(self._on_notification)
        self.insider_detector.add_listener(self._on_insider_alert)
        
        # Build UI
        self._build_ui()
        
        # Welcome message
        self.chat_feed.add_message(ChatMessage(
            message="Welcome to Polymarket Trading Bot! Add markets to start monitoring.",
            msg_type=MessageType.SYSTEM,
            title="System",
        ))
        
        # Load existing markets
        self._load_markets_from_state()
        
        # Start polling
        self._start_polling()
    
    def _build_ui(self) -> None:
        """Build the main UI layout."""
        # Top bar
        self._build_top_bar()
        
        # Main content area
        main_container = tk.Frame(self, bg=Colors.BG_DARK)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Left panel - Chat feed (60% width)
        left_panel = tk.Frame(main_container, bg=Colors.BG_DARK)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.chat_feed = ChatFeed(left_panel)
        self.chat_feed.pack(fill=tk.BOTH, expand=True)
        
        # Right panel - Markets and controls (40% width)
        right_panel = tk.Frame(main_container, bg=Colors.BG_DARK, width=500)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(5, 0))
        right_panel.pack_propagate(False)
        
        self._build_right_panel(right_panel)
    
    def _build_top_bar(self) -> None:
        """Build the top navigation bar."""
        top_bar = tk.Frame(self, bg=Colors.BG_MEDIUM, height=60)
        top_bar.pack(fill=tk.X, padx=0, pady=0)
        top_bar.pack_propagate(False)
        
        # Logo/Title
        tk.Label(
            top_bar,
            text="🚀 Polymarket Bot",
            font=("Segoe UI", 16, "bold"),
            bg=Colors.BG_MEDIUM,
            fg=Colors.TEXT_PRIMARY,
        ).pack(side=tk.LEFT, padx=20, pady=15)
        
        # Mode selector
        mode_frame = tk.Frame(top_bar, bg=Colors.BG_MEDIUM)
        mode_frame.pack(side=tk.LEFT, padx=20)
        
        tk.Label(
            mode_frame,
            text="Mode:",
            font=("Segoe UI", 10),
            bg=Colors.BG_MEDIUM,
            fg=Colors.TEXT_SECONDARY,
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        modes = [("Paper", "paper"), ("Dry Run", "dry_run"), ("Live", "live")]
        for text, value in modes:
            rb = tk.Radiobutton(
                mode_frame,
                text=text,
                variable=self.trading_mode,
                value=value,
                bg=Colors.BG_MEDIUM,
                fg=Colors.TEXT_PRIMARY,
                selectcolor=Colors.BG_LIGHT,
                activebackground=Colors.BG_MEDIUM,
                font=("Segoe UI", 10),
                command=self._on_mode_change,
            )
            rb.pack(side=tk.LEFT, padx=5)
        
        # Right side controls
        controls_frame = tk.Frame(top_bar, bg=Colors.BG_MEDIUM)
        controls_frame.pack(side=tk.RIGHT, padx=20)
        
        # Alerts button with badge
        alerts_btn_frame = tk.Frame(controls_frame, bg=Colors.BG_MEDIUM)
        alerts_btn_frame.pack(side=tk.LEFT, padx=5)
        
        alerts_btn = tk.Button(
            alerts_btn_frame,
            text="🔔 Alerts",
            command=self._show_alerts,
            bg=Colors.BG_LIGHT,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            cursor="hand2",
        )
        alerts_btn.pack()
        
        self.alert_badge = AlertBadge(alerts_btn_frame, count=0)
        self.alert_badge.place(relx=1.0, rely=0, anchor="ne")
        
        # Settings button
        tk.Button(
            controls_frame,
            text="⚙️ Settings",
            command=self._show_settings,
            bg=Colors.BG_LIGHT,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=5)
    
    def _build_right_panel(self, parent: tk.Frame) -> None:
        """Build the right panel with markets and stats."""
        # Portfolio stats
        stats_frame = tk.Frame(parent, bg=Colors.BG_DARK)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Row of stat cards
        stats_row = tk.Frame(stats_frame, bg=Colors.BG_DARK)
        stats_row.pack(fill=tk.X)
        
        self.stat_portfolio = StatCard(
            stats_row,
            title="Portfolio Value",
            value="$10,000.00",
            subtitle="Paper Trading",
            color=Colors.TEXT_PRIMARY,
        )
        self.stat_portfolio.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.stat_pnl = StatCard(
            stats_row,
            title="Total P&L",
            value="$0.00",
            subtitle="0.00%",
            color=Colors.TEXT_PRIMARY,
        )
        self.stat_pnl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Markets section
        markets_header = tk.Frame(parent, bg=Colors.BG_DARK)
        markets_header.pack(fill=tk.X, pady=(10, 5))
        
        tk.Label(
            markets_header,
            text="📊 Tracked Markets",
            font=("Segoe UI", 12, "bold"),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        ModernButton(
            markets_header,
            text="Add",
            icon="➕",
            style="primary",
            command=self._add_market,
        ).pack(side=tk.RIGHT)
        
        ModernButton(
            markets_header,
            text="Refresh",
            icon="🔄",
            style="secondary",
            command=self._refresh_all_markets,
        ).pack(side=tk.RIGHT, padx=(0, 5))
        
        # Markets list
        markets_container = tk.Frame(parent, bg=Colors.BG_DARK)
        markets_container.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Canvas with scrollbar for markets
        self.markets_canvas = tk.Canvas(
            markets_container,
            bg=Colors.BG_DARK,
            highlightthickness=0,
            borderwidth=0,
        )
        markets_scrollbar = ttk.Scrollbar(
            markets_container,
            orient="vertical",
            command=self.markets_canvas.yview
        )
        
        self.markets_frame = tk.Frame(self.markets_canvas, bg=Colors.BG_DARK)
        
        self.markets_canvas_window = self.markets_canvas.create_window(
            (0, 0),
            window=self.markets_frame,
            anchor="nw",
        )
        
        self.markets_canvas.configure(yscrollcommand=markets_scrollbar.set)
        
        markets_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.markets_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.markets_frame.bind("<Configure>", lambda e: self.markets_canvas.configure(
            scrollregion=self.markets_canvas.bbox("all")
        ))
        self.markets_canvas.bind("<Configure>", lambda e: self.markets_canvas.itemconfig(
            self.markets_canvas_window, width=e.width
        ))
        
        # Positions section
        positions_header = tk.Frame(parent, bg=Colors.BG_DARK)
        positions_header.pack(fill=tk.X, pady=(10, 5))
        
        tk.Label(
            positions_header,
            text="💼 Open Positions",
            font=("Segoe UI", 12, "bold"),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        # Positions list
        self.positions_frame = tk.Frame(parent, bg=Colors.BG_DARK)
        self.positions_frame.pack(fill=tk.X, pady=5)
        
        self._update_positions_display()
    
    def _on_mode_change(self) -> None:
        """Handle trading mode change."""
        mode = self.trading_mode.get()
        mode_names = {"paper": "Paper Trading", "dry_run": "Dry Run", "live": "Live Trading"}
        
        self.chat_feed.add_message(ChatMessage(
            message=f"Switched to {mode_names[mode]} mode",
            msg_type=MessageType.SYSTEM,
            title="Mode Change",
        ))
        
        if mode == "live":
            messagebox.showwarning(
                "Warning",
                "Live trading will use real funds! Make sure you understand the risks."
            )
        
        self._update_stats()
    
    def _on_notification(self, notification: Notification) -> None:
        """Handle new notifications."""
        msg_type = {
            NotificationType.INFO: MessageType.BOT,
            NotificationType.SUCCESS: MessageType.SUCCESS,
            NotificationType.WARNING: MessageType.ALERT,
            NotificationType.ERROR: MessageType.ERROR,
            NotificationType.TRADE: MessageType.TRADE,
            NotificationType.INSIDER_ALERT: MessageType.ALERT,
            NotificationType.MARKET_UPDATE: MessageType.BOT,
            NotificationType.SYSTEM: MessageType.SYSTEM,
        }.get(notification.type, MessageType.BOT)
        
        self.chat_feed.add_message(ChatMessage(
            message=notification.message,
            msg_type=msg_type,
            title=notification.title,
            timestamp=notification.timestamp.split("T")[1].split(".")[0] if "T" in notification.timestamp else notification.timestamp,
        ))
    
    def _on_insider_alert(self, alert: InsiderAlert) -> None:
        """Handle insider trading alerts."""
        self.alert_badge.set_count(self.insider_detector.get_unacknowledged_count())
        
        severity_emoji = {
            AlertSeverity.LOW: "ℹ️",
            AlertSeverity.MEDIUM: "⚠️",
            AlertSeverity.HIGH: "🚨",
            AlertSeverity.CRITICAL: "🔴",
        }
        
        self.chat_feed.add_message(ChatMessage(
            message=f"{severity_emoji.get(alert.severity, '⚠️')} {alert.reason}\n"
                    f"Market: {alert.market_question[:50]}...\n"
                    f"Trade: ${alert.trade_size:,.0f} {alert.trade_side}",
            msg_type=MessageType.ALERT,
            title="Insider Alert",
        ))
        
        self.notifications.insider_alert(
            title="Potential Insider Activity",
            message=alert.reason,
            data=alert.to_dict(),
        )
    
    def _add_market(self) -> None:
        """Add a new market to track."""
        dialog = AddMarketDialog(self)
        
        if dialog.result:
            metadata, outcome_name = dialog.result
            
            try:
                # Get outcome details
                descriptor = get_outcome_descriptor(metadata, outcome_name)
                snapshot = build_market_snapshot(metadata, descriptor)
                
                # Create market key
                market_key = f"{snapshot.market_id}|{descriptor.name}"
                
                if market_key in self.markets:
                    messagebox.showinfo("Info", "This market is already being tracked")
                    return
                
                # Store market data
                self.markets[market_key] = {
                    "market_id": snapshot.market_id,
                    "question": snapshot.question,
                    "outcome": descriptor.name,
                    "token_id": descriptor.token_id,
                    "resolution_datetime": snapshot.resolution_datetime.isoformat(),
                    "resolution_days": snapshot.resolution_days,
                    "metadata": metadata,
                    "order_book": snapshot.order_book,
                    "best_ask": snapshot.order_book["asks"][0][0] if snapshot.order_book.get("asks") else None,
                    "best_bid": snapshot.order_book["bids"][0][0] if snapshot.order_book.get("bids") else None,
                    "last_price": descriptor.last_price,
                    "volume": parse_volume(metadata),
                    "last_update": _now_iso(),
                }
                
                # Add to insider detector
                self.insider_detector.add_market(
                    snapshot.market_id,
                    snapshot.question,
                    descriptor.token_id,
                )
                
                self._update_markets_display()
                
                self.chat_feed.add_message(ChatMessage(
                    message=f"Added market: {snapshot.question[:50]}... ({descriptor.name})",
                    msg_type=MessageType.SUCCESS,
                    title="Market Added",
                ))
                
                self._save_markets()
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add market: {e}")
    
    def _remove_market(self, market_key: str) -> None:
        """Remove a market from tracking."""
        if market_key in self.markets:
            market = self.markets[market_key]
            del self.markets[market_key]
            self._update_markets_display()
            
            self.chat_feed.add_message(ChatMessage(
                message=f"Removed market: {market['question'][:50]}...",
                msg_type=MessageType.SYSTEM,
                title="Market Removed",
            ))
            
            self._save_markets()
    
    def _on_market_click(self, market_key: str) -> None:
        """Handle market card click."""
        if market_key not in self.markets:
            return
        
        market = self.markets[market_key]
        position = self.paper_trader.get_position(market["market_id"], market["outcome"])
        
        # Show trade dialog
        dialog = PaperTradeDialog(
            self,
            market_id=market["market_id"],
            question=market["question"],
            outcome=market["outcome"],
            current_price=market.get("best_ask") or market.get("last_price") or 0.5,
            order_book=market.get("order_book", {}),
            position=position,
        )
        
        if dialog.result:
            action, shares, price = dialog.result
            
            if action == "buy":
                success, message, trade = self.paper_trader.buy(
                    market_id=market["market_id"],
                    outcome=market["outcome"],
                    question=market["question"],
                    shares=shares,
                    price=price,
                    resolution_datetime=market.get("resolution_datetime"),
                )
            else:
                success, message, trade = self.paper_trader.sell(
                    market_id=market["market_id"],
                    outcome=market["outcome"],
                    shares=shares,
                    price=price,
                )
            
            if success:
                self.chat_feed.add_message(ChatMessage(
                    message=message,
                    msg_type=MessageType.TRADE,
                    title=f"Paper {action.title()}",
                ))
                
                self._update_stats()
                self._update_positions_display()
            else:
                messagebox.showerror("Trade Failed", message)
    
    def _refresh_all_markets(self) -> None:
        """Refresh all market data."""
        self.chat_feed.add_message(ChatMessage(
            message="Refreshing market data...",
            msg_type=MessageType.SYSTEM,
            title="Refresh",
        ))
        
        def refresh_thread():
            updated = 0
            for market_key, market in list(self.markets.items()):
                try:
                    token_id = market.get("token_id")
                    if token_id:
                        order_book = fetch_order_book(token_id)
                        
                        old_price = market.get("best_ask")
                        new_price = order_book["asks"][0][0] if order_book.get("asks") else None
                        
                        market["order_book"] = order_book
                        market["best_ask"] = new_price
                        market["best_bid"] = order_book["bids"][0][0] if order_book.get("bids") else None
                        market["last_update"] = _now_iso()
                        
                        # Check for large orders (insider detection)
                        suspicious = analyze_order_book_for_large_orders(order_book, 10000)
                        for order in suspicious:
                            self.insider_detector.analyze_trade(
                                market_id=market["market_id"],
                                market_question=market["question"],
                                trader_address="unknown",
                                trade_size=order["value"],
                                trade_side=order["side"],
                                outcome=market["outcome"],
                                price=order["price"],
                            )
                        
                        # Update paper positions
                        self.paper_trader.update_position_prices(
                            market["market_id"],
                            market["outcome"],
                            current_price=new_price,
                            current_bid=market["best_bid"],
                            current_ask=new_price,
                        )
                        
                        updated += 1
                except Exception as e:
                    print(f"Failed to refresh {market_key}: {e}")
            
            # Update UI from main thread
            self.after(0, lambda: self._on_refresh_complete(updated))
        
        threading.Thread(target=refresh_thread, daemon=True).start()
    
    def _on_refresh_complete(self, count: int) -> None:
        """Called when refresh is complete."""
        self._update_markets_display()
        self._update_stats()
        self._update_positions_display()
        
        self.chat_feed.add_message(ChatMessage(
            message=f"Refreshed {count} markets",
            msg_type=MessageType.SUCCESS,
            title="Refresh Complete",
        ))
    
    def _update_markets_display(self) -> None:
        """Update the markets list display."""
        # Clear existing
        for widget in self.markets_frame.winfo_children():
            widget.destroy()
        
        if not self.markets:
            tk.Label(
                self.markets_frame,
                text="No markets tracked yet.\nClick 'Add' to add a market.",
                font=("Segoe UI", 10),
                bg=Colors.BG_DARK,
                fg=Colors.TEXT_MUTED,
                pady=20,
            ).pack()
            return
        
        for market_key, market in self.markets.items():
            card_frame = tk.Frame(self.markets_frame, bg=Colors.BG_CARD)
            card_frame.pack(fill=tk.X, pady=3)
            
            # Make clickable
            card_frame.bind("<Button-1>", lambda e, k=market_key: self._on_market_click(k))
            card_frame.bind("<Enter>", lambda e, f=card_frame: f.configure(bg=Colors.BG_LIGHT))
            card_frame.bind("<Leave>", lambda e, f=card_frame: f.configure(bg=Colors.BG_CARD))
            
            inner = tk.Frame(card_frame, bg=Colors.BG_CARD)
            inner.pack(fill=tk.X, padx=10, pady=8)
            inner.bind("<Button-1>", lambda e, k=market_key: self._on_market_click(k))
            
            # Question
            q_label = tk.Label(
                inner,
                text=market["question"][:45] + "..." if len(market["question"]) > 45 else market["question"],
                font=("Segoe UI", 10, "bold"),
                bg=Colors.BG_CARD,
                fg=Colors.TEXT_PRIMARY,
                anchor="w",
                cursor="hand2",
            )
            q_label.pack(fill=tk.X)
            q_label.bind("<Button-1>", lambda e, k=market_key: self._on_market_click(k))
            
            # Details row
            details = tk.Frame(inner, bg=Colors.BG_CARD)
            details.pack(fill=tk.X, pady=(4, 0))
            details.bind("<Button-1>", lambda e, k=market_key: self._on_market_click(k))
            
            # Outcome badge
            badge = tk.Label(
                details,
                text=market["outcome"],
                font=("Segoe UI", 8),
                bg=Colors.PRIMARY,
                fg=Colors.TEXT_PRIMARY,
                padx=4,
                pady=1,
            )
            badge.pack(side=tk.LEFT)
            
            # Price
            price = market.get("best_ask") or market.get("last_price") or 0
            tk.Label(
                details,
                text=f"${price:.3f}",
                font=("Segoe UI", 10, "bold"),
                bg=Colors.BG_CARD,
                fg=Colors.TEXT_PRIMARY,
            ).pack(side=tk.LEFT, padx=(10, 0))
            
            # Remove button
            remove_btn = tk.Label(
                details,
                text="✕",
                font=("Segoe UI", 10),
                bg=Colors.BG_CARD,
                fg=Colors.TEXT_MUTED,
                cursor="hand2",
            )
            remove_btn.pack(side=tk.RIGHT)
            remove_btn.bind("<Button-1>", lambda e, k=market_key: self._remove_market(k))
            remove_btn.bind("<Enter>", lambda e, l=remove_btn: l.configure(fg=Colors.ERROR))
            remove_btn.bind("<Leave>", lambda e, l=remove_btn: l.configure(fg=Colors.TEXT_MUTED))
    
    def _update_positions_display(self) -> None:
        """Update the positions display."""
        # Clear existing
        for widget in self.positions_frame.winfo_children():
            widget.destroy()
        
        positions = self.paper_trader.get_all_positions()
        
        if not positions:
            tk.Label(
                self.positions_frame,
                text="No open positions",
                font=("Segoe UI", 9),
                bg=Colors.BG_DARK,
                fg=Colors.TEXT_MUTED,
            ).pack(pady=5)
            return
        
        for pos in positions:
            pos_frame = tk.Frame(self.positions_frame, bg=Colors.BG_CARD)
            pos_frame.pack(fill=tk.X, pady=2)
            
            inner = tk.Frame(pos_frame, bg=Colors.BG_CARD)
            inner.pack(fill=tk.X, padx=8, pady=6)
            
            # Question
            tk.Label(
                inner,
                text=pos.question[:40] + "..." if len(pos.question) > 40 else pos.question,
                font=("Segoe UI", 9),
                bg=Colors.BG_CARD,
                fg=Colors.TEXT_PRIMARY,
                anchor="w",
            ).pack(fill=tk.X)
            
            # Details
            details = tk.Frame(inner, bg=Colors.BG_CARD)
            details.pack(fill=tk.X, pady=(2, 0))
            
            tk.Label(
                details,
                text=f"{pos.shares:.1f} @ ${pos.average_price:.3f}",
                font=("Segoe UI", 8),
                bg=Colors.BG_CARD,
                fg=Colors.TEXT_SECONDARY,
            ).pack(side=tk.LEFT)
            
            pnl_color = Colors.PROFIT if pos.unrealized_pnl >= 0 else Colors.LOSS
            pnl_text = format_currency(pos.unrealized_pnl)
            tk.Label(
                details,
                text=f"{pnl_text} ({pos.unrealized_pnl_pct:+.1f}%)",
                font=("Segoe UI", 8, "bold"),
                bg=Colors.BG_CARD,
                fg=pnl_color,
            ).pack(side=tk.RIGHT)
    
    def _update_stats(self) -> None:
        """Update portfolio statistics."""
        summary = self.paper_trader.get_summary()
        
        self.stat_portfolio.update(
            value=format_currency(summary["total_value"]),
            subtitle=f"Cash: {format_currency(summary['cash_balance'])}",
        )
        
        pnl = summary["total_pnl"]
        pnl_pct = summary["total_pnl_pct"]
        pnl_color = Colors.PROFIT if pnl >= 0 else Colors.LOSS
        
        self.stat_pnl.update(
            value=format_currency(pnl),
            subtitle=format_pct(pnl_pct),
            color=pnl_color,
        )
    
    def _show_alerts(self) -> None:
        """Show alerts dialog."""
        alerts_window = tk.Toplevel(self)
        alerts_window.title("Insider Trading Alerts")
        alerts_window.geometry("600x500")
        alerts_window.configure(bg=Colors.BG_DARK)
        
        # Header
        header = tk.Frame(alerts_window, bg=Colors.BG_MEDIUM)
        header.pack(fill=tk.X)
        
        tk.Label(
            header,
            text="🚨 Insider Trading Alerts",
            font=("Segoe UI", 14, "bold"),
            bg=Colors.BG_MEDIUM,
            fg=Colors.TEXT_PRIMARY,
            pady=15,
            padx=15,
        ).pack(side=tk.LEFT)
        
        tk.Button(
            header,
            text="Acknowledge All",
            command=lambda: [self.insider_detector.acknowledge_all(), self.alert_badge.set_count(0)],
            bg=Colors.PRIMARY,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 9),
            relief=tk.FLAT,
        ).pack(side=tk.RIGHT, padx=15, pady=10)
        
        # Alerts list
        alerts_frame = tk.Frame(alerts_window, bg=Colors.BG_DARK)
        alerts_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        alerts = self.insider_detector.get_alerts(limit=50)
        
        if not alerts:
            tk.Label(
                alerts_frame,
                text="No alerts yet. Alerts will appear here when suspicious activity is detected.",
                font=("Segoe UI", 10),
                bg=Colors.BG_DARK,
                fg=Colors.TEXT_MUTED,
                pady=50,
            ).pack()
        else:
            canvas = tk.Canvas(alerts_frame, bg=Colors.BG_DARK, highlightthickness=0)
            scrollbar = ttk.Scrollbar(alerts_frame, orient="vertical", command=canvas.yview)
            scroll_frame = tk.Frame(canvas, bg=Colors.BG_DARK)
            
            canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            
            for alert in alerts:
                severity_colors = {
                    AlertSeverity.LOW: Colors.INFO,
                    AlertSeverity.MEDIUM: Colors.WARNING,
                    AlertSeverity.HIGH: Colors.ERROR,
                    AlertSeverity.CRITICAL: "#dc2626",
                }
                
                alert_card = tk.Frame(scroll_frame, bg=Colors.BG_CARD)
                alert_card.pack(fill=tk.X, pady=3, padx=5)
                
                inner = tk.Frame(alert_card, bg=Colors.BG_CARD)
                inner.pack(fill=tk.X, padx=10, pady=8)
                
                # Severity indicator
                tk.Label(
                    inner,
                    text=f"● {alert.severity.value.upper()}",
                    font=("Segoe UI", 9, "bold"),
                    bg=Colors.BG_CARD,
                    fg=severity_colors.get(alert.severity, Colors.WARNING),
                ).pack(anchor="w")
                
                # Reason
                tk.Label(
                    inner,
                    text=alert.reason,
                    font=("Segoe UI", 10),
                    bg=Colors.BG_CARD,
                    fg=Colors.TEXT_PRIMARY,
                    wraplength=500,
                    justify=tk.LEFT,
                ).pack(anchor="w", pady=(2, 0))
                
                # Market
                tk.Label(
                    inner,
                    text=f"Market: {alert.market_question[:50]}...",
                    font=("Segoe UI", 9),
                    bg=Colors.BG_CARD,
                    fg=Colors.TEXT_SECONDARY,
                ).pack(anchor="w", pady=(2, 0))
                
                # Timestamp
                tk.Label(
                    inner,
                    text=alert.timestamp,
                    font=("Segoe UI", 8),
                    bg=Colors.BG_CARD,
                    fg=Colors.TEXT_MUTED,
                ).pack(anchor="w")
    
    def _show_settings(self) -> None:
        """Show settings dialog."""
        settings_window = tk.Toplevel(self)
        settings_window.title("Settings")
        settings_window.geometry("500x600")
        settings_window.configure(bg=Colors.BG_DARK)
        
        # Header
        tk.Label(
            settings_window,
            text="⚙️ Settings",
            font=("Segoe UI", 16, "bold"),
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            pady=20,
        ).pack()
        
        # Paper Trading section
        paper_frame = tk.LabelFrame(
            settings_window,
            text="Paper Trading",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10, "bold"),
        )
        paper_frame.pack(fill=tk.X, padx=20, pady=10)
        
        summary = self.paper_trader.get_summary()
        
        tk.Label(
            paper_frame,
            text=f"Initial Capital: {format_currency(summary['initial_capital'])}",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=10, pady=5)
        
        tk.Label(
            paper_frame,
            text=f"Total Trades: {summary['total_trades']}  |  Win Rate: {summary['win_rate']:.1f}%",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_SECONDARY,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=10, pady=2)
        
        def reset_paper():
            if messagebox.askyesno("Confirm", "Reset paper trading portfolio? This cannot be undone."):
                self.paper_trader.reset(DEFAULT_BUDGET)
                self._update_stats()
                self._update_positions_display()
                self.chat_feed.add_message(ChatMessage(
                    message="Paper trading portfolio has been reset",
                    msg_type=MessageType.SYSTEM,
                    title="Reset",
                ))
                settings_window.destroy()
        
        tk.Button(
            paper_frame,
            text="Reset Portfolio",
            command=reset_paper,
            bg=Colors.ERROR,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 9),
            relief=tk.FLAT,
        ).pack(pady=10)
        
        # Insider Detection section
        insider_frame = tk.LabelFrame(
            settings_window,
            text="Insider Detection",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10, "bold"),
        )
        insider_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(
            insider_frame,
            text=f"Large trade threshold: ${self.insider_detector.config.large_trade_threshold:,.0f}",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=10, pady=5)
        
        tk.Label(
            insider_frame,
            text=f"New account threshold: {self.insider_detector.config.new_account_days} days",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_SECONDARY,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=10, pady=2)
        
        # Data section
        data_frame = tk.LabelFrame(
            settings_window,
            text="Data Management",
            bg=Colors.BG_DARK,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 10, "bold"),
        )
        data_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Button(
            data_frame,
            text="Export Trade History",
            command=self._export_trades,
            bg=Colors.PRIMARY,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 9),
            relief=tk.FLAT,
        ).pack(pady=10)
        
        tk.Button(
            data_frame,
            text="Clear All Alerts",
            command=lambda: [self.insider_detector.clear_all(), self.alert_badge.set_count(0)],
            bg=Colors.BG_LIGHT,
            fg=Colors.TEXT_PRIMARY,
            font=("Segoe UI", 9),
            relief=tk.FLAT,
        ).pack(pady=5)
    
    def _export_trades(self) -> None:
        """Export paper trade history to CSV."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfilename="paper_trades.csv",
        )
        
        if filepath:
            try:
                trades = self.paper_trader.get_trade_history(limit=1000)
                
                with open(filepath, "w") as f:
                    f.write("timestamp,action,market_id,outcome,shares,price,value,pnl\n")
                    for trade in reversed(trades):
                        f.write(f"{trade.timestamp},{trade.action.value},{trade.market_id},"
                                f"{trade.outcome},{trade.shares:.4f},{trade.price:.4f},"
                                f"{trade.value:.2f},{trade.pnl or ''}\n")
                
                messagebox.showinfo("Success", f"Exported {len(trades)} trades to {filepath}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export: {e}")
    
    def _start_polling(self) -> None:
        """Start background polling for market updates."""
        self.is_polling = True
        self._poll_markets()
    
    def _poll_markets(self) -> None:
        """Poll markets for updates."""
        if not self.is_polling:
            return
        
        # Run refresh in background
        if self.markets:
            self._refresh_all_markets()
        
        # Schedule next poll
        self.after(self.poll_interval * 1000, self._poll_markets)
    
    def _load_markets_from_state(self) -> None:
        """Load markets from saved state."""
        markets_file = Path("tracked_markets.json")
        if markets_file.exists():
            try:
                self.markets = json.loads(markets_file.read_text())
                self._update_markets_display()
            except Exception:
                pass
    
    def _save_markets(self) -> None:
        """Save tracked markets to file."""
        markets_file = Path("tracked_markets.json")
        try:
            markets_file.write_text(json.dumps(self.markets, indent=2, default=str))
        except Exception:
            pass
    
    def destroy(self) -> None:
        """Clean up on close."""
        self.is_polling = False
        self._save_markets()
        super().destroy()


def main():
    """Entry point for the application."""
    app = ModernTradingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
