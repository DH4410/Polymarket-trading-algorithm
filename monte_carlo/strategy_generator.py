"""Strategy configuration generator for Monte Carlo simulation.

Generates 500 different strategy configurations by varying:
- Risk parameters (stop loss, take profit)
- Position sizing (max position, portfolio %)
- Entry thresholds (g-score, confidence, ROI)
- Market filters (price range, volume, liquidity)
- Time preferences (resolution days)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import numpy as np


@dataclass
class StrategyConfig:
    """Configuration for a single bot strategy."""
    id: int
    name: str
    
    # Capital
    initial_capital: float = 200.0  # User requested €200
    max_position_size: float = 50.0
    max_position_pct: float = 0.15  # Max % of capital per trade
    
    # Risk management
    stop_loss_pct: float = 0.20
    take_profit_pct: float = 0.40
    
    # Swing trade settings
    swing_enabled: bool = True
    swing_take_profit_pct: float = 0.12
    swing_stop_loss_pct: float = 0.08
    
    # Entry thresholds
    min_g_score: float = 0.0003
    min_expected_roi: float = 0.05
    min_confidence: float = 0.50
    high_confidence: float = 0.70
    
    # Market filters
    min_price: float = 0.05
    max_price: float = 0.80
    min_volume: float = 1000.0
    min_liquidity: float = 500.0
    
    # Time preferences
    min_days: float = 0.1
    max_days: float = 180.0
    prefer_short_term: bool = False  # Weight towards faster resolution
    
    # Position limits
    max_positions: int = 30
    max_swing_positions: int = 15
    max_long_positions: int = 20
    
    # Test trades
    test_trade_enabled: bool = True
    test_trade_size: float = 10.0
    
    # Execution
    max_slippage_pct: float = 3.0
    
    # Meta
    strategy_type: str = "balanced"  # aggressive, conservative, balanced, momentum, value
    description: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'name': self.name,
            'initial_capital': self.initial_capital,
            'max_position_size': self.max_position_size,
            'max_position_pct': self.max_position_pct,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'swing_enabled': self.swing_enabled,
            'swing_take_profit_pct': self.swing_take_profit_pct,
            'swing_stop_loss_pct': self.swing_stop_loss_pct,
            'min_g_score': self.min_g_score,
            'min_expected_roi': self.min_expected_roi,
            'min_confidence': self.min_confidence,
            'high_confidence': self.high_confidence,
            'min_price': self.min_price,
            'max_price': self.max_price,
            'min_volume': self.min_volume,
            'min_liquidity': self.min_liquidity,
            'min_days': self.min_days,
            'max_days': self.max_days,
            'prefer_short_term': self.prefer_short_term,
            'max_positions': self.max_positions,
            'max_swing_positions': self.max_swing_positions,
            'max_long_positions': self.max_long_positions,
            'test_trade_enabled': self.test_trade_enabled,
            'test_trade_size': self.test_trade_size,
            'max_slippage_pct': self.max_slippage_pct,
            'strategy_type': self.strategy_type,
            'description': self.description,
        }


class StrategyGenerator:
    """Generates diverse strategy configurations for Monte Carlo testing."""
    
    # Strategy archetypes with parameter ranges
    ARCHETYPES = {
        'aggressive': {
            'stop_loss_pct': (0.10, 0.25),
            'take_profit_pct': (0.20, 0.60),
            'min_confidence': (0.35, 0.50),
            'min_g_score': (0.0001, 0.0005),
            'max_position_pct': (0.15, 0.30),
            'max_positions': (40, 60),
            'min_price': (0.02, 0.10),
            'max_price': (0.90, 0.95),
        },
        'conservative': {
            'stop_loss_pct': (0.08, 0.15),
            'take_profit_pct': (0.15, 0.30),
            'min_confidence': (0.65, 0.80),
            'min_g_score': (0.0005, 0.002),
            'max_position_pct': (0.05, 0.10),
            'max_positions': (10, 20),
            'min_price': (0.15, 0.30),
            'max_price': (0.65, 0.75),
        },
        'balanced': {
            'stop_loss_pct': (0.15, 0.25),
            'take_profit_pct': (0.25, 0.45),
            'min_confidence': (0.45, 0.60),
            'min_g_score': (0.0002, 0.001),
            'max_position_pct': (0.08, 0.15),
            'max_positions': (25, 40),
            'min_price': (0.05, 0.15),
            'max_price': (0.75, 0.85),
        },
        'momentum': {
            'stop_loss_pct': (0.12, 0.20),
            'take_profit_pct': (0.10, 0.25),  # Quick profits
            'min_confidence': (0.40, 0.55),
            'min_g_score': (0.0003, 0.001),
            'max_position_pct': (0.10, 0.20),
            'max_positions': (35, 50),
            'min_price': (0.10, 0.25),
            'max_price': (0.80, 0.90),
            'prefer_short_term': True,
        },
        'value': {
            'stop_loss_pct': (0.25, 0.40),  # Wide stops for long holds
            'take_profit_pct': (0.50, 1.00),  # Big profit targets
            'min_confidence': (0.55, 0.70),
            'min_g_score': (0.0001, 0.0004),
            'max_position_pct': (0.10, 0.20),
            'max_positions': (15, 30),
            'min_price': (0.03, 0.12),  # Deep value
            'max_price': (0.60, 0.75),
            'prefer_short_term': False,
        },
        'scalper': {
            'stop_loss_pct': (0.05, 0.10),  # Tight stops
            'take_profit_pct': (0.08, 0.15),  # Small quick profits
            'min_confidence': (0.50, 0.65),
            'min_g_score': (0.001, 0.005),  # High g-score requirement
            'max_position_pct': (0.03, 0.08),  # Small positions
            'max_positions': (50, 80),  # Many positions
            'min_price': (0.20, 0.40),
            'max_price': (0.60, 0.80),
            'prefer_short_term': True,
        },
        'high_roller': {
            'stop_loss_pct': (0.20, 0.35),
            'take_profit_pct': (0.40, 0.80),
            'min_confidence': (0.30, 0.45),  # Lower bar
            'min_g_score': (0.00005, 0.0003),
            'max_position_pct': (0.20, 0.40),  # Big bets
            'max_positions': (10, 20),  # Concentrated
            'min_price': (0.02, 0.08),  # Long shots
            'max_price': (0.85, 0.95),
        },
        'diversifier': {
            'stop_loss_pct': (0.15, 0.25),
            'take_profit_pct': (0.20, 0.35),
            'min_confidence': (0.45, 0.55),
            'min_g_score': (0.0002, 0.0008),
            'max_position_pct': (0.03, 0.06),  # Small positions
            'max_positions': (60, 100),  # Many positions
            'min_price': (0.08, 0.20),
            'max_price': (0.70, 0.85),
        },
    }
    
    def __init__(self, initial_capital: float = 200.0, seed: int = None):
        """Initialize the strategy generator.
        
        Args:
            initial_capital: Starting capital for each bot (default €200)
            seed: Random seed for reproducibility
        """
        self.initial_capital = initial_capital
        self.seed = seed
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
    
    def generate_strategies(self, count: int = 500) -> List[StrategyConfig]:
        """Generate a diverse set of strategy configurations.
        
        Args:
            count: Number of strategies to generate (default 500)
            
        Returns:
            List of StrategyConfig objects
        """
        strategies = []
        
        # Calculate how many of each archetype to generate
        archetype_names = list(self.ARCHETYPES.keys())
        num_archetypes = len(archetype_names)
        base_per_archetype = count // num_archetypes
        extras = count % num_archetypes
        
        strategy_id = 1
        
        for i, archetype in enumerate(archetype_names):
            # Distribute extras across first few archetypes
            num_for_archetype = base_per_archetype + (1 if i < extras else 0)
            
            for j in range(num_for_archetype):
                strategy = self._generate_single_strategy(
                    strategy_id=strategy_id,
                    archetype=archetype,
                    variation_index=j,
                )
                strategies.append(strategy)
                strategy_id += 1
        
        # Shuffle to mix archetypes
        random.shuffle(strategies)
        
        # Re-assign IDs after shuffle
        for i, strategy in enumerate(strategies):
            strategy.id = i + 1
        
        return strategies
    
    def _generate_single_strategy(
        self, 
        strategy_id: int, 
        archetype: str,
        variation_index: int,
    ) -> StrategyConfig:
        """Generate a single strategy configuration with random variation."""
        
        params = self.ARCHETYPES[archetype]
        
        # Helper to get random value from range
        def rand_range(key: str, default: Tuple[float, float]) -> float:
            low, high = params.get(key, default)
            return random.uniform(low, high)
        
        def rand_bool(key: str, default: bool = False) -> bool:
            return params.get(key, default)
        
        # Generate position size based on capital
        max_pos_pct = rand_range('max_position_pct', (0.08, 0.15))
        max_pos_size = min(
            self.initial_capital * max_pos_pct,
            self.initial_capital * 0.4  # Hard cap at 40%
        )
        
        # Generate test trade size (smaller)
        test_size = max(5.0, self.initial_capital * random.uniform(0.02, 0.08))
        
        # Calculate max positions based on capital
        base_max_positions = params.get('max_positions', (25, 40))
        # Scale positions down for smaller capital
        capital_scale = min(1.0, self.initial_capital / 1000)
        scaled_positions = (
            int(base_max_positions[0] * capital_scale),
            int(base_max_positions[1] * capital_scale)
        )
        max_positions = max(5, random.randint(max(5, scaled_positions[0]), max(10, scaled_positions[1])))
        
        # Swing positions as fraction of total
        max_swing = max(2, int(max_positions * random.uniform(0.3, 0.5)))
        max_long = max(3, int(max_positions * random.uniform(0.5, 0.8)))
        
        # Create strategy name
        suffix = f"v{variation_index + 1}"
        name = f"{archetype.capitalize()}_{suffix}"
        
        config = StrategyConfig(
            id=strategy_id,
            name=name,
            initial_capital=self.initial_capital,
            max_position_size=round(max_pos_size, 2),
            max_position_pct=round(max_pos_pct, 3),
            
            stop_loss_pct=round(rand_range('stop_loss_pct', (0.15, 0.25)), 3),
            take_profit_pct=round(rand_range('take_profit_pct', (0.25, 0.45)), 3),
            
            swing_enabled=random.random() > 0.2,  # 80% enable swing
            swing_take_profit_pct=round(random.uniform(0.08, 0.20), 3),
            swing_stop_loss_pct=round(random.uniform(0.05, 0.12), 3),
            
            min_g_score=round(rand_range('min_g_score', (0.0002, 0.001)), 6),
            min_expected_roi=round(random.uniform(0.03, 0.15), 3),
            min_confidence=round(rand_range('min_confidence', (0.45, 0.60)), 3),
            high_confidence=round(random.uniform(0.65, 0.85), 3),
            
            min_price=round(rand_range('min_price', (0.05, 0.15)), 3),
            max_price=round(rand_range('max_price', (0.75, 0.85)), 3),
            min_volume=round(random.uniform(500, 5000), 0),
            min_liquidity=round(random.uniform(200, 2000), 0),
            
            min_days=round(random.uniform(0.05, 1.0), 2),
            max_days=round(random.uniform(60, 365), 0),
            prefer_short_term=rand_bool('prefer_short_term', False),
            
            max_positions=max_positions,
            max_swing_positions=max_swing,
            max_long_positions=max_long,
            
            test_trade_enabled=random.random() > 0.3,  # 70% enable test trades
            test_trade_size=round(test_size, 2),
            
            max_slippage_pct=round(random.uniform(1.5, 5.0), 2),
            
            strategy_type=archetype,
            description=self._generate_description(archetype),
        )
        
        return config
    
    def _generate_description(self, archetype: str) -> str:
        """Generate a description for the strategy type."""
        descriptions = {
            'aggressive': "High-risk strategy targeting maximum returns with larger positions and wider stops",
            'conservative': "Low-risk strategy with tight filters and smaller positions",
            'balanced': "Moderate approach balancing risk and reward",
            'momentum': "Quick-trade strategy focusing on short-term price movements",
            'value': "Long-term strategy targeting undervalued positions",
            'scalper': "Many small quick trades with tight risk management",
            'high_roller': "Concentrated bets on high-conviction opportunities",
            'diversifier': "Spread risk across many small positions",
        }
        return descriptions.get(archetype, "Custom strategy configuration")
    
    def get_archetype_distribution(self, strategies: List[StrategyConfig]) -> Dict[str, int]:
        """Get count of strategies by archetype."""
        distribution = {}
        for strategy in strategies:
            archetype = strategy.strategy_type
            distribution[archetype] = distribution.get(archetype, 0) + 1
        return distribution
