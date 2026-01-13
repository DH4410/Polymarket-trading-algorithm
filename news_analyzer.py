"""News and sentiment analyzer for market prediction.

This module fetches news from various sources and analyzes sentiment
to help predict market movements.
"""

from __future__ import annotations

import re
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from enum import Enum
import hashlib

import requests


class Sentiment(Enum):
    VERY_BULLISH = "very_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VERY_BEARISH = "very_bearish"


class MarketCategory(Enum):
    POLITICS = "politics"
    CRYPTO = "crypto"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    FINANCE = "finance"
    TECHNOLOGY = "technology"
    WORLD_EVENTS = "world_events"
    SCIENCE = "science"
    OTHER = "other"


@dataclass
class NewsArticle:
    """A news article with sentiment analysis."""
    title: str
    source: str
    url: str
    timestamp: str
    content_snippet: str
    keywords: List[str]
    sentiment_score: float  # -1 (bearish) to +1 (bullish)
    relevance_score: float  # 0 to 1


@dataclass
class MarketSignal:
    """A trading signal based on news analysis."""
    market_id: str
    market_question: str
    category: MarketCategory
    sentiment: Sentiment
    sentiment_score: float
    confidence: float
    news_articles: List[NewsArticle]
    recommendation: str  # "BUY", "SELL", "HOLD"
    reasons: List[str]
    timestamp: str


# Keyword dictionaries for sentiment analysis
BULLISH_KEYWORDS = {
    "win", "winning", "victory", "success", "surge", "rally", "breakthrough",
    "approve", "approved", "approval", "pass", "passed", "passing",
    "increase", "rise", "rising", "gain", "positive", "confirm", "confirmed",
    "announce", "announced", "lead", "leading", "ahead", "favorite",
    "strong", "strength", "momentum", "support", "backed", "endorsement",
    "record", "high", "boost", "soar", "jump", "spike", "bullish",
    "agree", "agreement", "deal", "partnership", "alliance", "succeed",
    "progress", "advance", "improvement", "better", "best", "top",
}

BEARISH_KEYWORDS = {
    "lose", "losing", "loss", "defeat", "fail", "failed", "failure",
    "reject", "rejected", "rejection", "deny", "denied", "decline",
    "decrease", "drop", "fall", "falling", "negative", "concern",
    "struggle", "struggling", "behind", "trailing", "underdog",
    "weak", "weakness", "trouble", "problem", "issue", "crisis",
    "collapse", "crash", "plunge", "dive", "sink", "bearish",
    "disagree", "dispute", "conflict", "tension", "risk", "threat",
    "delay", "postpone", "suspend", "cancel", "withdraw", "quit",
    "scandal", "controversy", "investigation", "lawsuit", "charge",
}

# Category detection keywords
CATEGORY_KEYWORDS = {
    MarketCategory.POLITICS: {
        "election", "president", "congress", "senate", "governor", "vote",
        "democrat", "republican", "biden", "trump", "political", "politics",
        "legislation", "bill", "law", "policy", "campaign", "poll", "ballot",
        "primary", "caucus", "electoral", "candidate", "administration",
    },
    MarketCategory.CRYPTO: {
        "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
        "blockchain", "defi", "nft", "token", "coin", "wallet", "exchange",
        "mining", "halving", "altcoin", "solana", "cardano", "dogecoin",
    },
    MarketCategory.SPORTS: {
        "nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
        "baseball", "hockey", "tennis", "golf", "ufc", "boxing", "mma",
        "championship", "playoffs", "finals", "superbowl", "world series",
        "team", "player", "game", "match", "score", "season", "league",
    },
    MarketCategory.ENTERTAINMENT: {
        "movie", "film", "oscar", "emmy", "grammy", "music", "album",
        "celebrity", "hollywood", "netflix", "streaming", "tv", "show",
        "concert", "tour", "box office", "premiere", "award", "actor",
    },
    MarketCategory.FINANCE: {
        "stock", "market", "nasdaq", "s&p", "dow", "fed", "interest rate",
        "inflation", "gdp", "economy", "economic", "bank", "fed", "jerome powell",
        "earnings", "revenue", "profit", "ipo", "merger", "acquisition",
    },
    MarketCategory.TECHNOLOGY: {
        "tech", "technology", "ai", "artificial intelligence", "openai",
        "google", "apple", "microsoft", "meta", "amazon", "tesla", "nvidia",
        "startup", "silicon valley", "software", "hardware", "chip", "semiconductor",
    },
    MarketCategory.WORLD_EVENTS: {
        "war", "conflict", "military", "nato", "un", "united nations",
        "russia", "ukraine", "china", "iran", "israel", "middle east",
        "climate", "environment", "disaster", "earthquake", "hurricane",
        "pandemic", "covid", "virus", "health", "who", "treaty",
    },
    MarketCategory.SCIENCE: {
        "nasa", "space", "spacex", "mars", "moon", "rocket", "satellite",
        "science", "research", "study", "discovery", "scientist", "laboratory",
        "medicine", "drug", "fda", "clinical trial", "vaccine", "treatment",
    },
}


