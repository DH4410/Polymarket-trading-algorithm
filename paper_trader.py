"""Paper trading simulation engine for Polymarket."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum


class TradeAction(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class PaperPosition:
    """Represents a paper trading position."""
    market_id: str
    outcome: str
    question: str
    shares: float
    average_price: float
    entry_timestamp: str
    current_price: Optional[float] = None
    current_bid: Optional[float] = None
    current_ask: Optional[float] = None
    resolution_datetime: Optional[str] = None
    
    @property
    def cost_basis(self) -> float:
        return self.shares * self.average_price
    
    @property
    def market_value(self) -> float:
        price = self.current_bid or self.current_price or self.average_price
        return self.shares * price
    
    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis
    
    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis <= 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100
    
    def key(self) -> str:
        return f"{self.market_id}|{self.outcome}"
    
    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "outcome": self.outcome,
            "question": self.question,
            "shares": self.shares,
            "average_price": self.average_price,
            "entry_timestamp": self.entry_timestamp,
            "current_price": self.current_price,
            "current_bid": self.current_bid,
            "current_ask": self.current_ask,
            "resolution_datetime": self.resolution_datetime,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> "PaperPosition":
        return PaperPosition(**data)


@dataclass
class PaperTrade:
    """Represents a single paper trade."""
    id: str
    timestamp: str
    action: TradeAction
    market_id: str
    outcome: str
    question: str
    shares: float
    price: float
    value: float
    fees: float = 0.0
    slippage_bps: float = 0.0
    notes: str = ""
    pnl: Optional[float] = None  # For sell trades
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "market_id": self.market_id,
            "outcome": self.outcome,
            "question": self.question,
            "shares": self.shares,
            "price": self.price,
            "value": self.value,
            "fees": self.fees,
            "slippage_bps": self.slippage_bps,
            "notes": self.notes,
            "pnl": self.pnl,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> "PaperTrade":
        return PaperTrade(
            id=data["id"],
            timestamp=data["timestamp"],
            action=TradeAction(data["action"]),
            market_id=data["market_id"],
            outcome=data["outcome"],
            question=data["question"],
            shares=data["shares"],
            price=data["price"],
            value=data["value"],
            fees=data.get("fees", 0.0),
            slippage_bps=data.get("slippage_bps", 0.0),
            notes=data.get("notes", ""),
            pnl=data.get("pnl"),
        )


@dataclass
class PaperPortfolio:
    """Paper trading portfolio state."""
    initial_capital: float = 10000.0
    cash_balance: float = 10000.0
    positions: Dict[str, PaperPosition] = field(default_factory=dict)
    trade_history: List[PaperTrade] = field(default_factory=list)
    realized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    created_at: str = ""
    
    @property
    def total_position_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())
    
    @property
    def total_value(self) -> float:
        return self.cash_balance + self.total_position_value
    
    @property
    def total_pnl(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.realized_pnl + unrealized
    
    @property
    def total_pnl_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return (self.total_pnl / self.initial_capital) * 100
    
    @property
    def win_rate(self) -> float:
        if self.total_trades <= 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    def to_dict(self) -> Dict:
        return {
            "initial_capital": self.initial_capital,
            "cash_balance": self.cash_balance,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "trade_history": [t.to_dict() for t in self.trade_history],
            "realized_pnl": self.realized_pnl,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "created_at": self.created_at,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> "PaperPortfolio":
        portfolio = PaperPortfolio(
            initial_capital=data.get("initial_capital", 10000.0),
            cash_balance=data.get("cash_balance", 10000.0),
            realized_pnl=data.get("realized_pnl", 0.0),
            total_trades=data.get("total_trades", 0),
            winning_trades=data.get("winning_trades", 0),
            losing_trades=data.get("losing_trades", 0),
            created_at=data.get("created_at", ""),
        )
        portfolio.positions = {
            k: PaperPosition.from_dict(v) 
            for k, v in data.get("positions", {}).items()
        }
        portfolio.trade_history = [
            PaperTrade.from_dict(t) 
            for t in data.get("trade_history", [])
        ]
        return portfolio


class PaperTrader:
    """Paper trading engine that simulates trades without real money."""
    
    EXCHANGE_FEE = 0.02  # 2% fee on winning trades
    
    def __init__(self, storage_path: Optional[Path] = None, initial_capital: float = 10000.0):
        self.storage_path = storage_path or Path("paper_portfolio.json")
        self.portfolio: PaperPortfolio = self._load_or_create(initial_capital)
        self._trade_counter = len(self.portfolio.trade_history)
    
    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    
    def _generate_trade_id(self) -> str:
        self._trade_counter += 1
        return f"paper_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{self._trade_counter}"
    
    def _load_or_create(self, initial_capital: float) -> PaperPortfolio:
        """Load existing portfolio or create new one."""
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text())
                return PaperPortfolio.from_dict(data)
            except Exception:
                pass
        
        return PaperPortfolio(
            initial_capital=initial_capital,
            cash_balance=initial_capital,
            created_at=self._now_iso(),
        )
    
    def save(self) -> None:
        """Persist portfolio to disk."""
        try:
            self.storage_path.write_text(
                json.dumps(self.portfolio.to_dict(), indent=2)
            )
        except Exception as e:
            print(f"Failed to save paper portfolio: {e}")
    
    def reset(self, initial_capital: float = 10000.0) -> None:
        """Reset the paper portfolio."""
        self.portfolio = PaperPortfolio(
            initial_capital=initial_capital,
            cash_balance=initial_capital,
            created_at=self._now_iso(),
        )
        self._trade_counter = 0
        self.save()
    
    def buy(
        self,
        market_id: str,
        outcome: str,
        question: str,
        shares: float,
        price: float,
        resolution_datetime: Optional[str] = None,
        notes: str = "",
    ) -> Tuple[bool, str, Optional[PaperTrade]]:
        """
        Execute a paper buy order.
        
        Returns: (success, message, trade)
        """
        if shares <= 0:
            return False, "Shares must be positive", None
        
        if price <= 0 or price >= 1:
            return False, "Price must be between 0 and 1", None
        
        cost = shares * price
        
        if cost > self.portfolio.cash_balance:
            return False, f"Insufficient funds. Need ${cost:.2f}, have ${self.portfolio.cash_balance:.2f}", None
        
        # Deduct cash
        self.portfolio.cash_balance -= cost
        
        # Update or create position
        key = f"{market_id}|{outcome}"
        if key in self.portfolio.positions:
            pos = self.portfolio.positions[key]
            # Average up/down
            total_cost = pos.cost_basis + cost
            total_shares = pos.shares + shares
            pos.average_price = total_cost / total_shares
            pos.shares = total_shares
        else:
            self.portfolio.positions[key] = PaperPosition(
                market_id=market_id,
                outcome=outcome,
                question=question,
                shares=shares,
                average_price=price,
                entry_timestamp=self._now_iso(),
                current_price=price,
                current_ask=price,
                resolution_datetime=resolution_datetime,
            )
        
        # Record trade
        trade = PaperTrade(
            id=self._generate_trade_id(),
            timestamp=self._now_iso(),
            action=TradeAction.BUY,
            market_id=market_id,
            outcome=outcome,
            question=question,
            shares=shares,
            price=price,
            value=cost,
            notes=notes,
        )
        self.portfolio.trade_history.append(trade)
        
        self.save()
        return True, f"Bought {shares:.2f} shares at ${price:.4f}", trade
    
    def sell(
        self,
        market_id: str,
        outcome: str,
        shares: float,
        price: float,
        notes: str = "",
    ) -> Tuple[bool, str, Optional[PaperTrade]]:
        """
        Execute a paper sell order.
        
        Returns: (success, message, trade)
        """
        key = f"{market_id}|{outcome}"
        
        if key not in self.portfolio.positions:
            return False, "No position to sell", None
        
        pos = self.portfolio.positions[key]
        
        if shares > pos.shares:
            return False, f"Cannot sell {shares:.2f} shares, only have {pos.shares:.2f}", None
        
        if shares <= 0:
            return False, "Shares must be positive", None
        
        # Calculate proceeds and P&L
        proceeds = shares * price
        cost_basis = shares * pos.average_price
        pnl = proceeds - cost_basis
        
        # Update cash
        self.portfolio.cash_balance += proceeds
        
        # Update realized P&L
        self.portfolio.realized_pnl += pnl
        self.portfolio.total_trades += 1
        if pnl >= 0:
            self.portfolio.winning_trades += 1
        else:
            self.portfolio.losing_trades += 1
        
        # Update position
        pos.shares -= shares
        if pos.shares <= 0.0001:
            del self.portfolio.positions[key]
        
        # Record trade
        trade = PaperTrade(
            id=self._generate_trade_id(),
            timestamp=self._now_iso(),
            action=TradeAction.SELL,
            market_id=market_id,
            outcome=outcome,
            question=pos.question,
            shares=shares,
            price=price,
            value=proceeds,
            notes=notes,
            pnl=pnl,
        )
        self.portfolio.trade_history.append(trade)
        
        self.save()
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        return True, f"Sold {shares:.2f} shares at ${price:.4f} (P&L: {pnl_str})", trade
    
    def sell_all(self, market_id: str, outcome: str, price: float, notes: str = "") -> Tuple[bool, str, Optional[PaperTrade]]:
        """Sell entire position."""
        key = f"{market_id}|{outcome}"
        if key not in self.portfolio.positions:
            return False, "No position to sell", None
        
        shares = self.portfolio.positions[key].shares
        return self.sell(market_id, outcome, shares, price, notes)
    
    def update_position_prices(
        self,
        market_id: str,
        outcome: str,
        current_price: Optional[float] = None,
        current_bid: Optional[float] = None,
        current_ask: Optional[float] = None,
    ) -> None:
        """Update current market prices for a position."""
        key = f"{market_id}|{outcome}"
        if key in self.portfolio.positions:
            pos = self.portfolio.positions[key]
            if current_price is not None:
                pos.current_price = current_price
            if current_bid is not None:
                pos.current_bid = current_bid
            if current_ask is not None:
                pos.current_ask = current_ask
            self.save()
    
    def get_position(self, market_id: str, outcome: str) -> Optional[PaperPosition]:
        """Get a specific position."""
        key = f"{market_id}|{outcome}"
        return self.portfolio.positions.get(key)
    
    def get_all_positions(self) -> List[PaperPosition]:
        """Get all open positions."""
        return list(self.portfolio.positions.values())
    
    def get_trade_history(self, limit: int = 50) -> List[PaperTrade]:
        """Get recent trade history."""
        return list(reversed(self.portfolio.trade_history[-limit:]))
    
    def get_summary(self) -> Dict:
        """Get portfolio summary statistics."""
        return {
            "initial_capital": self.portfolio.initial_capital,
            "cash_balance": self.portfolio.cash_balance,
            "position_value": self.portfolio.total_position_value,
            "total_value": self.portfolio.total_value,
            "realized_pnl": self.portfolio.realized_pnl,
            "unrealized_pnl": sum(p.unrealized_pnl for p in self.portfolio.positions.values()),
            "total_pnl": self.portfolio.total_pnl,
            "total_pnl_pct": self.portfolio.total_pnl_pct,
            "total_trades": self.portfolio.total_trades,
            "winning_trades": self.portfolio.winning_trades,
            "losing_trades": self.portfolio.losing_trades,
            "win_rate": self.portfolio.win_rate,
            "open_positions": len(self.portfolio.positions),
            "created_at": self.portfolio.created_at,
        }


def calculate_simulated_fill(
    asks: List[Tuple[float, float]],
    target_value: float,
) -> Tuple[float, float, float]:
    """
    Simulate filling an order against an order book.
    
    Returns: (shares, avg_price, slippage_bps)
    """
    if not asks or target_value <= 0:
        return 0.0, 0.0, 0.0
    
    best_price = asks[0][0]
    total_cost = 0.0
    total_shares = 0.0
    remaining_value = target_value
    
    for price, size in asks:
        if price <= 0 or size <= 0:
            continue
        
        level_value = price * size
        take_value = min(level_value, remaining_value)
        
        if take_value <= 0:
            break
        
        shares = take_value / price
        total_cost += price * shares
        total_shares += shares
        remaining_value -= take_value
        
        if remaining_value <= 1e-9:
            break
    
    if total_shares <= 0:
        return 0.0, 0.0, 0.0
    
    avg_price = total_cost / total_shares
    slippage_bps = ((avg_price / best_price) - 1.0) * 10000 if best_price else 0.0
    
    return total_shares, avg_price, slippage_bps
