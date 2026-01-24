"""
Textbook Agent - Handles college textbook arbitrage via KeepaTracker
Unlike other agents, this one doesn't use AI prompts - it calls KeepaTracker API directly.
"""

import httpx
import logging
from .base import BaseAgent, Tier1Model, Tier2Model

logger = logging.getLogger(__name__)

KEEPA_TRACKER_URL = "http://127.0.0.1:8001"


class TextbookAgent(BaseAgent):
    """Agent for textbook arbitrage - calls KeepaTracker for ISBN lookup"""

    category_name = "textbook"

    # Textbooks don't use AI - they use Keepa lookup
    default_tier1_model = Tier1Model.GPT4O_MINI  # Not used
    default_tier2_model = Tier2Model.GPT4O  # Not used

    def get_prompt(self) -> str:
        """Not used - textbooks use Keepa lookup instead of AI"""
        return ""

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for textbooks before Keepa lookup.
        Returns (reason, "PASS") or (None, None) to continue.
        """
        title = data.get("Title", "").lower()

        # Skip non-textbook books
        non_textbook_keywords = [
            "novel", "fiction", "romance", "mystery", "thriller",
            "cookbook", "children", "coloring book", "comic",
            "manga", "graphic novel", "diary", "journal"
        ]
        for kw in non_textbook_keywords:
            if kw in title:
                return (f"NOT A TEXTBOOK - '{kw}' detected", "PASS")

        # Skip very old editions
        old_editions = ["1st edition", "2nd edition", "3rd edition", "4th edition", "5th edition"]
        for ed in old_editions:
            if ed in title:
                return (f"OLD EDITION - '{ed}' likely outdated", "PASS")

        return (None, None)

    async def analyze_textbook(self, data: dict, price: float) -> dict:
        """
        Call KeepaTracker to analyze textbook.
        Returns dict with AI columns matching gold format.
        """
        title = data.get("Title", "")
        description = data.get("Description", "") or data.get("ConditionDescription", "")
        url = data.get("ViewUrl", "") or data.get("CheckoutUrl", "")
        condition = data.get("Condition", "Used")

        # Extract additional book fields from uBuyFirst
        author = data.get("Author", "")
        publisher = data.get("Publisher", "")
        publication_year = data.get("PublicationYear", "")

        # Include ISBN from uBuyFirst fields if available
        isbn_field = data.get("ISBN", "") or data.get("ProductReferenceID", "")
        if isbn_field:
            description = f"{description} ISBN: {isbn_field}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{KEEPA_TRACKER_URL}/textbook/analyze",
                    json={
                        "title": title,
                        "price": price,
                        "url": url,
                        "description": description,
                        "condition": condition,
                        "author": author,
                        "publisher": publisher,
                        "publication_year": publication_year,
                    }
                )

                if response.status_code != 200:
                    logger.error(f"[TEXTBOOK] KeepaTracker error: {response.status_code}")
                    return self._pass_response("KeepaTracker API error")

                result = response.json()

                if result.get("status") == "profitable":
                    deal = result.get("deal", {})
                    return {
                        "Qualify": "YES",
                        "Recommendation": "BUY",
                        "verified": True,
                        "isbn": deal.get("isbn", ""),
                        "bookTitle": deal.get("title", ""),
                        "author": deal.get("author", ""),
                        "amazonPrice": deal.get("amazon_used_price", 0),
                        "profit": deal.get("estimated_profit", 0),
                        "roi": deal.get("roi_percent", 0),
                        "salesRank": deal.get("sales_rank", 0),
                        "bookAge": deal.get("book_age_years", 0),
                        "maxBuy": price,  # Current price is max buy if profitable
                        "amazonUrl": deal.get("amazon_url", ""),
                        "keepaUrl": deal.get("keepa_url", ""),
                        "confidence": 85,
                        "reasoning": f"Profitable textbook: ${deal.get('estimated_profit', 0):.2f} profit, {deal.get('roi_percent', 0):.0f}% ROI, rank {deal.get('sales_rank', 0):,}",
                    }
                else:
                    return self._pass_response("Not profitable or no ISBN found")

        except httpx.TimeoutException:
            logger.error("[TEXTBOOK] KeepaTracker timeout")
            return self._pass_response("KeepaTracker timeout")
        except Exception as e:
            logger.error(f"[TEXTBOOK] Error: {e}")
            return self._pass_response(f"Error: {str(e)}")

    def _pass_response(self, reason: str) -> dict:
        """Generate a PASS response"""
        return {
            "Qualify": "NO",
            "Recommendation": "PASS",
            "verified": False,
            "isbn": "",
            "bookTitle": "",
            "author": "",
            "amazonPrice": 0,
            "profit": 0,
            "roi": 0,
            "salesRank": 0,
            "bookAge": 0,
            "maxBuy": 0,
            "amazonUrl": "",
            "keepaUrl": "",
            "confidence": 90,
            "reasoning": reason,
        }

    def validate_response(self, response: dict) -> dict:
        """Validate textbook response"""
        # Ensure required fields exist
        required = ["Qualify", "Recommendation", "isbn", "profit", "roi", "reasoning"]
        for field in required:
            if field not in response:
                response[field] = "" if field in ["isbn", "reasoning"] else 0
        return response

    def should_skip_tier2(self, tier1_result: dict) -> bool:
        """Textbooks don't use Tier 2 - Keepa is the source of truth"""
        return True
