"""Core Monte Carlo Simulator.

Runs multiple trading bots with different strategies against simulated markets.
Tracks performance and generates comprehensive results.
"""

from __future__ import annotations

import copy
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from math import log1p
import numpy as np

from .strategy_generator import StrategyConfig, StrategyGenerator
from .market_simulator import MarketSimulator, SimulatedMarket, MarketOutcome


@dataclass
class SimulatedTrade:
    """A trade made by a simulated bot."""
    id: str
    bot_id: int
    market_id: str
    outcome: str
    question: str
    
    entry_time: datetime
    entry_price: float
    shares: float
    cost: float
    
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""  # "take_profit", "stop_loss", "resolution", "still_open"
    
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "open"  # "open", "closed"
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'bot_id': self.bot_id,
            'market_id': self.market_id,
            'outcome': self.outcome,
            'question': self.question[:50],
            'entry_time': self.entry_time.isoformat(),
            'entry_price': self.entry_price,
            'shares': self.shares,
            'cost': self.cost,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'status': self.status,
        }


@dataclass
class BotState:
    """State of a simulated trading bot."""
    id: int
    strategy: StrategyConfig
    
    # Capital
    initial_capital: float
    cash_balance: float
    
    # Trades
    open_trades: Dict[str, SimulatedTrade] = field(default_factory=dict)
    closed_trades: List[SimulatedTrade] = field(default_factory=list)
    
    # Statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    peak_value: float = 0.0
    max_drawdown: float = 0.0
    
    # Trade counter
    _trade_counter: int = 0
    
    @property
    def portfolio_value(self) -> float:
        """Current total portfolio value."""
        open_value = sum(t.shares * t.entry_price for t in self.open_trades.values())
        return self.cash_balance + open_value
    
    @property
    def total_return_pct(self) -> float:
        """Total return as percentage."""
        if self.initial_capital <= 0:
            return 0.0
        return ((self.portfolio_value - self.initial_capital) / self.initial_capital) * 100
    
    @property
    def win_rate(self) -> float:
        """Win rate as percentage."""
        total = self.winning_trades + self.losing_trades
        if total <= 0:
            return 0.0
        return (self.winning_trades / total) * 100
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'strategy_name': self.strategy.name,
            'strategy_type': self.strategy.strategy_type,
            'initial_capital': self.initial_capital,
            'cash_balance': self.cash_balance,
            'portfolio_value': self.portfolio_value,
            'total_pnl': self.total_pnl,
            'total_return_pct': self.total_return_pct,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'peak_value': self.peak_value,
            'max_drawdown': self.max_drawdown,
            'open_positions': len(self.open_trades),
        }


@dataclass
class SimulationResults:
    """Results from a Monte Carlo simulation run."""
    simulation_id: str
    start_time: datetime
    end_time: datetime
    
    # Configuration
    num_bots: int
    num_markets: int
    simulation_days: int
    initial_capital: float
    
    # Bot results
    bot_results: List[Dict] = field(default_factory=list)
    
    # Aggregated statistics
    avg_return_pct: float = 0.0
    median_return_pct: float = 0.0
    std_return_pct: float = 0.0
    
    best_return_pct: float = 0.0
    worst_return_pct: float = 0.0
    
    profitable_bots: int = 0
    profitable_pct: float = 0.0
    
    avg_trades_per_bot: float = 0.0
    avg_win_rate: float = 0.0
    
    # Strategy type performance
    strategy_performance: Dict[str, Dict] = field(default_factory=dict)
    
    # Top and bottom performers
    top_performers: List[Dict] = field(default_factory=list)
    bottom_performers: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'simulation_id': self.simulation_id,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'duration_seconds': (self.end_time - self.start_time).total_seconds(),
            'config': {
                'num_bots': self.num_bots,
                'num_markets': self.num_markets,
                'simulation_days': self.simulation_days,
                'initial_capital': self.initial_capital,
            },
            'summary': {
                'avg_return_pct': round(self.avg_return_pct, 2),
                'median_return_pct': round(self.median_return_pct, 2),
                'std_return_pct': round(self.std_return_pct, 2),
                'best_return_pct': round(self.best_return_pct, 2),
                'worst_return_pct': round(self.worst_return_pct, 2),
                'profitable_bots': self.profitable_bots,
                'profitable_pct': round(self.profitable_pct, 2),
                'avg_trades_per_bot': round(self.avg_trades_per_bot, 1),
                'avg_win_rate': round(self.avg_win_rate, 2),
            },
            'strategy_performance': self.strategy_performance,
            'top_performers': self.top_performers,
            'bottom_performers': self.bottom_performers,
            'all_bots': self.bot_results,
        }
    
    def save(self, filepath: Path) -> None:
        """Save results to JSON file."""
        filepath.write_text(json.dumps(self.to_dict(), indent=2))


