"""Results Analyzer and Visualizer for Monte Carlo Simulation.

Generates comprehensive analysis including:
- Performance distribution charts
- Strategy comparison
- Risk/reward analysis
- Optimal parameter identification
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np

# Try to import matplotlib for visualization
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.ticker import PercentFormatter
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None


class ResultsAnalyzer:
    """Analyzes and visualizes Monte Carlo simulation results."""
    
    def __init__(self, results: Dict, output_dir: Path = None):
        """Initialize the analyzer.
        
        Args:
            results: Results dictionary from SimulationResults.to_dict()
            output_dir: Directory to save visualizations
        """
        self.results = results
        self.output_dir = output_dir or Path("monte_carlo_results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract data
        self.bot_results = results.get('all_bots', [])
        self.summary = results.get('summary', {})
        self.strategy_perf = results.get('strategy_performance', {})
        self.config = results.get('config', {})
    
    def generate_full_report(self) -> Path:
        """Generate a comprehensive analysis report.
        
        Returns:
            Path to the generated report directory
        """
        print("\nGenerating Analysis Report...")
        print("=" * 50)
        
        # Generate visualizations if matplotlib available
        if MATPLOTLIB_AVAILABLE:
            self._generate_return_distribution()
            self._generate_strategy_comparison()
            self._generate_risk_reward_scatter()
            self._generate_top_performers_chart()
            self._generate_win_rate_analysis()
            print("  ✓ Generated all visualizations")
        else:
            print("  ⚠ matplotlib not available - skipping visualizations")
        
        # Generate text report
        report_path = self._generate_text_report()
        
        # Save raw results
        results_path = self.output_dir / "raw_results.json"
        with open(results_path, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"  ✓ Saved raw results to {results_path}")
        
        # Generate optimal strategy recommendations
        self._generate_recommendations()
        
        print(f"\n✅ Report saved to: {self.output_dir}")
        return self.output_dir
    
    def _generate_return_distribution(self) -> None:
        """Generate histogram of return distribution."""
        returns = [b['total_return_pct'] for b in self.bot_results]
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Color based on profit/loss
        colors = ['#3fb950' if r > 0 else '#f85149' for r in returns]
        
        n, bins, patches = ax.hist(returns, bins=50, edgecolor='white', alpha=0.8)
        
        # Color the bars
        for i, patch in enumerate(patches):
            if bins[i] >= 0:
                patch.set_facecolor('#3fb950')
            else:
                patch.set_facecolor('#f85149')
        
        # Add vertical line at 0
        ax.axvline(x=0, color='white', linestyle='--', linewidth=2, label='Break-even')
        
        # Add mean and median lines
        mean_ret = np.mean(returns)
        median_ret = np.median(returns)
        ax.axvline(x=mean_ret, color='#58a6ff', linestyle='-', linewidth=2, label=f'Mean: {mean_ret:.1f}%')
        ax.axvline(x=median_ret, color='#d29922', linestyle='-', linewidth=2, label=f'Median: {median_ret:.1f}%')
        
        ax.set_xlabel('Return (%)', fontsize=12)
        ax.set_ylabel('Number of Bots', fontsize=12)
        ax.set_title('Distribution of Bot Returns', fontsize=14, fontweight='bold')
        ax.legend(loc='upper right')
        ax.set_facecolor('#0d1117')
        fig.set_facecolor('#0d1117')
        ax.tick_params(colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')
        
        # Add statistics text box
        stats_text = (
            f"Profitable: {self.summary.get('profitable_pct', 0):.1f}%\n"
            f"Best: {self.summary.get('best_return_pct', 0):.1f}%\n"
            f"Worst: {self.summary.get('worst_return_pct', 0):.1f}%\n"
            f"Std Dev: {self.summary.get('std_return_pct', 0):.1f}%"
        )
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
                verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle='round', facecolor='#21262d', edgecolor='#30363d'),
                color='white')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'return_distribution.png', dpi=150, 
                   facecolor='#0d1117', edgecolor='none')
        plt.close()
    
    def _generate_strategy_comparison(self) -> None:
        """Generate bar chart comparing strategy types."""
        if not self.strategy_perf:
            return
        
        strategies = list(self.strategy_perf.keys())
        avg_returns = [self.strategy_perf[s]['avg_return_pct'] for s in strategies]
        profitable_pcts = [self.strategy_perf[s]['profitable_pct'] for s in strategies]
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # Bar colors based on positive/negative
        colors1 = ['#3fb950' if r > 0 else '#f85149' for r in avg_returns]
        colors2 = ['#3fb950' if p > 50 else '#f85149' for p in profitable_pcts]
        
        # Average returns
        bars1 = ax1.barh(strategies, avg_returns, color=colors1, edgecolor='white')
        ax1.axvline(x=0, color='white', linestyle='--', linewidth=1)
        ax1.set_xlabel('Average Return (%)', fontsize=11)
        ax1.set_title('Average Return by Strategy Type', fontsize=12, fontweight='bold')
        
        # Add value labels
        for bar, val in zip(bars1, avg_returns):
            ax1.text(val + (1 if val >= 0 else -1), bar.get_y() + bar.get_height()/2,
                    f'{val:.1f}%', va='center', ha='left' if val >= 0 else 'right',
                    color='white', fontsize=9)
        
        # Profitable percentage
        bars2 = ax2.barh(strategies, profitable_pcts, color=colors2, edgecolor='white')
        ax2.axvline(x=50, color='white', linestyle='--', linewidth=1, label='50% threshold')
        ax2.set_xlabel('Profitable Bots (%)', fontsize=11)
        ax2.set_title('Profitability Rate by Strategy Type', fontsize=12, fontweight='bold')
        ax2.set_xlim(0, 100)
        
        # Add value labels
        for bar, val in zip(bars2, profitable_pcts):
            ax2.text(val + 1, bar.get_y() + bar.get_height()/2,
                    f'{val:.1f}%', va='center', ha='left', color='white', fontsize=9)
        
        # Style both axes
        for ax in [ax1, ax2]:
            ax.set_facecolor('#0d1117')
            ax.tick_params(colors='white')
            ax.xaxis.label.set_color('white')
            ax.title.set_color('white')
            for spine in ax.spines.values():
                spine.set_color('#30363d')
        
        fig.set_facecolor('#0d1117')
        plt.tight_layout()
        plt.savefig(self.output_dir / 'strategy_comparison.png', dpi=150,
                   facecolor='#0d1117', edgecolor='none')
        plt.close()
    
    def _generate_risk_reward_scatter(self) -> None:
        """Generate scatter plot of risk vs reward."""
        # Extract risk (max drawdown or std) and reward (return)
        returns = [b['total_return_pct'] for b in self.bot_results]
        drawdowns = [b.get('max_drawdown', 0) * 100 for b in self.bot_results]
        strategies = [b['strategy_type'] for b in self.bot_results]
        
        # Color map for strategies
        unique_strategies = list(set(strategies))
        colors_map = {
            'aggressive': '#f85149',
            'conservative': '#3fb950',
            'balanced': '#58a6ff',
            'momentum': '#d29922',
            'value': '#a371f7',
            'scalper': '#db6d28',
            'high_roller': '#f778ba',
            'diversifier': '#79c0ff',
        }
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        for strategy in unique_strategies:
            mask = [s == strategy for s in strategies]
            s_returns = [r for r, m in zip(returns, mask) if m]
            s_drawdowns = [d for d, m in zip(drawdowns, mask) if m]
            
            color = colors_map.get(strategy, '#8b949e')
            ax.scatter(s_drawdowns, s_returns, c=color, alpha=0.6, 
                      s=50, label=strategy.capitalize(), edgecolors='white', linewidths=0.5)
        
        # Add quadrant lines
        ax.axhline(y=0, color='white', linestyle='--', linewidth=1, alpha=0.5)
        ax.axvline(x=20, color='white', linestyle='--', linewidth=1, alpha=0.5)
        
        # Labels for quadrants
        ax.text(0.02, 0.98, 'Low Risk\nHigh Return\n(IDEAL)', transform=ax.transAxes,
               fontsize=9, color='#3fb950', va='top', ha='left')
        ax.text(0.98, 0.98, 'High Risk\nHigh Return', transform=ax.transAxes,
               fontsize=9, color='#d29922', va='top', ha='right')
        ax.text(0.02, 0.02, 'Low Risk\nLow Return', transform=ax.transAxes,
               fontsize=9, color='#8b949e', va='bottom', ha='left')
        ax.text(0.98, 0.02, 'High Risk\nLow Return\n(AVOID)', transform=ax.transAxes,
               fontsize=9, color='#f85149', va='bottom', ha='right')
        
        ax.set_xlabel('Max Drawdown (%)', fontsize=12)
        ax.set_ylabel('Total Return (%)', fontsize=12)
        ax.set_title('Risk vs Reward Analysis', fontsize=14, fontweight='bold')
        ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), framealpha=0.9)
        
        ax.set_facecolor('#0d1117')
        fig.set_facecolor('#0d1117')
        ax.tick_params(colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'risk_reward_scatter.png', dpi=150,
                   facecolor='#0d1117', edgecolor='none', bbox_inches='tight')
        plt.close()
    
    def _generate_top_performers_chart(self) -> None:
        """Generate chart showing top and bottom performers."""
        top = self.results.get('top_performers', [])[:15]
        bottom = self.results.get('bottom_performers', [])[-15:]
        
        if not top or not bottom:
            return
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 8))
        
        # Top performers
        top_names = [f"Bot {b['id']} ({b['strategy_type'][:3]})" for b in top]
        top_returns = [b['total_return_pct'] for b in top]
        
        bars1 = ax1.barh(top_names, top_returns, color='#3fb950', edgecolor='white')
        ax1.set_xlabel('Return (%)', fontsize=11)
        ax1.set_title('🏆 Top 15 Performers', fontsize=12, fontweight='bold')
        
        # Add value labels
        for bar, val in zip(bars1, top_returns):
            ax1.text(val + 0.5, bar.get_y() + bar.get_height()/2,
                    f'{val:.1f}%', va='center', color='white', fontsize=9)
        
        # Bottom performers
        bottom_names = [f"Bot {b['id']} ({b['strategy_type'][:3]})" for b in bottom]
        bottom_returns = [b['total_return_pct'] for b in bottom]
        
        bars2 = ax2.barh(bottom_names, bottom_returns, color='#f85149', edgecolor='white')
        ax2.set_xlabel('Return (%)', fontsize=11)
        ax2.set_title('📉 Bottom 15 Performers', fontsize=12, fontweight='bold')
        
        # Add value labels
        for bar, val in zip(bars2, bottom_returns):
            ax2.text(val - 0.5, bar.get_y() + bar.get_height()/2,
                    f'{val:.1f}%', va='center', ha='right', color='white', fontsize=9)
        
        # Style both axes
        for ax in [ax1, ax2]:
            ax.set_facecolor('#0d1117')
            ax.tick_params(colors='white')
            ax.xaxis.label.set_color('white')
            ax.title.set_color('white')
            for spine in ax.spines.values():
                spine.set_color('#30363d')
        
        fig.set_facecolor('#0d1117')
        plt.tight_layout()
        plt.savefig(self.output_dir / 'top_bottom_performers.png', dpi=150,
                   facecolor='#0d1117', edgecolor='none')
        plt.close()
    
    def _generate_win_rate_analysis(self) -> None:
        """Generate analysis of win rates vs returns."""
        win_rates = [b['win_rate'] for b in self.bot_results]
        returns = [b['total_return_pct'] for b in self.bot_results]
        trades = [b['total_trades'] for b in self.bot_results]
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # Win rate vs return scatter
        scatter = ax1.scatter(win_rates, returns, c=trades, cmap='plasma', 
                             alpha=0.6, s=30, edgecolors='white', linewidths=0.5)
        ax1.axhline(y=0, color='white', linestyle='--', linewidth=1, alpha=0.5)
        ax1.axvline(x=50, color='white', linestyle='--', linewidth=1, alpha=0.5)
        
        ax1.set_xlabel('Win Rate (%)', fontsize=11)
        ax1.set_ylabel('Total Return (%)', fontsize=11)
        ax1.set_title('Win Rate vs Return (colored by # trades)', fontsize=12, fontweight='bold')
        
        cbar = plt.colorbar(scatter, ax=ax1)
        cbar.set_label('Number of Trades', color='white')
        cbar.ax.yaxis.set_tick_params(color='white')
        plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
        
        # Win rate distribution
        ax2.hist(win_rates, bins=30, color='#58a6ff', edgecolor='white', alpha=0.8)
        ax2.axvline(x=50, color='white', linestyle='--', linewidth=2, label='50% (break-even)')
        ax2.axvline(x=np.mean(win_rates), color='#3fb950', linestyle='-', linewidth=2, 
                   label=f'Mean: {np.mean(win_rates):.1f}%')
        
        ax2.set_xlabel('Win Rate (%)', fontsize=11)
        ax2.set_ylabel('Number of Bots', fontsize=11)
        ax2.set_title('Distribution of Win Rates', fontsize=12, fontweight='bold')
        ax2.legend()
        
        # Style both axes
        for ax in [ax1, ax2]:
            ax.set_facecolor('#0d1117')
            ax.tick_params(colors='white')
            ax.xaxis.label.set_color('white')
            ax.yaxis.label.set_color('white')
            ax.title.set_color('white')
            for spine in ax.spines.values():
                spine.set_color('#30363d')
        
        fig.set_facecolor('#0d1117')
        plt.tight_layout()
        plt.savefig(self.output_dir / 'win_rate_analysis.png', dpi=150,
                   facecolor='#0d1117', edgecolor='none')
        plt.close()
    
    def _generate_text_report(self) -> Path:
        """Generate a text-based analysis report."""
        report_path = self.output_dir / "analysis_report.txt"
        
        lines = []
        lines.append("=" * 70)
        lines.append("MONTE CARLO SIMULATION ANALYSIS REPORT")
        lines.append("=" * 70)
        lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Simulation ID: {self.results.get('simulation_id', 'N/A')}")
        
        # Configuration
        lines.append("\n" + "-" * 70)
        lines.append("CONFIGURATION")
        lines.append("-" * 70)
        lines.append(f"Number of Bots: {self.config.get('num_bots', 'N/A')}")
        lines.append(f"Number of Markets: {self.config.get('num_markets', 'N/A')}")
        lines.append(f"Simulation Days: {self.config.get('simulation_days', 'N/A')}")
        lines.append(f"Initial Capital: €{self.config.get('initial_capital', 'N/A')}")
        
        # Summary Statistics
        lines.append("\n" + "-" * 70)
        lines.append("SUMMARY STATISTICS")
        lines.append("-" * 70)
        lines.append(f"Average Return: {self.summary.get('avg_return_pct', 0):.2f}%")
        lines.append(f"Median Return: {self.summary.get('median_return_pct', 0):.2f}%")
        lines.append(f"Standard Deviation: {self.summary.get('std_return_pct', 0):.2f}%")
        lines.append(f"Best Return: {self.summary.get('best_return_pct', 0):.2f}%")
        lines.append(f"Worst Return: {self.summary.get('worst_return_pct', 0):.2f}%")
        lines.append(f"\nProfitable Bots: {self.summary.get('profitable_bots', 0)} ({self.summary.get('profitable_pct', 0):.1f}%)")
        lines.append(f"Average Trades per Bot: {self.summary.get('avg_trades_per_bot', 0):.1f}")
        lines.append(f"Average Win Rate: {self.summary.get('avg_win_rate', 0):.1f}%")
        
        # Strategy Performance
        lines.append("\n" + "-" * 70)
        lines.append("STRATEGY TYPE PERFORMANCE")
        lines.append("-" * 70)
        
        # Sort strategies by average return
        sorted_strategies = sorted(
            self.strategy_perf.items(),
            key=lambda x: x[1]['avg_return_pct'],
            reverse=True
        )
        
        for strategy, perf in sorted_strategies:
            lines.append(f"\n{strategy.upper()}")
            lines.append(f"  Count: {perf['count']} bots")
            lines.append(f"  Avg Return: {perf['avg_return_pct']:.2f}%")
            lines.append(f"  Median Return: {perf['median_return_pct']:.2f}%")
            lines.append(f"  Std Dev: {perf['std_return_pct']:.2f}%")
            lines.append(f"  Best: {perf['best_return_pct']:.2f}% | Worst: {perf['worst_return_pct']:.2f}%")
            lines.append(f"  Profitable: {perf['profitable_pct']:.1f}%")
        
        # Top Performers
        lines.append("\n" + "-" * 70)
        lines.append("TOP 10 PERFORMERS")
        lines.append("-" * 70)
        
        top = self.results.get('top_performers', [])[:10]
        for i, bot in enumerate(top, 1):
            lines.append(f"\n#{i}. Bot {bot['id']} ({bot['strategy_type']})")
            lines.append(f"    Return: {bot['total_return_pct']:.2f}%")
            lines.append(f"    Portfolio Value: €{bot['portfolio_value']:.2f}")
            lines.append(f"    Trades: {bot['total_trades']} | Win Rate: {bot['win_rate']:.1f}%")
        
        # Bottom Performers
        lines.append("\n" + "-" * 70)
        lines.append("BOTTOM 10 PERFORMERS")
        lines.append("-" * 70)
        
        bottom = self.results.get('bottom_performers', [])[-10:]
        for i, bot in enumerate(bottom, 1):
            lines.append(f"\n#{i}. Bot {bot['id']} ({bot['strategy_type']})")
            lines.append(f"    Return: {bot['total_return_pct']:.2f}%")
            lines.append(f"    Portfolio Value: €{bot['portfolio_value']:.2f}")
            lines.append(f"    Trades: {bot['total_trades']} | Win Rate: {bot['win_rate']:.1f}%")
        
        lines.append("\n" + "=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)
        
        report_path.write_text("\n".join(lines), encoding='utf-8')
        print(f"  ✓ Generated text report: {report_path}")
        
        return report_path
    
    def _generate_recommendations(self) -> None:
        """Generate strategy recommendations based on results."""
        rec_path = self.output_dir / "recommendations.txt"
        
        lines = []
        lines.append("=" * 70)
        lines.append("STRATEGY RECOMMENDATIONS")
        lines.append("=" * 70)
        
        # Find best performing strategy type
        if self.strategy_perf:
            best_strategy = max(
                self.strategy_perf.items(),
                key=lambda x: x[1]['avg_return_pct']
            )
            
            lines.append(f"\n🏆 BEST STRATEGY TYPE: {best_strategy[0].upper()}")
            lines.append(f"   Average Return: {best_strategy[1]['avg_return_pct']:.2f}%")
            lines.append(f"   Profitability Rate: {best_strategy[1]['profitable_pct']:.1f}%")
            
            # Find most consistent (lowest std dev among profitable)
            profitable_strategies = [
                (k, v) for k, v in self.strategy_perf.items() 
                if v['avg_return_pct'] > 0
            ]
            
            if profitable_strategies:
                most_consistent = min(
                    profitable_strategies,
                    key=lambda x: x[1]['std_return_pct']
                )
                
                lines.append(f"\n📊 MOST CONSISTENT: {most_consistent[0].upper()}")
                lines.append(f"   Standard Deviation: {most_consistent[1]['std_return_pct']:.2f}%")
                lines.append(f"   Average Return: {most_consistent[1]['avg_return_pct']:.2f}%")
        
        # Analyze top performers for common traits
        top = self.results.get('top_performers', [])[:20]
        if top:
            lines.append("\n" + "-" * 70)
            lines.append("COMMON TRAITS OF TOP PERFORMERS")
            lines.append("-" * 70)
            
            # Average characteristics
            avg_win_rate = np.mean([b['win_rate'] for b in top])
            avg_trades = np.mean([b['total_trades'] for b in top])
            
            lines.append(f"\n• Average Win Rate: {avg_win_rate:.1f}%")
            lines.append(f"• Average Trade Count: {avg_trades:.0f}")
            
            # Most common strategy types
            strategy_counts = {}
            for b in top:
                st = b['strategy_type']
                strategy_counts[st] = strategy_counts.get(st, 0) + 1
            
            most_common = sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True)
            lines.append("\n• Most Common Strategy Types in Top 20:")
            for strategy, count in most_common[:3]:
                lines.append(f"  - {strategy}: {count} bots ({count/20*100:.0f}%)")
        
        # Key insights
        lines.append("\n" + "-" * 70)
        lines.append("KEY INSIGHTS")
        lines.append("-" * 70)
        
        profitable_pct = self.summary.get('profitable_pct', 0)
        if profitable_pct > 60:
            lines.append("\n✅ POSITIVE OUTLOOK: Over 60% of strategies were profitable")
            lines.append("   The underlying strategy appears robust.")
        elif profitable_pct > 40:
            lines.append("\n⚠️ MIXED RESULTS: 40-60% of strategies were profitable")
            lines.append("   Strategy refinement recommended.")
        else:
            lines.append("\n❌ CONCERNING: Less than 40% of strategies were profitable")
            lines.append("   Significant strategy adjustments needed.")
        
        avg_return = self.summary.get('avg_return_pct', 0)
        if avg_return > 10:
            lines.append(f"\n💰 STRONG AVERAGE RETURN: {avg_return:.1f}%")
            lines.append("   The strategy shows good profit potential.")
        elif avg_return > 0:
            lines.append(f"\n📈 MODEST AVERAGE RETURN: {avg_return:.1f}%")
            lines.append("   Profitability exists but optimization needed.")
        else:
            lines.append(f"\n📉 NEGATIVE AVERAGE RETURN: {avg_return:.1f}%")
            lines.append("   Strategy needs fundamental changes.")
        
        lines.append("\n" + "=" * 70)
        
        rec_path.write_text("\n".join(lines), encoding='utf-8')
        print(f"  ✓ Generated recommendations: {rec_path}")
    
    def get_optimal_parameters(self) -> Dict:
        """Extract optimal parameters from top performers."""
        top = self.results.get('top_performers', [])[:10]
        
        if not top:
            return {}
        
        # This would need the full strategy configs to be useful
        # For now, return summary statistics
        return {
            'best_strategy_type': top[0]['strategy_type'] if top else 'unknown',
            'avg_win_rate_top10': np.mean([b['win_rate'] for b in top]),
            'avg_trades_top10': np.mean([b['total_trades'] for b in top]),
            'avg_return_top10': np.mean([b['total_return_pct'] for b in top]),
        }
