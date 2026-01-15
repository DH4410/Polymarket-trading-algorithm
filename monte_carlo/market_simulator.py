"""Market Data Simulator for Monte Carlo testing.

Generates realistic market scenarios with:
- Price movements based on random walk with drift
- Various market outcomes (win, loss, expired)
- Realistic order book liquidity
- Market resolution events
"""

from __future__ import annotations

import random
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
import numpy as np


class MarketOutcome(Enum):
    """Possible outcomes for a simulated market."""
    YES_WINS = "yes_wins"  # Yes outcome resolves to $1
    NO_WINS = "no_wins"    # No outcome resolves to $1 (Yes = $0)
    UNRESOLVED = "unresolved"  # Market hasn't resolved yet


class PriceMovementType(Enum):
    """Type of price movement pattern."""
    DRIFT_UP = "drift_up"
    DRIFT_DOWN = "drift_down"
    MEAN_REVERT = "mean_revert"
    VOLATILE = "volatile"
    STABLE = "stable"
    SPIKE_UP = "spike_up"
    SPIKE_DOWN = "spike_down"


@dataclass
class SimulatedMarket:
    """A simulated market for testing."""
    market_id: str
    question: str
    outcome_name: str  # "Yes" or "No"
    token_id: str
    
    # Initial state
    initial_price: float
    initial_volume: float
    initial_liquidity: float
    
    # Time
    start_time: datetime
    end_time: datetime
    resolution_days: float
    
    # Current state (evolves over simulation)
    current_price: float = 0.0
    current_volume: float = 0.0
    current_liquidity: float = 0.0
    
    # Price history for analysis
    price_history: List[Tuple[datetime, float]] = field(default_factory=list)
    
    # Resolution
    final_outcome: MarketOutcome = MarketOutcome.UNRESOLVED
    resolved: bool = False
    resolution_time: Optional[datetime] = None
    
    # Movement pattern for this market
    movement_type: PriceMovementType = PriceMovementType.MEAN_REVERT
    
    # Category
    category: str = "other"
    
    def __post_init__(self):
        if self.current_price == 0.0:
            self.current_price = self.initial_price
        if self.current_volume == 0.0:
            self.current_volume = self.initial_volume
        if self.current_liquidity == 0.0:
            self.current_liquidity = self.initial_liquidity
    
    def to_api_format(self) -> Dict:
        """Convert to format expected by the trading bot."""
        return {
            'slug': self.market_id,
            'id': self.market_id,
            'question': self.question,
            'title': self.question,
            'outcomes': json.dumps([self.outcome_name, "No" if self.outcome_name == "Yes" else "Yes"]),
            'clobTokenIds': json.dumps([self.token_id, f"{self.token_id}_other"]),
            'outcomePrices': json.dumps([str(self.current_price), str(1 - self.current_price)]),
            'endDate': self.end_time.isoformat().replace('+00:00', 'Z'),
            'volumeNum': self.current_volume,
            'volume': str(self.current_volume),
            'volume24hr': self.current_volume * 0.05,  # 5% of total as 24h volume
            'liquidity': self.current_liquidity,
            'active': True,
            'closed': self.resolved,
        }
    
    def get_order_book(self) -> Dict[str, List[Tuple[float, float]]]:
        """Generate a simulated order book around current price."""
        spread = random.uniform(0.005, 0.02)  # 0.5% to 2% spread
        
        # Generate ask levels (sell orders above current price)
        asks = []
        ask_price = self.current_price + spread / 2
        remaining_liquidity = self.current_liquidity * 0.5
        
        for _ in range(5):
            if ask_price >= 0.99 or remaining_liquidity <= 0:
                break
            size = remaining_liquidity * random.uniform(0.15, 0.35)
            asks.append((round(ask_price, 4), round(size / ask_price, 2)))
            remaining_liquidity -= size
            ask_price += random.uniform(0.005, 0.015)
        
        # Generate bid levels (buy orders below current price)
        bids = []
        bid_price = self.current_price - spread / 2
        remaining_liquidity = self.current_liquidity * 0.5
        
        for _ in range(5):
            if bid_price <= 0.01 or remaining_liquidity <= 0:
                break
            size = remaining_liquidity * random.uniform(0.15, 0.35)
            bids.append((round(bid_price, 4), round(size / bid_price, 2)))
            remaining_liquidity -= size
            bid_price -= random.uniform(0.005, 0.015)
        
        return {'asks': asks, 'bids': bids}