class MonteCarloSimulator:
    """
    Monte Carlo simulation engine for testing trading strategies.
    
    Runs multiple bots with different configurations against simulated
    market data to evaluate strategy performance.
    """
    
    EXCHANGE_FEE = 0.02  # 2% fee on winning trades
    
    def __init__(
        self,
        num_bots: int = 500,
        initial_capital: float = 200.0,
        simulation_days: int = 90,
        num_markets: int = 200,
        seed: int = None,
        on_progress: Callable[[int, int, str], None] = None,
    ):
        """Initialize the Monte Carlo simulator.
        
        Args:
            num_bots: Number of bots to simulate (default 500)
            initial_capital: Starting capital for each bot (default €200)
            simulation_days: Days to simulate (default 90)
            num_markets: Number of markets to generate (default 200)
            seed: Random seed for reproducibility
            on_progress: Callback for progress updates (current, total, message)
        """
        self.num_bots = num_bots
        self.initial_capital = initial_capital
        self.simulation_days = simulation_days
        self.num_markets = num_markets
        self.seed = seed
        self.on_progress = on_progress
        
        # Initialize generators
        self.strategy_generator = StrategyGenerator(initial_capital=initial_capital, seed=seed)
        self.market_simulator = MarketSimulator(seed=seed)
        
        # State
        self.bots: Dict[int, BotState] = {}
        self.markets: Dict[str, SimulatedMarket] = {}
        self.strategies: List[StrategyConfig] = []
        
        # Timing
        self.current_time: datetime = None
        self.start_time: datetime = None
        self.end_time: datetime = None
        
        # Results
        self.results: Optional[SimulationResults] = None
    
    def _log_progress(self, current: int, total: int, message: str) -> None:
        """Log progress to callback if available."""
        if self.on_progress:
            try:
                self.on_progress(current, total, message)
            except Exception:
                pass
    
    def run(self) -> SimulationResults:
        """Run the full Monte Carlo simulation.
        
        Returns:
            SimulationResults with comprehensive analysis
        """
        sim_start = datetime.now(timezone.utc)
        simulation_id = f"mc_{sim_start.strftime('%Y%m%d_%H%M%S')}"
        
        print(f"\n{'='*60}")
        print(f"MONTE CARLO SIMULATION - {simulation_id}")
        print(f"{'='*60}")
        print(f"Bots: {self.num_bots} | Capital: €{self.initial_capital}")
        print(f"Markets: {self.num_markets} | Days: {self.simulation_days}")
        print(f"{'='*60}\n")
        
        # Phase 1: Generate strategies
        self._log_progress(0, 100, "Generating strategies...")
        print("Phase 1: Generating strategies...")
        self.strategies = self.strategy_generator.generate_strategies(self.num_bots)
        print(f"  ✓ Generated {len(self.strategies)} unique strategies")
        
        # Phase 2: Generate markets
        self._log_progress(10, 100, "Generating markets...")
        print("\nPhase 2: Generating markets...")
        self.start_time = datetime.now(timezone.utc)
        self.end_time = self.start_time + timedelta(days=self.simulation_days)
        self.current_time = self.start_time
        
        markets = self.market_simulator.generate_markets(
            count=self.num_markets,
            simulation_days=self.simulation_days,
            start_date=self.start_time,
        )
        self.markets = {m.market_id: m for m in markets}
        print(f"  ✓ Generated {len(self.markets)} markets")
        
        # Phase 3: Initialize bots
        self._log_progress(20, 100, "Initializing bots...")
        print("\nPhase 3: Initializing bots...")
        self._initialize_bots()
        print(f"  ✓ Initialized {len(self.bots)} bots")
        
        # Phase 4: Run simulation
        self._log_progress(25, 100, "Running simulation...")
        print("\nPhase 4: Running simulation...")
        self._run_simulation_loop()
        
        # Phase 5: Collect results
        self._log_progress(95, 100, "Analyzing results...")
        print("\nPhase 5: Analyzing results...")
        self.results = self._compile_results(simulation_id, sim_start)
        
        self._log_progress(100, 100, "Complete!")
        print(f"\n{'='*60}")
        print("SIMULATION COMPLETE")
        print(f"{'='*60}\n")
        
        return self.results
    
    def _initialize_bots(self) -> None:
        """Initialize all bot states with their strategies."""
        for strategy in self.strategies:
            bot = BotState(
                id=strategy.id,
                strategy=strategy,
                initial_capital=strategy.initial_capital,
                cash_balance=strategy.initial_capital,
                peak_value=strategy.initial_capital,
            )
            self.bots[bot.id] = bot
    
    def _run_simulation_loop(self) -> None:
        """Main simulation loop - advance time and process all bots."""
        time_step_hours = 4  # Update every 4 hours
        total_hours = self.simulation_days * 24
        hours_simulated = 0
        
        while self.current_time < self.end_time:
            # Update all market prices
            for market in self.markets.values():
                self.market_simulator.simulate_price_movement(
                    market, 
                    self.current_time,
                    time_step_hours,
                )
            
            # Process each bot
            for bot in self.bots.values():
                self._process_bot_cycle(bot)
            
            # Advance time
            self.current_time += timedelta(hours=time_step_hours)
            hours_simulated += time_step_hours
            
            # Progress update
            progress = int(25 + (hours_simulated / total_hours) * 70)
            if hours_simulated % 24 == 0:  # Daily update
                day = hours_simulated // 24
                self._log_progress(
                    progress, 100, 
                    f"Simulating day {day}/{self.simulation_days}..."
                )
                if day % 10 == 0:
                    print(f"  Day {day}/{self.simulation_days} complete")
        
        # Final resolution - close all remaining positions
        print("  Resolving final positions...")
        self._resolve_all_positions()
    
    def _process_bot_cycle(self, bot: BotState) -> None:
        """Process a single bot's trading cycle."""
        strategy = bot.strategy
        
        # Update existing positions (check stops/targets)
        self._update_bot_positions(bot)
        
        # Look for new opportunities
        if len(bot.open_trades) < strategy.max_positions:
            self._scan_for_opportunities(bot)
        
        # Update peak value and drawdown
        current_value = bot.portfolio_value
        if current_value > bot.peak_value:
            bot.peak_value = current_value
        
        drawdown = (bot.peak_value - current_value) / bot.peak_value if bot.peak_value > 0 else 0
        if drawdown > bot.max_drawdown:
            bot.max_drawdown = drawdown
    
    def _update_bot_positions(self, bot: BotState) -> None:
        """Check and update all open positions for a bot."""
        strategy = bot.strategy
        trades_to_close = []
        
        for trade_id, trade in bot.open_trades.items():
            market = self.markets.get(trade.market_id)
            if not market:
                continue
            
            current_price = market.current_price
            
            # Check if market resolved
            if market.resolved:
                resolution_value = self.market_simulator.get_resolution_value(
                    trade.market_id, trade.outcome
                )
                if resolution_value is not None:
                    trades_to_close.append((trade_id, resolution_value, "resolution"))
                continue
            
            # Calculate current P&L
            unrealized_pnl_pct = (current_price - trade.entry_price) / trade.entry_price
            
            # Check take profit
            if unrealized_pnl_pct >= strategy.take_profit_pct:
                trades_to_close.append((trade_id, current_price, "take_profit"))
            # Check stop loss
            elif unrealized_pnl_pct <= -strategy.stop_loss_pct:
                trades_to_close.append((trade_id, current_price, "stop_loss"))
        
        # Close trades
        for trade_id, exit_price, reason in trades_to_close:
            self._close_trade(bot, trade_id, exit_price, reason)
    
    def _close_trade(
        self, 
        bot: BotState, 
        trade_id: str, 
        exit_price: float, 
        reason: str
    ) -> None:
        """Close a trade and record results."""
        if trade_id not in bot.open_trades:
            return
        
        trade = bot.open_trades.pop(trade_id)
        trade.exit_time = self.current_time
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.status = "closed"
        
        # Calculate P&L
        proceeds = trade.shares * exit_price
        
        # Apply fee on winning trades (resolution to $1)
        if exit_price > trade.entry_price:
            fee = proceeds * self.EXCHANGE_FEE
            proceeds -= fee
        
        trade.pnl = proceeds - trade.cost
        trade.pnl_pct = (trade.pnl / trade.cost) * 100 if trade.cost > 0 else 0
        
        # Update bot stats
        bot.cash_balance += proceeds
        bot.total_pnl += trade.pnl
        
        if trade.pnl > 0:
            bot.winning_trades += 1
        else:
            bot.losing_trades += 1
        
        bot.closed_trades.append(trade)
    
    def _scan_for_opportunities(self, bot: BotState) -> None:
        """Scan markets for trading opportunities for a bot."""
        strategy = bot.strategy
        
        # Get active markets
        active_markets = [m for m in self.markets.values() 
                        if not m.resolved and m.end_time > self.current_time]
        
        # Shuffle to add randomness (different bots see different order)
        np.random.shuffle(active_markets)
        
        opportunities_checked = 0
        max_checks = 50  # Don't check too many per cycle
        
        for market in active_markets:
            if opportunities_checked >= max_checks:
                break
            if len(bot.open_trades) >= strategy.max_positions:
                break
            
            opportunities_checked += 1
            
            # Skip if already have position in this market
            if any(t.market_id == market.market_id for t in bot.open_trades.values()):
                continue
            
            # Evaluate the market
            should_buy, confidence = self._evaluate_market_for_bot(bot, market)
            
            if should_buy:
                self._execute_buy(bot, market, confidence)
    
    def _evaluate_market_for_bot(
        self, 
        bot: BotState, 
        market: SimulatedMarket
    ) -> Tuple[bool, float]:
        """Evaluate if a bot should buy into a market.
        
        Returns:
            Tuple of (should_buy, confidence)
        """
        strategy = bot.strategy
        price = market.current_price
        
        # Check price bounds
        if price < strategy.min_price or price > strategy.max_price:
            return False, 0.0
        
        # Check volume/liquidity
        if market.current_volume < strategy.min_volume:
            return False, 0.0
        if market.current_liquidity < strategy.min_liquidity:
            return False, 0.0
        
        # Calculate resolution days
        resolution_days = (market.end_time - self.current_time).total_seconds() / 86400
        
        # Check time bounds
        if resolution_days < strategy.min_days or resolution_days > strategy.max_days:
            return False, 0.0
        
        # Calculate g-score
        g_score = self._compute_g(price, resolution_days)
        if g_score is None or g_score < strategy.min_g_score:
            return False, 0.0
        
        # Calculate expected ROI
        expected_roi = (1 - self.EXCHANGE_FEE) * ((1.0 - price) / price)
        if expected_roi < strategy.min_expected_roi:
            return False, 0.0
        
        # Calculate confidence
        confidence = self._calculate_confidence(
            price=price,
            volume=market.current_volume,
            liquidity=market.current_liquidity,
            resolution_days=resolution_days,
            g_score=g_score,
        )
        
        # Check confidence threshold
        if confidence < strategy.min_confidence:
            return False, 0.0
        
        return True, confidence
    
    def _compute_g(self, price: float, resolution_days: float, lambda_days: float = 1.0) -> Optional[float]:
        """Compute growth rate (g) metric."""
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
        
        # Volume factor
        if volume > 50000:
            score += 0.10
        elif volume > 10000:
            score += 0.06
        elif volume > 5000:
            score += 0.03
        
        # Liquidity factor
        if liquidity > 5000:
            score += 0.08
        elif liquidity > 1000:
            score += 0.04
        
        # Price factor (mid-range is more reliable)
        if 0.20 <= price <= 0.70:
            score += 0.08
        elif 0.10 <= price <= 0.85:
            score += 0.04
        
        # Time factor
        if 7 <= resolution_days <= 30:
            score += 0.08
        elif 3 <= resolution_days <= 60:
            score += 0.04
        
        # G-score factor
        if g_score > 0.01:
            score += 0.05
        elif g_score > 0.005:
            score += 0.03
        
        return min(score, 0.95)
    
    def _execute_buy(self, bot: BotState, market: SimulatedMarket, confidence: float) -> None:
        """Execute a buy trade for a bot."""
        strategy = bot.strategy
        
        # Determine position size
        is_high_confidence = confidence >= strategy.high_confidence
        
        if strategy.test_trade_enabled and not is_high_confidence:
            position_value = min(strategy.test_trade_size, bot.cash_balance * 0.05)
        else:
            position_value = min(
                strategy.max_position_size,
                bot.cash_balance * strategy.max_position_pct,
            )
        
        # Ensure minimum position
        if position_value < 5 or position_value > bot.cash_balance:
            return
        
        # Simulate slippage
        slippage = np.random.uniform(0, strategy.max_slippage_pct / 100)
        actual_price = market.current_price * (1 + slippage)
        actual_price = min(0.99, actual_price)
        
        shares = position_value / actual_price
        
        # Create trade
        bot._trade_counter += 1
        trade = SimulatedTrade(
            id=f"bot{bot.id}_trade{bot._trade_counter}",
            bot_id=bot.id,
            market_id=market.market_id,
            outcome=market.outcome_name,
            question=market.question,
            entry_time=self.current_time,
            entry_price=actual_price,
            shares=shares,
            cost=position_value,
        )
        
        bot.open_trades[trade.id] = trade
        bot.cash_balance -= position_value
        bot.total_trades += 1
    
    def _resolve_all_positions(self) -> None:
        """Resolve all remaining open positions at end of simulation."""
        for bot in self.bots.values():
            trade_ids = list(bot.open_trades.keys())
            for trade_id in trade_ids:
                trade = bot.open_trades[trade_id]
                market = self.markets.get(trade.market_id)
                
                if market and market.resolved:
                    # Use resolution value
                    exit_price = self.market_simulator.get_resolution_value(
                        trade.market_id, trade.outcome
                    )
                    if exit_price is None:
                        exit_price = market.current_price
                else:
                    # Use current market price
                    exit_price = market.current_price if market else trade.entry_price
                
                self._close_trade(bot, trade_id, exit_price, "simulation_end")
    
    def _compile_results(
        self, 
        simulation_id: str, 
        sim_start: datetime
    ) -> SimulationResults:
        """Compile comprehensive simulation results."""
        sim_end = datetime.now(timezone.utc)
        
        # Collect all bot results
        bot_results = [bot.to_dict() for bot in self.bots.values()]
        
        # Calculate aggregate statistics
        returns = [b['total_return_pct'] for b in bot_results]
        win_rates = [b['win_rate'] for b in bot_results]
        trade_counts = [b['total_trades'] for b in bot_results]
        
        profitable_count = sum(1 for r in returns if r > 0)
        
        # Strategy type performance
        strategy_perf = {}
        for strategy_type in set(b.strategy.strategy_type for b in self.bots.values()):
            type_bots = [b for b in self.bots.values() if b.strategy.strategy_type == strategy_type]
            type_returns = [b.total_return_pct for b in type_bots]
            
            strategy_perf[strategy_type] = {
                'count': len(type_bots),
                'avg_return_pct': round(np.mean(type_returns), 2) if type_returns else 0,
                'median_return_pct': round(np.median(type_returns), 2) if type_returns else 0,
                'std_return_pct': round(np.std(type_returns), 2) if type_returns else 0,
                'best_return_pct': round(max(type_returns), 2) if type_returns else 0,
                'worst_return_pct': round(min(type_returns), 2) if type_returns else 0,
                'profitable_pct': round(sum(1 for r in type_returns if r > 0) / len(type_returns) * 100, 2) if type_returns else 0,
            }
        
        # Sort bots by return
        sorted_results = sorted(bot_results, key=lambda x: x['total_return_pct'], reverse=True)
        
        results = SimulationResults(
            simulation_id=simulation_id,
            start_time=sim_start,
            end_time=sim_end,
            num_bots=self.num_bots,
            num_markets=self.num_markets,
            simulation_days=self.simulation_days,
            initial_capital=self.initial_capital,
            bot_results=bot_results,
            
            avg_return_pct=np.mean(returns) if returns else 0,
            median_return_pct=np.median(returns) if returns else 0,
            std_return_pct=np.std(returns) if returns else 0,
            best_return_pct=max(returns) if returns else 0,
            worst_return_pct=min(returns) if returns else 0,
            profitable_bots=profitable_count,
            profitable_pct=(profitable_count / len(returns) * 100) if returns else 0,
            avg_trades_per_bot=np.mean(trade_counts) if trade_counts else 0,
            avg_win_rate=np.mean(win_rates) if win_rates else 0,
            
            strategy_performance=strategy_perf,
            top_performers=sorted_results[:20],
            bottom_performers=sorted_results[-20:],
        )
        
        return results
    
    def get_bot_details(self, bot_id: int) -> Optional[Dict]:
        """Get detailed results for a specific bot."""
        bot = self.bots.get(bot_id)
        if not bot:
            return None
        
        return {
            'bot': bot.to_dict(),
            'strategy': bot.strategy.to_dict(),
            'closed_trades': [t.to_dict() for t in bot.closed_trades[-50:]],  # Last 50 trades
        }
