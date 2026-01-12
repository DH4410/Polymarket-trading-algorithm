"""Auto-trading bot that scans markets and makes trading decisions."""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from enum import Enum
from math import log1p

import requests

from polymarket_api import (
    GAMMA_API_BASE,
    CLOB_API_BASE,
    fetch_order_book,
    compute_resolution_days,
)


class BotDecision(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    SKIP = "skip"


@dataclass
class MarketOpportunity:
    """A market opportunity identified by the bot."""
    market_id: str
    slug: str
    question: str
    outcome: str
    token_id: str
    price: float
    resolution_days: float
    end_date: str
    volume: float
    liquidity: float
    g_score: float  # Growth rate metric
    expected_roi: float
    confidence: float
    decision: BotDecision
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "slug": self.slug,
            "question": self.question,
            "outcome": self.outcome,
            "token_id": self.token_id,
            "price": self.price,
            "resolution_days": self.resolution_days,
            "end_date": self.end_date,
            "volume": self.volume,
            "liquidity": self.liquidity,
            "g_score": self.g_score,
            "expected_roi": self.expected_roi,
            "confidence": self.confidence,
            "decision": self.decision.value,
            "reasons": self.reasons,
        }


@dataclass 
class BotTrade:
    """A trade executed by the bot."""
    id: str
    timestamp: str
    market_id: str
    question: str
    outcome: str
    action: str  # buy/sell
    shares: float
    entry_price: float
    current_price: float
    exit_price: Optional[float] = None
    exit_timestamp: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "open"  # open, closed, pending
    trade_type: str = "long"  # "swing" or "long"
    volume: float = 0.0  # Market volume when trade was made
    resolution_days: float = 0.0  # Days to resolution when traded
    
    @property
    def value(self) -> float:
        return self.shares * (self.current_price if self.status == "open" else (self.exit_price or self.entry_price))
    
    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "market_id": self.market_id,
            "question": self.question,
            "outcome": self.outcome,
            "action": self.action,
            "shares": self.shares,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "exit_price": self.exit_price,
            "exit_timestamp": self.exit_timestamp,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "status": self.status,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> "BotTrade":
        return BotTrade(**data)


@dataclass
class BotConfig:
    """Configuration for the auto-trading bot."""
    # Capital
    initial_capital: float = 10000.0
    max_position_size: float = 500.0  # Max per trade
    max_portfolio_pct: float = 0.10  # Max 10% in one market
    
    # Small test trades
    test_trade_size: float = 25.0  # $25 test trades for new opportunities
    test_trade_enabled: bool = True  # Enable small test trades
    
    # Swing trade settings
    swing_trade_enabled: bool = True
    swing_take_profit_pct: float = 0.15  # 15% quick profit for swing
    swing_stop_loss_pct: float = 0.10  # 10% stop loss for swing
    swing_min_volume: float = 50000.0  # Only swing trade on popular markets
    
    # Market filters
    min_price: float = 0.03  # Don't buy below 3 cents
    max_price: float = 0.85  # Don't buy above 85 cents
    min_days: float = 0.1    # Min 0.1 day to resolution (allow quick markets)
    max_days: float = 180.0  # Max 180 days
    min_volume: float = 1000.0  # Min $1000 volume
    min_liquidity: float = 500.0  # Min $500 liquidity
    prefer_high_volume: bool = True  # Prioritize popular markets
    high_volume_threshold: float = 100000.0  # $100k+ is "popular"
    
    # Strategy
    min_g_score: float = 0.0005  # Minimum growth rate (lowered for swing)
    min_expected_roi: float = 0.05  # Min 5% expected ROI (lowered for swing)
    confidence_threshold: float = 0.50  # Lower for more opportunities
    high_confidence_threshold: float = 0.70  # For full-size trades
    
    # Risk management - Long term
    stop_loss_pct: float = 0.25  # 25% stop loss
    take_profit_pct: float = 0.40  # 40% take profit
    
    # Timing
    scan_interval_seconds: int = 30  # Faster scanning (30 sec)
    max_markets_per_scan: int = 150  # Scan more markets
    
    # Positions - NO LIMIT for diversity
    max_positions: int = 50  # Allow up to 50 positions
    max_long_term_positions: int = 20  # Long term (>7 days)
    max_swing_positions: int = 30  # Swing trades (<7 days)
    skip_recently_scanned: bool = False  # Allow re-scanning
    market_cooldown_minutes: int = 5  # Only 5 min cooldown


