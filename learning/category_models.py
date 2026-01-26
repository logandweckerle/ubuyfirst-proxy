"""
Category-Specific Valuation Models

Each category has concrete rules for:
1. Opportunity detection (what signals a deal)
2. Value estimation (how to calculate worth)
3. Seller patterns (who has deals)
4. Keyword effectiveness (what to search for)

These rules are LEARNED from:
- Fast sales data (sold in < 5 min = proven deal)
- Purchase history outcomes
- Missed opportunity analysis
"""

import sqlite3
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Database paths
LEARNING_DB = Path(__file__).parent.parent / "learning_data.db"
TRACKING_DB = Path(__file__).parent.parent / "item_tracking.db"


def init_learning_db():
    """Initialize the learning database."""
    conn = sqlite3.connect(LEARNING_DB)
    cursor = conn.cursor()

    # Category rules table - stores learned rules per category
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            rule_type TEXT NOT NULL,  -- opportunity_signal, valuation, seller_pattern, keyword
            rule_name TEXT NOT NULL,
            rule_definition TEXT NOT NULL,  -- JSON definition
            confidence REAL DEFAULT 0,  -- 0-100 based on evidence
            evidence_count INTEGER DEFAULT 0,
            total_margin REAL DEFAULT 0,
            avg_margin REAL DEFAULT 0,
            hit_rate REAL DEFAULT 0,  -- % of time this rule led to profit
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, rule_type, rule_name)
        )
    """)

    # Seller category scores - how good is each seller in each category
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seller_category_scores (
            seller_name TEXT NOT NULL,
            category TEXT NOT NULL,
            fast_sales INTEGER DEFAULT 0,
            total_seen INTEGER DEFAULT 0,
            total_margin REAL DEFAULT 0,
            avg_time_to_sell REAL DEFAULT 0,
            is_estate_seller BOOLEAN DEFAULT 0,
            is_thrift_seller BOOLEAN DEFAULT 0,
            seller_type TEXT,  -- estate, thrift, individual, dealer
            score REAL DEFAULT 0,  -- 0-100 opportunity score
            last_seen TEXT,
            PRIMARY KEY (seller_name, category)
        )
    """)

    # Keyword category performance
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS keyword_category_performance (
            keyword TEXT NOT NULL,
            category TEXT NOT NULL,
            times_seen INTEGER DEFAULT 0,
            fast_sales INTEGER DEFAULT 0,
            buy_signals INTEGER DEFAULT 0,
            pass_signals INTEGER DEFAULT 0,
            total_margin REAL DEFAULT 0,
            avg_margin REAL DEFAULT 0,
            opportunity_score REAL DEFAULT 0,  -- higher = better keyword
            recommended_action TEXT,  -- add_to_search, remove_noise, priority
            last_updated TEXT,
            PRIMARY KEY (keyword, category)
        )
    """)

    # Brand value modifiers - some brands have premiums or discounts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS brand_modifiers (
            brand TEXT NOT NULL,
            category TEXT NOT NULL,
            modifier_type TEXT NOT NULL,  -- premium, discount, reliable_content, avoid
            modifier_value REAL DEFAULT 0,  -- multiplier or fixed value
            reason TEXT,
            evidence_count INTEGER DEFAULT 0,
            PRIMARY KEY (brand, category)
        )
    """)

    conn.commit()
    conn.close()
    logger.info(f"[LEARNING] Database initialized at {LEARNING_DB}")


