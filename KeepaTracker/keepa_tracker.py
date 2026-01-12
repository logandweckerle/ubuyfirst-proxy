"""
Keepa Tracker V2 - Webhook & Deals Based System
Efficient Amazon price monitoring without constant polling

Two approaches:
1. TRACKING API - Register ASINs with target prices, Keepa pushes notifications
2. DEALS API - Fetch recent price drops, filter against your tracked list

This replaces polling 2,599 ASINs with:
- One-time registration of trackings
- Webhook endpoint to receive alerts
- Periodic deals feed check (1 API call returns many drops)
"""

import os
import asyncio
import logging
import json
import csv
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

KEEPA_API_KEY = os.getenv("KEEPA_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Amazon SP-API credentials for gating checks
SP_API_REFRESH_TOKEN = os.getenv("SP_API_REFRESH_TOKEN", "")
SP_API_CLIENT_ID = os.getenv("SP_API_CLIENT_ID", "")
SP_API_CLIENT_SECRET = os.getenv("SP_API_CLIENT_SECRET", "")
SP_API_MARKETPLACE_ID = "ATVPDKIKX0DER"  # US marketplace

# Keepa API base URL
KEEPA_API_BASE = "https://api.keepa.com"

# Rate limiting
RATE_LIMIT_INTERVAL = 2  # seconds between calls

# Alert deduplication settings
ALERT_COOLDOWN_HOURS = 24  # Don't re-alert same ASIN within this period
ALERTED_ASINS_FILE = "alerted_asins.json"

# Analysis thresholds
MIN_MONTHLY_SALES = 50  # Minimum estimated monthly sales (lowered from 100)
MIN_PRICE_STABILITY_DAYS = 90  # Days of price history to analyze
MIN_FBA_SELLERS = 1  # Minimum FBA sellers on listing

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("keepa_v2")


# ============================================================
# ALERT DEDUPLICATION
# ============================================================

class AlertDeduplicator:
    """
    Prevents duplicate Discord alerts for the same ASIN.
    Persists to JSON file to survive restarts.
    """

    def __init__(self, filepath: str = ALERTED_ASINS_FILE):
        self.filepath = Path(filepath)
        self.alerted: Dict[str, str] = {}  # ASIN -> ISO timestamp
        self._load()

    def _load(self):
        """Load alerted ASINs from file"""
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)
                    self.alerted = data.get("alerted", {})
                    # Clean up old entries
                    self._cleanup()
                    logger.info(f"[DEDUP] Loaded {len(self.alerted)} alerted ASINs")
            except Exception as e:
                logger.error(f"[DEDUP] Error loading: {e}")
                self.alerted = {}

    def _save(self):
        """Save alerted ASINs to file"""
        try:
            with open(self.filepath, 'w') as f:
                json.dump({"alerted": self.alerted, "updated": datetime.now().isoformat()}, f, indent=2)
        except Exception as e:
            logger.error(f"[DEDUP] Error saving: {e}")

    def _cleanup(self):
        """Remove entries older than cooldown period"""
        cutoff = datetime.now() - timedelta(hours=ALERT_COOLDOWN_HOURS)
        old_count = len(self.alerted)
        self.alerted = {
            asin: ts for asin, ts in self.alerted.items()
            if datetime.fromisoformat(ts) > cutoff
        }
        removed = old_count - len(self.alerted)
        if removed > 0:
            logger.info(f"[DEDUP] Cleaned up {removed} expired entries")

    def should_alert(self, asin: str) -> bool:
        """Check if we should send alert for this ASIN"""
        if asin not in self.alerted:
            return True

        last_alert = datetime.fromisoformat(self.alerted[asin])
        cooldown = timedelta(hours=ALERT_COOLDOWN_HOURS)

        if datetime.now() - last_alert > cooldown:
            return True

        return False

    def mark_alerted(self, asin: str):
        """Mark ASIN as alerted"""
        self.alerted[asin] = datetime.now().isoformat()
        self._save()

    def get_stats(self) -> Dict:
        """Get deduplication stats"""
        return {
            "total_tracked": len(self.alerted),
            "cooldown_hours": ALERT_COOLDOWN_HOURS,
        }


# Global deduplicator instance
_deduplicator: Optional[AlertDeduplicator] = None


def get_deduplicator() -> AlertDeduplicator:
    """Get or create the global deduplicator"""
    global _deduplicator
    if _deduplicator is None:
        _deduplicator = AlertDeduplicator()
    return _deduplicator


# ============================================================
# PRODUCT ANALYSIS
# ============================================================

@dataclass
class ProductAnalysis:
    """
    Detailed analysis of a product for flip potential.
    Populated from Keepa product API data.
    """
    asin: str

    # Gating/Eligibility
    is_gated: Optional[bool] = None  # None = unknown, True = gated, False = ungated
    gating_reason: str = ""

    # Price History Analysis
    avg_price_90d: float = 0.0  # Average price over 90 days
    avg_price_180d: float = 0.0  # Average price over 180 days
    price_stability_score: float = 0.0  # 0-100, higher = more stable
    price_is_anomaly: bool = False  # True if current price is unusually low
    historical_low: float = 0.0
    historical_high: float = 0.0

    # Sales Velocity
    estimated_monthly_sales: int = 0
    sales_rank_avg_90d: int = 0
    sales_rank_current: int = 0
    sales_rank_drops_30d: int = 0  # Number of rank drops (sales) in 30 days

    # Competition
    fba_seller_count: int = 0
    fbm_seller_count: int = 0
    amazon_on_listing: bool = False
    buy_box_price: float = 0.0

    # Overall Score
    flip_score: int = 0  # 0-100, composite score
    recommendation: str = ""  # "STRONG BUY", "BUY", "RESEARCH", "PASS"
    flags: List[str] = field(default_factory=list)  # Warning flags

    def calculate_flip_score(self):
        """Calculate overall flip score based on all factors"""
        score = 50  # Start neutral
        self.flags = []

        # Gating check (-50 if gated)
        if self.is_gated:
            score -= 50
            self.flags.append("GATED")

        # Price stability (+20 if stable, -20 if volatile)
        if self.price_stability_score >= 70:
            score += 20
        elif self.price_stability_score < 30:
            score -= 20
            self.flags.append("VOLATILE_PRICE")

        # Price anomaly bonus (+15 if current price is anomaly low)
        if self.price_is_anomaly:
            score += 15

        # Sales velocity (+25 if 100+ sales, +10 if 50+, -15 if <30)
        if self.estimated_monthly_sales >= MIN_MONTHLY_SALES:
            score += 25
        elif self.estimated_monthly_sales >= 50:
            score += 10
        elif self.estimated_monthly_sales < 30:
            score -= 15
            self.flags.append("LOW_SALES")

        # Competition check (FBA or FBM sellers)
        total_sellers = self.fba_seller_count + self.fbm_seller_count
        if total_sellers >= MIN_FBA_SELLERS:
            score += 10  # Good - others are selling successfully
            if self.fba_seller_count >= 1:
                score += 5  # Bonus for FBA presence (validates FBA viability)
        else:
            score -= 10
            self.flags.append("NO_3P_SELLERS")

        # Amazon on listing is risky
        if self.amazon_on_listing:
            score -= 15
            self.flags.append("AMAZON_COMPETING")

        # Clamp score
        self.flip_score = max(0, min(100, score))

        # Set recommendation
        if self.is_gated:
            self.recommendation = "PASS - GATED"
        elif self.flip_score >= 75:
            self.recommendation = "STRONG BUY"
        elif self.flip_score >= 60:
            self.recommendation = "BUY"
        elif self.flip_score >= 40:
            self.recommendation = "RESEARCH"
        else:
            self.recommendation = "PASS"

    def to_dict(self) -> Dict:
        return {
            "asin": self.asin,
            "is_gated": self.is_gated,
            "gating_reason": self.gating_reason,
            "avg_price_90d": self.avg_price_90d,
            "avg_price_180d": self.avg_price_180d,
            "price_stability_score": self.price_stability_score,
            "price_is_anomaly": self.price_is_anomaly,
            "estimated_monthly_sales": self.estimated_monthly_sales,
            "sales_rank_avg_90d": self.sales_rank_avg_90d,
            "fba_seller_count": self.fba_seller_count,
            "amazon_on_listing": self.amazon_on_listing,
            "flip_score": self.flip_score,
            "recommendation": self.recommendation,
            "flags": self.flags,
        }


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class TrackedProduct:
    """Product with target price from your CSV"""
    asin: str
    title: str
    target_price: float  # Alert when price drops below this
    notes: str = ""
    status: str = "active"
    brand: str = ""  # Extracted from title
    category: str = ""  # For fee calculations

    @classmethod
    def from_csv_row(cls, row: Dict) -> 'TrackedProduct':
        """Parse from FlipAlert CSV export"""
        title = row.get('Title', '')[:200]
        return cls(
            asin=row.get('ASIN', '').strip(),
            title=title[:100],
            target_price=float(row.get('Target Price', 0) or 0),
            notes=row.get('Notes', ''),
            status=row.get('Status', 'active'),
            brand=cls.extract_brand(title),
            category=cls.detect_category(title),
        )

    @staticmethod
    def extract_brand(title: str) -> str:
        """Extract brand from product title (usually first word/phrase)"""
        # Common brands that might appear in FlipAlert exports
        known_brands = [
            'Nike', 'Adidas', 'Puma', 'Under Armour', 'New Balance', 'Reebok', 'ASICS',
            'LEGO', 'Hasbro', 'Mattel', 'Funko', 'Fisher-Price', 'Hot Wheels',
            'Pokemon', 'Yu-Gi-Oh', 'Magic The Gathering', 'MTG',
            'Sony', 'Microsoft', 'Nintendo', 'PlayStation', 'Xbox',
            'Apple', 'Samsung', 'LG', 'Bose', 'JBL', 'Beats',
            'Canon', 'Nikon', 'GoPro', 'DJI', 'Fujifilm',
            'Dyson', 'KitchenAid', 'Instant Pot', 'Ninja', 'Vitamix',
            'Crocs', 'Skechers', 'Vans', 'Converse', 'Dr. Martens',
            "Levi's", 'Champion', 'The North Face', 'Patagonia', 'Columbia',
            'Disney', 'Marvel', 'Star Wars', 'Barbie', 'Transformers',
        ]

        title_lower = title.lower()
        for brand in known_brands:
            if brand.lower() in title_lower:
                return brand

        # Fallback: first word before comma or hyphen is often the brand
        if ',' in title:
            potential_brand = title.split(',')[0].strip()
            if len(potential_brand) < 30 and ' ' not in potential_brand[:15]:
                return potential_brand.split()[0] if potential_brand.split() else ""

        # First word often is the brand
        first_word = title.split()[0] if title.split() else ""
        if len(first_word) >= 2 and first_word[0].isupper():
            return first_word

        return ""

    @staticmethod
    def detect_category(title: str) -> str:
        """Detect Amazon category from title keywords"""
        title_lower = title.lower()

        # Category detection based on keywords
        categories = {
            'shoes': ['shoe', 'sneaker', 'boot', 'sandal', 'slipper', 'loafer', 'dunk', 'jordan', 'yeezy'],
            'clothing': ['shirt', 'shorts', 'pants', 'jacket', 'hoodie', 'dress', 'dri-fit', 'sweatshirt'],
            'toys': ['lego', 'funko', 'figure', 'toy', 'playset', 'action figure', 'pokemon card', 'trading card'],
            'electronics': ['headphone', 'speaker', 'camera', 'tv', 'monitor', 'tablet', 'phone', 'laptop', 'console'],
            'video_games': ['nintendo', 'xbox', 'playstation', 'ps5', 'ps4', 'switch', 'game disc', 'video game'],
            'home': ['kitchen', 'vacuum', 'blender', 'cookware', 'instant pot', 'dyson', 'mattress'],
            'sports': ['golf', 'basketball', 'baseball', 'tennis', 'yoga', 'fitness', 'gym', 'workout'],
            'beauty': ['makeup', 'skincare', 'perfume', 'cologne', 'cosmetic', 'haircare'],
            'grocery': ['snack', 'food', 'vitamin', 'supplement', 'protein', 'coffee', 'tea'],
        }

        for category, keywords in categories.items():
            if any(kw in title_lower for kw in keywords):
                return category

        return 'general'