class NewsAnalyzer:
    """
    Analyzes news and social sentiment to generate trading signals.
    
    Uses multiple data sources:
    1. Free news APIs (when available)
    2. Google News RSS feeds
    3. Social media trends
    4. Keyword sentiment analysis
    """
    
    # Free news sources
    NEWS_SOURCES = [
        # Google News RSS (always available)
        {"name": "Google News", "type": "rss", "url": "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"},
    ]
    
    def __init__(
        self,
        cache_duration_minutes: int = 15,
        on_signal: Optional[Callable[[MarketSignal], None]] = None,
    ):
        self.cache_duration = timedelta(minutes=cache_duration_minutes)
        self.on_signal = on_signal
        
        # Cache
        self._news_cache: Dict[str, Tuple[datetime, List[NewsArticle]]] = {}
        self._signal_cache: Dict[str, MarketSignal] = {}
        
        # Running state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._markets_to_analyze: Dict[str, Dict] = {}  # market_id -> market_info
    
    def detect_category(self, text: str) -> MarketCategory:
        """Detect the category of a market based on its question/description."""
        text_lower = text.lower()
        
        category_scores = {}
        for category, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                category_scores[category] = score
        
        if category_scores:
            return max(category_scores, key=category_scores.get)
        return MarketCategory.OTHER
    
    def analyze_sentiment(self, text: str) -> Tuple[float, Sentiment]:
        """
        Analyze sentiment of text.
        Returns (score: -1 to +1, sentiment_enum)
        """
        text_lower = text.lower()
        words = set(re.findall(r'\b\w+\b', text_lower))
        
        bullish_count = len(words & BULLISH_KEYWORDS)
        bearish_count = len(words & BEARISH_KEYWORDS)
        
        total = bullish_count + bearish_count
        if total == 0:
            return 0.0, Sentiment.NEUTRAL
        
        # Score from -1 to +1
        score = (bullish_count - bearish_count) / total
        
        if score > 0.5:
            sentiment = Sentiment.VERY_BULLISH
        elif score > 0.15:
            sentiment = Sentiment.BULLISH
        elif score < -0.5:
            sentiment = Sentiment.VERY_BEARISH
        elif score < -0.15:
            sentiment = Sentiment.BEARISH
        else:
            sentiment = Sentiment.NEUTRAL
        
        return score, sentiment
    
    def _extract_keywords(self, question: str) -> List[str]:
        """Extract searchable keywords from a market question."""
        # Remove common words
        stop_words = {
            "will", "the", "be", "to", "a", "an", "in", "on", "at", "by", "for",
            "of", "or", "and", "is", "it", "that", "this", "with", "as", "are",
            "was", "were", "been", "being", "have", "has", "had", "do", "does",
            "did", "but", "if", "than", "so", "what", "when", "where", "who",
            "which", "how", "all", "each", "every", "both", "few", "more", "most",
            "other", "some", "such", "no", "nor", "not", "only", "own", "same",
            "too", "very", "just", "can", "could", "may", "might", "must", "shall",
            "should", "would", "before", "after", "during", "above", "below",
        }
        
        # Clean and tokenize
        text = re.sub(r'[^\w\s]', ' ', question.lower())
        words = text.split()
        
        # Filter
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        # Return top keywords (prioritize longer/specific words)
        keywords.sort(key=len, reverse=True)
        return keywords[:5]
    
    def _fetch_news_rss(self, query: str) -> List[NewsArticle]:
        """Fetch news from Google News RSS."""
        articles = []
        
        try:
            # Encode query for URL
            encoded_query = requests.utils.quote(query)
            url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
            
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
            
            # Parse XML (simple regex parsing to avoid lxml dependency)
            content = response.text
            
            # Extract items
            items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
            
            for item in items[:10]:  # Top 10 articles
                title_match = re.search(r'<title>(.*?)</title>', item)
                link_match = re.search(r'<link>(.*?)</link>', item)
                pub_date_match = re.search(r'<pubDate>(.*?)</pubDate>', item)
                source_match = re.search(r'<source.*?>(.*?)</source>', item)
                
                if title_match and link_match:
                    title = title_match.group(1).strip()
                    # Clean HTML entities
                    title = title.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    title = title.replace('&#39;', "'").replace('&quot;', '"')
                    
                    url = link_match.group(1).strip()
                    source = source_match.group(1).strip() if source_match else "Google News"
                    pub_date = pub_date_match.group(1).strip() if pub_date_match else datetime.now(timezone.utc).isoformat()
                    
                    # Analyze sentiment
                    sentiment_score, _ = self.analyze_sentiment(title)
                    
                    # Calculate relevance (how many query words appear in title)
                    query_words = set(query.lower().split())
                    title_words = set(title.lower().split())
                    relevance = len(query_words & title_words) / len(query_words) if query_words else 0
                    
                    articles.append(NewsArticle(
                        title=title,
                        source=source,
                        url=url,
                        timestamp=pub_date,
                        content_snippet=title,  # Using title as snippet
                        keywords=list(query_words & title_words),
                        sentiment_score=sentiment_score,
                        relevance_score=min(relevance + 0.3, 1.0),  # Boost relevance slightly
                    ))
        
        except Exception as e:
            pass
        
        return articles
    
    def get_news_for_market(self, market_id: str, question: str) -> List[NewsArticle]:
        """Get recent news articles relevant to a market."""
        cache_key = hashlib.md5(question.encode()).hexdigest()[:12]
        
        # Check cache
        if cache_key in self._news_cache:
            cached_time, cached_articles = self._news_cache[cache_key]
            if datetime.now(timezone.utc) - cached_time < self.cache_duration:
                return cached_articles
        
        # Extract keywords and search
        keywords = self._extract_keywords(question)
        if not keywords:
            return []
        
        # Create search query
        search_query = " ".join(keywords[:3])
        
        # Fetch news
        articles = self._fetch_news_rss(search_query)
        
        # Sort by relevance and recency
        articles.sort(key=lambda a: (a.relevance_score * 0.6 + abs(a.sentiment_score) * 0.4), reverse=True)
        
        # Cache results
        self._news_cache[cache_key] = (datetime.now(timezone.utc), articles)
        
        return articles[:10]  # Top 10
    
    def generate_signal(self, market_id: str, question: str, current_price: float) -> Optional[MarketSignal]:
        """Generate a trading signal for a market based on news sentiment."""
        # Detect category
        category = self.detect_category(question)
        
        # Get news
        articles = self.get_news_for_market(market_id, question)
        
        if not articles:
            return None
        
        # Aggregate sentiment
        total_sentiment = 0.0
        total_weight = 0.0
        
        for article in articles:
            weight = article.relevance_score
            total_sentiment += article.sentiment_score * weight
            total_weight += weight
        
        if total_weight == 0:
            return None
        
        avg_sentiment = total_sentiment / total_weight
        
        # Determine overall sentiment
        if avg_sentiment > 0.4:
            sentiment = Sentiment.VERY_BULLISH
        elif avg_sentiment > 0.15:
            sentiment = Sentiment.BULLISH
        elif avg_sentiment < -0.4:
            sentiment = Sentiment.VERY_BEARISH
        elif avg_sentiment < -0.15:
            sentiment = Sentiment.BEARISH
        else:
            sentiment = Sentiment.NEUTRAL
        
        # Generate recommendation
        reasons = []
        recommendation = "HOLD"
        confidence = 0.5
        
        # Bullish signals
        if sentiment in [Sentiment.BULLISH, Sentiment.VERY_BULLISH]:
            bullish_articles = [a for a in articles if a.sentiment_score > 0.1]
            if bullish_articles:
                reasons.append(f"{len(bullish_articles)} positive news articles found")
                reasons.append(f"Top headline: {bullish_articles[0].title[:60]}...")
            
            if current_price < 0.6:  # Good entry for YES
                recommendation = "BUY"
                confidence = 0.5 + avg_sentiment * 0.3
                reasons.append(f"Price ({current_price:.2f}) below fair value given positive sentiment")
        
        # Bearish signals
        elif sentiment in [Sentiment.BEARISH, Sentiment.VERY_BEARISH]:
            bearish_articles = [a for a in articles if a.sentiment_score < -0.1]
            if bearish_articles:
                reasons.append(f"{len(bearish_articles)} negative news articles found")
                reasons.append(f"Top headline: {bearish_articles[0].title[:60]}...")
            
            if current_price > 0.4:  # Current YES price too high
                recommendation = "SELL"  # or buy NO
                confidence = 0.5 + abs(avg_sentiment) * 0.3
                reasons.append(f"Price ({current_price:.2f}) above fair value given negative sentiment")
        
        # Neutral - look for volume/momentum
        else:
            reasons.append("Mixed or neutral news sentiment")
            confidence = 0.4
        
        signal = MarketSignal(
            market_id=market_id,
            market_question=question,
            category=category,
            sentiment=sentiment,
            sentiment_score=avg_sentiment,
            confidence=min(confidence, 0.85),
            news_articles=articles[:5],  # Top 5
            recommendation=recommendation,
            reasons=reasons,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        # Cache signal
        self._signal_cache[market_id] = signal
        
        # Callback
        if self.on_signal and recommendation in ["BUY", "SELL"]:
            self.on_signal(signal)
        
        return signal
    
    def add_market_to_analyze(self, market_id: str, question: str, price: float) -> None:
        """Add a market to the analysis queue."""
        self._markets_to_analyze[market_id] = {
            "question": question,
            "price": price,
        }
    
    def get_cached_signal(self, market_id: str) -> Optional[MarketSignal]:
        """Get cached signal for a market."""
        return self._signal_cache.get(market_id)
    
    def start(self) -> None:
        """Start background analysis."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop background analysis."""
        self._running = False
    
    def _analysis_loop(self) -> None:
        """Background loop to analyze markets."""
        while self._running:
            try:
                # Analyze each market
                for market_id, info in list(self._markets_to_analyze.items()):
                    if not self._running:
                        break
                    
                    self.generate_signal(market_id, info["question"], info["price"])
                    time.sleep(2)  # Rate limit
                
                # Wait before next round
                time.sleep(60)
                
            except Exception:
                time.sleep(10)


# Utility function
def get_market_category_display(category: MarketCategory) -> str:
    """Get display name for category."""
    names = {
        MarketCategory.POLITICS: "🏛️ Politics",
        MarketCategory.CRYPTO: "₿ Crypto",
        MarketCategory.SPORTS: "🏈 Sports",
        MarketCategory.ENTERTAINMENT: "🎬 Entertainment",
        MarketCategory.FINANCE: "📈 Finance",
        MarketCategory.TECHNOLOGY: "💻 Technology",
        MarketCategory.WORLD_EVENTS: "🌍 World Events",
        MarketCategory.SCIENCE: "🔬 Science",
        MarketCategory.OTHER: "📋 Other",
    }
    return names.get(category, "📋 Other")
