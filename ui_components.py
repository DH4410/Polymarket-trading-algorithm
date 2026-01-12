"""Modern UI components for the Polymarket trading application."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from datetime import datetime
from typing import Callable, Dict, List, Optional
from enum import Enum


# Modern color scheme
class Colors:
    # Backgrounds
    BG_DARK = "#1a1a2e"
    BG_MEDIUM = "#16213e"
    BG_LIGHT = "#0f3460"
    BG_CARD = "#1f2937"
    BG_INPUT = "#374151"
    
    # Accents
    PRIMARY = "#3b82f6"
    PRIMARY_HOVER = "#2563eb"
    SUCCESS = "#10b981"
    WARNING = "#f59e0b"
    ERROR = "#ef4444"
    INFO = "#06b6d4"
    
    # Text
    TEXT_PRIMARY = "#f9fafb"
    TEXT_SECONDARY = "#9ca3af"
    TEXT_MUTED = "#6b7280"
    
    # Borders
    BORDER = "#374151"
    BORDER_LIGHT = "#4b5563"
    
    # Special
    PROFIT = "#10b981"
    LOSS = "#ef4444"
    NEUTRAL = "#6b7280"


class MessageType(Enum):
    BOT = "bot"
    USER = "user"
    SYSTEM = "system"
    TRADE = "trade"
    ALERT = "alert"
    SUCCESS = "success"
    ERROR = "error"


def configure_dark_theme(root: tk.Tk) -> ttk.Style:
    """Configure a modern dark theme for ttk widgets."""
    style = ttk.Style()
    
    # Try to use a modern theme base
    try:
        style.theme_use("clam")
    except Exception:
        pass
    
    # Configure colors
    style.configure(".", 
        background=Colors.BG_DARK,
        foreground=Colors.TEXT_PRIMARY,
        fieldbackground=Colors.BG_INPUT,
        bordercolor=Colors.BORDER,
        darkcolor=Colors.BG_DARK,
        lightcolor=Colors.BG_LIGHT,
    )
    
    # Frame styles
    style.configure("TFrame", background=Colors.BG_DARK)
    style.configure("Card.TFrame", background=Colors.BG_CARD)
    style.configure("Dark.TFrame", background=Colors.BG_MEDIUM)
    
    # Label styles
    style.configure("TLabel", 
        background=Colors.BG_DARK, 
        foreground=Colors.TEXT_PRIMARY
    )
    style.configure("Header.TLabel", 
        background=Colors.BG_DARK, 
        foreground=Colors.TEXT_PRIMARY,
        font=("Segoe UI", 14, "bold")
    )
    style.configure("Title.TLabel",
        background=Colors.BG_DARK,
        foreground=Colors.TEXT_PRIMARY,
        font=("Segoe UI", 18, "bold")
    )
    style.configure("Subtitle.TLabel",
        background=Colors.BG_DARK,
        foreground=Colors.TEXT_SECONDARY,
        font=("Segoe UI", 10)
    )
    style.configure("Card.TLabel",
        background=Colors.BG_CARD,
        foreground=Colors.TEXT_PRIMARY
    )
    style.configure("Success.TLabel",
        foreground=Colors.SUCCESS
    )
    style.configure("Error.TLabel",
        foreground=Colors.ERROR
    )
    style.configure("Warning.TLabel",
        foreground=Colors.WARNING
    )
    
    # Button styles
    style.configure("TButton",
        background=Colors.PRIMARY,
        foreground=Colors.TEXT_PRIMARY,
        borderwidth=0,
        focuscolor=Colors.PRIMARY_HOVER,
        padding=(12, 6),
    )
    style.map("TButton",
        background=[("active", Colors.PRIMARY_HOVER), ("pressed", Colors.PRIMARY)],
    )
    
    style.configure("Success.TButton",
        background=Colors.SUCCESS,
    )
    style.configure("Danger.TButton",
        background=Colors.ERROR,
    )
    style.configure("Secondary.TButton",
        background=Colors.BG_LIGHT,
    )
    
    # Entry styles
    style.configure("TEntry",
        fieldbackground=Colors.BG_INPUT,
        foreground=Colors.TEXT_PRIMARY,
        bordercolor=Colors.BORDER,
        insertcolor=Colors.TEXT_PRIMARY,
        padding=8,
    )
    
    # Treeview styles
    style.configure("Treeview",
        background=Colors.BG_CARD,
        foreground=Colors.TEXT_PRIMARY,
        fieldbackground=Colors.BG_CARD,
        borderwidth=0,
        rowheight=32,
    )
    style.configure("Treeview.Heading",
        background=Colors.BG_MEDIUM,
        foreground=Colors.TEXT_PRIMARY,
        borderwidth=0,
        padding=8,
    )
    style.map("Treeview",
        background=[("selected", Colors.PRIMARY)],
        foreground=[("selected", Colors.TEXT_PRIMARY)],
    )
    
    # Notebook styles
    style.configure("TNotebook",
        background=Colors.BG_DARK,
        borderwidth=0,
    )
    style.configure("TNotebook.Tab",
        background=Colors.BG_MEDIUM,
        foreground=Colors.TEXT_SECONDARY,
        padding=(16, 8),
        borderwidth=0,
    )
    style.map("TNotebook.Tab",
        background=[("selected", Colors.BG_LIGHT)],
        foreground=[("selected", Colors.TEXT_PRIMARY)],
    )
    
    # Scrollbar
    style.configure("TScrollbar",
        background=Colors.BG_MEDIUM,
        troughcolor=Colors.BG_DARK,
        borderwidth=0,
        arrowcolor=Colors.TEXT_SECONDARY,
    )
    
    # Checkbox
    style.configure("TCheckbutton",
        background=Colors.BG_DARK,
        foreground=Colors.TEXT_PRIMARY,
    )
    
    # Combobox
    style.configure("TCombobox",
        fieldbackground=Colors.BG_INPUT,
        background=Colors.BG_INPUT,
        foreground=Colors.TEXT_PRIMARY,
        arrowcolor=Colors.TEXT_PRIMARY,
    )
    
    # LabelFrame
    style.configure("TLabelframe",
        background=Colors.BG_DARK,
        foreground=Colors.TEXT_PRIMARY,
        bordercolor=Colors.BORDER,
    )
    style.configure("TLabelframe.Label",
        background=Colors.BG_DARK,
        foreground=Colors.TEXT_PRIMARY,
        font=("Segoe UI", 10, "bold"),
    )
    
    return style


class ChatMessage:
    """Represents a single message in the chat feed."""
    def __init__(
        self,
        message: str,
        msg_type: MessageType = MessageType.BOT,
        timestamp: Optional[str] = None,
        title: Optional[str] = None,
        data: Optional[Dict] = None,
    ):
        self.message = message
        self.type = msg_type
        self.timestamp = timestamp or datetime.now().strftime("%H:%M:%S")
        self.title = title
        self.data = data or {}


class ChatFeed(tk.Frame):
    """A chat-style activity feed widget."""
    
    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, bg=Colors.BG_DARK, **kwargs)
        
        self.messages: List[ChatMessage] = []
        self.max_messages = 200
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        # Header
        header = tk.Frame(self, bg=Colors.BG_MEDIUM)
        header.pack(fill=tk.X, padx=2, pady=2)
        
        tk.Label(
            header,
            text="🤖 Trading Bot Activity",
            font=("Segoe UI", 12, "bold"),
            bg=Colors.BG_MEDIUM,
            fg=Colors.TEXT_PRIMARY,
            pady=8,
            padx=10,
        ).pack(side=tk.LEFT)
        
        self.status_label = tk.Label(
            header,
            text="● Online",
            font=("Segoe UI", 9),
            bg=Colors.BG_MEDIUM,
            fg=Colors.SUCCESS,
            pady=8,
            padx=10,
        )
        self.status_label.pack(side=tk.RIGHT)
        
        # Chat container with scrollbar
        container = tk.Frame(self, bg=Colors.BG_DARK)
        container.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        self.canvas = tk.Canvas(
            container,
            bg=Colors.BG_DARK,
            highlightthickness=0,
            borderwidth=0,
        )
        
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        
        self.messages_frame = tk.Frame(self.canvas, bg=Colors.BG_DARK)
        
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.messages_frame,
            anchor="nw",
        )
        
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Bind events
        self.messages_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
    
    def _on_frame_configure(self, event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        # Auto-scroll to bottom
        self.canvas.yview_moveto(1.0)
    
    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfig(self.canvas_window, width=event.width - 4)
    
    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def add_message(self, message: ChatMessage) -> None:
        """Add a new message to the feed."""
        self.messages.append(message)
        
        # Trim old messages
        if len(self.messages) > self.max_messages:
            # Remove oldest widget
            children = self.messages_frame.winfo_children()
            if children:
                children[0].destroy()
            self.messages = self.messages[-self.max_messages:]
        
        self._render_message(message)
    
    def _render_message(self, msg: ChatMessage) -> None:
        """Render a message widget."""
        # Message container
        msg_frame = tk.Frame(self.messages_frame, bg=Colors.BG_DARK)
        msg_frame.pack(fill=tk.X, padx=8, pady=4)
        
        # Get colors based on type
        colors = self._get_message_colors(msg.type)
        
        # Message bubble
        bubble = tk.Frame(msg_frame, bg=colors["bg"])
        bubble.pack(fill=tk.X, padx=4, pady=2)
        
        # Header row (timestamp + title)
        header = tk.Frame(bubble, bg=colors["bg"])
        header.pack(fill=tk.X, padx=8, pady=(6, 2))
        
        # Icon/emoji based on type
        icon = self._get_type_icon(msg.type)
        tk.Label(
            header,
            text=icon,
            font=("Segoe UI Emoji", 10),
            bg=colors["bg"],
            fg=colors["accent"],
        ).pack(side=tk.LEFT)
        
        if msg.title:
            tk.Label(
                header,
                text=msg.title,
                font=("Segoe UI", 9, "bold"),
                bg=colors["bg"],
                fg=colors["accent"],
            ).pack(side=tk.LEFT, padx=(4, 0))
        
        tk.Label(
            header,
            text=msg.timestamp,
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=Colors.TEXT_MUTED,
        ).pack(side=tk.RIGHT)
        
        # Message content
        content = tk.Label(
            bubble,
            text=msg.message,
            font=("Segoe UI", 10),
            bg=colors["bg"],
            fg=colors["fg"],
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        content.pack(fill=tk.X, padx=8, pady=(2, 6))
        
        # Auto-scroll to bottom
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)
    
    def _get_message_colors(self, msg_type: MessageType) -> Dict[str, str]:
        """Get colors for message type."""
        if msg_type == MessageType.SUCCESS:
            return {"bg": "#064e3b", "fg": Colors.TEXT_PRIMARY, "accent": Colors.SUCCESS}
        elif msg_type == MessageType.ERROR:
            return {"bg": "#7f1d1d", "fg": Colors.TEXT_PRIMARY, "accent": Colors.ERROR}
        elif msg_type == MessageType.ALERT:
            return {"bg": "#78350f", "fg": Colors.TEXT_PRIMARY, "accent": Colors.WARNING}
        elif msg_type == MessageType.TRADE:
            return {"bg": "#1e3a5f", "fg": Colors.TEXT_PRIMARY, "accent": Colors.PRIMARY}
        elif msg_type == MessageType.SYSTEM:
            return {"bg": Colors.BG_MEDIUM, "fg": Colors.TEXT_SECONDARY, "accent": Colors.TEXT_MUTED}
        else:  # BOT, USER
            return {"bg": Colors.BG_CARD, "fg": Colors.TEXT_PRIMARY, "accent": Colors.INFO}
    
    def _get_type_icon(self, msg_type: MessageType) -> str:
        """Get icon for message type."""
        icons = {
            MessageType.BOT: "🤖",
            MessageType.USER: "👤",
            MessageType.SYSTEM: "⚙️",
            MessageType.TRADE: "📈",
            MessageType.ALERT: "🚨",
            MessageType.SUCCESS: "✅",
            MessageType.ERROR: "❌",
        }
        return icons.get(msg_type, "💬")
    
    def set_status(self, text: str, color: str = Colors.SUCCESS) -> None:
        """Update the status indicator."""
        self.status_label.configure(text=f"● {text}", fg=color)
    
    def clear(self) -> None:
        """Clear all messages."""
        for widget in self.messages_frame.winfo_children():
            widget.destroy()
        self.messages = []


class MarketCard(tk.Frame):
    """A card widget displaying market information."""
    
    def __init__(
        self,
        parent: tk.Widget,
        market_id: str,
        question: str,
        outcome: str,
        price: float,
        change_pct: float = 0.0,
        volume: float = 0.0,
        on_click: Optional[Callable] = None,
        **kwargs
    ):
        super().__init__(parent, bg=Colors.BG_CARD, **kwargs)
        
        self.market_id = market_id
        self.on_click = on_click
        
        self._build_ui(question, outcome, price, change_pct, volume)
        
        if on_click:
            self.bind("<Button-1>", lambda e: on_click(market_id))
            self.bind("<Enter>", lambda e: self.configure(bg=Colors.BG_LIGHT))
            self.bind("<Leave>", lambda e: self.configure(bg=Colors.BG_CARD))
    
    def _build_ui(self, question: str, outcome: str, price: float, change_pct: float, volume: float) -> None:
        # Padding frame
        inner = tk.Frame(self, bg=Colors.BG_CARD)
        inner.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        
        # Question (truncated)
        display_question = question[:50] + "..." if len(question) > 50 else question
        tk.Label(
            inner,
            text=display_question,
            font=("Segoe UI", 10, "bold"),
            bg=Colors.BG_CARD,
            fg=Colors.TEXT_PRIMARY,
            anchor="w",
            wraplength=250,
        ).pack(fill=tk.X)
        
        # Outcome badge
        badge_frame = tk.Frame(inner, bg=Colors.BG_CARD)
        badge_frame.pack(fill=tk.X, pady=(4, 0))
        
        badge = tk.Label(
            badge_frame,
            text=outcome,
            font=("Segoe UI", 8),
            bg=Colors.PRIMARY,
            fg=Colors.TEXT_PRIMARY,
            padx=6,
            pady=2,
        )
        badge.pack(side=tk.LEFT)
        
        # Price and change
        price_frame = tk.Frame(inner, bg=Colors.BG_CARD)
        price_frame.pack(fill=tk.X, pady=(8, 0))
        
        tk.Label(
            price_frame,
            text=f"${price:.3f}",
            font=("Segoe UI", 16, "bold"),
            bg=Colors.BG_CARD,
            fg=Colors.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        
        change_color = Colors.PROFIT if change_pct >= 0 else Colors.LOSS
        change_text = f"+{change_pct:.1f}%" if change_pct >= 0 else f"{change_pct:.1f}%"
        tk.Label(
            price_frame,
            text=change_text,
            font=("Segoe UI", 10),
            bg=Colors.BG_CARD,
            fg=change_color,
        ).pack(side=tk.LEFT, padx=(8, 0))
        
        # Volume
        if volume > 0:
            tk.Label(
                inner,
                text=f"Vol: ${volume:,.0f}",
                font=("Segoe UI", 9),
                bg=Colors.BG_CARD,
                fg=Colors.TEXT_MUTED,
            ).pack(fill=tk.X, pady=(4, 0), anchor="w")


class StatCard(tk.Frame):
    """A card widget displaying a statistic."""
    
    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        value: str,
        subtitle: str = "",
        color: str = Colors.TEXT_PRIMARY,
        **kwargs
    ):
        super().__init__(parent, bg=Colors.BG_CARD, **kwargs)
        
        self.title_var = tk.StringVar(value=title)
        self.value_var = tk.StringVar(value=value)
        self.subtitle_var = tk.StringVar(value=subtitle)
        
        self._build_ui(color)
    
    def _build_ui(self, color: str) -> None:
        inner = tk.Frame(self, bg=Colors.BG_CARD)
        inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        
        tk.Label(
            inner,
            textvariable=self.title_var,
            font=("Segoe UI", 9),
            bg=Colors.BG_CARD,
            fg=Colors.TEXT_SECONDARY,
        ).pack(anchor="w")
        
        self.value_label = tk.Label(
            inner,
            textvariable=self.value_var,
            font=("Segoe UI", 20, "bold"),
            bg=Colors.BG_CARD,
            fg=color,
        )
        self.value_label.pack(anchor="w", pady=(4, 0))
        
        tk.Label(
            inner,
            textvariable=self.subtitle_var,
            font=("Segoe UI", 9),
            bg=Colors.BG_CARD,
            fg=Colors.TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))
    
    def update(self, value: str, subtitle: str = "", color: Optional[str] = None) -> None:
        """Update the stat values."""
        self.value_var.set(value)
        self.subtitle_var.set(subtitle)
        if color:
            self.value_label.configure(fg=color)


class AlertBadge(tk.Frame):
    """A notification badge widget."""
    
    def __init__(
        self,
        parent: tk.Widget,
        count: int = 0,
        **kwargs
    ):
        super().__init__(parent, bg=Colors.ERROR, **kwargs)
        
        self.count_var = tk.StringVar(value=str(count))
        
        self.label = tk.Label(
            self,
            textvariable=self.count_var,
            font=("Segoe UI", 8, "bold"),
            bg=Colors.ERROR,
            fg=Colors.TEXT_PRIMARY,
            padx=4,
            pady=1,
        )
        self.label.pack()
        
        if count <= 0:
            self.pack_forget()
    
    def set_count(self, count: int) -> None:
        """Update the badge count."""
        self.count_var.set(str(count))
        if count > 0:
            self.pack()
        else:
            self.pack_forget()


class ModernButton(tk.Frame):
    """A modern styled button."""
    
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command: Optional[Callable] = None,
        style: str = "primary",  # primary, success, danger, secondary
        icon: str = "",
        **kwargs
    ):
        bg_color = self._get_bg_color(style)
        hover_color = self._get_hover_color(style)
        
        super().__init__(parent, bg=bg_color, **kwargs)
        
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.command = command
        
        display_text = f"{icon} {text}" if icon else text
        
        self.label = tk.Label(
            self,
            text=display_text,
            font=("Segoe UI", 10),
            bg=bg_color,
            fg=Colors.TEXT_PRIMARY,
            padx=16,
            pady=8,
            cursor="hand2",
        )
        self.label.pack()
        
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.label.bind("<Button-1>", self._on_click)
    
    def _get_bg_color(self, style: str) -> str:
        colors = {
            "primary": Colors.PRIMARY,
            "success": Colors.SUCCESS,
            "danger": Colors.ERROR,
            "secondary": Colors.BG_LIGHT,
            "warning": Colors.WARNING,
        }
        return colors.get(style, Colors.PRIMARY)
    
    def _get_hover_color(self, style: str) -> str:
        colors = {
            "primary": Colors.PRIMARY_HOVER,
            "success": "#059669",
            "danger": "#dc2626",
            "secondary": Colors.BORDER_LIGHT,
            "warning": "#d97706",
        }
        return colors.get(style, Colors.PRIMARY_HOVER)
    
    def _on_enter(self, event) -> None:
        self.configure(bg=self.hover_color)
        self.label.configure(bg=self.hover_color)
    
    def _on_leave(self, event) -> None:
        self.configure(bg=self.bg_color)
        self.label.configure(bg=self.bg_color)
    
    def _on_click(self, event) -> None:
        if self.command:
            self.command()


class SearchEntry(tk.Frame):
    """A search input with icon."""
    
    def __init__(
        self,
        parent: tk.Widget,
        placeholder: str = "Search...",
        on_search: Optional[Callable[[str], None]] = None,
        **kwargs
    ):
        super().__init__(parent, bg=Colors.BG_INPUT, **kwargs)
        
        self.on_search = on_search
        self.placeholder = placeholder
        
        # Search icon
        tk.Label(
            self,
            text="🔍",
            font=("Segoe UI Emoji", 10),
            bg=Colors.BG_INPUT,
            fg=Colors.TEXT_MUTED,
        ).pack(side=tk.LEFT, padx=(8, 4))
        
        # Entry
        self.entry = tk.Entry(
            self,
            font=("Segoe UI", 10),
            bg=Colors.BG_INPUT,
            fg=Colors.TEXT_PRIMARY,
            insertbackground=Colors.TEXT_PRIMARY,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), pady=8)
        
        self.entry.insert(0, placeholder)
        self.entry.configure(fg=Colors.TEXT_MUTED)
        
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<Return>", self._on_enter)
    
    def _on_focus_in(self, event) -> None:
        if self.entry.get() == self.placeholder:
            self.entry.delete(0, tk.END)
            self.entry.configure(fg=Colors.TEXT_PRIMARY)
    
    def _on_focus_out(self, event) -> None:
        if not self.entry.get():
            self.entry.insert(0, self.placeholder)
            self.entry.configure(fg=Colors.TEXT_MUTED)
    
    def _on_enter(self, event) -> None:
        if self.on_search:
            value = self.entry.get()
            if value != self.placeholder:
                self.on_search(value)
    
    def get(self) -> str:
        value = self.entry.get()
        return "" if value == self.placeholder else value
    
    def clear(self) -> None:
        self.entry.delete(0, tk.END)
        self.entry.insert(0, self.placeholder)
        self.entry.configure(fg=Colors.TEXT_MUTED)
