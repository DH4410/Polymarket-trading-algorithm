"""Improved Modern Polymarket Trading Bot UI v2.

Features:
- Smoother UI with better responsiveness
- Central chat feed for bot activity
- Auto-trading mode with market scanning
- Bot evaluates markets and decides whether to trade
- Real-time P&L tracking
- Insider detection focused on small markets
"""

from __future__ import annotations

import json
import threading
import time
import queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config_manager import SimulatorConfig, ensure_config
from notification_manager import NotificationManager, NotificationType
from auto_trader import AutoTradingBot, BotConfig, BotDecision, MarketOpportunity, BotTrade
from insider_detector import InsiderDetector, InsiderAlert, AlertSeverity, InsiderDetectorConfig
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
from runtime_state import parse_volume, extract_parent_event, _now_iso

# Try to import news analyzer
try:
    from news_analyzer import NewsAnalyzer, MarketCategory, get_market_category_display
    NEWS_ANALYZER_AVAILABLE = True
except ImportError:
    NEWS_ANALYZER_AVAILABLE = False


# Paths
CONFIG_PATH = Path("config.yaml")
BOT_STATE_PATH = Path("bot_state.json")
NOTIFICATIONS_PATH = Path("notifications.json")
INSIDER_PATH = Path("insider_alerts.json")
MARKETS_PATH = Path("tracked_markets.json")


# ============================================================================
# Color Theme
# ============================================================================

class Theme:
    # Backgrounds
    BG_PRIMARY = "#0d1117"
    BG_SECONDARY = "#161b22"
    BG_TERTIARY = "#21262d"
    BG_CARD = "#1c2128"
    BG_INPUT = "#0d1117"
    BG_HOVER = "#30363d"
    
    # Accents
    ACCENT_BLUE = "#58a6ff"
    ACCENT_GREEN = "#3fb950"
    ACCENT_RED = "#f85149"
    ACCENT_YELLOW = "#d29922"
    ACCENT_PURPLE = "#a371f7"
    ACCENT_ORANGE = "#db6d28"
    
    # Text
    TEXT_PRIMARY = "#e6edf3"
    TEXT_SECONDARY = "#8b949e"
    TEXT_MUTED = "#6e7681"
    
    # Borders
    BORDER = "#30363d"
    BORDER_LIGHT = "#3d444d"
    
    # Status
    PROFIT = "#3fb950"
    LOSS = "#f85149"
    NEUTRAL = "#8b949e"


# ============================================================================
# UI Components
# ============================================================================

class SmoothScrollText(tk.Frame):
    """A text widget with smooth scrolling for the chat feed."""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=Theme.BG_SECONDARY)
        
        # Create text widget
        self.text = tk.Text(
            self,
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_PRIMARY,
            font=("Consolas", 10),
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=10,
            pady=10,
            cursor="arrow",
            state=tk.DISABLED,
            highlightthickness=0,
            borderwidth=0,
        )
        
        # Scrollbar
        self.scrollbar = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        
        # Layout
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Tags for message types
        self.text.tag_configure("timestamp", foreground=Theme.TEXT_MUTED, font=("Consolas", 9))
        self.text.tag_configure("bot", foreground=Theme.ACCENT_BLUE)
        self.text.tag_configure("trade", foreground=Theme.ACCENT_GREEN)
        self.text.tag_configure("alert", foreground=Theme.ACCENT_YELLOW)
        self.text.tag_configure("error", foreground=Theme.ACCENT_RED)
        self.text.tag_configure("success", foreground=Theme.ACCENT_GREEN)
        self.text.tag_configure("info", foreground=Theme.TEXT_SECONDARY)
        self.text.tag_configure("title", foreground=Theme.TEXT_PRIMARY, font=("Consolas", 10, "bold"))
    
    def add_message(self, message: str, msg_type: str = "info", title: str = "") -> None:
        """Add a message to the feed."""
        self.text.configure(state=tk.NORMAL)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Add timestamp
        self.text.insert(tk.END, f"[{timestamp}] ", "timestamp")
        
        # Add title if present
        if title:
            self.text.insert(tk.END, f"{title}: ", "title")
        
        # Add message
        self.text.insert(tk.END, f"{message}\n", msg_type)
        
        self.text.configure(state=tk.DISABLED)
        self.text.see(tk.END)
    
    def clear(self) -> None:
        """Clear all messages."""
        self.text.configure(state=tk.NORMAL)
        self.text.delete(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)


class StatDisplay(tk.Frame):
    """A stat display widget."""
    
    def __init__(self, parent, label: str, initial_value: str = "$0.00", **kwargs):
        super().__init__(parent, bg=Theme.BG_CARD, **kwargs)
        
        self.configure(padx=15, pady=10)
        
        self.label_widget = tk.Label(
            self,
            text=label,
            font=("Segoe UI", 9),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
        )
        self.label_widget.pack(anchor="w")
        
        self.value_var = tk.StringVar(value=initial_value)
        self.value_widget = tk.Label(
            self,
            textvariable=self.value_var,
            font=("Segoe UI", 18, "bold"),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
        )
        self.value_widget.pack(anchor="w")
        
        self.subtitle_var = tk.StringVar(value="")
        self.subtitle_widget = tk.Label(
            self,
            textvariable=self.subtitle_var,
            font=("Segoe UI", 9),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_MUTED,
        )
        self.subtitle_widget.pack(anchor="w")
    
    def set_value(self, value: str, subtitle: str = "", color: str = None) -> None:
        self.value_var.set(value)
        self.subtitle_var.set(subtitle)
        if color:
            self.value_widget.configure(fg=color)


class PositionRow(tk.Frame):
    """A row displaying a trading position."""
    
    def __init__(
        self,
        parent,
        trade: BotTrade,
        on_sell: callable = None,
        on_click: callable = None,
        **kwargs
    ):
        super().__init__(parent, bg=Theme.BG_CARD, **kwargs)
        
        self.trade = trade
        self.on_sell = on_sell
        self.on_click = on_click
        
        self.configure(padx=10, pady=8)
        self.bind("<Enter>", lambda e: self.configure(bg=Theme.BG_HOVER))
        self.bind("<Leave>", lambda e: self.configure(bg=Theme.BG_CARD))
        if on_click:
            self.bind("<Button-1>", lambda e: on_click(trade))
        
        # Left side - market info
        left = tk.Frame(self, bg=Theme.BG_CARD)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Question
        q_text = trade.question[:35] + "..." if len(trade.question) > 35 else trade.question
        tk.Label(
            left,
            text=q_text,
            font=("Segoe UI", 10),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill=tk.X)
        
        # Details
        details = tk.Frame(left, bg=Theme.BG_CARD)
        details.pack(fill=tk.X)
        
        tk.Label(
            details,
            text=f"{trade.shares:.1f} @ ${trade.entry_price:.3f}",
            font=("Segoe UI", 9),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_SECONDARY,
        ).pack(side=tk.LEFT)
        
        # Right side - P&L
        right = tk.Frame(self, bg=Theme.BG_CARD)
        right.pack(side=tk.RIGHT)
        
        pnl_color = Theme.PROFIT if trade.pnl >= 0 else Theme.LOSS
        pnl_text = f"+${trade.pnl:.2f}" if trade.pnl >= 0 else f"-${abs(trade.pnl):.2f}"
        
        tk.Label(
            right,
            text=pnl_text,
            font=("Segoe UI", 11, "bold"),
            bg=Theme.BG_CARD,
            fg=pnl_color,
        ).pack(anchor="e")
        
        tk.Label(
            right,
            text=f"{trade.pnl_pct:+.1%}",
            font=("Segoe UI", 9),
            bg=Theme.BG_CARD,
            fg=pnl_color,
        ).pack(anchor="e")
        
        # Sell button
        if on_sell and trade.status == "open":
            sell_btn = tk.Label(
                right,
                text="SELL",
                font=("Segoe UI", 8, "bold"),
                bg=Theme.ACCENT_RED,
                fg=Theme.TEXT_PRIMARY,
                padx=8,
                pady=2,
                cursor="hand2",
            )
            sell_btn.pack(anchor="e", pady=(4, 0))
            sell_btn.bind("<Button-1>", lambda e: on_sell(trade))