class AutoTradingBot:
    """
    Auto-trading bot that:
    1. Scans Polymarket for opportunities
    2. Evaluates markets using growth rate (g) metric
    3. Makes buy/sell decisions
    4. Tracks simulated P&L
    """
    
    EXCHANGE_FEE = 0.02  # 2% fee
    
    def __init__(
        self,
        config: Optional[BotConfig] = None,
        storage_path: Optional[Path] = None,
        on_trade: Optional[Callable[[BotTrade], None]] = None,
        on_opportunity: Optional[Callable[[MarketOpportunity], None]] = None,
        on_message: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config or BotConfig()
        self.storage_path = storage_path or Path("bot_state.json")
        
        # Callbacks
        self.on_trade = on_trade
        self.on_opportunity = on_opportunity
        self.on_message = on_message  # (message, type)
        
        # State
        self.cash_balance: float = self.config.initial_capital
        self.open_trades: Dict[str, BotTrade] = {}  # trade_id -> trade
        self.closed_trades: List[BotTrade] = []
        self.scanned_markets: Dict[str, MarketOpportunity] = {}  # market_key -> opportunity
        self.blacklist: set = set()  # Markets to skip
        
        # Stats
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
        self.total_pnl: float = 0.0
        
        # Control
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._trade_counter = 0
        
        # Market tracking for diversity
        self._scanned_times: Dict[str, datetime] = {}  # market_id -> last scan time
        self._market_categories: Dict[str, str] = {}  # market_id -> category
        self._scan_offset: int = 0  # For pagination
        
        self._load()
    
    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    
    def _log(self, message: str, msg_type: str = "info") -> None:
        """Log a message and notify listeners."""
        if self.on_message:
            try:
                self.on_message(message, msg_type)
            except Exception:
                pass
    
    def _generate_trade_id(self) -> str:
        self._trade_counter += 1
        return f"bot_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{self._trade_counter}"
    
    # -------------------------------------------------------------------------
    # Market Scanning
    # -------------------------------------------------------------------------
    
    def scan_markets(self) -> List[MarketOpportunity]:
        """Scan Polymarket for trading opportunities."""
        self._log("Scanning new markets for opportunities...", "info")
        
        opportunities = []
        skipped_owned = 0
        now = datetime.now(timezone.utc)
        
        try:
            # Fetch active markets from Polymarket API
            markets = self._fetch_active_markets()
            
            owned_market_ids = {t.market_id for t in self.open_trades.values()}
            
            for market in markets[:self.config.max_markets_per_scan]:
                try:
                    market_id = market.get("slug") or str(market.get("id"))
                    
                    # Skip if we already own this
                    if market_id in owned_market_ids:
                        skipped_owned += 1
                        continue
                    
                    opportunity = self._evaluate_market(market)
                    if opportunity:
                        # Mark as scanned
                        self._scanned_times[opportunity.market_id] = now
                        
                        opportunities.append(opportunity)
                        self.scanned_markets[f"{opportunity.market_id}|{opportunity.outcome}"] = opportunity
                        
                        if self.on_opportunity:
                            self.on_opportunity(opportunity)
                except Exception as e:
                    continue
            
            # Sort by g_score (best opportunities first)
            opportunities.sort(key=lambda x: x.g_score, reverse=True)
            
            # Log summary
            buy_count = sum(1 for o in opportunities if o.decision == BotDecision.BUY)
            self._log(
                f"Analyzed {len(opportunities)} markets | {buy_count} BUY signals | "
                f"Skipped {skipped_owned} owned | {len(self.open_trades)} positions open",
                "success"
            )
            
            # Clean up old scanned times (keep only last hour)
            cutoff = now - timedelta(hours=1)
            self._scanned_times = {k: v for k, v in self._scanned_times.items() if v > cutoff}
            
        except Exception as e:
            self._log(f"❌ Scan failed: {e}", "error")
        
        return opportunities
    
    def _fetch_active_markets(self) -> List[Dict]:
        """Fetch active markets from Polymarket, prioritizing popular ones."""
        all_markets = []
        
        try:
            # Fetch markets ordered by 24h volume for active trading
            url = f"{GAMMA_API_BASE}/markets"
            params = {
                "active": "true",
                "closed": "false",
                "limit": 100,
                "order": "volume24hr",  # Order by recent volume
                "ascending": "false",
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            all_markets = response.json()
            
            # Also fetch by total volume for established markets
            params2 = {
                "active": "true",
                "closed": "false", 
                "limit": 100,
                "order": "volumeNum",
                "ascending": "false",
            }
            response2 = requests.get(url, params=params2, timeout=15)
            if response2.ok:
                all_markets.extend(response2.json())
            
            # Remove duplicates
            seen = set()
            unique_markets = []
            for m in all_markets:
                mid = m.get("slug") or str(m.get("id"))
                if mid not in seen:
                    seen.add(mid)
                    unique_markets.append(m)
            
            # Filter markets - CRITICAL: Only include markets with FUTURE end dates
            valid_markets = []
            high_volume_markets = []
            swing_candidates = []
            owned_market_ids = {t.market_id for t in self.open_trades.values()}
            now = datetime.now(timezone.utc)
            
            for market in unique_markets:
                end_date_str = market.get("endDate")
                if not end_date_str:
                    continue
                if market.get("closed"):
                    continue
                
                # CRITICAL: Filter out old markets with past end dates
                try:
                    # Parse end date
                    if end_date_str.endswith('Z'):
                        end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                    else:
                        end_dt = datetime.fromisoformat(end_date_str)
                    
                    # Make timezone aware if needed
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    
                    # Skip markets that have already ended
                    if end_dt <= now:
                        continue
                    
                    # Calculate days to resolution
                    resolution_days = (end_dt - now).total_seconds() / 86400.0
                except Exception:
                    continue
                
                market_id = market.get("slug") or str(market.get("id"))
                
                # Skip if we already own this market
                if market_id in owned_market_ids:
                    continue
                
                # Skip recently scanned (cooldown)
                if self.config.skip_recently_scanned and market_id in self._scanned_times:
                    last_scan = self._scanned_times[market_id]
                    if (now - last_scan).total_seconds() < self.config.market_cooldown_minutes * 60:
                        continue
                
                # Get volumes
                volume = float(market.get("volumeNum") or market.get("volume") or 0)
                volume_24h = float(market.get("volume24hr") or 0)
                
                if volume < self.config.min_volume:
                    continue
                
                # Add resolution_days to market for later use
                market['_resolution_days'] = resolution_days
                market['_volume_24h'] = volume_24h
                
                # Categorize by volume and resolution time
                is_swing_candidate = (
                    resolution_days <= 7 and 
                    volume >= self.config.swing_min_volume and
                    volume_24h > 10000  # Active 24h volume
                )
                
                if is_swing_candidate:
                    swing_candidates.append(market)
                elif volume >= self.config.high_volume_threshold:
                    high_volume_markets.append(market)
                else:
                    valid_markets.append(market)
            
            # Sort by 24h volume (most active first)
            swing_candidates.sort(key=lambda x: float(x.get('volume24hr') or 0), reverse=True)
            high_volume_markets.sort(key=lambda x: float(x.get('volume24hr') or 0), reverse=True)
            
            # Shuffle the rest for variety
            random.shuffle(valid_markets)
            
            # Combine: swing candidates first, then popular, then others
            combined = swing_candidates + high_volume_markets + valid_markets
            
            self._log(f"Fetched {len(combined)} markets ({len(swing_candidates)} swing, {len(high_volume_markets)} popular, {len(valid_markets)} others)", "info")
            return combined
            
        except Exception as e:
            self._log(f"Failed to fetch markets: {e}", "error")
            return []
    
    def _evaluate_market(self, market: Dict) -> Optional[MarketOpportunity]:
        """Evaluate a market for trading opportunity."""
        market_id = market.get("slug") or str(market.get("id"))
        question = market.get("question") or market.get("title", "Unknown")
        
        # Skip blacklisted
        if market_id in self.blacklist:
            return None
        
        # Get resolution time
        end_date = market.get("endDate")
        if not end_date:
            return None
        
        try:
            resolution_days = compute_resolution_days(end_date)
        except Exception:
            return None
        
        # Check day bounds
        if resolution_days < self.config.min_days or resolution_days > self.config.max_days:
            return None
        
        # Get token IDs and prices
        outcomes = market.get("outcomes")
        token_ids = market.get("clobTokenIds")
        prices = market.get("outcomePrices")
        
        if not outcomes or not token_ids:
            return None
        
        try:
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if isinstance(prices, str):
                prices = json.loads(prices)
        except Exception:
            return None
        
        # Find best outcome to trade (usually "Yes")
        best_opportunity = None
        best_g = -999
        
        for i, outcome in enumerate(outcomes):
            if i >= len(token_ids):
                break
            
            token_id = str(token_ids[i])
            
            try:
                price = float(prices[i]) if prices and i < len(prices) else None
            except (TypeError, ValueError, IndexError):
                price = None
            
            if price is None:
                # Fetch from order book
                try:
                    book = fetch_order_book(token_id)
                    if book.get("asks"):
                        price = book["asks"][0][0]
                except Exception:
                    continue
            
            if price is None:
                continue
            
            # Check price bounds
            if price < self.config.min_price or price > self.config.max_price:
                continue
            
            # Calculate g (growth rate)
            g_score = self._compute_g(price, resolution_days)
            if g_score is None or g_score < self.config.min_g_score:
                continue
            
            # Calculate expected ROI
            expected_roi = (1 - self.EXCHANGE_FEE) * ((1.0 - price) / price)
            if expected_roi < self.config.min_expected_roi:
                continue
            
            if g_score > best_g:
                best_g = g_score
                
                # Calculate confidence based on various factors
                volume = float(market.get("volumeNum") or market.get("volume") or 0)
                liquidity = float(market.get("liquidity") or volume * 0.1)
                
                confidence = self._calculate_confidence(
                    price=price,
                    volume=volume,
                    liquidity=liquidity,
                    resolution_days=resolution_days,
                    g_score=g_score,
                )
                
                # Determine decision
                decision, reasons = self._make_decision(
                    price=price,
                    g_score=g_score,
                    expected_roi=expected_roi,
                    confidence=confidence,
                    resolution_days=resolution_days,
                )
                
                best_opportunity = MarketOpportunity(
                    market_id=market_id,
                    slug=market.get("slug", market_id),
                    question=question,
                    outcome=outcome,
                    token_id=token_id,
                    price=price,
                    resolution_days=resolution_days,
                    end_date=end_date,
                    volume=volume,
                    liquidity=liquidity,
                    g_score=g_score,
                    expected_roi=expected_roi,
                    confidence=confidence,
                    decision=decision,
                    reasons=reasons,
                )
        
        return best_opportunity
    
    def _compute_g(self, price: float, resolution_days: float, lambda_days: float = 1.0) -> Optional[float]:
        """Compute growth rate metric."""
        if price <= 0 or price >= 1 or resolution_days <= 0:
            return None
        
        r = (1 - self.EXCHANGE_FEE) * ((1.0 - price) / price)
        denom = resolution_days + lambda_days
        
        if denom <= 0:
            return None
        
        return log1p(r) / denom
    
    def _calculate_confidence(
        self,
        price: float,
        volume: float,
        liquidity: float,
        resolution_days: float,
        g_score: float,
    ) -> float:
        """Calculate confidence score (0-1)."""
        score = 0.5  # Base confidence
        
        # Volume factor (higher volume = more confidence)
        if volume > 100000:
            score += 0.15
        elif volume > 50000:
            score += 0.10
        elif volume > 10000:
            score += 0.05
        
        # Liquidity factor
        if liquidity > 10000:
            score += 0.10
        elif liquidity > 5000:
            score += 0.05
        
        # Price factor (mid-range prices are more reliable)
        if 0.20 <= price <= 0.70:
            score += 0.10
        elif 0.10 <= price <= 0.85:
            score += 0.05
        
        # Time factor (not too short, not too long)
        if 7 <= resolution_days <= 30:
            score += 0.10
        elif 3 <= resolution_days <= 60:
            score += 0.05
        
        # G-score factor
        if g_score > 0.01:
            score += 0.05
        
        return min(score, 1.0)
    
    def _make_decision(
        self,
        price: float,
        g_score: float,
        expected_roi: float,
        confidence: float,
        resolution_days: float,
    ) -> Tuple[BotDecision, List[str]]:
        """Make a buy/sell/hold decision."""
        reasons = []
        
        # Check confidence threshold
        if confidence < self.config.confidence_threshold:
            reasons.append(f"Low confidence ({confidence:.1%})")
            return BotDecision.SKIP, reasons
        
        # Strong buy signals
        if g_score > 0.005 and expected_roi > 0.30 and confidence > 0.7:
            reasons.append(f"High g-score: {g_score:.4f}")
            reasons.append(f"Expected ROI: {expected_roi:.1%}")
            reasons.append(f"Good confidence: {confidence:.1%}")
            return BotDecision.BUY, reasons
        
        # Normal buy signals
        if g_score > self.config.min_g_score and expected_roi > self.config.min_expected_roi:
            reasons.append(f"G-score: {g_score:.4f}")
            reasons.append(f"Expected ROI: {expected_roi:.1%}")
            return BotDecision.BUY, reasons
        
        # Hold if we have position
        reasons.append("Doesn't meet buy criteria")
        return BotDecision.HOLD, reasons
    
    # -------------------------------------------------------------------------
    # Trading Execution
    # -------------------------------------------------------------------------
    
    def execute_trade(self, opportunity: MarketOpportunity, force_test: bool = False) -> Optional[BotTrade]:
        """Execute a paper trade based on opportunity."""
        if opportunity.decision != BotDecision.BUY:
            return None
        
        # Determine if this is a swing trade (short-term, high-volume market)
        is_swing = (
            self.config.swing_trade_enabled and
            opportunity.volume >= self.config.swing_min_volume and
            opportunity.resolution_days <= 7
        )
        
        # Count current positions by type
        swing_count = sum(1 for t in self.open_trades.values() if t.trade_type == "swing")
        long_count = sum(1 for t in self.open_trades.values() if t.trade_type == "long")
        
        # Check position limits
        if is_swing and swing_count >= self.config.max_swing_positions:
            return None
        if not is_swing and long_count >= self.config.max_long_term_positions:
            return None
        if len(self.open_trades) >= self.config.max_positions:
            return None
        
        market_key = f"{opportunity.market_id}|{opportunity.outcome}"
        
        # Check if already have position
        for trade in self.open_trades.values():
            if trade.market_id == opportunity.market_id and trade.outcome == opportunity.outcome:
                return None  # Silent skip
        
        # Determine trade size
        is_test_trade = force_test or (
            self.config.test_trade_enabled and 
            opportunity.confidence < self.config.high_confidence_threshold and
            not is_swing  # Swing trades get full size if high volume
        )
        
        if is_test_trade:
            position_value = min(
                self.config.test_trade_size,
                self.cash_balance * 0.03,
            )
            trade_label = "TEST"
        elif is_swing:
            # Swing trades: medium size for quick profit
            position_value = min(
                self.config.max_position_size * 0.5,  # Half size for swing
                self.cash_balance * 0.08,
            )
            trade_label = "SWING"
        else:
            # Long-term: full size
            position_value = min(
                self.config.max_position_size,
                self.cash_balance * self.config.max_portfolio_pct,
                self.cash_balance * 0.2,
            )
            trade_label = "LONG"
        
        if position_value < 5:
            return None
        
        shares = position_value / opportunity.price
        
        trade = BotTrade(
            id=self._generate_trade_id(),
            timestamp=self._now_iso(),
            market_id=opportunity.market_id,
            question=opportunity.question,
            outcome=opportunity.outcome,
            action="buy",
            shares=shares,
            entry_price=opportunity.price,
            current_price=opportunity.price,
            status="open",
            trade_type="swing" if is_swing else "long",
            volume=opportunity.volume,
            resolution_days=opportunity.resolution_days,
        )
        
        self.cash_balance -= position_value
        self.open_trades[trade.id] = trade
        self.total_trades += 1
        
        days_str = f"{opportunity.resolution_days:.1f}d" if opportunity.resolution_days < 30 else f"{opportunity.resolution_days/30:.1f}mo"
        self._log(
            f"[{trade_label}] BOUGHT '{opportunity.question[:30]}...' "
            f"| ${position_value:.0f} @ ${opportunity.price:.3f} | Vol: ${opportunity.volume/1000:.0f}k | {days_str}",
            "trade"
        )
        
        if self.on_trade:
            self.on_trade(trade)
        
        self._save()
        return trade
    
    def update_positions(self) -> None:
        """Update prices and check stop-loss/take-profit for open positions."""
        for trade_id, trade in list(self.open_trades.items()):
            try:
                # Get market key
                market_key = f"{trade.market_id}|{trade.outcome}"
                
                # Get current price - first check scanned markets, then fetch fresh
                current_price = None
                
                if market_key in self.scanned_markets:
                    opp = self.scanned_markets[market_key]
                    current_price = opp.price
                else:
                    # Try to fetch fresh price from API using slug as query param
                    try:
                        url = f"{GAMMA_API_BASE}/markets"
                        response = requests.get(url, params={"slug": trade.market_id}, timeout=5)
                        if response.ok:
                            data = response.json()
                            # Response is a list when using slug param
                            if isinstance(data, list) and len(data) > 0:
                                market_data = data[0]
                            else:
                                market_data = data
                            
                            prices = market_data.get("outcomePrices")
                            outcomes = market_data.get("outcomes")
                            
                            if prices and outcomes:
                                try:
                                    if isinstance(prices, str):
                                        prices = json.loads(prices)
                                    if isinstance(outcomes, str):
                                        outcomes = json.loads(outcomes)
                                    
                                    # Find the matching outcome
                                    for i, outcome in enumerate(outcomes):
                                        if outcome == trade.outcome and i < len(prices):
                                            current_price = float(prices[i])
                                            break
                                except:
                                    pass
                    except:
                        pass
                
                # Fallback to current price if fetch failed
                if current_price is None:
                    current_price = trade.current_price
                
                # Update trade
                trade.current_price = current_price
                trade.pnl = (current_price - trade.entry_price) * trade.shares
                trade.pnl_pct = (current_price - trade.entry_price) / trade.entry_price if trade.entry_price > 0 else 0
                
                # Different thresholds for swing vs long trades
                if trade.trade_type == "swing":
                    stop_loss = self.config.swing_stop_loss_pct
                    take_profit = self.config.swing_take_profit_pct
                else:
                    stop_loss = self.config.stop_loss_pct
                    take_profit = self.config.take_profit_pct
                
                # Check stop-loss
                if trade.pnl_pct <= -stop_loss:
                    self._close_trade(trade, current_price, "stop_loss")
                
                # Check take-profit
                elif trade.pnl_pct >= take_profit:
                    self._close_trade(trade, current_price, "take_profit")
                
            except Exception:
                continue
    
    def _close_trade(self, trade: BotTrade, exit_price: float, reason: str) -> None:
        """Close a trade."""
        trade.exit_price = exit_price
        trade.exit_timestamp = self._now_iso()
        trade.status = "closed"
        trade.pnl = (exit_price - trade.entry_price) * trade.shares
        trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price if trade.entry_price > 0 else 0
        
        # Update balance
        proceeds = trade.shares * exit_price
        self.cash_balance += proceeds
        
        # Update stats
        self.total_pnl += trade.pnl
        if trade.pnl >= 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Move to closed
        del self.open_trades[trade.id]
        self.closed_trades.append(trade)
        
        # Keep only last 100 closed trades
        if len(self.closed_trades) > 100:
            self.closed_trades = self.closed_trades[-100:]
        
        pnl_str = f"+${trade.pnl:.2f}" if trade.pnl >= 0 else f"-${abs(trade.pnl):.2f}"
        result = "WIN" if trade.pnl >= 0 else "LOSS"
        
        self._log(
            f"[{result}] SOLD '{trade.question[:30]}...' - {reason.upper()} - P&L: {pnl_str} ({trade.pnl_pct:+.1%})",
            "trade"
        )
        
        if self.on_trade:
            self.on_trade(trade)
        
        self._save()
    
    def sell_position(self, trade_id: str, price: Optional[float] = None) -> bool:
        """Manually sell a position."""
        if trade_id not in self.open_trades:
            return False
        
        trade = self.open_trades[trade_id]
        exit_price = price or trade.current_price
        self._close_trade(trade, exit_price, "manual")
        return True
    
    # -------------------------------------------------------------------------
    # Auto-Trading Loop
    # -------------------------------------------------------------------------
    
    def start(self) -> None:
        """Start auto-trading."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        self._log("Auto-trading bot started!", "success")
    
    def stop(self) -> None:
        """Stop auto-trading."""
        self._running = False
        self._log("Auto-trading bot stopped", "info")
    
    def is_running(self) -> bool:
        return self._running
    
    def _run_loop(self) -> None:
        """Main trading loop."""
        while self._running:
            try:
                # Scan for opportunities
                opportunities = self.scan_markets()
                
                # Execute trades on best opportunities
                for opp in opportunities[:5]:  # Top 5
                    if opp.decision == BotDecision.BUY:
                        self.execute_trade(opp)
                
                # Update existing positions
                self.update_positions()
                
                # Wait before next scan
                for _ in range(self.config.scan_interval_seconds):
                    if not self._running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                self._log(f"Error in trading loop: {e}", "error")
                time.sleep(10)
    
    # -------------------------------------------------------------------------
    # Evaluate User-Added Market
    # -------------------------------------------------------------------------
    
    def evaluate_market_for_user(self, market_data: Dict, outcome: str, token_id: str) -> MarketOpportunity:
        """Evaluate a market that the user wants to add."""
        market_id = market_data.get("slug") or str(market_data.get("id"))
        question = market_data.get("question") or market_data.get("title", "Unknown")
        end_date = market_data.get("endDate")
        
        try:
            resolution_days = compute_resolution_days(end_date) if end_date else 30
        except Exception:
            resolution_days = 30
        
        # Get price from order book
        price = None
        try:
            book = fetch_order_book(token_id)
            if book.get("asks"):
                price = book["asks"][0][0]
        except Exception:
            pass
        
        if price is None:
            # Try from market data
            prices = market_data.get("outcomePrices")
            outcomes = market_data.get("outcomes")
            if prices and outcomes:
                try:
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                    if isinstance(outcomes, str):
                        outcomes = json.loads(outcomes)
                    idx = outcomes.index(outcome) if outcome in outcomes else 0
                    price = float(prices[idx])
                except Exception:
                    price = 0.5
        
        price = price or 0.5
        
        # Calculate metrics
        g_score = self._compute_g(price, resolution_days) or 0
        expected_roi = (1 - self.EXCHANGE_FEE) * ((1.0 - price) / price) if price > 0 else 0
        
        volume = float(market_data.get("volumeNum") or market_data.get("volume") or 0)
        liquidity = float(market_data.get("liquidity") or volume * 0.1)
        
        confidence = self._calculate_confidence(
            price=price,
            volume=volume,
            liquidity=liquidity,
            resolution_days=resolution_days,
            g_score=g_score,
        )
        
        decision, reasons = self._make_decision(
            price=price,
            g_score=g_score,
            expected_roi=expected_roi,
            confidence=confidence,
            resolution_days=resolution_days,
        )
        
        return MarketOpportunity(
            market_id=market_id,
            slug=market_data.get("slug", market_id),
            question=question,
            outcome=outcome,
            token_id=token_id,
            price=price,
            resolution_days=resolution_days,
            end_date=end_date or "",
            volume=volume,
            liquidity=liquidity,
            g_score=g_score,
            expected_roi=expected_roi,
            confidence=confidence,
            decision=decision,
            reasons=reasons,
        )
    
    # -------------------------------------------------------------------------
    # Stats & Persistence
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict:
        """Get bot statistics."""
        portfolio_value = self.cash_balance + sum(t.shares * t.current_price for t in self.open_trades.values())
        unrealized_pnl = sum(t.pnl for t in self.open_trades.values())
        
        return {
            "cash_balance": self.cash_balance,
            "portfolio_value": portfolio_value,
            "open_positions": len(self.open_trades),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0,
            "total_pnl": self.total_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_return_pct": (portfolio_value - self.config.initial_capital) / self.config.initial_capital * 100,
            "is_running": self._running,
        }
    
    def get_open_trades(self) -> List[BotTrade]:
        """Get all open trades."""
        return list(self.open_trades.values())
    
    def get_closed_trades(self, limit: int = 50) -> List[BotTrade]:
        """Get recent closed trades."""
        return list(reversed(self.closed_trades[-limit:]))
    
    def _save(self) -> None:
        """Save bot state."""
        try:
            data = {
                "cash_balance": self.cash_balance,
                "open_trades": {k: v.to_dict() for k, v in self.open_trades.items()},
                "closed_trades": [t.to_dict() for t in self.closed_trades],
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "total_pnl": self.total_pnl,
                "blacklist": list(self.blacklist),
                "trade_counter": self._trade_counter,
            }
            self.storage_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
    
    def _load(self) -> None:
        """Load bot state."""
        try:
            if self.storage_path.exists():
                data = json.loads(self.storage_path.read_text())
                self.cash_balance = data.get("cash_balance", self.config.initial_capital)
                self.open_trades = {k: BotTrade.from_dict(v) for k, v in data.get("open_trades", {}).items()}
                self.closed_trades = [BotTrade.from_dict(t) for t in data.get("closed_trades", [])]
                self.total_trades = data.get("total_trades", 0)
                self.winning_trades = data.get("winning_trades", 0)
                self.losing_trades = data.get("losing_trades", 0)
                self.total_pnl = data.get("total_pnl", 0.0)
                self.blacklist = set(data.get("blacklist", []))
                self._trade_counter = data.get("trade_counter", 0)
        except Exception:
            pass
    
    def reset(self) -> None:
        """Reset bot to initial state."""
        self.stop()
        self.cash_balance = self.config.initial_capital
        self.open_trades = {}
        self.closed_trades = []
        self.scanned_markets = {}
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self._trade_counter = 0
        self._save()
        self._log("🔄 Bot has been reset", "info")
