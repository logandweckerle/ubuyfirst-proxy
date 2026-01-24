"""
eBay Item Lookup Service

Provides functions to look up eBay items by title, seller, and price
using the Finding API and Browse API.

Extracted from main.py for better organization.
"""

import logging
import re
import urllib.parse
from typing import Optional
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

# Module configuration (set by configure_ebay_lookup)
_config = {
    "ebay_app_id": None,
    "http_client": None,  # Shared httpx client for connection pooling
}


def configure_ebay_lookup(ebay_app_id: str = None, http_client=None):
    """Configure the eBay lookup module with credentials and HTTP client."""
    if ebay_app_id:
        _config["ebay_app_id"] = ebay_app_id
    if http_client:
        _config["http_client"] = http_client


async def lookup_ebay_item(title: str, price: float = None) -> Optional[str]:
    """
    Look up an eBay item by title using the Finding API.
    Matches exact title and list price (not including shipping).
    Returns the viewItemURL if found, None otherwise.
    """
    ebay_app_id = _config.get("ebay_app_id")

    if not ebay_app_id:
        logger.debug("[EBAY] No App ID configured, skipping lookup")
        return None

    try:
        search_title = title.strip()

        api_url = "https://svcs.ebay.com/services/search/FindingService/v1"
        params = {
            "OPERATION-NAME": "findItemsByKeywords",
            "SERVICE-VERSION": "1.0.0",
            "SECURITY-APPNAME": ebay_app_id,
            "RESPONSE-DATA-FORMAT": "JSON",
            "REST-PAYLOAD": "",
            "keywords": search_title,
            "paginationInput.entriesPerPage": "3",
            "sortOrder": "StartTimeNewest"
        }

        # Use shared HTTP client if available (connection pooling)
        http_client = _config.get("http_client")
        if http_client:
            response = await http_client.get(api_url, params=params, timeout=5.0)
        else:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(api_url, params=params)

        if response.status_code != 200:
            logger.warning(f"[EBAY] API returned {response.status_code}")
            return None

        data = response.json()
        search_result = data.get("findItemsByKeywordsResponse", [{}])[0]

        if search_result.get("ack", [None])[0] != "Success":
            return None

        items = search_result.get("searchResult", [{}])[0].get("item", [])
        if not items:
            return None

        # Find best match by title and list price
        for item in items:
            item_title = item.get("title", [""])[0]
            view_url = item.get("viewItemURL", [None])[0]
            item_id = item.get("itemId", [None])[0]

            # Get list price (item price, not including shipping)
            selling_status = item.get("sellingStatus", [{}])[0]
            current_price = selling_status.get("currentPrice", [{}])[0]
            list_price = float(current_price.get("__value__", "0"))

            # Normalize titles for comparison (handle URL encoding from uBuyFirst)
            search_title_clean = unquote(title.replace('+', ' ')).strip().lower()
            item_title_clean = item_title.strip().lower()

            # Check title match (exact or contained)
            title_match = (search_title_clean == item_title_clean or
                          search_title_clean in item_title_clean or
                          item_title_clean in search_title_clean)

            if not title_match:
                continue

            # Check price match only if price is provided (within $0.02)
            if price is not None:
                if abs(list_price - price) < 0.02:
                    logger.info(f"[EBAY] [PASS] …EXACT: {item_id} @ ${list_price:.2f}")
                    return view_url

                # Title matched but price didn't - still return it
                logger.info(f"[EBAY] [PASS] …Title match: {item_id} @ ${list_price:.2f}")
                return view_url

            # No exact match - return first result
            logger.info(f"[EBAY] No exact match, using first result")
            return items[0].get("viewItemURL", [None])[0]

    except Exception as e:
        logger.error(f"[EBAY] Lookup error: {e}")
        return None


