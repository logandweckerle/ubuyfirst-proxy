"""
Unified Listing Adapter - Normalizes both uBuyFirst and Direct API data

This module provides a single normalization layer so both data sources
feed into the analysis pipeline with identical format.

ARCHITECTURE:
    uBuyFirst Webhook ─┐
                       ├─► StandardizedListing ─► Analysis Pipeline
    Direct eBay API ───┘

FIELD MAPPING:
    StandardizedListing     uBuyFirst           Direct API (EbayListing)
    ─────────────────────   ─────────────────   ─────────────────────────
    item_id                 ItemId              item_id
    title                   Title               title
    price                   TotalPrice ($X.XX)  price (float)
    category                Alias               (detected from title)
    images                  images[]            (fetched via get_item_details)
    description             Description         (fetched via get_item_details)
    gallery_url             GalleryURL          gallery_url/thumbnail_url
    view_url                ViewUrl             view_url
    seller_id               SellerUserID        seller_id
    seller_feedback         FeedbackScore       seller_feedback
    posted_time             PostedTime          start_time
    condition               Condition           condition
    source                  (set to 'ubuyfirst') (set to 'ebay_api')
    weight_from_specifics   -                   (from item specifics)
    metal_from_specifics    -                   (from item specifics)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import unquote

logger = logging.getLogger("listing_adapter")

# ============================================================
# STANDARDIZED LISTING MODEL
# ============================================================

@dataclass
class StandardizedListing:
    """
    Unified listing format for the analysis pipeline.
    Both uBuyFirst and Direct API normalize to this format.
    """
    # Core identifiers
    item_id: str
    title: str
    price: float

    # Category (gold, silver, tcg, lego, videogames, costume)
    category: str

    # Images - list of full-size URLs for AI analysis
    images: List[str] = field(default_factory=list)

    # Description text (for weight extraction)
    description: str = ""

    # URLs
    gallery_url: str = ""  # Thumbnail
    view_url: str = ""     # Link to eBay listing

    # Seller info
    seller_id: str = ""
    seller_feedback: int = 0
    seller_type: str = ""
    seller_score: int = 50
    seller_priority: str = "NORMAL"

    # Timing
    posted_time: Optional[datetime] = None

    # Condition
    condition: str = ""

    # Source tracking
    source: str = ""  # 'ubuyfirst' or 'ebay_api'

    # Item specifics (from eBay API)
    weight_from_specifics: str = ""
    metal_from_specifics: str = ""
    purity_from_specifics: str = ""

    # Original raw data (for debugging)
    raw_data: Dict = field(default_factory=dict)

    def to_pipeline_dict(self) -> Dict[str, Any]:
        """
        Convert to the dict format expected by match_mydata analysis pipeline.
        This is the canonical format that both sources produce.
        """
        result = {
            # Core fields
            "ItemId": self.item_id,
            "Title": self.title,
            "TotalPrice": f"${self.price:.2f}",
            "price": self.price,

            # Category
            "Alias": self.category,

            # Images (critical for scale photo analysis)
            "images": self.images,

            # Description (for weight extraction)
            "Description": self.description,

            # URLs
            "GalleryURL": self.gallery_url,
            "ViewUrl": self.view_url,

            # Seller info
            "SellerUserID": self.seller_id,
            "FeedbackScore": str(self.seller_feedback) if self.seller_feedback else "",
            "SellerType": self.seller_type,
            "SellerScore": self.seller_score,
            "SellerPriority": self.seller_priority,

            # Condition
            "Condition": self.condition,

            # Source tracking
            "source": self.source,

            # Request JSON response for full analysis details
            "response_type": "json",
        }

        # Add posted time if available
        if self.posted_time:
            try:
                result["PostedTime"] = self.posted_time.strftime('%m/%d/%Y %I:%M:%S %p')
            except:
                pass

        # Add item specifics if available (API-sourced)
        if self.weight_from_specifics:
            result["Weight"] = self.weight_from_specifics
        if self.metal_from_specifics:
            result["Metal"] = self.metal_from_specifics
        if self.purity_from_specifics:
            result["MetalPurity"] = self.purity_from_specifics

        return result


# ============================================================
# CATEGORY DETECTION
# ============================================================

# Keywords for category detection (used when Alias not provided)
# Order matters - more specific categories first
CATEGORY_KEYWORDS = {
    # TCG first (before 'gold' catches 'pokemon gold')
    'tcg': [
        # Pokemon keywords
        'pokemon', 'pokémon', 'pikachu', 'charizard', 'mewtwo',
        'booster box', 'booster pack', 'etb', 'elite trainer',
        'prismatic', 'evolutions', 'scarlet violet', 'sv8', 'sv7', 'sv6',
        'surging sparks', 'stellar crown', 'paldea evolved', 'obsidian flames',
        'crown zenith', 'hidden fates', 'celebrations', 'evolving skies',
        # MTG keywords
        'mtg', 'magic the gathering', 'magic: the gathering',
        'modern horizons', 'commander masters', 'double masters',
        'collector booster', 'draft booster', 'set booster',
        # Yu-Gi-Oh keywords
        'yugioh', 'yu-gi-oh', 'konami',
        # Generic TCG
        'tcg', 'trading card game', 'sealed box', 'factory sealed',
    ],
    'lego': ['lego', 'legoland', 'lego set', 'lego star wars', 'lego technic'],
    'videogames': [
        'ps5', 'ps4', 'ps3', 'ps2', 'playstation', 'xbox', 'xbox one', 'xbox 360',
        'nintendo', 'switch', 'wii u', 'wii ', 'gamecube', 'n64',
        'super nintendo', 'snes ', 'nes ', ' nes', 'famicom',
        'game boy', 'gameboy', 'nintendo ds', '3ds', 'ps vita', 'psp',
        'video game', 'videogame',
    ],
    # Precious metals last (most common default)
    'gold': [
        'gold', '14k', '10k', '18k', '22k', '24k', '8k', '9k',
        '585', '750', '417', '375', '916', '583', 'karat', '14kt', '18kt',
    ],
    'silver': [
        'sterling', 'silver', '925', '800', '830', '900',
        'coin silver', 'mexican silver', 'navajo', '.925',
        # Well-known sterling flatware makers (CRITICAL for pattern-name-only listings)
        'gorham', 'wallace', 'reed & barton', 'reed barton', 'alvin', 'durgin',
        'international silver', 'towle', 'lunt', 'kirk', 'stieff', 'oneida',
        'whiting', 'tiffany & co', 'georg jensen', 'christofle',
    ],
}

def detect_category(title: str, description: str = "") -> str:
    """
    Detect category from title and description.
    Returns: 'gold', 'silver', 'tcg', 'lego', 'videogames', or 'costume'
    """
    text = f"{title} {description}".lower()

    # Check each category's keywords
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return category

    # Default to costume jewelry if no match
    return 'costume'


# ============================================================
# UBUYFIRST ADAPTER
# ============================================================

def normalize_ubuyfirst(data: Dict[str, Any]) -> StandardizedListing:
    """
    Normalize uBuyFirst webhook data to StandardizedListing.

    uBuyFirst sends:
        - Title: string
        - TotalPrice: "$123.45" format
        - ItemId: string
        - GalleryURL: thumbnail URL
        - images: list of full image URLs
        - Alias: category string (gold, silver, etc.)
        - Description: full text
        - ViewUrl: eBay listing URL
        - SellerUserID: seller username
        - FeedbackScore: string
        - PostedTime: "MM/DD/YYYY HH:MM:SS AM/PM" format
        - Condition: string
    """
    # Extract price (handle "$123.45" format)
    price_str = data.get('TotalPrice', data.get('price', '0'))
    if isinstance(price_str, str):
        price = float(re.sub(r'[^\d.]', '', price_str) or 0)
    else:
        price = float(price_str or 0)

    # Get category from Alias or detect from title
    category = data.get('Alias', '').lower().strip()
    if not category:
        category = detect_category(data.get('Title', ''), data.get('Description', ''))

    # Parse posted time
    posted_time = None
    posted_str = data.get('PostedTime', '')
    if posted_str:
        try:
            # uBuyFirst format: "01/07/2026 10:30:45 AM"
            posted_time = datetime.strptime(posted_str, '%m/%d/%Y %I:%M:%S %p')
        except:
            try:
                # Try ISO format
                posted_time = datetime.fromisoformat(posted_str.replace('Z', '+00:00'))
            except:
                pass

    # Get images - uBuyFirst provides full URLs
    images = data.get('images', [])
    if not images:
        # Fallback to gallery URL
        gallery = data.get('GalleryURL', data.get('galleryURL', data.get('PictureURL', '')))
        if gallery:
            images = [gallery]

    # Parse seller feedback
    feedback = 0
    feedback_str = data.get('FeedbackScore', '')
    if feedback_str:
        try:
            feedback = int(feedback_str)
        except:
            pass

    # URL decode title if needed (uBuyFirst sometimes URL-encodes)
    title = data.get('Title', '')
    if '%' in title:
        try:
            title = unquote(title)
        except:
            pass

    return StandardizedListing(
        item_id=data.get('ItemId', data.get('itemId', '')),
        title=title,
        price=price,
        category=category,
        images=images,
        description=data.get('Description', ''),
        gallery_url=data.get('GalleryURL', data.get('galleryURL', '')),
        view_url=data.get('ViewUrl', data.get('viewUrl', '')),
        seller_id=data.get('SellerUserID', data.get('sellerUserID', '')),
        seller_feedback=feedback,
        posted_time=posted_time,
        condition=data.get('Condition', ''),
        source='ubuyfirst',
        raw_data=data,
    )


# ============================================================
# DIRECT API ADAPTER
# ============================================================

async def normalize_api_listing(listing, fetch_details: bool = True) -> StandardizedListing:
    """
    Normalize Direct eBay API EbayListing to StandardizedListing.

    EbayListing (from ebay_poller.py) has:
        - item_id: string
        - title: string
        - price: float
        - thumbnail_url / gallery_url: thumbnail only
        - view_url: eBay listing URL
        - seller_id: seller username
        - seller_feedback: int
        - start_time: datetime
        - condition: string
        - category_name: string
        - seller_score, seller_type, seller_priority: profile data

    CRITICAL: API listings only have thumbnails by default.
    We must call get_item_details() to fetch full images and description.
    """
    # Import here to avoid circular imports
    from ebay_poller import get_item_details

    # Start with basic data from EbayListing
    item_id = listing.item_id if hasattr(listing, 'item_id') else ''
    title = listing.title if hasattr(listing, 'title') else ''
    price = listing.price if hasattr(listing, 'price') else 0.0

    # Detect category from title (API doesn't provide Alias)
    category = detect_category(title)

    # Default to thumbnail
    images = []
    thumbnail = listing.thumbnail_url if hasattr(listing, 'thumbnail_url') else ''
    if not thumbnail:
        thumbnail = listing.gallery_url if hasattr(listing, 'gallery_url') else ''

    description = ''
    weight_specific = ''
    metal_specific = ''
    purity_specific = ''

    # CRITICAL: Fetch full images and description from eBay API
    if fetch_details and item_id:
        try:
            details = await get_item_details(item_id)
            if details:
                # Full image URLs (for scale photo analysis)
                if details.get('images'):
                    images = details['images']
                    logger.info(f"[ADAPTER] Fetched {len(images)} images for {item_id}")

                # Description (for weight extraction)
                if details.get('description'):
                    description = details['description']

                # Item specifics
                specifics = details.get('specifics', {})
                for key, value in specifics.items():
                    key_lower = key.lower()
                    if 'weight' in key_lower:
                        weight_specific = value
                    elif 'metal' in key_lower:
                        metal_specific = value
                    elif 'purity' in key_lower or 'fineness' in key_lower:
                        purity_specific = value
        except Exception as e:
            logger.warning(f"[ADAPTER] Could not fetch details for {item_id}: {e}")

    # Fallback to thumbnail if no full images fetched
    if not images and thumbnail:
        images = [thumbnail]

    return StandardizedListing(
        item_id=item_id,
        title=title,
        price=price,
        category=category,
        images=images,
        description=description,
        gallery_url=thumbnail,
        view_url=listing.view_url if hasattr(listing, 'view_url') else '',
        seller_id=listing.seller_id if hasattr(listing, 'seller_id') else '',
        seller_feedback=listing.seller_feedback if hasattr(listing, 'seller_feedback') else 0,
        seller_type=listing.seller_type if hasattr(listing, 'seller_type') else '',
        seller_score=listing.seller_score if hasattr(listing, 'seller_score') else 50,
        seller_priority=listing.seller_priority if hasattr(listing, 'seller_priority') else 'NORMAL',
        posted_time=listing.start_time if hasattr(listing, 'start_time') else None,
        condition=listing.condition if hasattr(listing, 'condition') else '',
        source='ebay_api',
        weight_from_specifics=weight_specific,
        metal_from_specifics=metal_specific,
        purity_from_specifics=purity_specific,
        raw_data=listing.to_dict() if hasattr(listing, 'to_dict') else {},
    )


# ============================================================
# UNIFIED ENTRY POINT
# ============================================================

async def normalize_listing(data: Any, source_hint: str = None) -> StandardizedListing:
    """
    Unified normalization - auto-detects source and normalizes.

    Args:
        data: Either a dict (uBuyFirst) or EbayListing object (API)
        source_hint: Optional hint ('ubuyfirst' or 'ebay_api')

    Returns:
        StandardizedListing ready for analysis pipeline
    """
    # Detect source type
    if source_hint == 'ebay_api' or hasattr(data, 'item_id'):
        # It's an EbayListing object from the API
        return await normalize_api_listing(data)
    elif source_hint == 'ubuyfirst' or isinstance(data, dict):
        # It's a dict from uBuyFirst webhook
        return normalize_ubuyfirst(data)
    else:
        raise ValueError(f"Unknown listing source type: {type(data)}")


# ============================================================
# VALIDATION
# ============================================================

def validate_listing(listing: StandardizedListing) -> List[str]:
    """
    Validate a standardized listing and return list of issues.
    Empty list = valid listing.
    """
    issues = []

    if not listing.item_id:
        issues.append("Missing item_id")
    if not listing.title:
        issues.append("Missing title")
    if listing.price <= 0:
        issues.append(f"Invalid price: {listing.price}")
    if not listing.category:
        issues.append("Missing category")

    # Warn if API listing has no images (can't analyze scale photos)
    if listing.source == 'ebay_api' and not listing.images:
        issues.append("API listing has no images - cannot analyze scale photos")

    return issues