@dataclass
class PriceDrop:
    """A detected price drop from Keepa"""
    asin: str
    title: str
    current_price: float
    previous_price: float
    target_price: float
    drop_percent: float
    sales_rank: int
    category: str
    image_url: str
    amazon_url: str
    timestamp: datetime = field(default_factory=datetime.now)
    product_category: str = ""  # For fee calculations

    @property
    def profit_potential(self) -> float:
        """
        Estimated profit using category-specific Amazon fees

        Fee structure:
        - Referral fee: varies by category (8-17%, most 15%)
        - FBA fee: based on size tier (~$3.22 small standard, ~$4.75 large standard)
        - Inbound placement: ~$0.27 avg per unit
        """
        if self.target_price <= self.current_price:
            return 0

        sell_price = self.target_price
        buy_price = self.current_price

        # Category-specific referral fees (Amazon 2024 rates)
        referral_rates = {
            'shoes': 0.15,       # 15% footwear
            'clothing': 0.17,   # 17% apparel
            'toys': 0.15,       # 15% toys
            'electronics': 0.08, # 8% consumer electronics
            'video_games': 0.15, # 15% video games
            'home': 0.15,       # 15% home & kitchen
            'sports': 0.15,     # 15% sports
            'beauty': 0.15,     # 8-15% beauty (using 15% as conservative)
            'grocery': 0.15,    # 8-15% grocery
            'general': 0.15,    # Default 15%
        }

        # FBA fulfillment fees (small standard as base, ~$3.22-$5.40)
        # Using tiered estimate based on sell price as proxy for size
        if sell_price < 20:
            fba_fee = 3.22  # Small standard
        elif sell_price < 50:
            fba_fee = 4.75  # Large standard small
        elif sell_price < 100:
            fba_fee = 5.40  # Large standard medium
        else:
            fba_fee = 6.50  # Large standard large

        # Inbound placement fee (~$0.27 avg)
        inbound_fee = 0.27

        # Calculate fees
        category_key = self.product_category if self.product_category in referral_rates else 'general'
        referral_fee = sell_price * referral_rates[category_key]

        # Minimum referral fee is $0.30
        referral_fee = max(referral_fee, 0.30)

        total_fees = referral_fee + fba_fee + inbound_fee

        profit = sell_price - buy_price - total_fees
        return profit

    @property
    def estimated_fees(self) -> Dict:
        """Return breakdown of estimated fees"""
        sell_price = self.target_price

        referral_rates = {
            'shoes': 0.15, 'clothing': 0.17, 'toys': 0.15, 'electronics': 0.08,
            'video_games': 0.15, 'home': 0.15, 'sports': 0.15, 'beauty': 0.15,
            'grocery': 0.15, 'general': 0.15,
        }

        if sell_price < 20:
            fba_fee = 3.22
        elif sell_price < 50:
            fba_fee = 4.75
        elif sell_price < 100:
            fba_fee = 5.40
        else:
            fba_fee = 6.50

        category_key = self.product_category if self.product_category in referral_rates else 'general'
        referral_fee = max(sell_price * referral_rates[category_key], 0.30)

        return {
            'referral_fee': round(referral_fee, 2),
            'fba_fee': fba_fee,
            'inbound_fee': 0.27,
            'total_fees': round(referral_fee + fba_fee + 0.27, 2),
            'referral_rate': referral_rates[category_key],
        }
    
    def to_dict(self) -> Dict:
        fees = self.estimated_fees
        return {
            "asin": self.asin,
            "title": self.title,
            "current_price": self.current_price,
            "previous_price": self.previous_price,
            "target_price": self.target_price,
            "drop_percent": round(self.drop_percent, 1),
            "profit_potential": round(self.profit_potential, 2),
            "sales_rank": self.sales_rank,
            "category": self.category,
            "product_category": self.product_category,
            "image_url": self.image_url,
            "amazon_url": self.amazon_url,
            "timestamp": self.timestamp.isoformat(),
            "fees": fees,
        }


# ============================================================
# KEEPA API CLIENT
# ============================================================

def get_current_rank(deal: Dict) -> int:
    """
    Extract current sales rank from Keepa deal/product response.

    Keepa returns sales rank in two formats:
    - salesRanks: {categoryId: [timestamp, rank, timestamp, rank, ...]} - More reliable
    - salesRank: int - May be null for variations

    Returns the most recent sales rank, or 0 if not found.
    """
    # First try salesRanks dict (more reliable)
    sales_ranks = deal.get('salesRanks', {})
    if sales_ranks:
        for cat_id, history in sales_ranks.items():
            if history and len(history) >= 2:
                # Walk backwards through array to find latest non-zero rank
                # Format: [timestamp, rank, timestamp, rank, ...]
                for i in range(len(history)-1, 0, -2):
                    if history[i] > 0:
                        return history[i]

    # Fallback to salesRank field
    rank = deal.get('salesRank')
    if rank is not None and rank > 0:
        return rank

    return 0


