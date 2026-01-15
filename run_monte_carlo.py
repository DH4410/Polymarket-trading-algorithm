#!/usr/bin/env python3
"""
Monte Carlo Simulation Runner for Polymarket Trading Bot

This script runs a comprehensive Monte Carlo simulation with 500 bots,
each with different strategy parameters, to test profitability and 
identify optimal trading strategies.

Usage:
    python run_monte_carlo.py [options]

Options:
    --bots N        Number of bots to simulate (default: 500)
    --capital N     Initial capital per bot in EUR (default: 200)
    --days N        Number of days to simulate (default: 90)
    --markets N     Number of markets to generate (default: 200)
    --seed N        Random seed for reproducibility
    --output DIR    Output directory for results
    --quick         Quick mode with fewer bots/days for testing

Example:
    python run_monte_carlo.py --bots 500 --capital 200 --days 90

Results will be saved to the monte_carlo_results/ directory including:
- Visualizations (if matplotlib installed)
- Detailed analysis report
- Raw JSON results
- Strategy recommendations
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from monte_carlo import (
    MonteCarloSimulator,
    StrategyGenerator,
    ResultsAnalyzer,
)


def print_banner():
    """Print a nice banner."""
    banner = """
╔════════════════════════════════════════════════════════════════════╗
║                                                                    ║
║     ███╗   ███╗ ██████╗ ███╗   ██╗████████╗███████╗               ║
║     ████╗ ████║██╔═══██╗████╗  ██║╚══██╔══╝██╔════╝               ║
║     ██╔████╔██║██║   ██║██╔██╗ ██║   ██║   █████╗                 ║
║     ██║╚██╔╝██║██║   ██║██║╚██╗██║   ██║   ██╔══╝                 ║
║     ██║ ╚═╝ ██║╚██████╔╝██║ ╚████║   ██║   ███████╗               ║
║     ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝               ║
║                                                                    ║
║      ██████╗ █████╗ ██████╗ ██╗      ██████╗                      ║
║     ██╔════╝██╔══██╗██╔══██╗██║     ██╔═══██╗                     ║
║     ██║     ███████║██████╔╝██║     ██║   ██║                     ║
║     ██║     ██╔══██║██╔══██╗██║     ██║   ██║                     ║
║     ╚██████╗██║  ██║██║  ██║███████╗╚██████╔╝                     ║
║      ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝                      ║
║                                                                    ║
║     Polymarket Trading Bot Strategy Testing System                 ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_config(args):
    """Print configuration summary."""
    print("\n┌──────────────────────────────────────────┐")
    print("│         SIMULATION CONFIGURATION         │")
    print("├──────────────────────────────────────────┤")
    print(f"│  Bots:            {args.bots:>6}               │")
    print(f"│  Capital/Bot:     €{args.capital:>6.2f}             │")
    print(f"│  Markets:         {args.markets:>6}               │")
    print(f"│  Days:            {args.days:>6}               │")
    print(f"│  Seed:            {args.seed if args.seed else 'Random':>6}               │")
    print("├──────────────────────────────────────────┤")
    print(f"│  Total Capital:   €{args.bots * args.capital:>10,.2f}         │")
    print("└──────────────────────────────────────────┘")


def progress_callback(current: int, total: int, message: str):
    """Progress callback for the simulator."""
    bar_length = 30
    filled = int(bar_length * current / total)
    bar = "█" * filled + "░" * (bar_length - filled)
    print(f"\r  [{bar}] {current}% - {message}", end="", flush=True)
    if current >= total:
        print()


