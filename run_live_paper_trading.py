#!/usr/bin/env python3
"""
Live Paper Trading with 500 Bots - Real Polymarket Data

This script runs 500 paper trading bots with different strategies,
all using LIVE data from the Polymarket API. Each bot has €200
starting capital and trades independently based on its strategy.

The bots don't actually execute trades - they paper trade using
real market prices, order books, and price movements.

Usage:
    python run_live_paper_trading.py [options]

Options:
    --bots N        Number of bots to run (default: 500)
    --capital N     Starting capital per bot (default: 200)
    --duration M    Duration in minutes (default: 60)
    --interval S    Scan interval in seconds (default: 30)
    --output DIR    Output directory for results

Example:
    python run_live_paper_trading.py --bots 500 --capital 200 --duration 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from math import log1p
import copy

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from auto_trader import (
    AutoTradingBot,
    BotConfig, 
    BotTrade,
    BotDecision,
    MarketOpportunity,
    GAMMA_API_BASE,
)
from monte_carlo.strategy_generator import StrategyGenerator, StrategyConfig

# Try matplotlib for visualization
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    np = None


@dataclass
class LiveBotState:
    """State tracking for a live paper trading bot."""
    bot_id: int
    strategy: StrategyConfig
    config: BotConfig
    
    # Performance
    initial_capital: float = 200.0
    current_cash: float = 200.0
    
    # Trade tracking
    open_trades: Dict[str, Dict] = field(default_factory=dict)
    closed_trades: List[Dict] = field(default_factory=list)
    
    # Stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    realized_pnl: float = 0.0
    
    # History for charting
    value_history: List[Tuple[datetime, float]] = field(default_factory=list)
    
    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L from open positions."""
        return sum(
            t.get('shares', 0) * (t.get('current_price', t.get('entry_price', 0)) - t.get('entry_price', 0))
            for t in self.open_trades.values()
        )
    
    @property
    def open_positions_value(self) -> float:
        """Value of all open positions at current prices."""
        return sum(
            t.get('shares', 0) * t.get('current_price', t.get('entry_price', 0))
            for t in self.open_trades.values()
        )
    
    @property
    def total_value(self) -> float:
        """Total portfolio value."""
        return self.current_cash + self.open_positions_value
    
    @property
    def total_pnl(self) -> float:
        """Total P&L (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl
    
    @property
    def total_return_pct(self) -> float:
        """Total return as percentage."""
        if self.initial_capital <= 0:
            return 0.0
        return ((self.total_value - self.initial_capital) / self.initial_capital) * 100
    
    @property
    def win_rate(self) -> float:
        """Win rate percentage."""
        total = self.winning_trades + self.losing_trades
        if total <= 0:
            return 0.0
        return (self.winning_trades / total) * 100
    
    def to_dict(self) -> Dict:
        return {
            'bot_id': self.bot_id,
            'strategy_name': self.strategy.name,
            'strategy_type': self.strategy.strategy_type,
            'initial_capital': self.initial_capital,
            'current_cash': round(self.current_cash, 2),
            'total_value': round(self.total_value, 2),
            'total_pnl': round(self.total_pnl, 2),
            'total_return_pct': round(self.total_return_pct, 2),
            'realized_pnl': round(self.realized_pnl, 2),
            'unrealized_pnl': round(self.unrealized_pnl, 2),
            'open_positions': len(self.open_trades),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': round(self.win_rate, 2),
        }


class LivePaperTradingSystem:
    """
    Runs multiple paper trading bots with live Polymarket data.
    
    Each bot has its own strategy configuration and trades independently,
    but they all share the same market data from the API.
    """
    
    EXCHANGE_FEE = 0.02  # 2% fee
    
    def __init__(
        self,
        num_bots: int = 500,
        initial_capital: float = 200.0,
        duration_minutes: int = 60,
        scan_interval_seconds: int = 30,
        output_dir: Path = None,
        seed: int = None,
    ):
        self.num_bots = num_bots
        self.initial_capital = initial_capital
        self.duration_minutes = duration_minutes
        self.scan_interval = scan_interval_seconds
        self.output_dir = output_dir or Path("live_paper_results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        if seed:
            random.seed(seed)
        
        # Bot states
        self.bots: Dict[int, LiveBotState] = {}
        self.strategies: List[StrategyConfig] = []
        
        # Shared market data cache
        self.market_cache: Dict[str, Dict] = {}
        self.last_market_fetch: datetime = None
        
        # Control
        self._running = False
        self._start_time: datetime = None
        self._end_time: datetime = None
        
        # Stats
        self.scan_count = 0
        self.total_api_calls = 0
    
    def _log(self, message: str, level: str = "info") -> None:
        """Print timestamped log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
            "trade": "💰",
        }.get(level, "")
        print(f"[{timestamp}] {prefix} {message}")
    
    def initialize(self) -> None:
        """Initialize all bots with their strategies."""
        self._log(f"Generating {self.num_bots} strategy configurations...")
        
        generator = StrategyGenerator(initial_capital=self.initial_capital)
        self.strategies = generator.generate_strategies(self.num_bots)
        
        for strategy in self.strategies:
            # Convert StrategyConfig to BotConfig
            config = self._strategy_to_bot_config(strategy)
            
            bot = LiveBotState(
                bot_id=strategy.id,
                strategy=strategy,
                config=config,
                initial_capital=self.initial_capital,
                current_cash=self.initial_capital,
            )
            self.bots[strategy.id] = bot
        
        self._log(f"Initialized {len(self.bots)} bots", "success")
        
        # Log strategy distribution
        dist = generator.get_archetype_distribution(self.strategies)
        dist_str = ", ".join(f"{k}:{v}" for k, v in sorted(dist.items()))
        self._log(f"Strategy distribution: {dist_str}")
    
    def _strategy_to_bot_config(self, strategy: StrategyConfig) -> BotConfig:
        """Convert a StrategyConfig to a BotConfig for the AutoTradingBot."""
        return BotConfig(
            initial_capital=strategy.initial_capital,
            max_position_size=strategy.max_position_size,
            max_portfolio_pct=strategy.max_position_pct,
            test_trade_size=strategy.test_trade_size,
            test_trade_enabled=strategy.test_trade_enabled,
            swing_trade_enabled=strategy.swing_enabled,
            swing_take_profit_pct=strategy.swing_take_profit_pct,
            swing_stop_loss_pct=strategy.swing_stop_loss_pct,
            min_price=strategy.min_price,
            max_price=strategy.max_price,
            min_days=strategy.min_days,
            max_days=strategy.max_days,
            min_volume=strategy.min_volume,
            min_liquidity=strategy.min_liquidity,
            min_g_score=strategy.min_g_score,
            min_expected_roi=strategy.min_expected_roi,
            confidence_threshold=strategy.min_confidence,
            high_confidence_threshold=strategy.high_confidence,
            stop_loss_pct=strategy.stop_loss_pct,
            take_profit_pct=strategy.take_profit_pct,
            max_positions=strategy.max_positions,
            max_swing_positions=strategy.max_swing_positions,
            max_long_term_positions=strategy.max_long_positions,
            max_slippage_pct=strategy.max_slippage_pct,
            verbose_logging=False,  # Disable per-bot logging
            log_rejected_markets=False,
            log_calculation_details=False,
            realistic_execution=True,
        )
    
    def fetch_live_markets(self) -> List[Dict]:
        """Fetch active markets from Polymarket API."""
        import requests
        
        all_markets = []
        
        try:
            # Fetch from multiple orderings
            orderings = [
                ("volume24hr", "false"),
                ("volumeNum", "false"),
                ("liquidity", "false"),
            ]
            
            for order_by, ascending in orderings:
                try:
                    params = {
                        "active": "true",
                        "closed": "false",
                        "limit": 100,
                        "order": order_by,
                        "ascending": ascending,
                    }
                    response = requests.get(
                        f"{GAMMA_API_BASE}/markets",
                        params=params,
                        timeout=15
                    )
                    if response.ok:
                        all_markets.extend(response.json())
                        self.total_api_calls += 1
                except Exception:
                    continue
            
            # Remove duplicates
            seen = set()
            unique = []
            for m in all_markets:
                mid = m.get("slug") or str(m.get("id"))
                if mid not in seen:
                    seen.add(mid)
                    unique.append(m)
                    self.market_cache[mid] = m
            
            self.last_market_fetch = datetime.now(timezone.utc)
            return unique
            
        except Exception as e:
            self._log(f"Failed to fetch markets: {e}", "error")
            return []
    
    def evaluate_market_for_bot(
        self, 
        bot: LiveBotState, 
        market: Dict
    ) -> Optional[Tuple[str, str, float, float, float]]:
        """
        Evaluate if a bot should buy into a market.
        
        Returns:
            Tuple of (market_id, outcome, price, shares, confidence) or None
        """
        config = bot.config
        
        market_id = market.get("slug") or str(market.get("id"))
        question = market.get("question") or market.get("title", "")
        
        # Skip if already have position
        if market_id in [t.get('market_id') for t in bot.open_trades.values()]:
            return None
        
        # Check position limits
        if len(bot.open_trades) >= config.max_positions:
            return None
        
        # Parse market data
        end_date = market.get("endDate")
        if not end_date:
            return None
        
        try:
            if end_date.endswith('Z'):
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            else:
                end_dt = datetime.fromisoformat(end_date)
            
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            if end_dt <= now:
                return None
            
            resolution_days = (end_dt - now).total_seconds() / 86400.0
        except:
            return None
        
        # Check time bounds
        if resolution_days < config.min_days or resolution_days > config.max_days:
            return None
        
        # Get price
        outcomes = market.get("outcomes")
        prices = market.get("outcomePrices")
        token_ids = market.get("clobTokenIds")
        
        if not outcomes or not prices or not token_ids:
            return None
        
        try:
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if isinstance(prices, str):
                prices = json.loads(prices)
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
        except:
            return None
        
        # Evaluate "Yes" outcome
        if len(prices) == 0:
            return None
        
        try:
            price = float(prices[0])
        except:
            return None
        
        # Check price bounds
        if price < config.min_price or price > config.max_price:
            return None
        
        # Check volume/liquidity
        volume = float(market.get("volumeNum") or market.get("volume") or 0)
        liquidity = float(market.get("liquidity") or volume * 0.1)
        
        if volume < config.min_volume or liquidity < config.min_liquidity:
            return None
        
        # Calculate g-score
        g_score = self._compute_g(price, resolution_days)
        if g_score is None or g_score < config.min_g_score:
            return None
        
        # Calculate expected ROI
        expected_roi = (1 - self.EXCHANGE_FEE) * ((1.0 - price) / price)
        if expected_roi < config.min_expected_roi:
            return None
        
        # Calculate confidence
        confidence = self._calculate_confidence(price, volume, liquidity, resolution_days, g_score)
        if confidence < config.confidence_threshold:
            return None
        
        # Determine position size
        is_high_conf = confidence >= config.high_confidence_threshold
        
        if config.test_trade_enabled and not is_high_conf:
            position_value = min(config.test_trade_size, bot.current_cash * 0.05)
        else:
            position_value = min(
                config.max_position_size,
                bot.current_cash * config.max_portfolio_pct,
            )
        
        if position_value < 5 or position_value > bot.current_cash:
            return None
        
        # Calculate shares with slippage
        slippage = random.uniform(0, config.max_slippage_pct / 100)
        actual_price = price * (1 + slippage)
        actual_price = min(0.99, actual_price)
        
        shares = position_value / actual_price
        
        return (market_id, outcomes[0], actual_price, shares, confidence)
    
    def _compute_g(self, price: float, resolution_days: float, lambda_days: float = 1.0) -> Optional[float]:
        """Compute growth rate (g) metric."""
        if price <= 0 or price >= 1 or resolution_days <= 0:
            return None
        r = (1 - self.EXCHANGE_FEE) * ((1.0 - price) / price)
        denom = resolution_days + lambda_days
        if denom <= 0:
            return None
        return log1p(r) / denom
    
    def _calculate_confidence(self, price, volume, liquidity, resolution_days, g_score) -> float:
        """Calculate confidence score."""
        score = 0.5
        
        if volume > 50000:
            score += 0.10
        elif volume > 10000:
            score += 0.06
        elif volume > 5000:
            score += 0.03
        
        if liquidity > 5000:
            score += 0.08
        elif liquidity > 1000:
            score += 0.04
        
        if 0.20 <= price <= 0.70:
            score += 0.08
        elif 0.10 <= price <= 0.85:
            score += 0.04
        
        if 7 <= resolution_days <= 30:
            score += 0.08
        elif 3 <= resolution_days <= 60:
            score += 0.04
        
        if g_score > 0.01:
            score += 0.05
        elif g_score > 0.005:
            score += 0.03
        
        return min(score, 0.95)
    
    def execute_buy(self, bot: LiveBotState, market_id: str, outcome: str, 
                   price: float, shares: float, question: str) -> None:
        """Execute a paper buy for a bot."""
        cost = shares * price
        
        trade_id = f"bot{bot.bot_id}_{len(bot.closed_trades) + len(bot.open_trades) + 1}"
        
        trade = {
            'trade_id': trade_id,
            'market_id': market_id,
            'outcome': outcome,
            'question': question[:60],
            'entry_price': price,
            'current_price': price,
            'shares': shares,
            'cost': cost,
            'entry_time': datetime.now(timezone.utc).isoformat(),
        }
        
        bot.open_trades[trade_id] = trade
        bot.current_cash -= cost
        bot.total_trades += 1
    
    def update_positions(self, bot: LiveBotState) -> None:
        """Update all positions for a bot and check stop-loss/take-profit."""
        config = bot.config
        trades_to_close = []
        
        for trade_id, trade in list(bot.open_trades.items()):
            market_id = trade.get('market_id')
            
            # Get current price from cache
            market = self.market_cache.get(market_id)
            if market:
                prices = market.get("outcomePrices")
                if prices:
                    try:
                        if isinstance(prices, str):
                            prices = json.loads(prices)
                        current_price = float(prices[0])
                        trade['current_price'] = current_price
                    except:
                        current_price = trade.get('current_price', trade['entry_price'])
            else:
                current_price = trade.get('current_price', trade['entry_price'])
            
            entry_price = trade['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
            
            # Check stop-loss
            if pnl_pct <= -config.stop_loss_pct:
                trades_to_close.append((trade_id, current_price, "stop_loss"))
            # Check take-profit
            elif pnl_pct >= config.take_profit_pct:
                trades_to_close.append((trade_id, current_price, "take_profit"))
        
        for trade_id, exit_price, reason in trades_to_close:
            self.close_trade(bot, trade_id, exit_price, reason)
    
    def close_trade(self, bot: LiveBotState, trade_id: str, exit_price: float, reason: str) -> None:
        """Close a trade for a bot."""
        if trade_id not in bot.open_trades:
            return
        
        trade = bot.open_trades.pop(trade_id)
        
        entry_price = trade['entry_price']
        shares = trade['shares']
        
        # Apply slippage on exit
        actual_exit = exit_price * 0.98  # ~2% bid-ask spread
        
        proceeds = shares * actual_exit
        pnl = proceeds - trade['cost']
        pnl_pct = (actual_exit - entry_price) / entry_price if entry_price > 0 else 0
        
        trade['exit_price'] = actual_exit
        trade['exit_time'] = datetime.now(timezone.utc).isoformat()
        trade['pnl'] = pnl
        trade['pnl_pct'] = pnl_pct
        trade['exit_reason'] = reason
        
        bot.closed_trades.append(trade)
        bot.current_cash += proceeds
        bot.realized_pnl += pnl
        
        if pnl >= 0:
            bot.winning_trades += 1
        else:
            bot.losing_trades += 1
    
    def run_cycle(self) -> None:
        """Run one cycle of market scanning and trading for all bots."""
        self.scan_count += 1
        
        # Fetch fresh market data
        markets = self.fetch_live_markets()
        if not markets:
            self._log("No markets fetched - skipping cycle", "warning")
            return
        
        self._log(f"Cycle {self.scan_count}: Processing {len(markets)} markets for {len(self.bots)} bots")
        
        trades_made = 0
        positions_closed = 0
        
        # Shuffle markets for variety
        random.shuffle(markets)
        
        # Process each bot
        for bot in self.bots.values():
            # Update existing positions
            old_open = len(bot.open_trades)
            self.update_positions(bot)
            positions_closed += (old_open - len(bot.open_trades))
            
            # Look for new opportunities (limit markets checked per bot)
            markets_to_check = markets[:50]  # Each bot checks up to 50 markets
            random.shuffle(markets_to_check)
            
            for market in markets_to_check:
                if len(bot.open_trades) >= bot.config.max_positions:
                    break
                
                result = self.evaluate_market_for_bot(bot, market)
                if result:
                    market_id, outcome, price, shares, confidence = result
                    question = market.get("question", "")[:60]
                    self.execute_buy(bot, market_id, outcome, price, shares, question)
                    trades_made += 1
            
            # Record value history
            bot.value_history.append((datetime.now(timezone.utc), bot.total_value))
        
        # Calculate stats
        profitable = sum(1 for b in self.bots.values() if b.total_return_pct > 0)
        avg_return = sum(b.total_return_pct for b in self.bots.values()) / len(self.bots) if self.bots else 0
        total_positions = sum(len(b.open_trades) for b in self.bots.values())
        
        self._log(
            f"Cycle complete: {trades_made} buys, {positions_closed} exits | "
            f"Positions: {total_positions} | Profitable: {profitable}/{len(self.bots)} | "
            f"Avg return: {avg_return:+.2f}%"
        )
    
    def run(self) -> Dict:
        """Run the live paper trading session."""
        self._log("=" * 60)
        self._log("LIVE PAPER TRADING SYSTEM")
        self._log("=" * 60)
        self._log(f"Bots: {self.num_bots} | Capital: €{self.initial_capital} each")
        self._log(f"Duration: {self.duration_minutes} minutes | Interval: {self.scan_interval}s")
        self._log("=" * 60)
        
        # Initialize
        self.initialize()
        
        self._start_time = datetime.now(timezone.utc)
        self._end_time = self._start_time + timedelta(minutes=self.duration_minutes)
        self._running = True
        
        cycle_count = 0
        
        try:
            while self._running and datetime.now(timezone.utc) < self._end_time:
                cycle_start = time.time()
                
                self.run_cycle()
                cycle_count += 1
                
                # Progress update
                elapsed = (datetime.now(timezone.utc) - self._start_time).total_seconds() / 60
                remaining = self.duration_minutes - elapsed
                
                if cycle_count % 5 == 0:  # Every 5 cycles
                    self._print_leaderboard()
                
                self._log(f"⏱️ Elapsed: {elapsed:.1f}min | Remaining: {remaining:.1f}min")
                
                # Wait for next cycle
                cycle_duration = time.time() - cycle_start
                sleep_time = max(0, self.scan_interval - cycle_duration)
                if sleep_time > 0 and datetime.now(timezone.utc) < self._end_time:
                    time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            self._log("\nStopping - interrupted by user", "warning")
        
        self._running = False
        
        # Close all remaining positions
        self._log("\nClosing all remaining positions...")
        for bot in self.bots.values():
            for trade_id in list(bot.open_trades.keys()):
                trade = bot.open_trades[trade_id]
                self.close_trade(bot, trade_id, trade.get('current_price', trade['entry_price']), "session_end")
        
        # Generate results
        results = self._compile_results()
        self._save_results(results)
        self._print_final_results(results)
        
        if MATPLOTLIB_AVAILABLE:
            self._generate_charts(results)
        
        return results
    
    def _print_leaderboard(self) -> None:
        """Print current top performers."""
        sorted_bots = sorted(self.bots.values(), key=lambda b: b.total_return_pct, reverse=True)
        
        print("\n" + "─" * 60)
        print("🏆 CURRENT LEADERBOARD (Top 10)")
        print("─" * 60)
        
        for i, bot in enumerate(sorted_bots[:10], 1):
            print(f"  {i:2}. Bot #{bot.bot_id:03d} ({bot.strategy.strategy_type[:8]:8}) | "
                  f"Return: {bot.total_return_pct:+6.2f}% | "
                  f"Trades: {bot.total_trades:3} | "
                  f"Open: {len(bot.open_trades):2}")
        
        print("─" * 60 + "\n")
    
    def _compile_results(self) -> Dict:
        """Compile final results."""
        bot_results = [bot.to_dict() for bot in self.bots.values()]
        
        returns = [b['total_return_pct'] for b in bot_results]
        
        # Strategy performance
        strategy_perf = {}
        for strategy_type in set(b.strategy.strategy_type for b in self.bots.values()):
            type_bots = [b for b in self.bots.values() if b.strategy.strategy_type == strategy_type]
            type_returns = [b.total_return_pct for b in type_bots]
            
            strategy_perf[strategy_type] = {
                'count': len(type_bots),
                'avg_return_pct': round(sum(type_returns) / len(type_returns), 2) if type_returns else 0,
                'best_return_pct': round(max(type_returns), 2) if type_returns else 0,
                'worst_return_pct': round(min(type_returns), 2) if type_returns else 0,
                'profitable_pct': round(sum(1 for r in type_returns if r > 0) / len(type_returns) * 100, 2) if type_returns else 0,
            }
        
        sorted_results = sorted(bot_results, key=lambda x: x['total_return_pct'], reverse=True)
        
        return {
            'session_id': f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'start_time': self._start_time.isoformat(),
            'end_time': datetime.now(timezone.utc).isoformat(),
            'config': {
                'num_bots': self.num_bots,
                'initial_capital': self.initial_capital,
                'duration_minutes': self.duration_minutes,
                'scan_interval_seconds': self.scan_interval,
            },
            'summary': {
                'avg_return_pct': round(sum(returns) / len(returns), 2) if returns else 0,
                'median_return_pct': round(sorted(returns)[len(returns)//2], 2) if returns else 0,
                'best_return_pct': round(max(returns), 2) if returns else 0,
                'worst_return_pct': round(min(returns), 2) if returns else 0,
                'profitable_bots': sum(1 for r in returns if r > 0),
                'profitable_pct': round(sum(1 for r in returns if r > 0) / len(returns) * 100, 2) if returns else 0,
                'total_trades': sum(b['total_trades'] for b in bot_results),
                'avg_trades_per_bot': round(sum(b['total_trades'] for b in bot_results) / len(bot_results), 1) if bot_results else 0,
                'total_api_calls': self.total_api_calls,
                'scan_cycles': self.scan_count,
            },
            'strategy_performance': strategy_perf,
            'top_performers': sorted_results[:20],
            'bottom_performers': sorted_results[-20:],
            'all_bots': bot_results,
        }
    
    def _save_results(self, results: Dict) -> None:
        """Save results to file."""
        filepath = self.output_dir / f"results_{results['session_id']}.json"
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2)
        self._log(f"Results saved to: {filepath}", "success")
    
    def _print_final_results(self, results: Dict) -> None:
        """Print final results summary."""
        summary = results['summary']
        
        print("\n" + "=" * 70)
        print("                    FINAL RESULTS")
        print("=" * 70)
        
        print(f"""
┌────────────────────────────────────────────────────────────────┐
│                     SESSION SUMMARY                            │
├────────────────────────────────────────────────────────────────┤
│  Duration:                    {self.duration_minutes:>6} minutes               │
│  Scan Cycles:                 {summary['scan_cycles']:>6}                       │
│  API Calls:                   {summary['total_api_calls']:>6}                       │
├────────────────────────────────────────────────────────────────┤
│  PERFORMANCE                                                   │
├────────────────────────────────────────────────────────────────┤
│  Average Return:              {summary['avg_return_pct']:>+7.2f}%                  │
│  Median Return:               {summary['median_return_pct']:>+7.2f}%                  │
│  Best Return:                 {summary['best_return_pct']:>+7.2f}%                  │
│  Worst Return:                {summary['worst_return_pct']:>+7.2f}%                  │
├────────────────────────────────────────────────────────────────┤
│  Profitable Bots:             {summary['profitable_bots']:>6} ({summary['profitable_pct']:.1f}%)             │
│  Total Trades:                {summary['total_trades']:>6}                       │
│  Avg Trades/Bot:              {summary['avg_trades_per_bot']:>6.1f}                       │
└────────────────────────────────────────────────────────────────┘
""")
        
        # Strategy performance
        print("\n┌────────────────────────────────────────────────────────────┐")
        print("│              STRATEGY TYPE PERFORMANCE                     │")
        print("├──────────────┬──────────┬──────────┬────────────┬──────────┤")
        print("│ Strategy     │ Avg Ret  │ Best Ret │ Profitable │ Count    │")
        print("├──────────────┼──────────┼──────────┼────────────┼──────────┤")
        
        sorted_perf = sorted(
            results['strategy_performance'].items(),
            key=lambda x: x[1]['avg_return_pct'],
            reverse=True
        )
        
        for strategy, perf in sorted_perf:
            name = strategy[:12].ljust(12)
            avg = f"{perf['avg_return_pct']:+.1f}%".rjust(8)
            best = f"{perf['best_return_pct']:+.1f}%".rjust(8)
            profit = f"{perf['profitable_pct']:.0f}%".rjust(10)
            count = str(perf['count']).rjust(8)
            print(f"│ {name} │ {avg} │ {best} │ {profit} │ {count} │")
        
        print("└──────────────┴──────────┴──────────┴────────────┴──────────┘")
        
        # Top performers
        print("\n🏆 TOP 5 PERFORMERS:")
        for i, bot in enumerate(results['top_performers'][:5], 1):
            print(f"   {i}. Bot #{bot['bot_id']:03d} ({bot['strategy_type']}) - "
                  f"Return: {bot['total_return_pct']:+.2f}% | "
                  f"Trades: {bot['total_trades']}")
        
        print(f"\n📁 Full results saved to: {self.output_dir.absolute()}")
    
    def _generate_charts(self, results: Dict) -> None:
        """Generate visualization charts."""
        import numpy as np
        
        returns = [b['total_return_pct'] for b in results['all_bots']]
        
        # Return distribution
        fig, ax = plt.subplots(figsize=(12, 6))
        
        n, bins, patches = ax.hist(returns, bins=40, edgecolor='white', alpha=0.8)
        
        for i, patch in enumerate(patches):
            if bins[i] >= 0:
                patch.set_facecolor('#3fb950')
            else:
                patch.set_facecolor('#f85149')
        
        ax.axvline(x=0, color='white', linestyle='--', linewidth=2)
        ax.axvline(x=np.mean(returns), color='#58a6ff', linewidth=2, label=f'Mean: {np.mean(returns):.1f}%')
        
        ax.set_xlabel('Return (%)')
        ax.set_ylabel('Number of Bots')
        ax.set_title('Live Paper Trading - Return Distribution')
        ax.legend()
        ax.set_facecolor('#0d1117')
        fig.set_facecolor('#0d1117')
        ax.tick_params(colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'return_distribution.png', dpi=150, facecolor='#0d1117')
        plt.close()
        
        self._log("Generated charts", "success")


def main():
    parser = argparse.ArgumentParser(description="Live Paper Trading with 500 Bots")
    
    parser.add_argument("--bots", "-b", type=int, default=500, help="Number of bots (default: 500)")
    parser.add_argument("--capital", "-c", type=float, default=200.0, help="Capital per bot (default: 200)")
    parser.add_argument("--duration", "-d", type=int, default=60, help="Duration in minutes (default: 60)")
    parser.add_argument("--interval", "-i", type=int, default=30, help="Scan interval in seconds (default: 30)")
    parser.add_argument("--output", "-o", type=str, default="live_paper_results", help="Output directory")
    parser.add_argument("--seed", "-s", type=int, default=None, help="Random seed")
    
    args = parser.parse_args()
    
    print("""
╔════════════════════════════════════════════════════════════════════╗
║                                                                    ║
║     ██╗     ██╗██╗   ██╗███████╗    ████████╗██████╗  █████╗       ║
║     ██║     ██║██║   ██║██╔════╝    ╚══██╔══╝██╔══██╗██╔══██╗      ║
║     ██║     ██║██║   ██║█████╗         ██║   ██████╔╝███████║      ║
║     ██║     ██║╚██╗ ██╔╝██╔══╝         ██║   ██╔══██╗██╔══██║      ║
║     ███████╗██║ ╚████╔╝ ███████╗       ██║   ██║  ██║██║  ██║      ║
║     ╚══════╝╚═╝  ╚═══╝  ╚══════╝       ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝      ║
║                                                                    ║
║     500 Bots • Live Polymarket Data • Paper Trading                ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
    """)
    
    system = LivePaperTradingSystem(
        num_bots=args.bots,
        initial_capital=args.capital,
        duration_minutes=args.duration,
        scan_interval_seconds=args.interval,
        output_dir=Path(args.output),
        seed=args.seed,
    )
    
    try:
        results = system.run()
        return 0
    except KeyboardInterrupt:
        print("\n\n⚠️ Session interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Session failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
