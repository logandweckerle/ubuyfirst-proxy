"""
Deal Scoring System

Unified scoring system to identify deal opportunities across ALL categories.
Combines multiple signals into a single "deal score" (0-100).

Higher score = better deal opportunity, regardless of category.
"""

import re
import logging
from typing import Dict, Optional, Tuple, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============================================================
# DEAL SCORE WEIGHTS (adjust these to tune the system)
# ============================================================

WEIGHTS = {
    'freshness': 20,      # How new the listing is (max 20 points)
    'seller_profile': 25, # Seller type/score (max 25 points)
    'price_margin': 30,   # Profit margin potential (max 30 points)
    'best_offer': 10,     # Negotiation opportunity (max 10 points)
    'listing_quality': 10,# Photo count, description (max 10 points)
    'misspelling': 5,     # Brand misspellings = less competition (max 5 points)
}

# Total should be 100
assert sum(WEIGHTS.values()) == 100, f"Weights must sum to 100, got {sum(WEIGHTS.values())}"


# ============================================================
# MISSPELLING DETECTION
# ============================================================

# Common valuable brand misspellings (misspelling -> correct)
BRAND_MISSPELLINGS = {
    # Gold/Jewelry
    'tifany': 'tiffany', 'tiffiny': 'tiffany', 'tiffney': 'tiffany',
    'cartir': 'cartier', 'cartie': 'cartier', 'cariter': 'cartier',
    'rolex': 'rolex',  # People sometimes write 'rollex'
    'rollex': 'rolex', 'rolek': 'rolex',
    'bvlagri': 'bvlgari', 'bulgari': 'bvlgari', 'bvulgari': 'bvlgari',
    'herms': 'hermes', 'hermès': 'hermes', 'hemes': 'hermes',
    'pandorra': 'pandora', 'pandoa': 'pandora',
    'swarvoski': 'swarovski', 'swarofski': 'swarovski', 'swaroski': 'swarovski',

    # Silver
    'gorhem': 'gorham', 'goreham': 'gorham',
    'towel': 'towle',  # Common typo for Towle silver
    'wallice': 'wallace', 'walace': 'wallace',
    'reeed': 'reed', 'reed barton': 'reed & barton',
    'gerog jensen': 'georg jensen', 'george jensen': 'georg jensen',

    # Video Games
    'nintedo': 'nintendo', 'nintindo': 'nintendo', 'nitendo': 'nintendo',
    'playstion': 'playstation', 'playstaion': 'playstation',
    'pokmon': 'pokemon', 'pokemom': 'pokemon', 'pokémon': 'pokemon',
    'zelda': 'zelda',  # Sometimes 'zeld' or 'zelda's
    'maro': 'mario', 'mairio': 'mario',

    # LEGO
    'leggo': 'lego', 'leog': 'lego', 'lgeo': 'lego',
    'star war': 'star wars', 'starwars': 'star wars',
    'millenium falcon': 'millennium falcon', 'milenium': 'millennium',

    # TCG
    'pokemom': 'pokemon', 'pokmon': 'pokemon',
    'charzard': 'charizard', 'charazard': 'charizard',
    'pikichu': 'pikachu', 'picachu': 'pikachu',
    'magic gathering': 'magic the gathering', 'mtg': 'magic the gathering',
    'yugio': 'yugioh', 'yu-gi-o': 'yugioh',
}

# Valuable brands to check for misspellings
VALUABLE_BRANDS = [
    # Jewelry
    'tiffany', 'cartier', 'rolex', 'bvlgari', 'hermes', 'pandora', 'swarovski',
    'david yurman', 'john hardy', 'lagos', 'ippolita',
    # Silver
    'gorham', 'towle', 'wallace', 'reed & barton', 'georg jensen', 'christofle',
    'tiffany', 'kirk stieff', 'international silver', 'oneida',
    # Video Games
    'nintendo', 'playstation', 'pokemon', 'zelda', 'mario', 'xbox',
    # LEGO
    'lego', 'star wars', 'millennium falcon', 'hogwarts', 'batman',
    # TCG
    'pokemon', 'charizard', 'pikachu', 'magic the gathering', 'yugioh',
]


def detect_misspellings(title: str) -> List[Tuple[str, str]]:
    """
    Detect brand misspellings in title.
    Returns list of (misspelling, correct_brand) tuples.
    """
    title_lower = title.lower()
    found = []

    for misspelled, correct in BRAND_MISSPELLINGS.items():
        if misspelled in title_lower and correct not in title_lower:
            found.append((misspelled, correct))

    return found


# ============================================================
# LISTING QUALITY INDICATORS
# ============================================================