class MarketRow(tk.Frame):
    """A row displaying a tracked market."""
    
    def __init__(
        self,
        parent,
        market_data: Dict,
        opportunity: Optional[MarketOpportunity] = None,
        on_click: callable = None,
        on_remove: callable = None,
        **kwargs
    ):
        super().__init__(parent, bg=Theme.BG_CARD, **kwargs)
        
        self.market_data = market_data
        self.opportunity = opportunity
        
        self.configure(padx=10, pady=8)
        self.bind("<Enter>", lambda e: self.configure(bg=Theme.BG_HOVER))
        self.bind("<Leave>", lambda e: self.configure(bg=Theme.BG_CARD))
        if on_click:
            self.bind("<Button-1>", lambda e: on_click(market_data))
        
        # Left side
        left = tk.Frame(self, bg=Theme.BG_CARD)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Question
        question = market_data.get("question", "Unknown")
        q_text = question[:40] + "..." if len(question) > 40 else question
        tk.Label(
            left,
            text=q_text,
            font=("Segoe UI", 10),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
            anchor="w",
            cursor="hand2",
        ).pack(fill=tk.X)
        
        # Tags row
        tags = tk.Frame(left, bg=Theme.BG_CARD)
        tags.pack(fill=tk.X, pady=(2, 0))
        
        # Outcome badge
        outcome = market_data.get("outcome", "Yes")
        tk.Label(
            tags,
            text=outcome,
            font=("Segoe UI", 8),
            bg=Theme.ACCENT_BLUE,
            fg=Theme.TEXT_PRIMARY,
            padx=4,
            pady=1,
        ).pack(side=tk.LEFT)
        
        # Bot decision badge
        if opportunity:
            decision_colors = {
                BotDecision.BUY: Theme.ACCENT_GREEN,
                BotDecision.SELL: Theme.ACCENT_RED,
                BotDecision.HOLD: Theme.ACCENT_YELLOW,
                BotDecision.SKIP: Theme.TEXT_MUTED,
            }
            tk.Label(
                tags,
                text=opportunity.decision.value.upper(),
                font=("Segoe UI", 8, "bold"),
                bg=decision_colors.get(opportunity.decision, Theme.TEXT_MUTED),
                fg=Theme.TEXT_PRIMARY,
                padx=4,
                pady=1,
            ).pack(side=tk.LEFT, padx=(4, 0))
        
        # Right side - price and metrics
        right = tk.Frame(self, bg=Theme.BG_CARD)
        right.pack(side=tk.RIGHT)
        
        price = market_data.get("best_ask") or market_data.get("price") or 0
        tk.Label(
            right,
            text=f"${price:.3f}",
            font=("Segoe UI", 12, "bold"),
            bg=Theme.BG_CARD,
            fg=Theme.TEXT_PRIMARY,
        ).pack(anchor="e")
        
        if opportunity and opportunity.g_score:
            g_color = Theme.ACCENT_GREEN if opportunity.g_score > 0.003 else Theme.TEXT_SECONDARY
            tk.Label(
                right,
                text=f"g: {opportunity.g_score:.4f}",
                font=("Segoe UI", 9),
                bg=Theme.BG_CARD,
                fg=g_color,
            ).pack(anchor="e")
        
        # Remove button
        if on_remove:
            remove_btn = tk.Label(
                right,
                text="✕",
                font=("Segoe UI", 10),
                bg=Theme.BG_CARD,
                fg=Theme.TEXT_MUTED,
                cursor="hand2",
            )
            remove_btn.pack(anchor="e", pady=(2, 0))
            remove_btn.bind("<Enter>", lambda e: remove_btn.configure(fg=Theme.ACCENT_RED))
            remove_btn.bind("<Leave>", lambda e: remove_btn.configure(fg=Theme.TEXT_MUTED))
            remove_btn.bind("<Button-1>", lambda e: on_remove(market_data))


# ============================================================================
# Main Application
# ============================================================================