async def lookup_ebay_item_by_seller(title: str, seller_name: str, price: float = None) -> Optional[str]:
    """
    Look up an eBay item by seller name, title, and price.
    Uses Browse API (direct API) with seller filter - more reliable than Finding API.
    Returns the direct item URL (ebay.com/itm/ITEM_ID) if found, None otherwise.
    """
    if not seller_name:
        logger.debug("[EBAY] No seller name provided, falling back to title lookup")
        return await lookup_ebay_item(title, price)

    try:
        # Import ebay_poller functions lazily to avoid circular imports
        from ebay_poller import get_oauth_token, browse_api_available, BROWSE_API_URL

        # Clean up seller name and title (remove URL encoding)
        clean_seller = unquote(seller_name.replace('+', ' ')).strip().lower()
        clean_title = unquote(title.replace('+', ' ')).strip()

        logger.info(f"[EBAY] Looking up item by seller '{clean_seller}': {clean_title[:50]}...")

        # Smart keyword extraction for specific categories
        # For PSA/graded cards: extract key identifiers
        psa_match = re.search(r'PSA\s*(\d+)', clean_title, re.I)
        card_num_match = re.search(r'#(\d+)', clean_title)
        year_match = re.search(r'\b(19\d{2}|20\d{2})\b', clean_title)

        # For Pokemon: extract set name patterns
        pokemon_sets = ['Prismatic', 'Evolutions', 'Crown Zenith', 'Paldea', 'Obsidian', 'Scarlet', 'Violet', 'Base Set']

        # TRY BROWSE API FIRST (more reliable - Finding API often returns 500)
        if browse_api_available():
            token = await get_oauth_token()
            if token:
                logger.info(f"[EBAY] Using Browse API with seller filter...")

                # Build filter with seller filter - format: sellers:{seller_id}
                filters = [
                    "buyingOptions:{FIXED_PRICE}",
                    "itemLocationCountry:US",
                    f"sellers:{{{clean_seller}}}"
                ]

                # Add price filter if price is known (wider range for better matching)
                if price and price > 0:
                    price_min = price * 0.85
                    price_max = price * 1.15
                    filters.append(f"price:[{price_min:.2f}..{price_max:.2f}],priceCurrency:USD")

                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                }

                # Clean title for better search - remove problematic characters
                search_title = clean_title
                # Remove fractions and special chars that break search
                search_title = re.sub(r'[½¼¾⅓⅔⅛⅜⅝⅞°™®©]', '', search_title)
                search_title = re.sub(r'\d+/\d+', '', search_title)  # Remove fractions like 5/8
                search_title = re.sub(r'[^\w\s\-\.\#]', ' ', search_title)  # Keep # for card numbers
                search_title = re.sub(r'\s+', ' ', search_title).strip()

                # Smart keyword extraction based on item type
                if psa_match or 'pokemon' in clean_title.lower() or 'panini' in clean_title.lower():
                    # TCG/Sports cards: prioritize card number, year, player/character, grade
                    key_parts = []
                    if year_match:
                        key_parts.append(year_match.group(1))
                    if card_num_match:
                        key_parts.append(f"#{card_num_match.group(1)}")
                    if psa_match:
                        key_parts.append(f"PSA {psa_match.group(1)}")
                    # Add first 4 words (usually character/player name)
                    key_parts.extend(search_title.split()[:4])
                    keywords = ' '.join(key_parts[:8])
                    logger.debug(f"[EBAY] TCG keywords: {keywords}")
                else:
                    # Default: Use first 8 words
                    keywords = ' '.join(search_title.split()[:8])

                params = {
                    "q": keywords,
                    "sort": "newlyListed",
                    "limit": "25",
                    "filter": ",".join(filters),
                }

                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(BROWSE_API_URL, headers=headers, params=params)

                        if response.status_code == 200:
                            data = response.json()
                            items = data.get("itemSummaries", [])

                            if items:
                                logger.info(f"[EBAY] Browse API found {len(items)} items from seller '{clean_seller}'")

                                # Find exact or best title/price match
                                clean_title_lower = clean_title.lower()
                                best_match = None
                                best_score = 0

                                for item in items:
                                    item_title = item.get("title", "")
                                    item_id = item.get("itemId", "")
                                    item_url = item.get("itemWebUrl", "")

                                    # Get price
                                    item_price = 0
                                    price_info = item.get("price", {})
                                    try:
                                        item_price = float(price_info.get("value", 0))
                                    except:
                                        pass

                                    # Calculate title similarity score
                                    item_title_lower = item_title.lower()
                                    title_words = set(clean_title_lower.split())
                                    item_words = set(item_title_lower.split())
                                    word_overlap = len(title_words & item_words)

                                    # Score based on percentage of words matched
                                    # (prevents short titles from matching everything)
                                    if len(title_words) > 0:
                                        overlap_pct = word_overlap / len(title_words)
                                    else:
                                        overlap_pct = 0

                                    score = word_overlap

                                    # Bonus for high percentage overlap (>70% of words match)
                                    if overlap_pct >= 0.7:
                                        score += 5

                                    # Huge bonus for exact/near-exact title match
                                    if clean_title_lower in item_title_lower or item_title_lower in clean_title_lower:
                                        score += 20

                                    # Boost score for exact price match
                                    if price and item_price > 0:
                                        price_diff = abs(item_price - price)
                                        if price_diff < 1.0:  # Exact price match
                                            score += 10
                                        elif price_diff < price * 0.05:  # Within 5%
                                            score += 5

                                    if score > best_score:
                                        best_score = score
                                        best_match = {
                                            "id": item_id,
                                            "url": item_url,
                                            "title": item_title,
                                            "price": item_price
                                        }

                                # Require minimum score to avoid false matches
                                # Score = word_overlap + price_bonus (up to 10)
                                # Minimum 3 word overlap OR exact price match needed
                                min_score = 3
                                if best_match and best_score >= min_score:
                                    logger.info(f"[EBAY] MATCH via Browse API (score={best_score}): {best_match['id']} @ ${best_match['price']:.2f} - {best_match['title'][:50]}")
                                    return best_match["url"]
                                elif best_match:
                                    logger.info(f"[EBAY] WEAK MATCH rejected (score={best_score}<{min_score}): {best_match['title'][:40]}")
                            else:
                                logger.debug(f"[EBAY] Browse API: No items found for seller '{clean_seller}' with keywords")

                                # FALLBACK: Try WITHOUT seller filter (seller name might not match exactly)
                                if price and price > 0:
                                    logger.info(f"[EBAY] Retrying WITHOUT seller filter...")
                                    filters_no_seller = [
                                        "buyingOptions:{FIXED_PRICE}",
                                        "itemLocationCountry:US",
                                        f"price:[{price * 0.95:.2f}..{price * 1.05:.2f}],priceCurrency:USD"  # Tighter price range
                                    ]
                                    params_retry = {
                                        "q": keywords,
                                        "sort": "newlyListed",
                                        "limit": "10",
                                        "filter": ",".join(filters_no_seller),
                                    }
                                    try:
                                        response2 = await client.get(BROWSE_API_URL, headers=headers, params=params_retry)
                                        if response2.status_code == 200:
                                            data2 = response2.json()
                                            items2 = data2.get("itemSummaries", [])
                                            if items2:
                                                logger.info(f"[EBAY] Fallback found {len(items2)} items (no seller filter)")
                                                # Find EXACT price+title match only (strict mode)
                                                for item in items2:
                                                    item_title = item.get("title", "").lower()
                                                    item_price = float(item.get("price", {}).get("value", 0))
                                                    # Require exact price AND high word overlap
                                                    if abs(item_price - price) < 1.0:
                                                        title_words = set(clean_title_lower.split())
                                                        item_words = set(item_title.split())
                                                        overlap = len(title_words & item_words)
                                                        if overlap >= 4:  # At least 4 words must match
                                                            item_url = item.get("itemWebUrl", "")
                                                            logger.info(f"[EBAY] FALLBACK MATCH: {item.get('itemId')} @ ${item_price:.2f}")
                                                            return item_url
                                    except Exception as e2:
                                        logger.debug(f"[EBAY] Fallback search error: {e2}")
                        else:
                            logger.warning(f"[EBAY] Browse API returned {response.status_code}")

                except Exception as e:
                    logger.warning(f"[EBAY] Browse API error: {e}")

        # FALLBACK 1: Try Finding API findItemsIneBayStores (seller store indexing might be faster)
        ebay_app_id = _config.get("ebay_app_id")
        if ebay_app_id:
            logger.debug("[EBAY] Trying seller store lookup...")
            api_url = "https://svcs.ebay.com/services/search/FindingService/v1"

            # First try findItemsIneBayStores - searches seller's store directly
            store_params = {
                "OPERATION-NAME": "findItemsIneBayStores",
                "SERVICE-VERSION": "1.0.0",
                "SECURITY-APPNAME": ebay_app_id,
                "RESPONSE-DATA-FORMAT": "JSON",
                "REST-PAYLOAD": "",
                "storeName": clean_seller,  # Seller's store name
                "keywords": ' '.join(clean_title.split()[:5]),  # First 5 words
                "paginationInput.entriesPerPage": "10",
                "sortOrder": "StartTimeNewest"
            }

            try:
                async with httpx.AsyncClient(timeout=5.0) as http_client:
                    response = await http_client.get(api_url, params=store_params)

                if response.status_code == 200:
                    data = response.json()
                    search_result = data.get("findItemsIneBayStoresResponse", [{}])[0]

                    if search_result.get("ack", [None])[0] == "Success":
                        items = search_result.get("searchResult", [{}])[0].get("item", [])
                        if items:
                            logger.info(f"[EBAY] Store lookup found {len(items)} items")
                            # Match by price
                            for item in items:
                                item_price = float(item.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0].get("__value__", 0))
                                if price and abs(item_price - price) < price * 0.1:  # Within 10%
                                    first_url = item.get("viewItemURL", [None])[0]
                                    first_id = item.get("itemId", [None])[0]
                                    if first_url:
                                        logger.info(f"[EBAY] MATCH via Store lookup: {first_id} @ ${item_price:.2f}")
                                        return first_url
            except Exception as e:
                logger.debug(f"[EBAY] Store lookup error: {e}")

            # FALLBACK 2: Try findItemsAdvanced with seller filter
            logger.debug("[EBAY] Trying Finding API findItemsAdvanced...")
            params = {
                "OPERATION-NAME": "findItemsAdvanced",
                "SERVICE-VERSION": "1.0.0",
                "SECURITY-APPNAME": ebay_app_id,
                "RESPONSE-DATA-FORMAT": "JSON",
                "REST-PAYLOAD": "",
                "keywords": clean_title[:80],
                "itemFilter(0).name": "Seller",
                "itemFilter(0).value": clean_seller,
                "paginationInput.entriesPerPage": "10",
                "sortOrder": "StartTimeNewest"
            }

            try:
                async with httpx.AsyncClient(timeout=5.0) as http_client:
                    response = await http_client.get(api_url, params=params)

                if response.status_code == 200:
                    data = response.json()
                    search_result = data.get("findItemsAdvancedResponse", [{}])[0]

                    if search_result.get("ack", [None])[0] == "Success":
                        items = search_result.get("searchResult", [{}])[0].get("item", [])
                        if items:
                            logger.info(f"[EBAY] Finding API found {len(items)} items from seller")
                            first_url = items[0].get("viewItemURL", [None])[0]
                            first_id = items[0].get("itemId", [None])[0]
                            if first_url:
                                logger.info(f"[EBAY] MATCH via Finding API: {first_id}")
                                return first_url
                else:
                    logger.debug(f"[EBAY] Finding API returned {response.status_code}")
            except Exception as e:
                logger.debug(f"[EBAY] Finding API error: {e}")

        return None

    except Exception as e:
        logger.error(f"[EBAY] Seller lookup error: {e}")
        return None


def get_ebay_search_url(title: str) -> str:
    """Fallback: Generate eBay search URL from title"""
    search_title = title.replace('+', ' ')[:80]
    encoded_title = urllib.parse.quote(search_title)
    return f"https://www.ebay.com/sch/i.html?_nkw={encoded_title}"
