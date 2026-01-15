"""Monte Carlo Simulation System for Polymarket Trading Bot.

This package provides tools to:
1. Run 500+ simulated bots with different strategy parameters
2. Test various trading configurations
3. Analyze performance across multiple scenarios
4. Visualize results to find optimal strategies
"""

from .simulator import MonteCarloSimulator
from .strategy_generator import StrategyGenerator, StrategyConfig
from .market_simulator import MarketSimulator, SimulatedMarket
from .results_analyzer import ResultsAnalyzer

__all__ = [
    'MonteCarloSimulator',
    'StrategyGenerator',
    'StrategyConfig', 
    'MarketSimulator',
    'SimulatedMarket',
    'ResultsAnalyzer',
]