# Keywords that suggest poor listing quality (opportunity!)
POOR_LISTING_KEYWORDS = [
    'no idea', 'dont know', "don't know", 'unsure', 'unknown',
    'found in', 'found at', 'found this', 'cleaning out',
    'estate sale', 'estate find', 'garage sale', 'yard sale',
    'grandma', 'grandmother', 'inherited', 'passed away',
    'downsizing', 'moving sale', 'must sell', 'need gone',
    'no reserve', 'starting at', 'no returns', 'as is',
]

# Keywords suggesting seller knows value (less opportunity)
KNOWLEDGEABLE_SELLER_KEYWORDS = [
    'rare', 'htf', 'hard to find', 'collectible', 'vintage',
    'investment', 'appreciating', 'museum quality',
    'appraisal', 'appraised at', 'valued at', 'worth',
    'graded', 'certified', 'authenticated', 'coa',
]


def analyze_listing_quality(title: str, description: str = "") -> Dict[str, Any]:
    """
    Analyze listing quality indicators.
    Returns quality metrics.
    """
    text = f"{title} {description}".lower()

    poor_indicators = [kw for kw in POOR_LISTING_KEYWORDS if kw in text]
    knowledge_indicators = [kw for kw in KNOWLEDGEABLE_SELLER_KEYWORDS if kw in text]

    # More poor indicators = better opportunity
    # More knowledge indicators = worse opportunity
    quality_score = len(poor_indicators) * 10 - len(knowledge_indicators) * 5
    quality_score = max(0, min(100, 50 + quality_score))  # Normalize to 0-100

    return {
        'score': quality_score,
        'poor_indicators': poor_indicators,
        'knowledge_indicators': knowledge_indicators,
        'opportunity_level': 'high' if quality_score >= 70 else ('medium' if quality_score >= 40 else 'low')
    }


# ============================================================
# UNIFIED DEAL SCORE CALCULATION
# ============================================================

@dataclass
class DealScore:
    """Container for deal scoring results"""
    total_score: int  # 0-100
    grade: str  # A, B, C, D, F
    components: Dict[str, int]  # Individual component scores
    signals: List[str]  # Human-readable signals
    recommendation: str  # 'HOT', 'WARM', 'COLD'


