"""Insider trading detector for Polymarket."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set
from enum import Enum

import requests


# Polymarket API endpoints
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"


class AlertSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TraderProfile:
    """Profile of a trader's activity."""
    address: str
    first_seen: str
    total_trades: int = 0
    total_volume: float = 0.0
    markets_traded: Set[str] = field(default_factory=set)
    large_trades: int = 0  # Trades over $1000
    
    def days_active(self) -> float:
        try:
            first = datetime.fromisoformat(self.first_seen.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return (now - first).total_seconds() / 86400
        except Exception:
            return 0.0
    
    def is_new_account(self, threshold_days: float = 7.0) -> bool:
        return self.days_active() < threshold_days
    
    def is_low_activity(self, threshold_trades: int = 5) -> bool:
        return self.total_trades < threshold_trades
    
    def to_dict(self) -> Dict:
        return {
            "address": self.address,
            "first_seen": self.first_seen,
            "total_trades": self.total_trades,
            "total_volume": self.total_volume,
            "markets_traded": list(self.markets_traded),
            "large_trades": self.large_trades,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> "TraderProfile":
        profile = TraderProfile(
            address=data["address"],
            first_seen=data["first_seen"],
            total_trades=data.get("total_trades", 0),
            total_volume=data.get("total_volume", 0.0),
            large_trades=data.get("large_trades", 0),
        )
        profile.markets_traded = set(data.get("markets_traded", []))
        return profile


@dataclass
class InsiderAlert:
    """An alert for suspicious trading activity."""
    id: str
    timestamp: str
    severity: AlertSeverity
    market_id: str
    market_question: str
    trader_address: str
    trade_size: float
    trade_side: str  # "buy" or "sell"
    outcome: str
    price: float
    reason: str
    trader_profile: Optional[TraderProfile] = None
    acknowledged: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "market_id": self.market_id,
            "market_question": self.market_question,
            "trader_address": self.trader_address,
            "trade_size": self.trade_size,
            "trade_side": self.trade_side,
            "outcome": self.outcome,
            "price": self.price,
            "reason": self.reason,
            "trader_profile": self.trader_profile.to_dict() if self.trader_profile else None,
            "acknowledged": self.acknowledged,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> "InsiderAlert":
        return InsiderAlert(
            id=data["id"],
            timestamp=data["timestamp"],
            severity=AlertSeverity(data["severity"]),
            market_id=data["market_id"],
            market_question=data["market_question"],
            trader_address=data["trader_address"],
            trade_size=data["trade_size"],
            trade_side=data["trade_side"],
            outcome=data["outcome"],
            price=data["price"],
            reason=data["reason"],
            trader_profile=TraderProfile.from_dict(data["trader_profile"]) if data.get("trader_profile") else None,
            acknowledged=data.get("acknowledged", False),
        )


@dataclass
class InsiderDetectorConfig:
    """Configuration for the insider detector.
    
    Optimized for detecting insider trading in SMALL markets,
    where insiders are more likely to operate.
    """
    # Thresholds for alerts - LOWER for small markets
    large_trade_threshold: float = 1000.0  # $1,000 (lower for small markets)
    small_market_threshold: float = 500.0  # $500 for very small markets
    new_account_days: float = 14.0  # Account age threshold (2 weeks)
    low_activity_trades: int = 3  # Trade count threshold (stricter)
    
    # Small market detection
    small_market_volume_max: float = 50000.0  # Markets under $50k volume are "small"
    tiny_market_volume_max: float = 10000.0  # Markets under $10k are "tiny"
    
    # Monitoring settings
    poll_interval_seconds: int = 30
    max_alerts_stored: int = 500
    
    # What to monitor
    monitor_new_accounts: bool = True
    monitor_large_trades: bool = True
    monitor_sudden_volume: bool = True
    monitor_small_markets: bool = True  # Focus on small markets
    volume_spike_multiplier: float = 3.0  # 3x normal volume (more sensitive)
    
    # Relative thresholds for small markets
    small_market_trade_pct: float = 0.05  # Alert if trade is >5% of market volume
    price_impact_threshold: float = 0.03  # Alert if trade moves price >3%


class InsiderDetector:
    """
    Detects potential insider trading activity on Polymarket.
    
    Monitors for:
    - New accounts placing large bets (>$10k)
    - Sudden volume spikes
    - Unusual trading patterns before major events
    """
    
    def __init__(
        self,
        config: Optional[InsiderDetectorConfig] = None,
        storage_path: Optional[Path] = None,
    ):
        self.config = config or InsiderDetectorConfig()
        self.storage_path = storage_path or Path("insider_alerts.json")
        
        self.alerts: List[InsiderAlert] = []
        self.trader_profiles: Dict[str, TraderProfile] = {}
        self.monitored_markets: Dict[str, Dict] = {}  # market_id -> market info
        self.market_volume_history: Dict[str, List[float]] = {}  # market_id -> recent volumes
        
        self.listeners: List[Callable[[InsiderAlert], None]] = []
        self._alert_counter = 0
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        self._load()
    
    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    
    def _generate_alert_id(self) -> str:
        self._alert_counter += 1
        return f"insider_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{self._alert_counter}"
    
    def add_listener(self, callback: Callable[[InsiderAlert], None]) -> None:
        """Register a callback for new alerts."""
        self.listeners.append(callback)
    
    def remove_listener(self, callback: Callable[[InsiderAlert], None]) -> None:
        """Remove an alert listener."""
        if callback in self.listeners:
            self.listeners.remove(callback)
    
    def add_market(self, market_id: str, question: str, token_id: str) -> None:
        """Add a market to monitor."""
        self.monitored_markets[market_id] = {
            "market_id": market_id,
            "question": question,
            "token_id": token_id,
            "added_at": self._now_iso(),
        }
        self._save()
    
    def remove_market(self, market_id: str) -> None:
        """Remove a market from monitoring."""
        self.monitored_markets.pop(market_id, None)
        self._save()
    
    def get_monitored_markets(self) -> List[Dict]:
        """Get list of monitored markets."""
        return list(self.monitored_markets.values())
    
    def analyze_trade(
        self,
        market_id: str,
        market_question: str,
        trader_address: str,
        trade_size: float,
        trade_side: str,
        outcome: str,
        price: float,
        trader_first_seen: Optional[str] = None,
        trader_trade_count: Optional[int] = None,
        market_volume: Optional[float] = None,  # Total market volume
    ) -> Optional[InsiderAlert]:
        """
        Analyze a trade for suspicious activity.
        Optimized for detecting insider trading in SMALL markets.
        
        Returns an InsiderAlert if suspicious, None otherwise.
        """
        alerts_generated = []
        
        # Get or create trader profile
        if trader_address not in self.trader_profiles:
            self.trader_profiles[trader_address] = TraderProfile(
                address=trader_address,
                first_seen=trader_first_seen or self._now_iso(),
                total_trades=trader_trade_count or 0,
            )
        
        profile = self.trader_profiles[trader_address]
        profile.total_trades += 1
        profile.total_volume += trade_size
        profile.markets_traded.add(market_id)
        if trade_size >= 500:
            profile.large_trades += 1
        
        # Determine if this is a small market (where insiders operate)
        is_small_market = market_volume is not None and market_volume < self.config.small_market_volume_max
        is_tiny_market = market_volume is not None and market_volume < self.config.tiny_market_volume_max
        
        # Adjust thresholds for small markets
        effective_threshold = self.config.large_trade_threshold
        if is_tiny_market:
            effective_threshold = self.config.small_market_threshold
        elif is_small_market:
            effective_threshold = self.config.large_trade_threshold * 0.5
        
        # Check trade as percentage of market volume (key for small markets!)
        if market_volume and market_volume > 0 and self.config.monitor_small_markets:
            trade_pct = trade_size / market_volume
            if trade_pct >= self.config.small_market_trade_pct:
                severity = AlertSeverity.HIGH if trade_pct > 0.10 else AlertSeverity.MEDIUM
                alert = self._create_alert(
                    severity=severity,
                    market_id=market_id,
                    market_question=market_question,
                    trader_address=trader_address,
                    trade_size=trade_size,
                    trade_side=trade_side,
                    outcome=outcome,
                    price=price,
                    reason=f"Large trade relative to market: ${trade_size:,.0f} = {trade_pct:.1%} of ${market_volume:,.0f} volume",
                    trader_profile=profile,
                )
                alerts_generated.append(alert)
        
        # Check for large trade from new/low-activity account
        if trade_size >= effective_threshold:
            is_new = profile.is_new_account(self.config.new_account_days)
            is_low_activity = profile.is_low_activity(self.config.low_activity_trades)
            
            if is_new and self.config.monitor_new_accounts:
                # Higher severity for small markets
                if is_tiny_market:
                    severity = AlertSeverity.CRITICAL
                elif is_small_market:
                    severity = AlertSeverity.HIGH
                elif trade_size >= 50000:
                    severity = AlertSeverity.CRITICAL
                else:
                    severity = AlertSeverity.HIGH
                    
                market_size_note = " (SMALL MARKET)" if is_small_market else ""
                alert = self._create_alert(
                    severity=severity,
                    market_id=market_id,
                    market_question=market_question,
                    trader_address=trader_address,
                    trade_size=trade_size,
                    trade_side=trade_side,
                    outcome=outcome,
                    price=price,
                    reason=f"New account ({profile.days_active():.1f} days) placed ${trade_size:,.0f} trade{market_size_note}",
                    trader_profile=profile,
                )
                alerts_generated.append(alert)
            
            elif is_low_activity and self.config.monitor_large_trades:
                severity = AlertSeverity.HIGH if (is_small_market or trade_size >= 25000) else AlertSeverity.MEDIUM
                alert = self._create_alert(
                    severity=severity,
                    market_id=market_id,
                    market_question=market_question,
                    trader_address=trader_address,
                    trade_size=trade_size,
                    trade_side=trade_side,
                    outcome=outcome,
                    price=price,
                    reason=f"Low-activity account ({profile.total_trades} trades) placed ${trade_size:,.0f} trade",
                    trader_profile=profile,
                )
                alerts_generated.append(alert)
        
        self._save()
        
        return alerts_generated[0] if alerts_generated else None
    
    def check_volume_spike(
        self,
        market_id: str,
        market_question: str,
        current_volume: float,
        outcome: str = "Yes",
    ) -> Optional[InsiderAlert]:
        """Check if there's a volume spike in a market."""
        if not self.config.monitor_sudden_volume:
            return None
        
        if market_id not in self.market_volume_history:
            self.market_volume_history[market_id] = []
        
        history = self.market_volume_history[market_id]
        history.append(current_volume)
        
        # Keep last 24 data points
        if len(history) > 24:
            history = history[-24:]
            self.market_volume_history[market_id] = history
        
        # Need at least 5 data points for comparison
        if len(history) < 5:
            return None
        
        # Calculate average of previous volumes (excluding current)
        avg_volume = sum(history[:-1]) / len(history[:-1])
        
        if avg_volume > 0 and current_volume > avg_volume * self.config.volume_spike_multiplier:
            spike_ratio = current_volume / avg_volume
            alert = self._create_alert(
                severity=AlertSeverity.MEDIUM,
                market_id=market_id,
                market_question=market_question,
                trader_address="N/A",
                trade_size=current_volume,
                trade_side="volume",
                outcome=outcome,
                price=0.0,
                reason=f"Volume spike detected: {spike_ratio:.1f}x normal ({avg_volume:,.0f} → {current_volume:,.0f})",
            )
            return alert
        
        return None
    
    def _create_alert(
        self,
        severity: AlertSeverity,
        market_id: str,
        market_question: str,
        trader_address: str,
        trade_size: float,
        trade_side: str,
        outcome: str,
        price: float,
        reason: str,
        trader_profile: Optional[TraderProfile] = None,
    ) -> InsiderAlert:
        """Create and store a new alert."""
        alert = InsiderAlert(
            id=self._generate_alert_id(),
            timestamp=self._now_iso(),
            severity=severity,
            market_id=market_id,
            market_question=market_question,
            trader_address=trader_address,
            trade_size=trade_size,
            trade_side=trade_side,
            outcome=outcome,
            price=price,
            reason=reason,
            trader_profile=trader_profile,
        )
        
        with self._lock:
            self.alerts.append(alert)
            if len(self.alerts) > self.config.max_alerts_stored:
                self.alerts = self.alerts[-self.config.max_alerts_stored:]
        
        # Notify listeners
        for listener in self.listeners:
            try:
                listener(alert)
            except Exception:
                pass
        
        self._save()
        return alert
    
    def get_alerts(self, limit: int = 50, unacknowledged_only: bool = False) -> List[InsiderAlert]:
        """Get recent alerts."""
        alerts = self.alerts
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]
        return list(reversed(alerts[-limit:]))
    
    def get_alerts_by_severity(self, severity: AlertSeverity, limit: int = 50) -> List[InsiderAlert]:
        """Get alerts filtered by severity."""
        filtered = [a for a in self.alerts if a.severity == severity]
        return list(reversed(filtered[-limit:]))
    
    def acknowledge_alert(self, alert_id: str) -> None:
        """Mark an alert as acknowledged."""
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                break
        self._save()
    
    def acknowledge_all(self) -> None:
        """Acknowledge all alerts."""
        for alert in self.alerts:
            alert.acknowledged = True
        self._save()
    
    def get_unacknowledged_count(self) -> int:
        """Get count of unacknowledged alerts."""
        return sum(1 for a in self.alerts if not a.acknowledged)
    
    def get_trader_profile(self, address: str) -> Optional[TraderProfile]:
        """Get a trader's profile."""
        return self.trader_profiles.get(address)
    
    def get_suspicious_traders(self, min_large_trades: int = 3) -> List[TraderProfile]:
        """Get traders with multiple large trades."""
        return [
            p for p in self.trader_profiles.values()
            if p.large_trades >= min_large_trades
        ]
    
    def _save(self) -> None:
        """Persist state to disk."""
        try:
            data = {
                "alerts": [a.to_dict() for a in self.alerts],
                "trader_profiles": {k: v.to_dict() for k, v in self.trader_profiles.items()},
                "monitored_markets": self.monitored_markets,
                "market_volume_history": self.market_volume_history,
            }
            self.storage_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
    
    def _load(self) -> None:
        """Load state from disk."""
        try:
            if self.storage_path.exists():
                data = json.loads(self.storage_path.read_text())
                self.alerts = [InsiderAlert.from_dict(a) for a in data.get("alerts", [])]
                self.trader_profiles = {
                    k: TraderProfile.from_dict(v) 
                    for k, v in data.get("trader_profiles", {}).items()
                }
                self.monitored_markets = data.get("monitored_markets", {})
                self.market_volume_history = data.get("market_volume_history", {})
                self._alert_counter = len(self.alerts)
        except Exception:
            pass
    
    def clear_all(self) -> None:
        """Clear all alerts and data."""
        self.alerts = []
        self.trader_profiles = {}
        self.market_volume_history = {}
        self._alert_counter = 0
        self._save()
    
    def start_monitoring(self) -> None:
        """Start background monitoring thread."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._running = False
    
    def _monitor_loop(self) -> None:
        """Background loop to fetch and analyze trades."""
        while self._running:
            try:
                # First, auto-fetch active markets if we don't have enough
                self._auto_fetch_markets()
                
                # Then scan for suspicious activity
                self._scan_all_markets()
            except Exception:
                pass
            
            # Wait for next poll
            for _ in range(self.config.poll_interval_seconds):
                if not self._running:
                    break
                time.sleep(1)
    
    def _auto_fetch_markets(self) -> None:
        """Auto-fetch active markets to monitor."""
        try:
            from polymarket_api import GAMMA_API_BASE
            from datetime import datetime, timezone
            
            # Fetch active markets by 24h volume
            url = f"{GAMMA_API_BASE}/markets"
            params = {
                "active": "true",
                "closed": "false",
                "limit": 50,
                "order": "volume24hr",
                "ascending": "false",
            }
            
            response = requests.get(url, params=params, timeout=15)
            if not response.ok:
                return
            
            markets = response.json()
            now = datetime.now(timezone.utc)
            
            for market in markets:
                market_id = market.get("slug") or str(market.get("id"))
                
                # Skip if already monitored
                if market_id in self.monitored_markets:
                    continue
                
                # Check end date is in future
                end_date_str = market.get("endDate")
                if end_date_str:
                    try:
                        if end_date_str.endswith('Z'):
                            end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        else:
                            end_dt = datetime.fromisoformat(end_date_str)
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                        if end_dt <= now:
                            continue
                    except:
                        continue
                
                # Get token ID
                token_ids = market.get("clobTokenIds")
                if not token_ids:
                    continue
                
                try:
                    if isinstance(token_ids, str):
                        import json
                        token_ids = json.loads(token_ids)
                    token_id = str(token_ids[0]) if token_ids else None
                except:
                    continue
                
                if not token_id:
                    continue
                
                # Add to monitored markets
                question = market.get("question") or market.get("title", "Unknown")
                volume = float(market.get("volumeNum") or 0)
                
                self.monitored_markets[market_id] = {
                    "market_id": market_id,
                    "question": question,
                    "token_id": token_id,
                    "volume": volume,
                    "added_at": self._now_iso(),
                }
            
            self._save()
            
        except Exception:
            pass
    
    def _scan_all_markets(self) -> None:
        """Scan all monitored markets for suspicious trades."""
        for market_id, market_info in list(self.monitored_markets.items()):
            try:
                token_id = market_info.get("token_id")
                question = market_info.get("question", "Unknown")
                
                if not token_id:
                    continue
                
                # Fetch recent trades
                trades = fetch_recent_trades(token_id, limit=50)
                
                for trade in trades:
                    trade_size = float(trade.get("size", 0)) * float(trade.get("price", 0))
                    
                    # Analyze if it's a large trade
                    if trade_size >= self.config.large_trade_threshold:
                        self.analyze_trade(
                            market_id=market_id,
                            market_question=question,
                            trader_address=trade.get("maker", "unknown"),
                            trade_size=trade_size,
                            trade_side=trade.get("side", "buy"),
                            outcome="Yes",
                            price=float(trade.get("price", 0)),
                        )
                        
            except Exception:
                continue


def fetch_recent_trades(token_id: str, limit: int = 100) -> List[Dict]:
    """
    Fetch recent trades for a token from Polymarket API.
    
    Note: This is a simplified version. The actual implementation would need
    to use the correct API endpoint when available.
    """
    try:
        # The CLOB API trades endpoint (if available)
        url = f"{CLOB_API_BASE}/trades"
        params = {"token_id": token_id, "limit": limit}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    
    return []


def analyze_order_book_for_large_orders(
    order_book: Dict,
    threshold: float = 10000.0,
) -> List[Dict]:
    """
    Analyze order book for large orders that might indicate insider activity.
    
    Returns list of suspicious orders.
    """
    suspicious = []
    
    for side in ["asks", "bids"]:
        orders = order_book.get(side, [])
        for price, size in orders:
            value = price * size
            if value >= threshold:
                suspicious.append({
                    "side": side,
                    "price": price,
                    "size": size,
                    "value": value,
                })
    
    return suspicious