def run_simulation(args):
    """Run the Monte Carlo simulation."""
    print_banner()
    print_config(args)
    
    print("\n" + "=" * 60)
    print("Starting Monte Carlo Simulation...")
    print("=" * 60)
    
    start_time = time.time()
    
    # Create simulator
    simulator = MonteCarloSimulator(
        num_bots=args.bots,
        initial_capital=args.capital,
        simulation_days=args.days,
        num_markets=args.markets,
        seed=args.seed,
        on_progress=progress_callback,
    )
    
    # Run simulation
    results = simulator.run()
    
    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results_file = output_dir / f"simulation_{results.simulation_id}.json"
    results.save(results_file)
    print(f"\n✓ Raw results saved to: {results_file}")
    
    # Generate analysis report
    print("\n" + "=" * 60)
    print("Generating Analysis Report...")
    print("=" * 60)
    
    analyzer = ResultsAnalyzer(results.to_dict(), output_dir)
    report_dir = analyzer.generate_full_report()
    
    # Print summary
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 60)
    print("                    SIMULATION COMPLETE")
    print("=" * 60)
    
    print(f"""
┌────────────────────────────────────────────────────────────┐
│                     RESULTS SUMMARY                        │
├────────────────────────────────────────────────────────────┤
│  Total Bots Simulated:          {results.num_bots:>6}                    │
│  Total Markets Generated:       {results.num_markets:>6}                    │
│  Simulation Period:             {results.simulation_days:>6} days               │
├────────────────────────────────────────────────────────────┤
│  PERFORMANCE METRICS                                       │
├────────────────────────────────────────────────────────────┤
│  Average Return:                {results.avg_return_pct:>+7.2f}%                  │
│  Median Return:                 {results.median_return_pct:>+7.2f}%                  │
│  Standard Deviation:            {results.std_return_pct:>7.2f}%                   │
│                                                            │
│  Best Return:                   {results.best_return_pct:>+7.2f}%                  │
│  Worst Return:                  {results.worst_return_pct:>+7.2f}%                  │
├────────────────────────────────────────────────────────────┤
│  PROFITABILITY                                             │
├────────────────────────────────────────────────────────────┤
│  Profitable Bots:               {results.profitable_bots:>6} ({results.profitable_pct:.1f}%)             │
│  Losing Bots:                   {results.num_bots - results.profitable_bots:>6} ({100-results.profitable_pct:.1f}%)             │
│  Average Win Rate:              {results.avg_win_rate:>6.1f}%                   │
│  Average Trades/Bot:            {results.avg_trades_per_bot:>6.1f}                    │
├────────────────────────────────────────────────────────────┤
│  Execution Time:                {elapsed:>6.1f} seconds             │
└────────────────────────────────────────────────────────────┘
""")
    
    # Print strategy performance summary
    print("\n┌────────────────────────────────────────────────────────────┐")
    print("│              STRATEGY TYPE PERFORMANCE                     │")
    print("├──────────────┬──────────┬──────────┬────────────┬──────────┤")
    print("│ Strategy     │ Avg Ret  │ Best Ret │ Profitable │ Count    │")
    print("├──────────────┼──────────┼──────────┼────────────┼──────────┤")
    
    # Sort by average return
    sorted_perf = sorted(
        results.strategy_performance.items(),
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
    
    # Print top 5 performers
    print("\n🏆 TOP 5 PERFORMERS:")
    for i, bot in enumerate(results.top_performers[:5], 1):
        print(f"   {i}. Bot #{bot['id']:03d} ({bot['strategy_type']}) - "
              f"Return: {bot['total_return_pct']:+.2f}% | "
              f"Win Rate: {bot['win_rate']:.1f}% | "
              f"Trades: {bot['total_trades']}")
    
    # Print output location
    print(f"\n📁 Full results saved to: {report_dir.absolute()}")
    print(f"   - analysis_report.txt  : Detailed text report")
    print(f"   - recommendations.txt  : Strategy recommendations")
    print(f"   - raw_results.json     : Complete simulation data")
    print(f"   - *.png                : Visualization charts")
    
    # Final verdict
    print("\n" + "=" * 60)
    if results.profitable_pct > 60:
        print("✅ VERDICT: Strategy shows STRONG profitability potential!")
    elif results.profitable_pct > 40:
        print("⚠️  VERDICT: Strategy shows MODERATE profitability - needs tuning")
    else:
        print("❌ VERDICT: Strategy needs SIGNIFICANT improvements")
    print("=" * 60 + "\n")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Monte Carlo Simulation for Polymarket Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--bots", "-b",
        type=int,
        default=500,
        help="Number of bots to simulate (default: 500)"
    )
    
    parser.add_argument(
        "--capital", "-c",
        type=float,
        default=200.0,
        help="Initial capital per bot in EUR (default: 200)"
    )
    
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=90,
        help="Number of days to simulate (default: 90)"
    )
    
    parser.add_argument(
        "--markets", "-m",
        type=int,
        default=200,
        help="Number of markets to generate (default: 200)"
    )
    
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )
    
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="monte_carlo_results",
        help="Output directory for results (default: monte_carlo_results)"
    )
    
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Quick mode: 50 bots, 30 days, 50 markets (for testing)"
    )
    
    args = parser.parse_args()
    
    # Quick mode overrides
    if args.quick:
        args.bots = 50
        args.days = 30
        args.markets = 50
        print("\n⚡ Quick mode enabled - using reduced parameters for testing\n")
    
    # Validate arguments
    if args.bots < 1:
        parser.error("Number of bots must be at least 1")
    if args.capital < 10:
        parser.error("Capital must be at least €10")
    if args.days < 1:
        parser.error("Days must be at least 1")
    if args.markets < 10:
        parser.error("Markets must be at least 10")
    
    try:
        results = run_simulation(args)
        return 0
    except KeyboardInterrupt:
        print("\n\n⚠️  Simulation interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