def calculate_deal_score(
    # Price/margin info
    listing_price: float,
    market_price: float = None,
    profit: float = None,
    margin_percent: float = None,

    # Freshness
    freshness_minutes: float = None,
    freshness_score: int = None,

    # Seller info
    seller_score: int = None,
    seller_type: str = None,
    feedback_score: int = None,
    account_type: str = None,  # 'individual' or 'business'

    # Listing info
    best_offer: bool = False,
    title: str = "",
    description: str = "",
    photo_count: int = None,

    # Category
    category: str = None,
) -> DealScore:
    """
    Calculate unified deal score (0-100) combining all factors.

    Returns DealScore with total score, grade, and component breakdown.
    """
    components = {}
    signals = []

    # =========================================
    # 1. FRESHNESS SCORE (max 20 points)
    # =========================================
    if freshness_score is not None:
        # Already calculated 0-100, scale to 0-20
        components['freshness'] = int(freshness_score * WEIGHTS['freshness'] / 100)
    elif freshness_minutes is not None:
        if freshness_minutes < 2:
            components['freshness'] = 20
            signals.append("SUPER FRESH (<2 min)")
        elif freshness_minutes < 5:
            components['freshness'] = 18
            signals.append("Very fresh (<5 min)")
        elif freshness_minutes < 15:
            components['freshness'] = 15
        elif freshness_minutes < 30:
            components['freshness'] = 12
        elif freshness_minutes < 60:
            components['freshness'] = 8
        else:
            components['freshness'] = 4
    else:
        components['freshness'] = 10  # Unknown = average

    # =========================================
    # 2. SELLER PROFILE (max 25 points)
    # =========================================
    if seller_score is not None:
        # Already calculated 0-100, scale to 0-25
        components['seller_profile'] = int(seller_score * WEIGHTS['seller_profile'] / 100)

        if seller_score >= 80:
            signals.append(f"IDEAL SELLER (score:{seller_score})")
        elif seller_score >= 65:
            signals.append(f"Good seller profile ({seller_score})")
    else:
        # Calculate from available data
        seller_pts = 12  # Default average

        if seller_type:
            type_lower = seller_type.lower()
            if any(x in type_lower for x in ['estate', 'thrift', 'charity', 'liquidator']):
                seller_pts = 22
                signals.append(f"HIGH-VALUE seller type: {seller_type}")
            elif any(x in type_lower for x in ['dealer', 'professional', 'store']):
                seller_pts = 5

        if account_type and account_type.lower() == 'individual':
            seller_pts = min(25, seller_pts + 5)
            signals.append("Individual seller (not business)")

        if feedback_score is not None and feedback_score < 100:
            seller_pts = min(25, seller_pts + 3)
            signals.append(f"Low feedback ({feedback_score})")

        components['seller_profile'] = seller_pts

    # =========================================
    # 3. PRICE MARGIN (max 30 points)
    # =========================================
    if profit is not None and listing_price > 0:
        margin_pct = (profit / listing_price) * 100

        if margin_pct >= 50:
            components['price_margin'] = 30
            signals.append(f"EXCELLENT margin (+{margin_pct:.0f}%)")
        elif margin_pct >= 35:
            components['price_margin'] = 25
            signals.append(f"Great margin (+{margin_pct:.0f}%)")
        elif margin_pct >= 20:
            components['price_margin'] = 20
        elif margin_pct >= 10:
            components['price_margin'] = 15
        elif margin_pct >= 0:
            components['price_margin'] = 10
        else:
            components['price_margin'] = 5
    elif margin_percent is not None:
        if margin_percent >= 50:
            components['price_margin'] = 30
        elif margin_percent >= 35:
            components['price_margin'] = 25
        elif margin_percent >= 20:
            components['price_margin'] = 20
        elif margin_percent >= 10:
            components['price_margin'] = 15
        else:
            components['price_margin'] = 10
    else:
        components['price_margin'] = 15  # Unknown = average

    # =========================================
    # 4. BEST OFFER (max 10 points)
    # =========================================
    if best_offer:
        components['best_offer'] = 10
        signals.append("BEST OFFER available")
    else:
        components['best_offer'] = 0

    # =========================================
    # 5. LISTING QUALITY (max 10 points)
    # =========================================
    quality_analysis = analyze_listing_quality(title, description)
    # Scale 0-100 to 0-10
    components['listing_quality'] = int(quality_analysis['score'] * WEIGHTS['listing_quality'] / 100)

    if quality_analysis['poor_indicators']:
        signals.append(f"Opportunity keywords: {', '.join(quality_analysis['poor_indicators'][:3])}")

    # Photo count bonus (fewer photos = opportunity)
    if photo_count is not None:
        if photo_count <= 2:
            components['listing_quality'] = min(10, components['listing_quality'] + 3)
            signals.append("Low photo count (opportunity)")

    # =========================================
    # 6. MISSPELLING BONUS (max 5 points)
    # =========================================
    misspellings = detect_misspellings(title)
    if misspellings:
        components['misspelling'] = 5
        signals.append(f"Misspelling detected: {misspellings[0][0]} -> {misspellings[0][1]}")
    else:
        components['misspelling'] = 0

    # =========================================
    # CALCULATE TOTAL
    # =========================================
    total_score = sum(components.values())
    total_score = max(0, min(100, total_score))  # Clamp to 0-100

    # Determine grade
    if total_score >= 80:
        grade = 'A'
        recommendation = 'HOT'
    elif total_score >= 65:
        grade = 'B'
        recommendation = 'WARM'
    elif total_score >= 50:
        grade = 'C'
        recommendation = 'WARM'
    elif total_score >= 35:
        grade = 'D'
        recommendation = 'COLD'
    else:
        grade = 'F'
        recommendation = 'COLD'

    return DealScore(
        total_score=total_score,
        grade=grade,
        components=components,
        signals=signals,
        recommendation=recommendation
    )


def format_deal_score(score: DealScore) -> str:
    """Format deal score for display/logging"""
    lines = [
        f"Deal Score: {score.total_score}/100 (Grade: {score.grade}) - {score.recommendation}",
        f"Components: {score.components}",
    ]
    if score.signals:
        lines.append(f"Signals: {', '.join(score.signals)}")
    return " | ".join(lines)


# ============================================================
# CATEGORY-AGNOSTIC OPPORTUNITY DETECTION
# ============================================================

def detect_opportunity_keywords(title: str, description: str = "") -> Dict[str, Any]:
    """
    Detect keywords that indicate deal opportunity regardless of category.
    """
    text = f"{title} {description}".lower()

    opportunities = {
        'estate_sale': any(x in text for x in ['estate', 'inherited', 'passed away', 'deceased']),
        'thrift_charity': any(x in text for x in ['thrift', 'goodwill', 'salvation army', 'charity', 'hospice']),
        'liquidation': any(x in text for x in ['liquidation', 'liquidating', 'closing', 'must sell', 'need gone']),
        'casual_seller': any(x in text for x in ['found', 'cleaning out', 'dont know', "don't know", 'no idea']),
        'moving_sale': any(x in text for x in ['moving', 'downsizing', 'relocating']),
        'garage_sale': any(x in text for x in ['garage sale', 'yard sale', 'storage unit', 'attic']),
        'no_reserve': 'no reserve' in text or 'nr' in text.split(),
    }

    # Count active opportunities
    active = [k for k, v in opportunities.items() if v]

    return {
        'opportunities': opportunities,
        'active_count': len(active),
        'active_types': active,
        'is_high_opportunity': len(active) >= 2
    }