class TradingBotApp(tk.Tk):
    """Modern Polymarket Trading Bot Application."""
    
    def __init__(self):
        super().__init__()
        
        self.title("🚀 Polymarket Trading Bot")
        self.geometry("1400x900")
        self.configure(bg=Theme.BG_PRIMARY)
        self.minsize(1100, 700)
        
        # Message queue for thread-safe UI updates
        self.message_queue = queue.Queue()
        
        # Initialize components
        self.config = ensure_config(CONFIG_PATH)
        self.notifications = NotificationManager(NOTIFICATIONS_PATH)
        
        # Initialize auto-trading bot with improved config
        self.bot = AutoTradingBot(
            config=BotConfig(
                initial_capital=10000.0,
                max_position_size=500.0,
                min_volume=500.0,       # Lowered for diversity
                scan_interval_seconds=10,  # FASTER scanning (10 sec)
                max_positions=50,  # Allow many positions
                swing_trade_enabled=True,  # Enable swing trading
                prefer_high_volume=False,  # DON'T just focus on popular markets
                use_news_analysis=NEWS_ANALYZER_AVAILABLE,  # Use news if available
            ),
            storage_path=BOT_STATE_PATH,
            on_trade=self._on_bot_trade,
            on_opportunity=self._on_bot_opportunity,
            on_message=self._on_bot_message,
        )
        
        # Initialize insider detector (monitors ALL scanned markets)
        # Lower thresholds to catch more trades in smaller markets
        self.insider_detector = InsiderDetector(
            config=InsiderDetectorConfig(
                large_trade_threshold=500.0,  # Show trades $500+ in normal markets
                small_market_threshold=100.0,  # Show trades $100+ in small markets
                small_market_volume_max=100000.0,  # Markets under $100k are "small"
                tiny_market_volume_max=25000.0,  # Markets under $25k are "tiny"
                monitor_small_markets=True,
                poll_interval_seconds=15,  # Fast polling
                small_market_trade_pct=0.01,  # 1% of market volume triggers alert
                max_alerts_stored=1000,  # Keep more alerts
            ),
            storage_path=INSIDER_PATH,
        )
        self.insider_detector.add_listener(self._on_insider_alert)
        
        # Tracked markets
        self.tracked_markets: Dict[str, Dict] = {}
        self.market_opportunities: Dict[str, MarketOpportunity] = {}
        
        # UI state
        self.auto_trade_enabled = tk.BooleanVar(value=False)
        self.selected_position: Optional[str] = None
        self._last_stats_update = datetime.now()
        
        # Build UI
        self._build_ui()
        
        # Load saved markets
        self._load_markets()
        
        # Start message processing
        self._process_messages()
        
        # Welcome message
        self.chat.add_message(
            "Welcome! I'm your Polymarket trading assistant. "
            "Add markets to track, and I'll analyze them for trading opportunities.",
            "bot",
            "Bot"
        )
        self.chat.add_message(
            "Enable 'Auto Trade' to let me automatically find and execute profitable trades. "
            "Bot now supports SWING trades on popular markets for quick profits!",
            "info"
        )
        
        # Start periodic updates
        self._start_updates()
    
    def _build_ui(self) -> None:
        """Build the main UI."""
        # Configure grid - 2 columns, 2 rows for main content
        self.grid_columnconfigure(0, weight=3)  # Left panel (chat)
        self.grid_columnconfigure(1, weight=2)  # Right panel (markets/positions)
        self.grid_rowconfigure(1, weight=3)     # Main content row
        self.grid_rowconfigure(2, weight=1)     # Bottom row for trade log
        
        # Top bar
        self._build_top_bar()
        
        # Left panel - Chat feed
        self._build_chat_panel()
        
        # Right panel - Markets and positions
        self._build_right_panel()
        
        # Bottom left - Stats Dashboard
        self._build_stats_dashboard()
        
        # Bottom right - Trade Log
        self._build_trade_log_panel()
        
        # Track last update time for throttling
        self._last_ui_update = 0
    
    def _build_top_bar(self) -> None:
        """Build the top navigation bar."""
        top_bar = tk.Frame(self, bg=Theme.BG_SECONDARY, height=60)
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        top_bar.grid_propagate(False)
        
        # Logo
        tk.Label(
            top_bar,
            text="🚀 Polymarket Bot",
            font=("Segoe UI", 16, "bold"),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT, padx=20, pady=15)
        
        # Stats row
        stats_frame = tk.Frame(top_bar, bg=Theme.BG_SECONDARY)
        stats_frame.pack(side=tk.LEFT, padx=30)
        
        self.portfolio_label = tk.Label(
            stats_frame,
            text="Portfolio: $10,000.00",
            font=("Segoe UI", 11),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_PRIMARY,
        )
        self.portfolio_label.pack(side=tk.LEFT, padx=10)
        
        self.pnl_label = tk.Label(
            stats_frame,
            text="P&L: $0.00 (0.0%)",
            font=("Segoe UI", 11),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_SECONDARY,
        )
        self.pnl_label.pack(side=tk.LEFT, padx=10)
        
        # Right side controls
        controls = tk.Frame(top_bar, bg=Theme.BG_SECONDARY)
        controls.pack(side=tk.RIGHT, padx=20)
        
        # Auto trade toggle
        self.auto_trade_btn = tk.Button(
            controls,
            text="▶ Start Auto Trade",
            font=("Segoe UI", 10),
            bg=Theme.ACCENT_GREEN,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=15,
            pady=5,
            cursor="hand2",
            command=self._toggle_auto_trade,
        )
        self.auto_trade_btn.pack(side=tk.LEFT, padx=5)
        
        # Scan button
        tk.Button(
            controls,
            text="Scan Markets",
            font=("Segoe UI", 10),
            bg=Theme.BG_TERTIARY,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=15,
            pady=5,
            cursor="hand2",
            command=self._manual_scan,
        ).pack(side=tk.LEFT, padx=5)
        
        # Settings
        tk.Button(
            controls,
            text="Settings",
            font=("Segoe UI", 10),
            bg=Theme.BG_TERTIARY,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=10,
            pady=5,
            cursor="hand2",
            command=self._show_settings,
        ).pack(side=tk.LEFT, padx=5)
    
    def _build_chat_panel(self) -> None:
        """Build the left chat panel."""
        left_panel = tk.Frame(self, bg=Theme.BG_PRIMARY)
        left_panel.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=10)
        
        # Header
        header = tk.Frame(left_panel, bg=Theme.BG_PRIMARY)
        header.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(
            header,
            text="Bot Activity",
            font=("Segoe UI", 14, "bold"),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        self.status_label = tk.Label(
            header,
            text="● Idle",
            font=("Segoe UI", 10),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_SECONDARY,
        )
        self.status_label.pack(side=tk.RIGHT)
        
        # Chat feed
        self.chat = SmoothScrollText(left_panel)
        self.chat.pack(fill=tk.BOTH, expand=True)
    
    def _build_right_panel(self) -> None:
        """Build the right panel with markets and positions."""
        right_panel = tk.Frame(self, bg=Theme.BG_PRIMARY)
        right_panel.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=10)
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Configure notebook style for dark theme
        style = ttk.Style()
        
        # Use clam theme as base (better for customization)
        try:
            style.theme_use("clam")
        except:
            pass
        
        # Configure the notebook itself
        style.configure("TNotebook", 
            background=Theme.BG_PRIMARY,
            borderwidth=0,
            tabmargins=[0, 0, 0, 0],
        )
        
        style.configure("TNotebook.Tab", 
            background=Theme.BG_TERTIARY,
            foreground=Theme.TEXT_PRIMARY,
            padding=[15, 8],
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        
        # Map for different states (selected, active, etc.)
        style.map("TNotebook.Tab",
            background=[
                ("selected", Theme.BG_SECONDARY),
                ("active", Theme.BG_HOVER),
                ("!selected", Theme.BG_TERTIARY),
            ],
            foreground=[
                ("selected", Theme.TEXT_PRIMARY),
                ("active", Theme.TEXT_PRIMARY),
                ("!selected", Theme.TEXT_SECONDARY),
            ],
            expand=[("selected", [1, 1, 1, 0])],
        )
        
        # Tab 1: Trading (Markets)
        markets_tab = tk.Frame(self.notebook, bg=Theme.BG_PRIMARY)
        self.notebook.add(markets_tab, text="  Trading  ")
        self._build_markets_tab(markets_tab)
        
        # Tab 2: Bot Positions
        positions_tab = tk.Frame(self.notebook, bg=Theme.BG_PRIMARY)
        self.notebook.add(positions_tab, text="  Positions  ")
        self._build_positions_tab(positions_tab)
        
        # Tab 3: Alerts
        alerts_tab = tk.Frame(self.notebook, bg=Theme.BG_PRIMARY)
        self.notebook.add(alerts_tab, text="  Alerts  ")
        self._build_alerts_tab(alerts_tab)
    
    def _build_markets_tab(self, parent: tk.Frame) -> None:
        """Build the markets tab."""
        # Header with add button
        header = tk.Frame(parent, bg=Theme.BG_PRIMARY)
        header.pack(fill=tk.X, pady=(10, 5))
        
        tk.Label(
            header,
            text="Tracked Markets",
            font=("Segoe UI", 12, "bold"),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        tk.Button(
            header,
            text="+ Add Market",
            font=("Segoe UI", 9),
            bg=Theme.ACCENT_BLUE,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._add_market_dialog,
        ).pack(side=tk.RIGHT)
        
        # Markets list
        self.markets_container = tk.Frame(parent, bg=Theme.BG_PRIMARY)
        self.markets_container.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Canvas for scrolling
        self.markets_canvas = tk.Canvas(
            self.markets_container,
            bg=Theme.BG_PRIMARY,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(self.markets_container, command=self.markets_canvas.yview)
        self.markets_frame = tk.Frame(self.markets_canvas, bg=Theme.BG_PRIMARY)
        
        self.markets_canvas.create_window((0, 0), window=self.markets_frame, anchor="nw")
        self.markets_canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.markets_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.markets_frame.bind("<Configure>", 
            lambda e: self.markets_canvas.configure(scrollregion=self.markets_canvas.bbox("all")))
        self.markets_canvas.bind("<Configure>",
            lambda e: self.markets_canvas.itemconfig(
                self.markets_canvas.find_all()[0] if self.markets_canvas.find_all() else None,
                width=e.width
            ) if self.markets_canvas.find_all() else None)
    
    def _build_trade_log_panel(self) -> None:
        """Build the bottom right trade log panel."""
        log_panel = tk.Frame(self, bg=Theme.BG_SECONDARY)
        log_panel.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=(5, 10))
        
        # Header
        header = tk.Frame(log_panel, bg=Theme.BG_SECONDARY)
        header.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        tk.Label(
            header,
            text="📊 Trade Log",
            font=("Segoe UI", 11, "bold"),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        self.trade_log_count = tk.Label(
            header,
            text="0 trades",
            font=("Segoe UI", 9),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_MUTED,
        )
        self.trade_log_count.pack(side=tk.RIGHT)
        
        # Trade log text area with scroll
        log_container = tk.Frame(log_panel, bg=Theme.BG_SECONDARY)
        log_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.trade_log_text = tk.Text(
            log_container,
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_PRIMARY,
            font=("Consolas", 9),
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=8,
            pady=8,
            height=8,
            state=tk.DISABLED,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        )
        
        scrollbar = ttk.Scrollbar(log_container, command=self.trade_log_text.yview)
        self.trade_log_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.trade_log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure tags for trade log
        self.trade_log_text.tag_configure("buy", foreground=Theme.ACCENT_GREEN)
        self.trade_log_text.tag_configure("sell_win", foreground=Theme.ACCENT_GREEN)
        self.trade_log_text.tag_configure("sell_loss", foreground=Theme.ACCENT_RED)
        self.trade_log_text.tag_configure("timestamp", foreground=Theme.TEXT_MUTED)
        self.trade_log_text.tag_configure("amount", foreground=Theme.ACCENT_BLUE)
        self.trade_log_text.tag_configure("pnl_pos", foreground=Theme.PROFIT)
        self.trade_log_text.tag_configure("pnl_neg", foreground=Theme.LOSS)
    
    def _build_stats_dashboard(self) -> None:
        """Build the bottom left stats dashboard panel."""
        stats_panel = tk.Frame(self, bg=Theme.BG_SECONDARY)
        stats_panel.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=(5, 10))
        
        # Header
        header = tk.Frame(stats_panel, bg=Theme.BG_SECONDARY)
        header.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        tk.Label(
            header,
            text="📈 Performance Dashboard",
            font=("Segoe UI", 11, "bold"),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        # Main content area
        content = tk.Frame(stats_panel, bg=Theme.BG_SECONDARY)
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Left stats column
        left_col = tk.Frame(content, bg=Theme.BG_CARD)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        tk.Label(left_col, text="Session Stats", font=("Segoe UI", 9, "bold"),
                bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY).pack(pady=(8, 4))
        
        # Create labels for session stats
        self.session_stats_frame = tk.Frame(left_col, bg=Theme.BG_CARD)
        self.session_stats_frame.pack(fill=tk.X, padx=8, pady=4)
        
        self.stat_labels = {}
        for stat_name in ["Trades Today", "Win Rate", "Avg P&L", "Best Trade", "Worst Trade"]:
            row = tk.Frame(self.session_stats_frame, bg=Theme.BG_CARD)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=stat_name, font=("Segoe UI", 8), 
                    bg=Theme.BG_CARD, fg=Theme.TEXT_MUTED).pack(side=tk.LEFT)
            self.stat_labels[stat_name] = tk.Label(row, text="--", font=("Segoe UI", 8, "bold"),
                    bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY)
            self.stat_labels[stat_name].pack(side=tk.RIGHT)
        
        # Right - Category breakdown
        right_col = tk.Frame(content, bg=Theme.BG_CARD)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        tk.Label(right_col, text="Portfolio by Category", font=("Segoe UI", 9, "bold"),
                bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY).pack(pady=(8, 4))
        
        self.category_frame = tk.Frame(right_col, bg=Theme.BG_CARD)
        self.category_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        
        # Category colors
        self.category_colors = {
            "politics": "#E74C3C",
            "crypto": "#F39C12", 
            "sports": "#2ECC71",
            "finance": "#3498DB",
            "entertainment": "#9B59B6",
            "science": "#1ABC9C",
            "world": "#34495E",
            "other": "#95A5A6",
        }
    
    def _update_stats_dashboard(self) -> None:
        """Update the stats dashboard with current data."""
        try:
            stats = self.bot.get_stats()
            trades = self.bot.get_open_trades()
            
            # Calculate session stats
            total_trades = stats.get('total_trades', 0)
            win_rate = stats.get('win_rate', 0)
            
            # Find best and worst trades from current positions
            best_pnl = 0
            worst_pnl = 0
            total_pnl = 0
            for trade in trades:
                # Use pnl_pct which is the attribute on BotTrade
                pnl_pct = getattr(trade, 'pnl_pct', 0)
                total_pnl += pnl_pct
                if pnl_pct > best_pnl:
                    best_pnl = pnl_pct
                if pnl_pct < worst_pnl:
                    worst_pnl = pnl_pct
            
            avg_pnl = total_pnl / len(trades) if trades else 0
            
            # Update stat labels
            self.stat_labels["Trades Today"].configure(text=str(total_trades))
            self.stat_labels["Win Rate"].configure(
                text=f"{win_rate:.1f}%",
                fg=Theme.PROFIT if win_rate >= 50 else Theme.LOSS
            )
            self.stat_labels["Avg P&L"].configure(
                text=f"{avg_pnl:+.1f}%",
                fg=Theme.PROFIT if avg_pnl >= 0 else Theme.LOSS
            )
            self.stat_labels["Best Trade"].configure(
                text=f"+{best_pnl:.1f}%" if best_pnl > 0 else "--",
                fg=Theme.PROFIT
            )
            self.stat_labels["Worst Trade"].configure(
                text=f"{worst_pnl:.1f}%" if worst_pnl < 0 else "--",
                fg=Theme.LOSS
            )
            
            # Update category breakdown
            for widget in self.category_frame.winfo_children():
                widget.destroy()
            
            # Count positions by category
            category_counts = {}
            for trade in trades:
                cat = getattr(trade, 'category', 'other') or 'other'
                category_counts[cat] = category_counts.get(cat, 0) + 1
            
            if category_counts:
                total = sum(category_counts.values())
                for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
                    pct = (count / total) * 100
                    color = self.category_colors.get(cat, "#95A5A6")
                    
                    row = tk.Frame(self.category_frame, bg=Theme.BG_CARD)
                    row.pack(fill=tk.X, pady=1)
                    
                    # Category name
                    tk.Label(row, text=cat.capitalize(), font=("Segoe UI", 8),
                            bg=Theme.BG_CARD, fg=color).pack(side=tk.LEFT)
                    
                    # Count and percentage
                    tk.Label(row, text=f"{count} ({pct:.0f}%)", font=("Segoe UI", 8),
                            bg=Theme.BG_CARD, fg=Theme.TEXT_MUTED).pack(side=tk.RIGHT)
            else:
                tk.Label(self.category_frame, text="No positions yet", font=("Segoe UI", 8),
                        bg=Theme.BG_CARD, fg=Theme.TEXT_MUTED).pack()
                        
        except Exception as e:
            print(f"Error updating stats dashboard: {e}")

    def _build_positions_tab(self, parent: tk.Frame) -> None:
        """Build the positions tab."""
        # Stats row
        stats = tk.Frame(parent, bg=Theme.BG_PRIMARY)
        stats.pack(fill=tk.X, pady=10)
        
        self.stat_value = StatDisplay(stats, "Portfolio Value", "$10,000.00")
        self.stat_value.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.stat_pnl = StatDisplay(stats, "Total P&L", "$0.00")
        self.stat_pnl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Positions header
        header = tk.Frame(parent, bg=Theme.BG_PRIMARY)
        header.pack(fill=tk.X, pady=(10, 5))
        
        tk.Label(
            header,
            text="Open Positions",
            font=("Segoe UI", 12, "bold"),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        self.positions_count = tk.Label(
            header,
            text="0 positions",
            font=("Segoe UI", 10),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_SECONDARY,
        )
        self.positions_count.pack(side=tk.RIGHT)
        
        # Positions list
        self.positions_container = tk.Frame(parent, bg=Theme.BG_PRIMARY)
        self.positions_container.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.positions_canvas = tk.Canvas(
            self.positions_container,
            bg=Theme.BG_PRIMARY,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(self.positions_container, command=self.positions_canvas.yview)
        self.positions_frame = tk.Frame(self.positions_canvas, bg=Theme.BG_PRIMARY)
        
        self.positions_canvas.create_window((0, 0), window=self.positions_frame, anchor="nw")
        self.positions_canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.positions_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.positions_frame.bind("<Configure>",
            lambda e: self.positions_canvas.configure(scrollregion=self.positions_canvas.bbox("all")))
    
    def _build_alerts_tab(self, parent: tk.Frame) -> None:
        """Build the alerts tab."""
        # Header
        header = tk.Frame(parent, bg=Theme.BG_PRIMARY)
        header.pack(fill=tk.X, pady=(10, 5))
        
        tk.Label(
            header,
            text="Insider Trading Alerts",
            font=("Segoe UI", 12, "bold"),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        tk.Label(
            header,
            text="(Focused on small markets)",
            font=("Segoe UI", 9),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_MUTED,
        ).pack(side=tk.LEFT, padx=(10, 0))
        
        # Alerts list
        self.alerts_frame = tk.Frame(parent, bg=Theme.BG_PRIMARY)
        self.alerts_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self._update_alerts_display()
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    def _toggle_auto_trade(self) -> None:
        """Toggle auto-trading on/off."""
        if self.bot.is_running():
            self.bot.stop()
            self.insider_detector.stop_monitoring()
            self.auto_trade_btn.configure(text="Start Auto Trade", bg=Theme.ACCENT_GREEN)
            self.status_label.configure(text="Idle", fg=Theme.TEXT_SECONDARY)
            self.chat.add_message("Auto-trading stopped", "info", "Bot")
        else:
            self.bot.start()
            self.insider_detector.start_monitoring()  # Start monitoring for insider trades
            self.auto_trade_btn.configure(text="Stop Auto Trade", bg=Theme.ACCENT_RED)
            self.status_label.configure(text="Trading", fg=Theme.ACCENT_GREEN)
            self.chat.add_message(
                "Auto-trading started! Scanning for opportunities... "
                f"(Up to {self.bot.config.max_positions} positions allowed)",
                "success",
                "Bot"
            )
    
    def _manual_scan(self) -> None:
        """Manually trigger a market scan."""
        self.chat.add_message("Starting market scan...", "info", "Scan")
        
        def scan():
            opportunities = self.bot.scan_markets()
            self.message_queue.put(("scan_complete", opportunities))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _on_bot_message(self, message: str, msg_type: str) -> None:
        """Handle bot messages (thread-safe)."""
        self.message_queue.put(("message", (message, msg_type)))
    
    def _on_bot_trade(self, trade: BotTrade) -> None:
        """Handle bot trade events (thread-safe)."""
        self.message_queue.put(("trade", trade))
    
    def _on_bot_opportunity(self, opportunity: MarketOpportunity) -> None:
        """Handle new opportunity discovered - also add to insider monitoring."""
        self.market_opportunities[f"{opportunity.market_id}|{opportunity.outcome}"] = opportunity
        
        # Add ALL scanned markets to insider detector for monitoring
        # This ensures we catch insider activity on popular markets
        self.insider_detector.add_market(
            opportunity.market_id,
            opportunity.question,
            opportunity.token_id
        )
    
    def _on_insider_alert(self, alert: InsiderAlert) -> None:
        """Handle insider trading alerts (thread-safe)."""
        # Always add to alerts tab
        self.message_queue.put(("insider_alert", alert))
        
        # For MAJOR alerts ($100k+ from new accounts), also show in bot activity
        if alert.trade_size >= 100000:
            self.message_queue.put(("major_insider_alert", alert))
    
    def _process_messages(self) -> None:
        """Process messages from the queue (runs on main thread)."""
        try:
            while True:
                msg_type, data = self.message_queue.get_nowait()
                
                if msg_type == "message":
                    message, mtype = data
                    self.chat.add_message(message, mtype)
                
                elif msg_type == "trade":
                    self._update_positions_display()
                    self._update_stats()
                
                elif msg_type == "scan_complete":
                    opportunities = data
                    buy_ops = [o for o in opportunities if o.decision == BotDecision.BUY]
                    self.chat.add_message(
                        f"Scan complete: {len(opportunities)} markets analyzed, {len(buy_ops)} buy opportunities",
                        "success",
                        "Scan"
                    )
                    self._update_markets_display()
                
                elif msg_type == "insider_alert":
                    alert = data
                    self._update_alerts_display()
                
                elif msg_type == "major_insider_alert":
                    alert = data
                    self.chat.add_message(
                        f"MAJOR INSIDER ALERT: ${alert.trade_size:,.0f} {alert.trade_side.upper()} detected!\n"
                        f"Market: {alert.market_question[:50]}...\n"
                        f"Reason: {alert.reason}",
                        "alert",
                        "INSIDER"
                    )
                    self._update_alerts_display()
                    
        except queue.Empty:
            pass
        
        # Schedule next check
        self.after(100, self._process_messages)
    
    def _add_market_dialog(self) -> None:
        """Show dialog to add a market."""
        dialog = tk.Toplevel(self)
        dialog.title("Add Market")
        dialog.geometry("500x400")
        dialog.configure(bg=Theme.BG_SECONDARY)
        dialog.transient(self)
        dialog.grab_set()
        
        # URL input
        tk.Label(
            dialog,
            text="Enter Polymarket URL or slug:",
            font=("Segoe UI", 11),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=20, pady=(20, 5))
        
        url_var = tk.StringVar()
        url_entry = tk.Entry(
            dialog,
            textvariable=url_var,
            font=("Segoe UI", 11),
            width=50,
            bg=Theme.BG_INPUT,
            fg=Theme.TEXT_PRIMARY,
            insertbackground=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
        )
        url_entry.pack(padx=20, pady=5, fill=tk.X)
        
        # Result frame
        result_frame = tk.Frame(dialog, bg=Theme.BG_SECONDARY)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        result_var = tk.StringVar(value="Enter a URL and click Fetch")
        result_label = tk.Label(
            result_frame,
            textvariable=result_var,
            font=("Segoe UI", 10),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_SECONDARY,
            wraplength=440,
            justify=tk.LEFT,
        )
        result_label.pack(anchor="w")
        
        # Outcome selection
        outcome_var = tk.StringVar()
        outcome_frame = tk.Frame(result_frame, bg=Theme.BG_SECONDARY)
        outcome_frame.pack(fill=tk.X, pady=10)
        
        market_data = {}
        
        def fetch():
            url = url_var.get().strip()
            if not url:
                result_var.set("Please enter a URL")
                return
            
            try:
                slug = extract_slug(url)
                ref_type, metadata = resolve_reference(slug)
                
                if ref_type == "event":
                    markets = metadata.get("markets", [])
                    if markets:
                        metadata = markets[0]
                        slug = metadata.get("slug") or str(metadata.get("id"))
                        metadata = fetch_market(slug)
                
                market_data.clear()
                market_data.update(metadata)
                
                question = metadata.get("question", "Unknown")
                
                # Get outcomes
                outcomes = list_outcomes(metadata)
                
                # Clear old outcome buttons
                for w in outcome_frame.winfo_children():
                    w.destroy()
                
                tk.Label(
                    outcome_frame,
                    text="Select outcome:",
                    font=("Segoe UI", 10),
                    bg=Theme.BG_SECONDARY,
                    fg=Theme.TEXT_PRIMARY,
                ).pack(anchor="w")
                
                for outcome in outcomes:
                    price_str = f" (${outcome.last_price:.3f})" if outcome.last_price else ""
                    tk.Radiobutton(
                        outcome_frame,
                        text=f"{outcome.name}{price_str}",
                        variable=outcome_var,
                        value=f"{outcome.name}|{outcome.token_id}",
                        bg=Theme.BG_SECONDARY,
                        fg=Theme.TEXT_PRIMARY,
                        selectcolor=Theme.BG_TERTIARY,
                        activebackground=Theme.BG_SECONDARY,
                        font=("Segoe UI", 10),
                    ).pack(anchor="w")
                
                if outcomes:
                    outcome_var.set(f"{outcomes[0].name}|{outcomes[0].token_id}")
                
                result_var.set(f"Found: {question[:80]}...")
                
            except Exception as e:
                result_var.set(f"Error: {e}")
        
        def add():
            if not market_data or not outcome_var.get():
                return
            
            outcome_name, token_id = outcome_var.get().split("|")
            
            # Evaluate with bot
            opportunity = self.bot.evaluate_market_for_user(market_data, outcome_name, token_id)
            
            # Store market
            market_key = f"{opportunity.market_id}|{outcome_name}"
            self.tracked_markets[market_key] = {
                "market_id": opportunity.market_id,
                "question": opportunity.question,
                "outcome": outcome_name,
                "token_id": token_id,
                "price": opportunity.price,
                "metadata": market_data,
            }
            self.market_opportunities[market_key] = opportunity
            
            # Add to insider detector
            volume = float(market_data.get("volumeNum") or market_data.get("volume") or 0)
            self.insider_detector.add_market(opportunity.market_id, opportunity.question, token_id)
            
            # Update UI
            self._update_markets_display()
            self._save_markets()
            
            # Show bot's decision
            decision_msg = {
                BotDecision.BUY: f"BUY SIGNAL! g={opportunity.g_score:.4f}, ROI={opportunity.expected_roi:.1%}",
                BotDecision.HOLD: f"HOLD - Not meeting buy criteria",
                BotDecision.SKIP: f"SKIP - {', '.join(opportunity.reasons)}",
                BotDecision.SELL: f"SELL signal",
            }
            
            self.chat.add_message(
                f"Added market: {opportunity.question[:50]}...\n"
                f"Bot Decision: {decision_msg.get(opportunity.decision, 'Unknown')}",
                "success" if opportunity.decision == BotDecision.BUY else "info",
                "Market Added"
            )
            
            dialog.destroy()
        
        # Buttons
        btn_frame = tk.Frame(dialog, bg=Theme.BG_SECONDARY)
        btn_frame.pack(fill=tk.X, padx=20, pady=20)
        
        tk.Button(
            btn_frame,
            text="Fetch",
            font=("Segoe UI", 10),
            bg=Theme.ACCENT_BLUE,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=20,
            pady=5,
            command=fetch,
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Button(
            btn_frame,
            text="Add Market",
            font=("Segoe UI", 10),
            bg=Theme.ACCENT_GREEN,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=20,
            pady=5,
            command=add,
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Button(
            btn_frame,
            text="Cancel",
            font=("Segoe UI", 10),
            bg=Theme.BG_TERTIARY,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=20,
            pady=5,
            command=dialog.destroy,
        ).pack(side=tk.LEFT)
    
    def _remove_market(self, market_data: Dict) -> None:
        """Remove a tracked market."""
        market_key = f"{market_data['market_id']}|{market_data['outcome']}"
        if market_key in self.tracked_markets:
            del self.tracked_markets[market_key]
            self._update_markets_display()
            self._save_markets()
            self.chat.add_message(f"Removed market: {market_data['question'][:40]}...", "info")
    
    def _sell_position(self, trade: BotTrade) -> None:
        """Sell a position."""
        if messagebox.askyesno("Confirm Sell", f"Sell position in '{trade.question[:40]}...'?"):
            self.bot.sell_position(trade.id)
            self._update_positions_display()
            self._update_stats()
    
    # =========================================================================
    # UI Updates
    # =========================================================================
    
    def _update_markets_display(self) -> None:
        """Update the markets list."""
        for widget in self.markets_frame.winfo_children():
            widget.destroy()
        
        if not self.tracked_markets:
            tk.Label(
                self.markets_frame,
                text="No markets tracked.\nClick 'Add Market' to start.",
                font=("Segoe UI", 10),
                bg=Theme.BG_PRIMARY,
                fg=Theme.TEXT_MUTED,
                pady=30,
            ).pack()
            return
        
        for market_key, market_data in self.tracked_markets.items():
            opportunity = self.market_opportunities.get(market_key)
            row = MarketRow(
                self.markets_frame,
                market_data,
                opportunity=opportunity,
                on_remove=self._remove_market,
            )
            row.pack(fill=tk.X, pady=2)
    
    def _update_positions_display(self) -> None:
        """Update the positions list with optimized rendering."""
        trades = self.bot.get_open_trades()
        
        # Check if position count changed - only rebuild if needed
        current_count = len(trades)
        current_ids = set(t.id for t in trades)
        
        # Store state for comparison
        if not hasattr(self, '_last_position_ids'):
            self._last_position_ids = set()
        
        # Only rebuild widgets if positions changed
        needs_rebuild = (current_ids != self._last_position_ids)
        
        self.positions_count.configure(text=f"{current_count} positions")
        
        if needs_rebuild:
            self._last_position_ids = current_ids
            
            for widget in self.positions_frame.winfo_children():
                widget.destroy()
            
            if not trades:
                tk.Label(
                    self.positions_frame,
                    text="No open positions.\nThe bot will show positions here when it trades.",
                    font=("Segoe UI", 10),
                    bg=Theme.BG_PRIMARY,
                    fg=Theme.TEXT_MUTED,
                    pady=30,
                ).pack()
                return
            
            for trade in trades:
                row = PositionRow(
                    self.positions_frame,
                    trade,
                    on_sell=self._sell_position,
                )
                row.pack(fill=tk.X, pady=2)
    
    def _update_stats(self) -> None:
        """Update portfolio statistics."""
        stats = self.bot.get_stats()
        
        self.portfolio_label.configure(
            text=f"Portfolio: ${stats['portfolio_value']:,.2f}"
        )
        
        pnl = stats['total_pnl'] + stats['unrealized_pnl']
        pnl_pct = stats['total_return_pct']
        pnl_color = Theme.PROFIT if pnl >= 0 else Theme.LOSS
        pnl_text = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        
        self.pnl_label.configure(
            text=f"P&L: {pnl_text} ({pnl_pct:+.1f}%)",
            fg=pnl_color
        )
        
        self.stat_value.set_value(f"${stats['portfolio_value']:,.2f}")
        self.stat_pnl.set_value(
            pnl_text,
            f"Win rate: {stats['win_rate']:.0f}%",
            pnl_color
        )
    
    def _update_alerts_display(self) -> None:
        """Update the alerts list with current time and market info."""
        for widget in self.alerts_frame.winfo_children():
            widget.destroy()
        
        # Header with current time
        header = tk.Frame(self.alerts_frame, bg=Theme.BG_PRIMARY)
        header.pack(fill=tk.X, pady=(0, 10))
        
        current_time = datetime.now().strftime("%H:%M:%S")
        tk.Label(
            header,
            text=f"Last Updated: {current_time}",
            font=("Segoe UI", 9),
            bg=Theme.BG_PRIMARY,
            fg=Theme.TEXT_MUTED,
        ).pack(side=tk.RIGHT)
        
        alerts = self.insider_detector.get_alerts(limit=20)
        
        if not alerts:
            tk.Label(
                self.alerts_frame,
                text="Monitoring ALL markets for insider activity...\n\n"
                     "The bot watches for:\n"
                     "• Trades >$100 in tiny markets (<$25k volume)\n"
                     "• Trades >$250 in small markets (<$100k volume)\n"
                     "• Trades >$500 in normal markets\n"
                     "• Trades >1% of total market volume\n"
                     "• New accounts (<14 days) placing bets\n"
                     "• Unusual volume spikes (2.5x normal)\n\n"
                     "MAJOR alerts ($100k+) will appear in Bot Activity.\n\n"
                     f"Currently monitoring: {len(self.insider_detector.monitored_markets)} markets",
                font=("Segoe UI", 10),
                bg=Theme.BG_PRIMARY,
                fg=Theme.TEXT_MUTED,
                pady=20,
                justify=tk.LEFT,
            ).pack()
            return
        
        for alert in alerts:
            severity_colors = {
                AlertSeverity.LOW: Theme.TEXT_SECONDARY,
                AlertSeverity.MEDIUM: Theme.ACCENT_YELLOW,
                AlertSeverity.HIGH: Theme.ACCENT_ORANGE,
                AlertSeverity.CRITICAL: Theme.ACCENT_RED,
            }
            
            alert_frame = tk.Frame(self.alerts_frame, bg=Theme.BG_CARD)
            alert_frame.pack(fill=tk.X, pady=2)
            
            inner = tk.Frame(alert_frame, bg=Theme.BG_CARD)
            inner.pack(fill=tk.X, padx=10, pady=8)
            
            # Top row: severity + time
            top_row = tk.Frame(inner, bg=Theme.BG_CARD)
            top_row.pack(fill=tk.X)
            
            tk.Label(
                top_row,
                text=f"● {alert.severity.value.upper()}",
                font=("Segoe UI", 9, "bold"),
                bg=Theme.BG_CARD,
                fg=severity_colors.get(alert.severity, Theme.ACCENT_YELLOW),
            ).pack(side=tk.LEFT)
            
            # Parse and format timestamp nicely
            try:
                alert_time = datetime.fromisoformat(alert.timestamp.replace("Z", "+00:00"))
                time_str = alert_time.strftime("%m/%d %H:%M:%S")
            except Exception:
                time_str = alert.timestamp[:19]
            
            tk.Label(
                top_row,
                text=time_str,
                font=("Segoe UI", 8),
                bg=Theme.BG_CARD,
                fg=Theme.TEXT_MUTED,
            ).pack(side=tk.RIGHT)
            
            # Market name (highlighted)
            market_text = alert.market_question[:60] + "..." if len(alert.market_question) > 60 else alert.market_question
            tk.Label(
                inner,
                text=market_text,
                font=("Segoe UI", 10, "bold"),
                bg=Theme.BG_CARD,
                fg=Theme.ACCENT_BLUE,
                wraplength=350,
                justify=tk.LEFT,
            ).pack(anchor="w", pady=(4, 2))
            
            # Reason
            tk.Label(
                inner,
                text=alert.reason,
                font=("Segoe UI", 9),
                bg=Theme.BG_CARD,
                fg=Theme.TEXT_PRIMARY,
                wraplength=350,
                justify=tk.LEFT,
            ).pack(anchor="w")
            
            # Trade details
            details = f"${alert.trade_size:,.0f} {alert.trade_side.upper()} @ ${alert.price:.3f} | {alert.outcome}"
            tk.Label(
                inner,
                text=details,
                font=("Segoe UI", 8),
                bg=Theme.BG_CARD,
                fg=Theme.TEXT_SECONDARY,
            ).pack(anchor="w", pady=(2, 0))
    
    def _update_trade_log_display(self) -> None:
        """Update the trade log panel with recent trades."""
        trade_log = self.bot.get_trade_log(limit=30)
        
        self.trade_log_count.configure(text=f"{len(trade_log)} recent trades")
        
        self.trade_log_text.configure(state=tk.NORMAL)
        self.trade_log_text.delete(1.0, tk.END)
        
        if not trade_log:
            self.trade_log_text.insert(tk.END, "No trades yet.\n", "timestamp")
            self.trade_log_text.insert(tk.END, "When the bot makes trades, they will appear here with:\n")
            self.trade_log_text.insert(tk.END, "• Buy/Sell action\n")
            self.trade_log_text.insert(tk.END, "• Amount traded\n")
            self.trade_log_text.insert(tk.END, "• P&L outcome\n")
            self.trade_log_text.configure(state=tk.DISABLED)
            return
        
        for entry in trade_log:
            # Parse timestamp
            try:
                ts = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
                time_str = ts.strftime("%H:%M:%S")
            except:
                time_str = entry['timestamp'][:8]
            
            # Format based on action
            if entry['action'] == "BUY":
                self.trade_log_text.insert(tk.END, f"[{time_str}] ", "timestamp")
                self.trade_log_text.insert(tk.END, "BUY ", "buy")
                self.trade_log_text.insert(tk.END, f"${entry['amount']:.0f} ", "amount")
                self.trade_log_text.insert(tk.END, f"@ ${entry['price']:.3f}\n")
                # Question on next line
                q_text = entry['question'][:45] + "..." if len(entry['question']) > 45 else entry['question']
                self.trade_log_text.insert(tk.END, f"         {q_text}\n", "timestamp")
            
            elif entry['action'] == "SELL":
                self.trade_log_text.insert(tk.END, f"[{time_str}] ", "timestamp")
                
                result = entry.get('result', 'UNKNOWN')
                pnl = entry.get('pnl', 0)
                
                if result == "WIN":
                    self.trade_log_text.insert(tk.END, "SELL ", "sell_win")
                    self.trade_log_text.insert(tk.END, f"${entry['amount']:.0f} ", "amount")
                    self.trade_log_text.insert(tk.END, "→ ", "timestamp")
                    self.trade_log_text.insert(tk.END, f"+${pnl:.2f} ✓\n", "pnl_pos")
                else:
                    self.trade_log_text.insert(tk.END, "SELL ", "sell_loss")
                    self.trade_log_text.insert(tk.END, f"${entry['amount']:.0f} ", "amount")
                    self.trade_log_text.insert(tk.END, "→ ", "timestamp")
                    self.trade_log_text.insert(tk.END, f"-${abs(pnl):.2f} ✗\n", "pnl_neg")
                
                q_text = entry['question'][:45] + "..." if len(entry['question']) > 45 else entry['question']
                self.trade_log_text.insert(tk.END, f"         {q_text}\n", "timestamp")
        
        self.trade_log_text.configure(state=tk.DISABLED)
        self.trade_log_text.see(tk.END)
    
    def _show_settings(self) -> None:
        """Show settings dialog."""
        dialog = tk.Toplevel(self)
        dialog.title("Settings")
        dialog.geometry("400x500")
        dialog.configure(bg=Theme.BG_SECONDARY)
        dialog.transient(self)
        
        tk.Label(
            dialog,
            text="Bot Settings",
            font=("Segoe UI", 16, "bold"),
            bg=Theme.BG_SECONDARY,
            fg=Theme.TEXT_PRIMARY,
        ).pack(pady=20)
        
        # Stats
        stats = self.bot.get_stats()
        
        info_frame = tk.Frame(dialog, bg=Theme.BG_CARD)
        info_frame.pack(fill=tk.X, padx=20, pady=10)
        
        for label, value in [
            ("Total Trades", str(stats['total_trades'])),
            ("Winning Trades", str(stats['winning_trades'])),
            ("Losing Trades", str(stats['losing_trades'])),
            ("Win Rate", f"{stats['win_rate']:.1f}%"),
            ("Cash Balance", f"${stats['cash_balance']:,.2f}"),
        ]:
            row = tk.Frame(info_frame, bg=Theme.BG_CARD)
            row.pack(fill=tk.X, padx=10, pady=3)
            tk.Label(row, text=label, bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY, 
                    font=("Segoe UI", 10)).pack(side=tk.LEFT)
            tk.Label(row, text=value, bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                    font=("Segoe UI", 10, "bold")).pack(side=tk.RIGHT)
        
        # Reset button
        def reset():
            if messagebox.askyesno("Confirm", "Reset bot? This will clear all trades and positions."):
                self.bot.reset()
                self._update_stats()
                self._update_positions_display()
                self.chat.add_message("Bot has been reset to initial state", "info", "Reset")
                dialog.destroy()
        
        tk.Button(
            dialog,
            text="Reset Bot",
            font=("Segoe UI", 10),
            bg=Theme.ACCENT_RED,
            fg=Theme.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=20,
            pady=8,
            command=reset,
        ).pack(pady=20)
    
    def _start_updates(self) -> None:
        """Start periodic UI updates - faster refresh for real-time feel."""
        self._update_counter = 0
        
        def update():
            self._update_counter += 1
            
            # ALWAYS update positions to get fresh prices (even when bot not running)
            # This ensures P&L is always calculated with current market prices
            try:
                self.bot.update_positions()
            except Exception:
                pass
            
            # Update stats every tick (2 seconds) - lightweight operation
            self._update_stats()
            
            # Update positions every 2 ticks (4 seconds) - heavier operation
            if self._update_counter % 2 == 0:
                self._update_positions_display()
                self._update_stats_dashboard()
            
            # Update trade log every 3 ticks (6 seconds)
            if self._update_counter % 3 == 0:
                self._update_trade_log_display()
            
            # Update alerts every 4 ticks (8 seconds)
            if self._update_counter % 4 == 0:
                self._update_alerts_display()
            
            # Refresh: 2 seconds
            self.after(2000, update)
        
        # Initial updates
        self._update_trade_log_display()
        self._update_stats_dashboard()
        self.after(2000, update)
    
    def _load_markets(self) -> None:
        """Load saved markets."""
        if MARKETS_PATH.exists():
            try:
                self.tracked_markets = json.loads(MARKETS_PATH.read_text())
                self._update_markets_display()
            except Exception:
                pass
    
    def _save_markets(self) -> None:
        """Save tracked markets."""
        try:
            # Convert to JSON-serializable format
            data = {}
            for k, v in self.tracked_markets.items():
                data[k] = {key: val for key, val in v.items() if key != "metadata"}
            MARKETS_PATH.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
    
    def destroy(self) -> None:
        """Clean up on close."""
        self.bot.stop()
        self._save_markets()
        super().destroy()


def main():
    app = TradingBotApp()
    app.mainloop()


if __name__ == "__main__":
    main()