class KeepaClientV2:
    """
    Efficient Keepa API client using:
    1. Tracking API for webhook notifications
    2. Deals API for recent price drops
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or KEEPA_API_KEY
        self.tracked_products: Dict[str, TrackedProduct] = {}  # ASIN -> Product
        self.tracked_brands: Dict[str, List[str]] = {}  # Brand -> List of ASINs
        self._last_call = 0

        # Stats
        self.stats = {
            "api_calls": 0,
            "tokens_left": 0,
            "deals_checked": 0,
            "alerts_sent": 0,
            "last_check": None,
            "brands_tracked": 0,
        }
    
    async def _rate_limit(self):
        """Respect rate limits"""
        import time
        now = time.time()
        elapsed = now - self._last_call
        if elapsed < RATE_LIMIT_INTERVAL:
            await asyncio.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self._last_call = time.time()
    
    async def _api_call(self, endpoint: str, params: Dict = None) -> Dict:
        """Make API call to Keepa"""
        await self._rate_limit()
        
        url = f"{KEEPA_API_BASE}/{endpoint}"
        params = params or {}
        params["key"] = self.api_key
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                self.stats["api_calls"] += 1
                
                if response.status_code == 200:
                    data = response.json()
                    self.stats["tokens_left"] = data.get("tokensLeft", 0)
                    return data
                else:
                    logger.error(f"[KEEPA] API error {response.status_code}: {response.text}")
                    return {}
        except Exception as e:
            logger.error(f"[KEEPA] Request error: {e}")
            return {}
    
    def load_tracked_products_csv(self, filepath: str):
        """Load products from FlipAlert CSV export with target prices"""
        path = Path(filepath)
        if not path.exists():
            logger.warning(f"[KEEPA] CSV not found: {filepath}")
            return

        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    product = TrackedProduct.from_csv_row(row)
                    if product.asin and product.target_price > 0:
                        self.tracked_products[product.asin] = product
                        count += 1

                        # Build brand index for brand-based deal monitoring
                        if product.brand:
                            brand_lower = product.brand.lower()
                            if brand_lower not in self.tracked_brands:
                                self.tracked_brands[brand_lower] = []
                            if product.asin not in self.tracked_brands[brand_lower]:
                                self.tracked_brands[brand_lower].append(product.asin)
                except Exception as e:
                    logger.debug(f"[KEEPA] Error parsing row: {e}")

        self.stats["brands_tracked"] = len(self.tracked_brands)
        logger.info(f"[KEEPA] Loaded {count} products with target prices from {len(self.tracked_brands)} brands")

    def get_tracked_brands(self) -> Dict[str, int]:
        """Get all tracked brands with product counts"""
        return {brand: len(asins) for brand, asins in self.tracked_brands.items()}

    def save_tracked_brands(self, filepath: str = "tracked_brands.txt"):
        """Save tracked brands to file for reference"""
        brands = sorted(self.tracked_brands.keys())
        with open(filepath, 'w') as f:
            for brand in brands:
                count = len(self.tracked_brands[brand])
                f.write(f"{brand} ({count} products)\n")
        logger.info(f"[KEEPA] Saved {len(brands)} brands to {filepath}")
    
    # ========================================================
    # DEALS API - Most efficient for monitoring many products
    # ========================================================
    
    async def get_deals(
        self,
        domain: str = "US",
        price_types: int = None,
        delta_percent_range: Tuple[int, int] = (40, 100),
        delta_last_hours: int = 48,
        sales_rank_range: Tuple[int, int] = (1, 300000),  # Expanded from 150k
        price_range: Tuple[int, int] = (2500, 80000),  # $25-$800 in cents
        sort_by: int = 3,  # 3 = Sales Rank (best sellers first), 4 = drop %
        page: int = 0,
        must_have_amazon: bool = True,
        exclude_categories: List[int] = None,
        include_categories: List[int] = None,
    ) -> List[Dict]:
        """
        Fetch recent deals (price drops) from Keepa

        This is MUCH more efficient than polling individual ASINs!
        One API call can return up to 150 deals (5 tokens).

        Args:
            domain: Amazon marketplace (US, UK, DE, etc)
            price_types: Price type to monitor
                        0=Amazon, 1=New 3P, 2=Used, 3=Sales Rank, 7=New FBM, 10=New FBA, 18=Buy Box
            delta_percent_range: Min/max price drop percentage (e.g. 40-100 = 40%+ drops)
            delta_last_hours: Only show drops from last X hours
            sales_rank_range: Filter by sales rank (use to get items with sales velocity)
            price_range: Price range in cents (e.g., [2500, 80000] = $25-$800)
            sort_by: 1=Deal age, 2=Absolute delta, 3=Sales Rank (best sellers), 4=Percentage delta
            page: Pagination (0-66 max, iterate while 150 results returned)
            must_have_amazon: If True, only return products where Amazon is selling
            exclude_categories: Category IDs to exclude (e.g., [7141123011] for apparel)
            include_categories: Category IDs to include (overrides exclude if both set)

        Returns:
            List of deal dictionaries
        """
        # priceTypes must be an array with ONE value only (Keepa limitation)
        # 0=Amazon, 1=New 3rd party, 2=Used, 7=New FBM, 10=New FBA, 18=Buy Box
        if price_types is None:
            price_types = [0]  # Amazon first-party (retail arbitrage target)
        elif isinstance(price_types, int):
            price_types = [price_types]

        # Default category exclusions: Apparel, Shoes, Books, Audible, Software, Digital Music
        if exclude_categories is None and include_categories is None:
            exclude_categories = [
                7141123011,   # Clothing
                7141124011,   # Shoes
                7147440011,   # Luggage (often apparel-adjacent)
                283155,       # Books
                2350149011,   # Audible
                173507,       # Music
                2625373011,   # Digital Music
                979455011,    # Software
            ]

        # Build deal request - Keepa expects domainId INSIDE selection JSON
        domain_id = self._domain_to_id(domain)

        selection = {
            "page": page,
            "domainId": domain_id,
            "deltaPercentRange": list(delta_percent_range),
            "deltaLastRange": [0, delta_last_hours * 60],  # In minutes
            "currentRange": list(price_range),
            "priceTypes": price_types,
            "sortType": sort_by,
            "isRangeEnabled": True,
            "singleVariation": True,  # Avoid duplicate variations
            "filterErotic": True,     # Exclude adult items
            "hasReviews": False,      # Don't require reviews
        }

        # Only add salesRankRange if we want to filter (excludes items with no rank)
        if sales_rank_range and sales_rank_range[0] > 0:
            selection["salesRankRange"] = list(sales_rank_range)

        # Add Amazon offer filter
        if must_have_amazon:
            selection["mustHaveAmazonOffer"] = True

        # Add category filters
        if include_categories:
            selection["includeCategories"] = include_categories
        elif exclude_categories:
            selection["excludeCategories"] = exclude_categories

        deal_params = {
            "domain": domain_id,
            "selection": json.dumps(selection),
        }
        
        data = await self._api_call("deal", deal_params)
        
        deals = data.get("deals", {}).get("dr", [])
        self.stats["deals_checked"] += len(deals)
        self.stats["last_check"] = datetime.now()
        
        logger.info(f"[KEEPA] Deals API returned {len(deals)} price drops")
        return deals
    
    async def check_deals_against_tracked(self) -> List[PriceDrop]:
        """
        Main monitoring function:
        1. Fetch recent deals from Keepa
        2. Check if any match our tracked ASINs
        3. Return matches that are below target price
        """
        if not self.tracked_products:
            logger.warning("[KEEPA] No tracked products loaded!")
            return []
        
        # Fetch deals (recent price drops) - Use Buy Box price for arbitrage
        raw_deals = await self.get_deals(
            price_types=18,  # Buy Box with shipping - most relevant for arbitrage
            delta_percent_range=(15, 100),  # At least 15% drop
            delta_last_hours=6,  # Last 6 hours
            sales_rank_range=(1, 1000000),
            price_range=(500, 80000),  # $5-$800
            must_have_amazon=False,  # Include all sellers, not just Amazon
        )
        
        matches = []
        
        for deal in raw_deals:
            asin = deal.get("asin", "")
            
            # Check if this ASIN is in our tracked list
            if asin not in self.tracked_products:
                continue
            
            tracked = self.tracked_products[asin]
            
            # Helper to safely get int from potentially nested data
            def safe_int(val, default=0):
                if val is None:
                    return default
                if isinstance(val, (int, float)):
                    return int(val)
                if isinstance(val, list) and len(val) > 0:
                    return safe_int(val[0], default)
                return default

            # Get current price (in cents, convert to dollars)
            current_prices = deal.get("current", [])
            current_price_cents = safe_int(current_prices[0] if len(current_prices) > 0 else 0, 0)  # Amazon price
            if current_price_cents <= 0:
                current_price_cents = safe_int(current_prices[1] if len(current_prices) > 1 else 0, 0)  # New price

            current_price = current_price_cents / 100.0 if current_price_cents > 0 else 0

            # Check if below target price
            if current_price <= 0 or current_price > tracked.target_price:
                continue

            # Get previous price
            delta_raw = deal.get("delta", [])
            prev_price_cents = safe_int(delta_raw[0] if len(delta_raw) > 0 else 0, 0)
            prev_price = (current_price_cents + prev_price_cents) / 100.0
            
            # Calculate drop percent
            drop_pct = ((prev_price - current_price) / prev_price * 100) if prev_price > 0 else 0
            
            # Create PriceDrop object with category for fee calculation
            price_drop = PriceDrop(
                asin=asin,
                title=tracked.title,
                current_price=current_price,
                previous_price=prev_price,
                target_price=tracked.target_price,
                drop_percent=drop_pct,
                sales_rank=get_current_rank(deal),  # Use helper to parse salesRanks dict
                category=str(deal.get("categories", ["Unknown"])[0]) if deal.get("categories") else "Unknown",
                image_url=f"https://images-na.ssl-images-amazon.com/images/I/{deal.get('image', '')}" if deal.get('image') else "",
                amazon_url=f"https://www.amazon.com/dp/{asin}",
                product_category=tracked.category,  # Pass category for accurate fee calculation
            )

            matches.append(price_drop)
            logger.info(f"[KEEPA] 🎯 MATCH: {asin} - ${current_price:.2f} (target: ${tracked.target_price:.2f}, profit: ${price_drop.profit_potential:.2f})")
        
        logger.info(f"[KEEPA] Found {len(matches)} deals matching tracked products")
        return matches

    async def check_deals_by_brand(
        self,
        min_profit: float = 5.0,
        max_sales_rank: int = 500000,
    ) -> List[Dict]:
        """
        Find deals from tracked brands that aren't in our ASIN list.

        This is the key insight: if we already sell Nike products successfully,
        other Nike deals are likely also sellable. This finds NEW opportunities
        from brands we already know we're allowed to sell.

        Args:
            min_profit: Minimum estimated profit after fees
            max_sales_rank: Filter by sales rank (lower = faster selling)

        Returns:
            List of potential deals from tracked brands (not in tracked ASINs)
        """
        if not self.tracked_brands:
            logger.warning("[KEEPA] No tracked brands loaded!")
            return []

        # Fetch recent deals
        raw_deals = await self.get_deals(
            delta_percent_range=(25, 100),  # At least 25% drop for new opportunities
            delta_last_hours=12,
            sales_rank_range=(1, max_sales_rank),
        )

        brand_opportunities = []

        for deal in raw_deals:
            asin = deal.get("asin", "")

            # Skip if already in our tracked list (those are handled separately)
            if asin in self.tracked_products:
                continue

            # Get title from deal (Keepa includes this in some responses)
            title = deal.get("title", "")

            # Extract brand from title
            detected_brand = TrackedProduct.extract_brand(title).lower() if title else ""

            # Check if this brand is in our tracked brands
            if detected_brand and detected_brand in self.tracked_brands:
                # Helper to safely get int from potentially nested data
                def safe_int(val, default=0):
                    if val is None:
                        return default
                    if isinstance(val, (int, float)):
                        return int(val)
                    if isinstance(val, list) and len(val) > 0:
                        return safe_int(val[0], default)
                    return default

                # Get price info
                current_prices = deal.get("current", [])
                current_price_cents = safe_int(current_prices[0] if len(current_prices) > 0 else 0, 0)
                if current_price_cents <= 0:
                    current_price_cents = safe_int(current_prices[1] if len(current_prices) > 1 else 0, 0)

                current_price = current_price_cents / 100.0 if current_price_cents > 0 else 0

                if current_price <= 0:
                    continue

                # Get previous price and calculate drop
                delta_raw = deal.get("delta", [])
                prev_price_cents = safe_int(delta_raw[0] if len(delta_raw) > 0 else 0, 0)
                prev_price = (current_price_cents + prev_price_cents) / 100.0

                # Estimate sell price as 80% of previous price (conservative)
                estimated_sell_price = prev_price * 0.80

                # Calculate profit using category from title
                detected_category = TrackedProduct.detect_category(title) if title else 'general'

                # Get sales rank using helper (parses salesRanks dict properly)
                sales_rank = get_current_rank(deal)

                # Skip if no sales rank data (API already filters, but double-check)
                # A rank of 0 means we couldn't extract it - skip
                if sales_rank == 0 or sales_rank > max_sales_rank:
                    continue

                # Skip very cheap items (not worth the effort for brand opportunities)
                if current_price < 10.0:
                    continue

                # Create temp PriceDrop to calculate fees
                temp_drop = PriceDrop(
                    asin=asin,
                    title=title,
                    current_price=current_price,
                    previous_price=prev_price,
                    target_price=estimated_sell_price,
                    drop_percent=0,
                    sales_rank=sales_rank,
                    category="",
                    image_url="",
                    amazon_url="",
                    product_category=detected_category,
                )

                estimated_profit = temp_drop.profit_potential

                if estimated_profit >= min_profit:
                    opportunity = {
                        "asin": asin,
                        "title": title[:100] if title else f"Unknown - {asin}",
                        "brand": detected_brand,
                        "current_price": current_price,
                        "previous_price": prev_price,
                        "estimated_sell_price": estimated_sell_price,
                        "estimated_profit": round(estimated_profit, 2),
                        "sales_rank": sales_rank,
                        "category": detected_category,
                        "amazon_url": f"https://www.amazon.com/dp/{asin}",
                        "reason": f"Brand '{detected_brand}' matches {len(self.tracked_brands[detected_brand])} tracked products",
                    }
                    brand_opportunities.append(opportunity)
                    logger.info(f"[KEEPA] 🏷️ BRAND MATCH: {detected_brand} - {asin} - est profit ${estimated_profit:.2f}")

        # Sort by estimated profit
        brand_opportunities.sort(key=lambda x: x["estimated_profit"], reverse=True)

        logger.info(f"[KEEPA] Found {len(brand_opportunities)} brand-based opportunities")
        return brand_opportunities

    async def check_open_discovery_deals(
        self,
        min_discount_pct: float = 40.0,  # 40% minimum discount
        min_profit: float = 5.0,
        max_sales_rank: int = 500000,
        price_range: Tuple[int, int] = (1000, 10000),  # $10-$100 in cents
    ) -> List[Dict]:
        """
        OPEN DISCOVERY MODE - Find ANY profitable deal on Amazon.

        Unlike check_deals_against_tracked which only matches your ASINs,
        this finds ANY deal that meets profit criteria.

        Args:
            min_discount_pct: Minimum discount from previous price (default 40%)
            min_profit: Minimum estimated profit after fees
            max_sales_rank: Filter by sales rank (lower = faster selling)
            price_range: Price range in cents (min, max)

        Returns:
            List of profitable deals from any product on Amazon
        """
        logger.info(f"[KEEPA] Open Discovery: {min_discount_pct}%+ drop, ${min_profit}+ profit, rank < {max_sales_rank}, price ${price_range[0]/100:.0f}-${price_range[1]/100:.0f}")

        # Fetch deals from multiple price segments to ensure we get higher-priced items too
        # The Keepa API sorts by % drop, which tends to favor lower-priced items
        # By fetching multiple segments, we ensure we get opportunities at all price points
        raw_deals = []
        seen_asins = set()

        # Split the price range into segments for better coverage
        min_price = price_range[0]
        max_price = price_range[1]
        price_segments = [
            (min_price, 3000),       # $10-30 (lower tier)
            (3000, 6000),            # $30-60 (mid tier)
            (6000, max_price),       # $60-100 (high tier - best profit margins)
        ]

        # Filter segments to only those within the requested range
        price_segments = [
            (max(seg[0], min_price), min(seg[1], max_price))
            for seg in price_segments
            if seg[0] < max_price and seg[1] > min_price
        ]

        for seg_min, seg_max in price_segments:
            if seg_min >= seg_max:
                continue
            logger.info(f"[KEEPA] Fetching segment ${seg_min/100:.0f}-${seg_max/100:.0f}")
            page_deals = await self.get_deals(
                price_types=18,  # Buy Box with shipping - most relevant for arbitrage
                delta_percent_range=(int(min_discount_pct), 100),
                delta_last_hours=24,  # Extended to 24 hours to catch more deals
                sales_rank_range=(1, max_sales_rank),
                price_range=(seg_min, seg_max),
                must_have_amazon=False,  # Don't require Amazon as seller - include all FBA/FBM
                sort_by=4,  # Sort by percentage drop (highest discount first) instead of sales rank
            )
            # Dedupe by ASIN across segments
            for deal in page_deals:
                asin = deal.get("asin", "")
                if asin and asin not in seen_asins:
                    seen_asins.add(asin)
                    raw_deals.append(deal)

        logger.info(f"[KEEPA] Fetched {len(raw_deals)} total deals across {len(price_segments)} segment(s)")

        opportunities = []

        # Skip titles containing book/media keywords
        skip_keywords = [
            'audiobook', 'audible', 'kindle', 'ebook', 'paperback', 'hardcover',
            'book 1', 'book 2', 'book 3', 'book 4', 'book 5', 'book one', 'book two',
            'series:', 'serie ', '-serie', 'novel', 'edition:', 'vol.', 'volume ', 'chapter',
            ': a novel', '(novel)', 'trilogy', 'saga', 'unabridged',
            'expanse', 'thanatonautes', 'rising:',  # Specific book series
        ]

        # Categories to exclude (secondary check beyond API filter)
        excluded_category_ids = {
            283155,       # Books
            2350149011,   # Audible Audiobooks
            173507,       # Music
            2625373011,   # Digital Music
            979455011,    # Software
            4991425011,   # Kindle Store
            9479199011,   # Kindle eBooks
        }

        for deal in raw_deals:
            asin = deal.get("asin", "")
            title = deal.get("title", "")

            # Check deal categories against excluded list
            deal_categories = set(deal.get("categories", []))
            if deal_categories & excluded_category_ids:
                continue  # Skip if any category matches excluded list

            # Skip books/media by title keywords
            title_lower = title.lower() if title else ""
            if any(kw in title_lower for kw in skip_keywords):
                continue

            # Helper to safely get int from potentially nested data
            def safe_int(val, default=0):
                if val is None:
                    return default
                if isinstance(val, (int, float)):
                    return int(val)
                if isinstance(val, list) and len(val) > 0:
                    return safe_int(val[0], default)
                return default

            # Get current price (in cents, convert to dollars)
            # For Buy Box (type 18), the price is at index 18 in the array
            # Indices: 0=Amazon, 1=New 3P, 10=New FBA, 18=Buy Box
            current_prices = deal.get("current", [])

            # Try Buy Box (18) first, then Amazon (0), then New (1)
            current_price_cents = 0
            for idx in [18, 0, 1, 10]:  # Buy Box, Amazon, New 3P, New FBA
                if len(current_prices) > idx:
                    val = safe_int(current_prices[idx], 0)
                    if val > 0:
                        current_price_cents = val
                        break

            current_price = current_price_cents / 100.0 if current_price_cents > 0 else 0

            if current_price <= 0:
                continue

            # Get discount percentage from Keepa's pre-calculated deltaPercent
            # deltaPercent is a nested array - find the highest discount across all price types
            delta_percent_arr = deal.get("deltaPercent", [])
            actual_discount = 0

            for i, val in enumerate(delta_percent_arr):
                if isinstance(val, list) and len(val) > 0:
                    pct = val[0] if isinstance(val[0], (int, float)) else 0
                    if pct > actual_discount:
                        actual_discount = pct
                elif isinstance(val, (int, float)) and val > actual_discount:
                    actual_discount = val

            # Calculate previous price from discount
            # If current = $30 and discount = 40%, then prev = 30 / (1 - 0.40) = $50
            if actual_discount > 0:
                prev_price = current_price / (1 - actual_discount / 100)
            else:
                # Fallback: try delta array (raw price change in cents)
                delta_raw = deal.get("delta", [])
                prev_price_cents = 0
                for idx in [18, 0, 1, 10]:
                    if len(delta_raw) > idx:
                        val = safe_int(delta_raw[idx], 0)
                        if val > 0:  # Only use positive deltas (price dropped)
                            prev_price_cents = val
                            break

                if prev_price_cents > 0:
                    prev_price = (current_price_cents + prev_price_cents) / 100.0
                    # Calculate actual discount from the delta
                    actual_discount = (prev_price_cents / (current_price_cents + prev_price_cents)) * 100
                else:
                    # Try creationDate-based calculation using avg30/avg90 if available
                    avg30 = deal.get("avg30", [])
                    avg90 = deal.get("avg90", [])
                    avg_price_cents = 0
                    for idx in [18, 0, 1, 10]:
                        if len(avg30) > idx:
                            val = safe_int(avg30[idx], 0)
                            if val > 0:
                                avg_price_cents = val
                                break
                    if avg_price_cents == 0:
                        for idx in [18, 0, 1, 10]:
                            if len(avg90) > idx:
                                val = safe_int(avg90[idx], 0)
                                if val > 0:
                                    avg_price_cents = val
                                    break

                    if avg_price_cents > current_price_cents:
                        prev_price = avg_price_cents / 100.0
                        actual_discount = ((avg_price_cents - current_price_cents) / avg_price_cents) * 100
                    else:
                        # No valid delta found - skip without logging (too spammy)
                        continue

            if prev_price <= current_price:
                logger.info(f"[KEEPA] Skip {asin}: prev ${prev_price:.2f} <= current ${current_price:.2f} (delta: {prev_price - current_price:.0f})")
                continue

            if actual_discount < min_discount_pct:
                logger.info(f"[KEEPA] Skip {asin}: current ${current_price:.2f}, discount {actual_discount:.1f}%")
                continue

            # Sales rank - use helper to properly parse salesRanks dict
            sales_rank = get_current_rank(deal)
            # Note: API already filters by salesRankRange, so we trust API-filtered deals

            # Estimate sell price as the previous price (what it was selling for)
            estimated_sell_price = prev_price

            # Detect category for fee calculation
            detected_category = TrackedProduct.detect_category(title) if title else 'general'

            # Create temp PriceDrop to calculate fees
            temp_drop = PriceDrop(
                asin=asin,
                title=title,
                current_price=current_price,
                previous_price=prev_price,
                target_price=estimated_sell_price,
                drop_percent=actual_discount,
                sales_rank=sales_rank,
                category="",
                image_url="",
                amazon_url="",
                product_category=detected_category,
            )

            estimated_profit = temp_drop.profit_potential
            fees = temp_drop.estimated_fees

            # Log deals that fail profit check to understand why
            if estimated_profit < min_profit:
                logger.info(f"[KEEPA] Skip {asin}: ${current_price:.2f} -> ${prev_price:.2f} ({actual_discount:.0f}% off) - profit ${estimated_profit:.2f} < ${min_profit} (fees: ${fees['total_fees']:.2f})")

            if estimated_profit >= min_profit:
                opportunity = {
                    "asin": asin,
                    "title": title[:100] if title else f"Unknown - {asin}",
                    "current_price": round(current_price, 2),
                    "previous_price": round(prev_price, 2),
                    "discount_pct": round(actual_discount, 1),
                    "estimated_sell_price": round(estimated_sell_price, 2),
                    "estimated_profit": round(estimated_profit, 2),
                    "sales_rank": sales_rank,
                    "category": detected_category,
                    "amazon_url": f"https://www.amazon.com/dp/{asin}",
                    "source": "open_discovery",
                }
                opportunities.append(opportunity)
                logger.info(f"[KEEPA] 🔥 OPEN DEAL: {asin} - ${current_price:.2f} (was ${prev_price:.2f}, {actual_discount:.0f}% off, profit ${estimated_profit:.2f})")

        # Sort by profit
        opportunities.sort(key=lambda x: x["estimated_profit"], reverse=True)

        logger.info(f"[KEEPA] Open Discovery found {len(opportunities)} profitable deals")
        return opportunities

    # ========================================================
    # TRACKING API - For webhook-based alerts
    # ========================================================
    
    async def add_tracking(
        self,
        asin: str,
        target_price: float,
        domain: str = "US",
    ) -> bool:
        """
        Register an ASIN for tracking with Keepa
        When price drops below target, Keepa will push notification
        
        Args:
            asin: Amazon ASIN
            target_price: Alert when price drops below this (in dollars)
            domain: Amazon marketplace
        """
        # Convert price to cents (Keepa format)
        threshold_cents = int(target_price * 100)
        
        params = {
            "type": "add",
            "asin": asin,
            "domain": self._domain_to_id(domain),
            "thresholdValue": threshold_cents,
            "csvType": 1,  # 1 = New price
            "isDrop": "true",
            "notificationType": "[false,false,false,false,false,true,false]",  # API notification only
        }
        
        data = await self._api_call("tracking", params)
        
        if data.get("tracking"):
            logger.info(f"[KEEPA] Added tracking for {asin} @ ${target_price:.2f}")
            return True
        else:
            logger.warning(f"[KEEPA] Failed to add tracking for {asin}")
            return False
    
    async def remove_tracking(self, asin: str, domain: str = "US") -> bool:
        """Remove tracking for an ASIN"""
        params = {
            "type": "remove",
            "asin": asin,
            "domain": self._domain_to_id(domain),
        }
        
        data = await self._api_call("tracking", params)
        return bool(data.get("tracking"))
    
    async def get_trackings(self, asins_only: bool = True) -> List:
        """Get list of all current trackings"""
        params = {
            "type": "list",
            "asinsOnly": str(asins_only).lower(),
        }
        
        data = await self._api_call("tracking", params)
        return data.get("trackings", [])
    
    async def get_notifications(self, since_hours: int = 24) -> List[Dict]:
        """Get recent notifications (triggered alerts)"""
        # Keepa uses custom time format
        since_keepa_time = self._datetime_to_keepa_time(
            datetime.now() - timedelta(hours=since_hours)
        )
        
        params = {
            "type": "notification",
            "since": since_keepa_time,
            "revise": "false",
        }
        
        data = await self._api_call("tracking", params)
        return data.get("notifications", [])
    
    async def set_webhook_url(self, webhook_url: str) -> bool:
        """
        Set webhook URL for Keepa to push notifications
        
        When a tracking is triggered, Keepa will POST to this URL
        """
        params = {
            "type": "webhook",
            "url": webhook_url,
        }
        
        data = await self._api_call("tracking", params)
        
        if data.get("url") == webhook_url:
            logger.info(f"[KEEPA] Webhook URL set: {webhook_url[:50]}...")
            return True
        return False
    
    async def register_all_trackings(self, batch_size: int = 50) -> Dict:
        """
        Register all loaded products as trackings with Keepa
        
        This is a one-time operation - after this, Keepa monitors for you!
        
        Returns stats on success/failure
        """
        if not self.tracked_products:
            return {"error": "No products loaded"}
        
        results = {"added": 0, "failed": 0, "skipped": 0}
        
        products = list(self.tracked_products.values())
        logger.info(f"[KEEPA] Registering {len(products)} trackings...")
        
        for i, product in enumerate(products):
            if product.target_price <= 0:
                results["skipped"] += 1
                continue
            
            success = await self.add_tracking(product.asin, product.target_price)
            
            if success:
                results["added"] += 1
            else:
                results["failed"] += 1
            
            # Progress log every 100
            if (i + 1) % 100 == 0:
                logger.info(f"[KEEPA] Progress: {i+1}/{len(products)}")
        
        logger.info(f"[KEEPA] Registration complete: {results}")
        return results
    
    # ========================================================
    # PRODUCT API - Detailed product analysis
    # ========================================================

    async def get_product_details(self, asin: str, domain: str = "US") -> Optional[Dict]:
        """
        Fetch detailed product data from Keepa Product API.

        Returns comprehensive data including:
        - Price history (Amazon, New, Used, FBA)
        - Sales rank history
        - Offer counts
        - Buy box statistics

        Note: Costs 1 token per product (vs 50 for deals)
        """
        params = {
            "asin": asin,
            "domain": self._domain_to_id(domain),
            "stats": 180,  # Get 180-day statistics
            "history": 1,  # Include price history
            "offers": 20,  # Include offer data
            "rating": 1,   # Include review data
        }

        data = await self._api_call("product", params)

        if data.get("products"):
            return data["products"][0]
        return None

    async def analyze_product(self, asin: str) -> ProductAnalysis:
        """
        Perform comprehensive analysis of a product for flip potential.

        Fetches Keepa data and analyzes:
        - 90/180 day price stability
        - Sales velocity from rank history
        - Seller competition
        - Buy box ownership
        """
        analysis = ProductAnalysis(asin=asin)

        # Fetch detailed product data
        product = await self.get_product_details(asin)

        if not product:
            analysis.flags.append("NO_DATA")
            analysis.recommendation = "RESEARCH - No Keepa data"
            return analysis

        # Parse price history and statistics
        try:
            stats = product.get("stats", {})
            csv_data = product.get("csv", [])

            # === PRICE ANALYSIS ===
            # Keepa stores prices in cents, -1 means no data
            # csv indices: 0=Amazon, 1=New, 2=Used, 7=New FBA, 18=Buy Box

            # Get 90/180 day averages from stats
            if stats:
                # New price averages (index 1)
                avg_90 = stats.get("avg90", [[]])[1] if len(stats.get("avg90", [[]])) > 1 else None
                avg_180 = stats.get("avg180", [[]])[1] if len(stats.get("avg180", [[]])) > 1 else None

                if avg_90 and avg_90 > 0:
                    analysis.avg_price_90d = avg_90 / 100.0
                if avg_180 and avg_180 > 0:
                    analysis.avg_price_180d = avg_180 / 100.0

                # Min/Max prices
                min_prices = stats.get("min", [])
                max_prices = stats.get("max", [])
                if len(min_prices) > 1 and min_prices[1] > 0:
                    analysis.historical_low = min_prices[1] / 100.0
                if len(max_prices) > 1 and max_prices[1] > 0:
                    analysis.historical_high = max_prices[1] / 100.0

            # Calculate price stability score
            if analysis.avg_price_90d > 0 and analysis.historical_high > 0:
                price_range = analysis.historical_high - analysis.historical_low
                if analysis.historical_high > 0:
                    volatility = price_range / analysis.historical_high
                    analysis.price_stability_score = max(0, min(100, 100 - (volatility * 100)))

            # Check if current price is anomaly (30%+ below 90-day avg)
            current_prices = stats.get("current", []) if stats else []
            current_new = current_prices[1] / 100.0 if len(current_prices) > 1 and current_prices[1] > 0 else 0

            if current_new > 0 and analysis.avg_price_90d > 0:
                discount_from_avg = (analysis.avg_price_90d - current_new) / analysis.avg_price_90d
                if discount_from_avg >= 0.30:  # 30% or more below average
                    analysis.price_is_anomaly = True

            # === SALES RANK ANALYSIS ===
            analysis.sales_rank_current = get_current_rank(product)

            # Get 90-day average rank
            if stats:
                avg_rank = stats.get("avg90", [])
                if len(avg_rank) > 0:
                    # Sales rank is at different index depending on category
                    rank_idx = len(avg_rank) - 1  # Usually last element
                    if avg_rank[rank_idx] and avg_rank[rank_idx] > 0:
                        analysis.sales_rank_avg_90d = avg_rank[rank_idx]

            # Estimate monthly sales from rank (rough category-independent formula)
            # Based on empirical data: Sales ≈ (Category_Constant / Rank) ^ 0.6
            # This is a simplified estimate - real calculation varies by category
            if analysis.sales_rank_current > 0:
                rank = analysis.sales_rank_current
                if rank <= 1000:
                    analysis.estimated_monthly_sales = int(500 * (1000 / rank) ** 0.5)
                elif rank <= 10000:
                    analysis.estimated_monthly_sales = int(200 * (10000 / rank) ** 0.6)
                elif rank <= 100000:
                    analysis.estimated_monthly_sales = int(50 * (100000 / rank) ** 0.7)
                elif rank <= 500000:
                    analysis.estimated_monthly_sales = int(10 * (500000 / rank) ** 0.8)
                else:
                    analysis.estimated_monthly_sales = max(1, int(5 * (1000000 / rank)))

            # Count rank drops in 30 days (approximates sales)
            # Each significant rank drop typically indicates a sale
            if csv_data and len(csv_data) > 3:  # Sales rank is index 3
                rank_history = csv_data[3] if len(csv_data) > 3 else []
                if rank_history:
                    drops = 0
                    for i in range(2, len(rank_history), 2):  # Every other is value
                        if i + 2 < len(rank_history):
                            if rank_history[i] > 0 and rank_history[i + 2] > 0:
                                if rank_history[i + 2] < rank_history[i]:  # Rank improved
                                    drops += 1
                    analysis.sales_rank_drops_30d = drops

            # === SELLER COMPETITION ===
            # Offer counts
            offer_counts = product.get("offerCountNew", 0)
            offer_counts_fba = product.get("offerCountFBA", 0)
            analysis.fba_seller_count = offer_counts_fba if offer_counts_fba else 0
            analysis.fbm_seller_count = max(0, (offer_counts or 0) - analysis.fba_seller_count)

            # Check if Amazon is selling
            if csv_data and len(csv_data) > 0:
                amazon_prices = csv_data[0]  # Index 0 is Amazon price
                if amazon_prices:
                    # Check last few entries for Amazon presence
                    recent_amazon = amazon_prices[-2] if len(amazon_prices) >= 2 else -1
                    if recent_amazon > 0:
                        analysis.amazon_on_listing = True

            # Buy box price
            if stats and "buyBoxPrice" in stats:
                bb = stats["buyBoxPrice"]
                if bb and bb > 0:
                    analysis.buy_box_price = bb / 100.0

        except Exception as e:
            logger.error(f"[KEEPA] Error analyzing product {asin}: {e}")
            analysis.flags.append(f"PARSE_ERROR: {str(e)[:50]}")

        # Calculate final flip score
        analysis.calculate_flip_score()

        return analysis

    async def analyze_and_filter_deals(
        self,
        deals: List[PriceDrop],
        min_flip_score: int = 50,
    ) -> List[Tuple[PriceDrop, ProductAnalysis]]:
        """
        Analyze a list of deals and filter by flip score.

        Args:
            deals: List of PriceDrop objects to analyze
            min_flip_score: Minimum flip score to include (default 50)

        Returns:
            List of (PriceDrop, ProductAnalysis) tuples for deals that pass
        """
        results = []

        for deal in deals:
            analysis = await self.analyze_product(deal.asin)

            if analysis.flip_score >= min_flip_score:
                results.append((deal, analysis))
                logger.info(f"[KEEPA] ✓ {deal.asin} - Score {analysis.flip_score}: {analysis.recommendation}")
            else:
                logger.debug(f"[KEEPA] ✗ {deal.asin} - Score {analysis.flip_score}: {analysis.recommendation} - {analysis.flags}")

        return results

    # ========================================================
    # GATING CHECK (Amazon SP-API)
    # ========================================================

    async def check_gating(self, asin: str) -> Tuple[bool, str]:
        """
        Check if seller is gated/restricted from selling this ASIN.

        Uses Amazon SP-API Listings Restrictions endpoint.
        Requires SP-API credentials to be configured.

        Returns:
            (is_gated: bool, reason: str)
        """
        if not SP_API_REFRESH_TOKEN or not SP_API_CLIENT_ID:
            return (None, "SP-API not configured")

        try:
            # Get access token
            token_url = "https://api.amazon.com/auth/o2/token"
            token_data = {
                "grant_type": "refresh_token",
                "refresh_token": SP_API_REFRESH_TOKEN,
                "client_id": SP_API_CLIENT_ID,
                "client_secret": SP_API_CLIENT_SECRET,
            }

            async with httpx.AsyncClient() as client:
                token_response = await client.post(token_url, data=token_data)
                if token_response.status_code != 200:
                    return (None, "Failed to get access token")

                access_token = token_response.json().get("access_token")

                # Check listing restrictions
                restrictions_url = f"https://sellingpartnerapi-na.amazon.com/listings/2021-08-01/restrictions"
                params = {
                    "asin": asin,
                    "sellerId": os.getenv("SP_API_SELLER_ID", ""),
                    "marketplaceIds": SP_API_MARKETPLACE_ID,
                    "conditionType": "new_new",
                }
                headers = {
                    "x-amz-access-token": access_token,
                    "Content-Type": "application/json",
                }

                response = await client.get(restrictions_url, params=params, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    restrictions = data.get("restrictions", [])

                    if not restrictions:
                        return (False, "Ungated - OK to sell")

                    # Check restriction types
                    for r in restrictions:
                        if r.get("conditionType") == "new_new":
                            reasons = r.get("reasons", [])
                            if reasons:
                                reason_codes = [rr.get("reasonCode", "") for rr in reasons]
                                if "APPROVAL_REQUIRED" in reason_codes:
                                    return (True, "Approval required")
                                elif "ASIN_NOT_FOUND" in reason_codes:
                                    return (None, "ASIN not found")
                            return (True, "Restricted")

                    return (False, "Ungated")
                else:
                    return (None, f"API error: {response.status_code}")

        except Exception as e:
            logger.error(f"[SP-API] Gating check error for {asin}: {e}")
            return (None, f"Error: {str(e)[:50]}")

    # ========================================================
    # HELPERS
    # ========================================================

    def _domain_to_id(self, domain: str) -> int:
        """Convert domain string to Keepa domain ID"""
        domains = {
            "US": 1, "GB": 2, "DE": 3, "FR": 4, "JP": 5,
            "CA": 6, "IT": 8, "ES": 9, "IN": 10, "MX": 11,
        }
        return domains.get(domain.upper(), 1)
    
    def _datetime_to_keepa_time(self, dt: datetime) -> int:
        """Convert datetime to Keepa time format (minutes since 2011-01-01)"""
        keepa_epoch = datetime(2011, 1, 1)
        delta = dt - keepa_epoch
        return int(delta.total_seconds() / 60)
    
    def get_stats(self) -> Dict:
        """Get tracker statistics"""
        # Get top brands by product count
        top_brands = sorted(
            [(brand, len(asins)) for brand, asins in self.tracked_brands.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]

        return {
            **self.stats,
            "tracked_products": len(self.tracked_products),
            "tracked_brands": len(self.tracked_brands),
            "top_brands": top_brands,
            "last_check": self.stats["last_check"].isoformat() if self.stats["last_check"] else None,
        }


# ============================================================
# DISCORD ALERTS
# ============================================================

async def send_discord_alert(
    drop: PriceDrop,
    analysis: Optional[ProductAnalysis] = None,
    skip_dedup: bool = False,
    source: str = "",
) -> bool:
    """
    Send Discord webhook for a price drop.

    Args:
        drop: The price drop to alert on
        analysis: Optional product analysis to include
        skip_dedup: If True, skip deduplication check
        source: Optional source label (e.g., "🔥 OPEN DISCOVERY")

    Returns:
        True if alert was sent, False if skipped/failed
    """
    if not DISCORD_WEBHOOK_URL:
        return False

    # Check deduplication
    dedup = get_deduplicator()
    if not skip_dedup and not dedup.should_alert(drop.asin):
        logger.info(f"[KEEPA] Skipping duplicate alert for {drop.asin}")
        return False

    # Color based on analysis score or profit
    if analysis and analysis.flip_score >= 75:
        color = 0x00FF00  # Bright green for STRONG BUY
    elif analysis and analysis.flip_score >= 60:
        color = 0x00FF88  # Green for BUY
    elif drop.profit_potential >= 10:
        color = 0xFFAA00  # Orange for decent profit
    else:
        color = 0xFFFF00  # Yellow for marginal

    # Build fields list
    fields = [
        {"name": "Current Price", "value": f"${drop.current_price:.2f}", "inline": True},
        {"name": "Target Price", "value": f"${drop.target_price:.2f}", "inline": True},
        {"name": "Est. Profit", "value": f"${drop.profit_potential:.2f}", "inline": True},
    ]

    # Add analysis fields if available
    if analysis:
        fields.extend([
            {"name": "Flip Score", "value": f"{analysis.flip_score}/100", "inline": True},
            {"name": "Monthly Sales", "value": f"~{analysis.estimated_monthly_sales}", "inline": True},
            {"name": "3P Sellers", "value": f"{analysis.fba_seller_count} FBA / {analysis.fbm_seller_count} FBM", "inline": True},
        ])

        if analysis.avg_price_90d > 0:
            fields.append({"name": "90d Avg Price", "value": f"${analysis.avg_price_90d:.2f}", "inline": True})

        if analysis.flags:
            fields.append({"name": "Flags", "value": ", ".join(analysis.flags), "inline": False})

        title_prefix = f"{'🟢' if analysis.flip_score >= 75 else '🟡' if analysis.flip_score >= 60 else '🟠'} {analysis.recommendation}"
    else:
        title_prefix = source if source else "🔥 Price Drop"
        fields.extend([
            {"name": "Drop %", "value": f"{drop.drop_percent:.1f}%", "inline": True},
            {"name": "Sales Rank", "value": f"{drop.sales_rank:,}", "inline": True},
        ])

    embed = {
        "title": f"{title_prefix}: ${drop.current_price:.2f}",
        "description": drop.title[:200],
        "url": drop.amazon_url,
        "color": color,
        "fields": fields,
        "thumbnail": {"url": drop.image_url} if drop.image_url else None,
        "footer": {"text": f"ASIN: {drop.asin}"},
        "timestamp": drop.timestamp.isoformat(),
    }

    payload = {
        "username": "Keepa Tracker",
        "embeds": [embed],
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10.0)
            if response.status_code in (200, 204):
                # Mark as alerted AFTER successful send
                dedup.mark_alerted(drop.asin)
                logger.info(f"[KEEPA] Discord alert sent for {drop.asin}")
                return True
    except Exception as e:
        logger.error(f"[KEEPA] Discord error: {e}")

    return False


async def send_brand_opportunity_alert(opportunity: Dict) -> bool:
    """
    Send Discord webhook for a brand-based opportunity.

    Returns:
        True if alert was sent, False if skipped/failed
    """
    if not DISCORD_WEBHOOK_URL:
        return False

    # Check deduplication
    dedup = get_deduplicator()
    asin = opportunity.get('asin', '')
    if not dedup.should_alert(asin):
        logger.info(f"[KEEPA] Skipping duplicate brand alert for {asin}")
        return False

    # Purple color for brand-based opportunities
    color = 0x9B59B6

    embed = {
        "title": f"🏷️ Brand Opportunity: ${opportunity['current_price']:.2f}",
        "description": opportunity['title'][:200],
        "url": opportunity['amazon_url'],
        "color": color,
        "fields": [
            {"name": "Current Price", "value": f"${opportunity['current_price']:.2f}", "inline": True},
            {"name": "Est. Sell Price", "value": f"${opportunity['estimated_sell_price']:.2f}", "inline": True},
            {"name": "Est. Profit", "value": f"${opportunity['estimated_profit']:.2f}", "inline": True},
            {"name": "Brand", "value": opportunity['brand'].title(), "inline": True},
            {"name": "Sales Rank", "value": f"{opportunity['sales_rank']:,}", "inline": True},
            {"name": "Category", "value": opportunity['category'], "inline": True},
        ],
        "footer": {"text": f"ASIN: {asin} | {opportunity['reason']}"},
        "timestamp": datetime.now().isoformat(),
    }

    payload = {
        "username": "Keepa Tracker",
        "embeds": [embed],
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10.0)
            if response.status_code in (200, 204):
                # Mark as alerted AFTER successful send
                dedup.mark_alerted(asin)
                logger.info(f"[KEEPA] Brand opportunity alert sent for {asin}")
                return True
    except Exception as e:
        logger.error(f"[KEEPA] Discord error: {e}")

    return False


async def send_smart_deal_alert(score: 'DealScore', skip_dedup: bool = False) -> bool:
    """
    Send Discord webhook for a smart-analyzed deal.

    Uses the DealScore from deal_analyzer.py to create rich alerts
    with scoring breakdown and analysis reasons.

    Args:
        score: DealScore object from DealAnalyzer
        skip_dedup: If True, skip deduplication check

    Returns:
        True if alert was sent, False if skipped/failed
    """
    if not DISCORD_WEBHOOK_URL:
        return False

    # Check deduplication
    dedup = get_deduplicator()
    if not skip_dedup and not dedup.should_alert(score.asin):
        logger.info(f"[SMART] Skipping duplicate alert for {score.asin}")
        return False

    # Color based on score
    if score.total_score >= 75:
        color = 0x00FF00  # Bright green for STRONG BUY
        emoji = "🟢"
    elif score.total_score >= 60:
        color = 0x00FF88  # Green for BUY
        emoji = "🟡"
    elif score.total_score >= 45:
        color = 0xFFAA00  # Orange for RESEARCH
        emoji = "🟠"
    else:
        color = 0xFF6B6B  # Red for PASS
        emoji = "🔴"

    # Build score breakdown string
    breakdown_parts = []
    for key, value in score.score_breakdown.items():
        name = key.replace("_", " ").title()
        breakdown_parts.append(f"{name}: {value}")
    breakdown_str = " | ".join(breakdown_parts)

    # Build fields
    fields = [
        {"name": "💰 Buy Price", "value": f"${score.current_price:.2f}", "inline": True},
        {"name": "📈 Sell Price", "value": f"${score.sell_price:.2f}", "inline": True},
        {"name": "💵 Est. Profit", "value": f"${score.estimated_profit:.2f}", "inline": True},
        {"name": "📊 Score", "value": f"**{score.total_score}/100**", "inline": True},
        {"name": "📉 ROI", "value": f"{score.roi_percent:.1f}%", "inline": True},
        {"name": "🛒 Monthly Sales", "value": f"~{score.estimated_monthly_sales}", "inline": True},
    ]

    # Price analysis
    if score.price_drop_percent > 0:
        fields.append({"name": "⬇️ Price Drop", "value": f"{score.price_drop_percent:.1f}% below 90d avg", "inline": True})

    # Amazon competition
    if score.amazon_is_competing:
        fields.append({"name": "⚠️ Amazon", "value": "Competing", "inline": True})
    else:
        fields.append({"name": "✅ Amazon", "value": "Not competing", "inline": True})

    # Score breakdown
    fields.append({"name": "📋 Score Breakdown", "value": f"`{breakdown_str}`", "inline": False})

    # Top reasons (limit to 3)
    if score.reasons:
        reasons_str = "\n".join([f"• {r}" for r in score.reasons[:4]])
        fields.append({"name": "📝 Analysis", "value": reasons_str, "inline": False})

    # Flags/warnings
    if score.flags:
        flags_str = ", ".join([f"⚠️ {f}" for f in score.flags])
        fields.append({"name": "🚩 Flags", "value": flags_str, "inline": False})

    embed = {
        "title": f"{emoji} {score.recommendation}: ${score.current_price:.2f}",
        "description": f"**{score.title[:150]}**" if score.title else f"ASIN: {score.asin}",
        "url": f"https://www.amazon.com/dp/{score.asin}",
        "color": color,
        "fields": fields,
        "footer": {"text": f"ASIN: {score.asin} | Smart Deal Analyzer"},
        "timestamp": datetime.now().isoformat(),
    }

    payload = {
        "username": "Smart Deal Analyzer",
        "embeds": [embed],
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10.0)
            if response.status_code in (200, 204):
                dedup.mark_alerted(score.asin)
                logger.info(f"[SMART] Discord alert sent for {score.asin} (Score: {score.total_score})")
                return True
    except Exception as e:
        logger.error(f"[SMART] Discord error: {e}")

    return False


# ============================================================
# WEBHOOK RECEIVER (For Keepa push notifications)
# ============================================================

async def handle_keepa_webhook(payload: Dict) -> Dict:
    """
    Handle incoming webhook from Keepa
    
    Keepa will POST here when a tracking is triggered.
    This endpoint should be added to main.py
    """
    logger.info(f"[KEEPA WEBHOOK] Received notification")
    
    try:
        asin = payload.get("asin", "")
        current_price = payload.get("currentPrice", 0) / 100.0
        threshold = payload.get("thresholdValue", 0) / 100.0
        
        # Create a price drop alert
        drop = PriceDrop(
            asin=asin,
            title=payload.get("title", "Unknown"),
            current_price=current_price,
            previous_price=0,  # Not provided in webhook
            target_price=threshold,
            drop_percent=0,
            sales_rank=payload.get("salesRank", 0),
            category="",
            image_url="",
            amazon_url=f"https://www.amazon.com/dp/{asin}",
        )
        
        # Send to Discord
        await send_discord_alert(drop)
        
        return {"status": "ok", "asin": asin}
        
    except Exception as e:
        logger.error(f"[KEEPA WEBHOOK] Error: {e}")
        return {"status": "error", "message": str(e)}


# ============================================================
# BACKGROUND MONITOR
# ============================================================

_client: Optional[KeepaClientV2] = None
_monitor_task: Optional[asyncio.Task] = None


async def start_deals_monitor(
    csv_path: str = "asin-tracker-tasks-export.csv",
    check_interval: int = 300,  # 5 minutes
    enable_brand_monitoring: bool = True,  # Also check deals from tracked brands
    brand_check_interval: int = 3,  # Check brands every N cycles
    enable_open_discovery: bool = True,  # Find ANY profitable deals
    open_discovery_interval: int = 2,  # Check open discovery every N cycles
    enable_analysis: bool = True,  # Perform detailed analysis before alerting
    min_flip_score: int = 50,  # Minimum flip score to alert (if analysis enabled)
):
    """
    Start background monitoring using Deals API

    This checks the Deals API periodically and alerts on matches.
    Much more efficient than polling individual ASINs!

    Features:
    - Deduplication: Each ASIN only alerted once per 24 hours
    - Analysis: Optional detailed product analysis before alerting
    - Brand monitoring: Find deals from tracked brands
    """
    global _client

    _client = KeepaClientV2()
    _client.load_tracked_products_csv(csv_path)

    # Save brands list for reference
    _client.save_tracked_brands()

    # Initialize deduplicator
    dedup = get_deduplicator()

    logger.info(f"[KEEPA] Starting deals monitor (every {check_interval}s)")
    logger.info(f"[KEEPA] Tracking {len(_client.tracked_products)} products from {len(_client.tracked_brands)} brands")
    logger.info(f"[KEEPA] Analysis: {'ENABLED' if enable_analysis else 'DISABLED'}, Min flip score: {min_flip_score}")
    logger.info(f"[KEEPA] Deduplication: {dedup.get_stats()}")

    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            alerts_sent = 0
            alerts_skipped = 0

            # Check deals against our tracked ASIN list
            matches = await _client.check_deals_against_tracked()

            # Filter and send alerts
            for drop in matches:
                analysis = None

                if enable_analysis:
                    # Perform detailed analysis
                    analysis = await _client.analyze_product(drop.asin)

                    # Skip if flip score too low
                    if analysis.flip_score < min_flip_score:
                        logger.info(f"[KEEPA] Skipping {drop.asin} - Flip score {analysis.flip_score} < {min_flip_score}")
                        alerts_skipped += 1
                        continue

                # Send alert (deduplication handled inside)
                if await send_discord_alert(drop, analysis):
                    alerts_sent += 1
                    _client.stats["alerts_sent"] += 1
                else:
                    alerts_skipped += 1

            # Every N cycles, also check brand-based opportunities
            brand_alerts_sent = 0
            if enable_brand_monitoring and cycle_count % brand_check_interval == 0:
                brand_opportunities = await _client.check_deals_by_brand(
                    min_profit=25.0,  # Raised from $5 - brand opportunities need real margin
                    max_sales_rank=300000,  # Expanded from 150K
                )

                # Send alerts for brand opportunities (limit to top 5 to avoid spam)
                for opp in brand_opportunities[:5]:
                    if await send_brand_opportunity_alert(opp):
                        brand_alerts_sent += 1

            # Open Discovery - Find ANY profitable deal (40%+ discount)
            open_discovery_sent = 0
            if enable_open_discovery and cycle_count % open_discovery_interval == 0:
                open_deals = await _client.check_open_discovery_deals(
                    min_discount_pct=40.0,  # 40% minimum discount
                    min_profit=5.0,
                    max_sales_rank=500000,
                    price_range=(1000, 10000),  # $10-$100
                )

                # Send alerts for open discovery (limit to top 5)
                dedup = get_deduplicator()
                for deal in open_deals[:5]:
                    asin = deal["asin"]
                    if dedup.should_alert(asin):
                        # Create PriceDrop for alert
                        price_drop = PriceDrop(
                            asin=asin,
                            title=deal["title"],
                            current_price=deal["current_price"],
                            previous_price=deal["previous_price"],
                            target_price=deal["estimated_sell_price"],
                            drop_percent=deal["discount_pct"],
                            sales_rank=deal["sales_rank"],
                            category=deal["category"],
                            image_url="",
                            amazon_url=deal["amazon_url"],
                            product_category=deal["category"],
                        )
                        if await send_discord_alert(price_drop, source="🔥 OPEN DISCOVERY"):
                            dedup.mark_alerted(asin)
                            open_discovery_sent += 1

            logger.info(
                f"[KEEPA] Cycle {cycle_count}: "
                f"{len(matches)} matches, {alerts_sent} sent, {alerts_skipped} skipped"
                + (f", {brand_alerts_sent} brand alerts" if brand_alerts_sent else "")
                + (f", {open_discovery_sent} discovery alerts" if open_discovery_sent else "")
            )

        except Exception as e:
            logger.error(f"[KEEPA] Monitor error: {e}")

        await asyncio.sleep(check_interval)


async def stop_monitor():
    """Stop background monitoring"""
    global _monitor_task
    if _monitor_task:
        _monitor_task.cancel()
        _monitor_task = None
        logger.info("[KEEPA] Monitor stopped")


def get_client() -> Optional[KeepaClientV2]:
    """Get the current client instance"""
    return _client


# ============================================================
# CLI TESTING
# ============================================================

async def test_keepa_v2():
    """Test the new Keepa integration"""
    print("\n=== Keepa Tracker V2 Test ===\n")
    
    if not KEEPA_API_KEY:
        print("ERROR: KEEPA_API_KEY not set")
        return
    
    client = KeepaClientV2()
    
    # Test deals API
    print("Testing Deals API...")
    deals = await client.get_deals(
        delta_percent_range=(30, 100),
        delta_last_hours=24,
    )
    print(f"Found {len(deals)} deals in last 24h with 30%+ drop")
    
    if deals:
        deal = deals[0]
        print(f"\nSample deal:")
        print(f"  ASIN: {deal.get('asin')}")
        print(f"  Sales Rank: {deal.get('salesRank')}")
    
    print(f"\nStats: {client.get_stats()}")


if __name__ == "__main__":
    asyncio.run(test_keepa_v2())