@dataclass
class OpportunitySignal:
    """A signal that indicates an opportunity."""
    name: str
    weight: float  # 0-1, how much this signal contributes
    description: str
    conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValuationRule:
    """A rule for calculating value."""
    name: str
    formula: str  # Python expression or description
    applies_when: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class CategoryModel:
    """Base class for category-specific valuation models."""

    category: str = "base"

    # Opportunity signals - what makes something a potential deal
    opportunity_signals: List[OpportunitySignal] = []

    # Valuation rules - how to calculate value
    valuation_rules: List[ValuationRule] = []

    # High-value keywords for this category
    priority_keywords: List[str] = []

    # Noise keywords to filter out
    noise_keywords: List[str] = []

    # Reliable brands (content matches claims)
    reliable_brands: List[str] = []

    # Brands to avoid (overpriced for content)
    avoid_brands: List[str] = []

    def __init__(self):
        init_learning_db()

    def calculate_opportunity_score(self, title: str, price: float, seller: str, data: Dict) -> Tuple[float, List[str]]:
        """
        Calculate opportunity score (0-100) based on signals.
        Returns (score, list of matched signals).
        """
        score = 0.0
        matched_signals = []

        for signal in self.opportunity_signals:
            if self._check_signal(signal, title, price, seller, data):
                score += signal.weight * 100
                matched_signals.append(signal.name)

        # Cap at 100
        return min(score, 100), matched_signals

    def _check_signal(self, signal: OpportunitySignal, title: str, price: float, seller: str, data: Dict) -> bool:
        """Check if a signal condition is met."""
        title_lower = title.lower()
        seller_lower = seller.lower() if seller else ""

        conditions = signal.conditions

        # Check title keywords
        if "title_contains" in conditions:
            keywords = conditions["title_contains"]
            if not any(kw in title_lower for kw in keywords):
                return False

        # Check title must NOT contain
        if "title_not_contains" in conditions:
            keywords = conditions["title_not_contains"]
            if any(kw in title_lower for kw in keywords):
                return False

        # Check price range
        if "price_max" in conditions and price > conditions["price_max"]:
            return False
        if "price_min" in conditions and price < conditions["price_min"]:
            return False

        # Check seller type
        if "seller_type" in conditions:
            seller_type = self._detect_seller_type(seller)
            if seller_type not in conditions["seller_type"]:
                return False

        # Check seller keywords
        if "seller_contains" in conditions:
            keywords = conditions["seller_contains"]
            if not any(kw in seller_lower for kw in keywords):
                return False

        return True

    def _detect_seller_type(self, seller: str) -> str:
        """Detect seller type from username."""
        seller_lower = seller.lower() if seller else ""

        estate_keywords = ["estate", "grandma", "grandpa", "inherited", "attic", "downsiz"]
        thrift_keywords = ["goodwill", "salvation", "hospice", "thrift", "charity", "habitat"]
        dealer_keywords = ["jewel", "gold", "silver", "coin", "pawn", "watch", "antique"]

        for kw in estate_keywords:
            if kw in seller_lower:
                return "estate"

        for kw in thrift_keywords:
            if kw in seller_lower:
                return "thrift"

        for kw in dealer_keywords:
            if kw in seller_lower:
                return "dealer"

        return "individual"

    def get_keyword_recommendations(self) -> Dict[str, List[str]]:
        """Get keyword recommendations for uBuyFirst."""
        return {
            "add": self.priority_keywords,
            "remove": self.noise_keywords,
        }

    def save_rule(self, rule_type: str, rule_name: str, definition: Dict, confidence: float = 0):
        """Save a learned rule to the database."""
        conn = sqlite3.connect(LEARNING_DB)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO category_rules (category, rule_type, rule_name, rule_definition, confidence)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(category, rule_type, rule_name) DO UPDATE SET
                rule_definition = excluded.rule_definition,
                confidence = excluded.confidence,
                updated_at = CURRENT_TIMESTAMP
        """, (self.category, rule_type, rule_name, json.dumps(definition), confidence))

        conn.commit()
        conn.close()

    def update_seller_score(self, seller: str, fast_sale: bool = False, margin: float = 0):
        """Update seller's score for this category."""
        conn = sqlite3.connect(LEARNING_DB)
        cursor = conn.cursor()

        seller_type = self._detect_seller_type(seller)
        is_estate = seller_type == "estate"
        is_thrift = seller_type == "thrift"

        cursor.execute("""
            INSERT INTO seller_category_scores
            (seller_name, category, fast_sales, total_seen, total_margin, is_estate_seller, is_thrift_seller, seller_type, last_seen)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(seller_name, category) DO UPDATE SET
                fast_sales = fast_sales + ?,
                total_seen = total_seen + 1,
                total_margin = total_margin + ?,
                last_seen = ?
        """, (
            seller, self.category, 1 if fast_sale else 0, margin, is_estate, is_thrift, seller_type, datetime.now().isoformat(),
            1 if fast_sale else 0, margin, datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

    def update_keyword_performance(self, keyword: str, fast_sale: bool = False, was_buy: bool = False, margin: float = 0):
        """Update keyword performance for this category."""
        conn = sqlite3.connect(LEARNING_DB)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO keyword_category_performance
            (keyword, category, times_seen, fast_sales, buy_signals, total_margin, last_updated)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(keyword, category) DO UPDATE SET
                times_seen = times_seen + 1,
                fast_sales = fast_sales + ?,
                buy_signals = buy_signals + ?,
                total_margin = total_margin + ?,
                last_updated = ?
        """, (
            keyword, self.category, 1 if fast_sale else 0, 1 if was_buy else 0, margin, datetime.now().isoformat(),
            1 if fast_sale else 0, 1 if was_buy else 0, margin, datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()


class GoldModel(CategoryModel):
    """Gold jewelry valuation model."""

    category = "gold"

    # LEARNED FROM MISSED OPPORTUNITY ANALYSIS:
    opportunity_signals = [
        OpportunitySignal(
            name="estate_seller_gold",
            weight=0.3,
            description="Estate sellers often underprice gold",
            conditions={
                "seller_type": ["estate", "thrift"],
            }
        ),
        OpportunitySignal(
            name="michael_anthony_brand",
            weight=0.25,
            description="Michael Anthony = reliable 14K gold content",
            conditions={
                "title_contains": ["michael anthony"],
            }
        ),
        OpportunitySignal(
            name="italian_gold",
            weight=0.2,
            description="Italian gold chains are usually solid and well-marked",
            conditions={
                "title_contains": ["italy", "italian", "milor", "unoaerre"],
            }
        ),
        OpportunitySignal(
            name="scrap_lot_terms",
            weight=0.25,
            description="Scrap/lot terms indicate seller pricing as scrap",
            conditions={
                "title_contains": ["scrap", "lot", "grams", "dwt", "broken", "as is"],
                "title_not_contains": ["diamond", "sapphire", "ruby", "emerald"],
            }
        ),
        OpportunitySignal(
            name="class_ring_signet",
            weight=0.2,
            description="Class rings and signets are usually solid gold",
            conditions={
                "title_contains": ["class ring", "signet", "school ring"],
            }
        ),
        OpportunitySignal(
            name="vintage_no_stones",
            weight=0.2,
            description="Vintage gold without stones = metal value pricing",
            conditions={
                "title_contains": ["vintage", "antique", "vtg", "estate"],
                "title_not_contains": ["diamond", "carat", "ct ", "ctw", "cttw"],
            }
        ),
    ]

    priority_keywords = [
        "michael anthony", "14k scrap", "18k scrap", "10k scrap",
        "gold lot", "scrap gold", "class ring", "signet ring",
        "italian gold", "milor", "14k grams", "18k grams",
        "gold chain lot", "gold jewelry lot", "estate gold",
        "broken gold", "as is gold", "gold for scrap",
    ]

    noise_keywords = [
        "gold tone", "gold plated", "gold filled", "gf",
        "vermeil", "bonded", "overlay", "clad",
        "costume", "fashion", "replica",
    ]

    reliable_brands = [
        "michael anthony", "milor", "unoaerre", "balestra",
        "aurafin", "brev", "italy",
    ]

    avoid_brands = [
        "tiffany", "cartier", "david yurman", "james avery",
        "pandora", "lagos", "john hardy",  # Priced for brand, not gold
    ]


class SilverModel(CategoryModel):
    """Sterling silver valuation model."""

    category = "silver"

    # LEARNED FROM MISSED OPPORTUNITY ANALYSIS:
    opportunity_signals = [
        OpportunitySignal(
            name="vintage_925_no_stones",
            weight=0.35,
            description="Vintage 925 without stones consistently sells under melt",
            conditions={
                "title_contains": ["vintage", "925", "sterling"],
                "title_not_contains": ["turquoise", "opal", "coral", "jade", "stone"],
            }
        ),
        OpportunitySignal(
            name="estate_thrift_silver",
            weight=0.3,
            description="Estate/thrift sellers underprice silver",
            conditions={
                "seller_type": ["estate", "thrift"],
            }
        ),
        OpportunitySignal(
            name="flatware_makers",
            weight=0.25,
            description="Premium flatware makers = heavy sterling",
            conditions={
                "title_contains": ["gorham", "towle", "wallace", "reed barton", "kirk", "international", "alvin"],
            }
        ),
        OpportunitySignal(
            name="scrap_lot_terms",
            weight=0.25,
            description="Scrap/lot terms = priced as scrap",
            conditions={
                "title_contains": ["scrap", "lot", "grams", "troy", "melt"],
            }
        ),
        OpportunitySignal(
            name="heavy_serving_pieces",
            weight=0.2,
            description="Serving pieces are heavy sterling",
            conditions={
                "title_contains": ["ladle", "serving", "bowl", "tray", "compote", "pitcher"],
            }
        ),
        OpportunitySignal(
            name="mexican_silver",
            weight=0.2,
            description="Mexican silver often underpriced",
            conditions={
                "title_contains": ["mexican", "mexico", "taxco", "sanborns"],
            }
        ),
    ]

    priority_keywords = [
        "sterling scrap", "sterling lot", "925 scrap",
        "gorham", "towle", "wallace", "reed barton",
        "sterling flatware", "sterling serving",
        "ladle sterling", "sterling bowl", "sterling tray",
        "mexican silver", "taxco", "coin silver",
        "sterling grams", "troy oz sterling",
    ]

    noise_keywords = [
        "silver plated", "silverplate", "epns", "wm rogers",
        "silver tone", "tibetan silver", "german silver",
        "nickel silver", "alpaca", "stainless",
    ]

    reliable_brands = [
        "gorham", "towle", "wallace", "reed & barton",
        "kirk", "stieff", "international", "alvin",
        "whiting", "durgin", "shreve",
    ]


class WatchModel(CategoryModel):
    """Watch valuation model - focused on parts, vintage, and gold cases."""

    category = "watch"

    # LEARNED FROM MISSED OPPORTUNITY ANALYSIS:
    opportunity_signals = [
        OpportunitySignal(
            name="estate_pocket_watch",
            weight=0.4,
            description="Estate sellers with pocket watches = high opportunity",
            conditions={
                "seller_type": ["estate", "thrift", "individual"],
                "title_contains": ["pocket watch", "pocket"],
            }
        ),
        OpportunitySignal(
            name="gold_case_watch",
            weight=0.35,
            description="Gold case watches have melt value floor",
            conditions={
                "title_contains": ["14k", "18k", "10k", "solid gold", "gold case"],
                "title_not_contains": ["gold filled", "gf", "plated", "tone"],
            }
        ),
        OpportunitySignal(
            name="parts_repair_lot",
            weight=0.3,
            description="Parts/repair watches are underpriced",
            conditions={
                "title_contains": ["parts", "repair", "not working", "broken", "as is", "project", "lot"],
            }
        ),
        OpportunitySignal(
            name="vintage_mechanical",
            weight=0.25,
            description="Vintage mechanical watches from non-dealers",
            conditions={
                "title_contains": ["vintage", "antique", "manual", "wind"],
                "seller_type": ["estate", "thrift", "individual"],
            }
        ),
        OpportunitySignal(
            name="coin_silver_pocket",
            weight=0.25,
            description="Coin silver pocket watch cases have melt value",
            conditions={
                "title_contains": ["coin silver", "silveroid", "silver case", "900 silver"],
            }
        ),
        OpportunitySignal(
            name="railroad_pocket",
            weight=0.2,
            description="Railroad pocket watches are collectible",
            conditions={
                "title_contains": ["railroad", "railway", "bunn special", "950", "992"],
            }
        ),
        OpportunitySignal(
            name="watchmaker_lot",
            weight=0.2,
            description="Watchmaker lots = parts value exceeds price",
            conditions={
                "title_contains": ["watchmaker", "horologist", "movement lot", "parts lot"],
            }
        ),
    ]

    priority_keywords = [
        "pocket watch lot", "watch parts lot", "watchmaker lot",
        "gold watch", "14k watch", "18k watch", "10k watch",
        "coin silver pocket", "railroad pocket",
        "not working watch", "watch for parts", "broken watch",
        "vintage pocket", "antique pocket", "estate watch",
        "waltham pocket", "elgin pocket", "hamilton pocket", "illinois pocket",
        "movement lot", "watch movement",
    ]

    noise_keywords = [
        "smartwatch", "smart watch", "apple watch", "fitbit",
        "michael kors", "fossil", "guess", "invicta",
        "fashion watch", "quartz",  # For vintage searches
    ]

    reliable_brands = [
        # Pocket watches with known value
        "waltham", "elgin", "hamilton", "illinois", "howard", "ball",
        # Vintage wrist with parts value
        "omega", "longines", "tissot", "bulova", "gruen",
    ]

    avoid_brands = [
        # Fashion watches - no resale
        "michael kors", "fossil", "guess", "invicta", "stuhrling",
        # Hard to value without expertise
        "rolex", "patek", "audemars",  # These need expert verification
    ]


# Initialize models
MODELS = {
    "gold": GoldModel(),
    "silver": SilverModel(),
    "watch": WatchModel(),
}


def get_model(category: str) -> Optional[CategoryModel]:
    """Get the model for a category."""
    return MODELS.get(category.lower())


def get_all_models() -> Dict[str, CategoryModel]:
    """Get all category models."""
    return MODELS