class MarketSimulator:
    """Generates and manages simulated markets for Monte Carlo testing."""
    
    # Realistic market categories with base probabilities
    CATEGORIES = {
        'sports': {'base_accuracy': 0.55, 'volatility': 0.3, 'volume_mult': 1.5},
        'politics': {'base_accuracy': 0.52, 'volatility': 0.2, 'volume_mult': 2.0},
        'crypto': {'base_accuracy': 0.50, 'volatility': 0.5, 'volume_mult': 1.8},
        'entertainment': {'base_accuracy': 0.55, 'volatility': 0.25, 'volume_mult': 1.0},
        'finance': {'base_accuracy': 0.51, 'volatility': 0.35, 'volume_mult': 1.3},
        'technology': {'base_accuracy': 0.53, 'volatility': 0.4, 'volume_mult': 1.2},
        'world_events': {'base_accuracy': 0.52, 'volatility': 0.45, 'volume_mult': 1.4},
        'other': {'base_accuracy': 0.50, 'volatility': 0.3, 'volume_mult': 1.0},
    }
    
    # Question templates for each category
    QUESTION_TEMPLATES = {
        'sports': [
            "Will {team} win their next game?",
            "Will {team} make the playoffs?",
            "Will the {event} have over 100 points scored?",
            "Will {player} score over 25 points?",
        ],
        'politics': [
            "Will {candidate} win the election?",
            "Will {bill} pass by {date}?",
            "Will approval ratings be above 45%?",
            "Will the {party} win the {state} primary?",
        ],
        'crypto': [
            "Will Bitcoin be above ${price} by {date}?",
            "Will Ethereum reach ${price}?",
            "Will {coin} market cap exceed ${value}?",
            "Will Bitcoin ETF be approved by {date}?",
        ],
        'entertainment': [
            "Will {movie} gross over ${amount} opening weekend?",
            "Will {artist} win the Grammy?",
            "Will {show} be renewed for another season?",
        ],
        'finance': [
            "Will S&P 500 be above {value} by {date}?",
            "Will unemployment stay below {pct}%?",
            "Will the Fed raise rates in {month}?",
        ],
        'technology': [
            "Will {company} release {product} by {date}?",
            "Will AI model {name} be released?",
            "Will {tech} reach {milestone} users?",
        ],
        'world_events': [
            "Will {event} happen before {date}?",
            "Will {country} {action} by {date}?",
            "Will climate target be met?",
        ],
        'other': [
            "Will {event} occur by {date}?",
            "Will {metric} exceed {value}?",
        ],
    }
    
    def __init__(self, seed: int = None):
        """Initialize the market simulator.
        
        Args:
            seed: Random seed for reproducibility
        """
        self.seed = seed
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        
        self.markets: Dict[str, SimulatedMarket] = {}
        self._market_counter = 0
    
    def generate_markets(
        self, 
        count: int = 200,
        simulation_days: int = 90,
        start_date: datetime = None,
    ) -> List[SimulatedMarket]:
        """Generate a set of simulated markets.
        
        Args:
            count: Number of markets to generate
            simulation_days: Total days the simulation will run
            start_date: Start date for simulation (default: now)
            
        Returns:
            List of SimulatedMarket objects
        """
        if start_date is None:
            start_date = datetime.now(timezone.utc)
        
        markets = []
        categories = list(self.CATEGORIES.keys())
        
        for i in range(count):
            category = random.choice(categories)
            market = self._generate_single_market(
                category=category,
                start_date=start_date,
                simulation_days=simulation_days,
            )
            markets.append(market)
            self.markets[market.market_id] = market
        
        return markets
    
    def _generate_single_market(
        self,
        category: str,
        start_date: datetime,
        simulation_days: int,
    ) -> SimulatedMarket:
        """Generate a single simulated market."""
        self._market_counter += 1
        
        cat_params = self.CATEGORIES.get(category, self.CATEGORIES['other'])
        
        # Generate resolution time (between 1 hour and simulation_days from start)
        min_hours = 1
        max_hours = simulation_days * 24
        resolution_hours = random.uniform(min_hours, max_hours)
        resolution_days = resolution_hours / 24
        
        end_time = start_date + timedelta(hours=resolution_hours)
        
        # Generate initial price based on category accuracy
        # Markets with higher accuracy tend to start with more extreme prices
        base_accuracy = cat_params['base_accuracy']
        
        # Price distribution: favor mid-range prices but allow extremes
        if random.random() < 0.3:
            # 30% chance of extreme price (potential high return)
            initial_price = random.choice([
                random.uniform(0.03, 0.15),  # Low price (high potential)
                random.uniform(0.85, 0.95),  # High price (low potential)
            ])
        else:
            # 70% mid-range prices
            initial_price = random.uniform(0.20, 0.75)
        
        # Generate volume and liquidity
        base_volume = random.uniform(1000, 100000)
        volume = base_volume * cat_params['volume_mult']
        liquidity = volume * random.uniform(0.05, 0.20)
        
        # Determine movement pattern
        movement_type = random.choice(list(PriceMovementType))
        
        # Generate question
        templates = self.QUESTION_TEMPLATES.get(category, self.QUESTION_TEMPLATES['other'])
        question = random.choice(templates)
        # Fill in placeholders with generic values
        question = question.format(
            team="Team Alpha", player="Player X", event="Championship",
            candidate="Candidate A", bill="Bill 123", date="March 2026",
            party="Party X", state="State Y", price="50,000", coin="Altcoin",
            value="1B", movie="Blockbuster", artist="Artist Z", show="Hit Show",
            company="Tech Corp", product="New Product", name="GPT-5",
            tech="Service", milestone="100M", country="Nation X", action="act",
            metric="Value", pct="5", amount="100M", month="March",
        )
        
        market = SimulatedMarket(
            market_id=f"sim_market_{self._market_counter:04d}",
            question=question,
            outcome_name="Yes",
            token_id=f"sim_token_{self._market_counter:04d}",
            initial_price=round(initial_price, 4),
            initial_volume=round(volume, 2),
            initial_liquidity=round(liquidity, 2),
            start_time=start_date,
            end_time=end_time,
            resolution_days=resolution_days,
            movement_type=movement_type,
            category=category,
        )
        
        # Initialize price history
        market.price_history.append((start_date, initial_price))
        
        return market
    
    def simulate_price_movement(
        self, 
        market: SimulatedMarket, 
        current_time: datetime,
        time_step_hours: float = 1.0,
    ) -> float:
        """Simulate price movement for a market.
        
        Args:
            market: The market to update
            current_time: Current simulation time
            time_step_hours: Hours since last update
            
        Returns:
            New price
        """
        if market.resolved:
            return market.current_price
        
        # Check if market should resolve
        if current_time >= market.end_time:
            self._resolve_market(market, current_time)
            return market.current_price
        
        old_price = market.current_price
        cat_params = self.CATEGORIES.get(market.category, self.CATEGORIES['other'])
        volatility = cat_params['volatility']
        
        # Time-based volatility scaling (more volatile near resolution)
        time_remaining = (market.end_time - current_time).total_seconds()
        total_time = (market.end_time - market.start_time).total_seconds()
        time_factor = 1 + (1 - time_remaining / total_time) * 0.5  # Up to 50% more volatile near end
        
        # Calculate price change based on movement type
        daily_volatility = volatility * 0.1  # Base daily volatility
        hourly_volatility = daily_volatility / np.sqrt(24)
        step_volatility = hourly_volatility * np.sqrt(time_step_hours) * time_factor
        
        # Random component
        random_change = np.random.normal(0, step_volatility)
        
        # Drift component based on movement type
        drift = 0
        if market.movement_type == PriceMovementType.DRIFT_UP:
            drift = 0.002 * time_step_hours
        elif market.movement_type == PriceMovementType.DRIFT_DOWN:
            drift = -0.002 * time_step_hours
        elif market.movement_type == PriceMovementType.MEAN_REVERT:
            # Revert towards 0.5
            drift = (0.5 - old_price) * 0.01 * time_step_hours
        elif market.movement_type == PriceMovementType.VOLATILE:
            step_volatility *= 1.5
        elif market.movement_type == PriceMovementType.SPIKE_UP:
            if random.random() < 0.05:  # 5% chance of spike
                drift = random.uniform(0.05, 0.15)
        elif market.movement_type == PriceMovementType.SPIKE_DOWN:
            if random.random() < 0.05:  # 5% chance of spike
                drift = random.uniform(-0.15, -0.05)
        
        # Calculate new price
        new_price = old_price + drift + random_change
        
        # Clamp to valid range
        new_price = max(0.01, min(0.99, new_price))
        
        # Update market state
        market.current_price = round(new_price, 4)
        market.price_history.append((current_time, market.current_price))
        
        # Update volume (random walk around initial)
        volume_change = random.uniform(-0.05, 0.10) * market.initial_volume * time_step_hours / 24
        market.current_volume = max(100, market.current_volume + volume_change)
        
        # Update liquidity
        liq_change = random.uniform(-0.03, 0.05) * market.initial_liquidity * time_step_hours / 24
        market.current_liquidity = max(50, market.current_liquidity + liq_change)
        
        return market.current_price
    
    def _resolve_market(self, market: SimulatedMarket, resolution_time: datetime) -> None:
        """Resolve a market and determine the outcome."""
        market.resolved = True
        market.resolution_time = resolution_time
        
        # Determine outcome based on final price and some randomness
        # Higher price = more likely Yes wins
        # But there's always uncertainty
        
        final_price = market.current_price
        
        # Add some noise to simulate real-world uncertainty
        effective_probability = final_price + random.uniform(-0.1, 0.1)
        effective_probability = max(0.05, min(0.95, effective_probability))
        
        # Roll the dice
        if random.random() < effective_probability:
            market.final_outcome = MarketOutcome.YES_WINS
            market.current_price = 1.0  # Yes settles at $1
        else:
            market.final_outcome = MarketOutcome.NO_WINS
            market.current_price = 0.0  # Yes settles at $0
    
    def get_market_snapshot(self, market_id: str) -> Optional[Dict]:
        """Get current snapshot of a market in API format."""
        market = self.markets.get(market_id)
        if market:
            return market.to_api_format()
        return None
    
    def get_all_active_markets(self, current_time: datetime) -> List[Dict]:
        """Get all active (unresolved) markets in API format."""
        active = []
        for market in self.markets.values():
            if not market.resolved and current_time < market.end_time:
                active.append(market.to_api_format())
        return active
    
    def advance_time(self, hours: float) -> None:
        """Advance simulation time and update all markets.
        
        Args:
            hours: Number of hours to advance
        """
        # This is called by the simulator to update all market prices
        pass  # Actual price updates happen in simulate_price_movement
    
    def get_resolution_value(self, market_id: str, outcome: str) -> Optional[float]:
        """Get the resolution value for a position.
        
        Args:
            market_id: Market identifier
            outcome: Outcome name (e.g., "Yes")
            
        Returns:
            Settlement value (0.0 or 1.0) or None if not resolved
        """
        market = self.markets.get(market_id)
        if not market or not market.resolved:
            return None
        
        if outcome.lower() == "yes":
            return 1.0 if market.final_outcome == MarketOutcome.YES_WINS else 0.0
        else:
            return 0.0 if market.final_outcome == MarketOutcome.YES_WINS else 1.0
    
    def get_statistics(self) -> Dict:
        """Get statistics about generated markets."""
        total = len(self.markets)
        resolved = sum(1 for m in self.markets.values() if m.resolved)
        
        category_counts = {}
        for market in self.markets.values():
            cat = market.category
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        outcomes = {
            'yes_wins': sum(1 for m in self.markets.values() 
                          if m.final_outcome == MarketOutcome.YES_WINS),
            'no_wins': sum(1 for m in self.markets.values() 
                         if m.final_outcome == MarketOutcome.NO_WINS),
        }
        
        avg_initial_price = np.mean([m.initial_price for m in self.markets.values()]) if self.markets else 0
        avg_volume = np.mean([m.initial_volume for m in self.markets.values()]) if self.markets else 0
        
        return {
            'total_markets': total,
            'resolved_markets': resolved,
            'active_markets': total - resolved,
            'category_distribution': category_counts,
            'outcomes': outcomes,
            'avg_initial_price': round(avg_initial_price, 4),
            'avg_volume': round(avg_volume, 2),
        }
