"""
Pipeline Orchestrator

Coordinates Tier 0, Tier 1, and Tier 2 analysis.
Single entry point for the analysis pipeline.

Flow:
1. Tier 0: Rule-based filtering (instant PASS/RESEARCH for obvious cases)
2. Tier 1: Cheap AI assessment (GPT-4o-mini, Gemini Flash)
3. Tier 2: Premium verification (GPT-4o, Claude Sonnet) - only for BUY/RESEARCH

The orchestrator handles:
- Category detection
- Agent selection
- Image pre-fetching
- Result aggregation
- Discord alerts
- Training data logging
"""

import logging
import asyncio
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from .tier0 import Tier0Filter, get_tier0_filter
from .tier1 import Tier1Analyzer, Tier1Result
# Tier2 functions imported from main.py which configures them
from .tier2 import (
    background_sonnet_verify,
    tier2_reanalyze,
    tier2_reanalyze_openai,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Final result from the analysis pipeline"""
    recommendation: str  # BUY, RESEARCH, PASS
    confidence: int
    reasoning: str
    profit: float
    max_buy: float
    market_price: float
    category: str

    # Pipeline metadata
    tier0_result: Optional[Tuple[str, str]] = None  # (reason, rec) if Tier 0 triggered
    tier1_result: Optional[Dict] = None
    tier2_result: Optional[Dict] = None
    tier2_ran: bool = False
    tier2_override: bool = False

    # Timing
    total_time_ms: int = 0
    tier0_time_ms: int = 0
    tier1_time_ms: int = 0
    tier2_time_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to response dict"""
        result = {
            "Recommendation": self.recommendation,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "Profit": self.profit,
            "maxBuy": self.max_buy,
            "marketprice": self.market_price,
            "category": self.category,
            "tier2": self.tier2_ran,
            "tier2_override": self.tier2_override,
        }

        # Merge Tier 1 details
        if self.tier1_result:
            for key in ["karat", "weight", "itemtype", "brand", "model", "weight_source"]:
                if key in self.tier1_result:
                    result[key] = self.tier1_result[key]

        return result


class PipelineOrchestrator:
    """
    Main orchestrator for the analysis pipeline.

    Usage:
        orchestrator = PipelineOrchestrator(agents, blocked_sellers)
        result = await orchestrator.analyze(data)
    """

    def __init__(
        self,
        agents: Dict[str, Any] = None,
        blocked_sellers: set = None,
        user_prices_db=None,
        openai_client=None,
        anthropic_client=None,
    ):
        """
        Initialize the pipeline orchestrator.

        Args:
            agents: Dict mapping category names to agent instances
            blocked_sellers: Set of blocked seller usernames
            user_prices_db: User price database lookup function
            openai_client: OpenAI API client
            anthropic_client: Anthropic API client
        """
        self.agents = agents or {}

        # Initialize tiers
        self.tier0 = Tier0Filter(blocked_sellers, user_prices_db)
        self.tier1 = Tier1Analyzer(openai_client, anthropic_client)
        self.tier2 = Tier2Verifier(openai_client, anthropic_client)

        # Stats tracking
        self.stats = {
            "total_analyzed": 0,
            "tier0_filtered": 0,
            "tier1_buy": 0,
            "tier1_research": 0,
            "tier1_pass": 0,
            "tier2_verified": 0,
            "tier2_overrides": 0,
        }

    def detect_category(self, data: Dict[str, Any]) -> str:
        """
        Detect the category for a listing.

        Args:
            data: Listing data with Title, CategoryName, etc.

        Returns:
            Category string (gold, silver, watch, videogames, etc.)
        """
        # This should be replaced with actual category detection logic
        # For now, use a simple implementation
        title = data.get("Title", "").lower()
        category_name = data.get("CategoryName", "").lower()
        alias = data.get("Alias", "").lower()

        # Watch detection (highest priority)
        if "watch" in title or "watch" in category_name or "watch" in alias:
            if any(w in title for w in ["wristwatch", "pocket watch", "timepiece"]):
                return "watch"
            if "watches" in category_name:
                return "watch"

        # Video games
        if any(w in title for w in ["nintendo", "playstation", "xbox", "ps5", "ps4", "switch"]):
            return "videogames"
        if "video game" in category_name:
            return "videogames"

        # TCG/Pokemon
        if any(w in title for w in ["pokemon", "pokémon", "tcg", "booster", "etb"]):
            return "tcg"

        # LEGO
        if "lego" in title or "lego" in category_name:
            return "lego"

        # Gold
        if any(w in title for w in ["14k", "18k", "10k", "24k", "gold"]):
            if "silver" not in title:
                return "gold"

        # Silver (default for precious metals)
        if any(w in title for w in ["sterling", "silver", ".925", "925"]):
            return "silver"

        # Default
        return "silver"

    def get_agent(self, category: str):
        """Get the agent for a category"""
        return self.agents.get(category)

    async def analyze(
        self,
        data: Dict[str, Any],
        category: str = None,
        images: bytes = None,
    ) -> PipelineResult:
        """
        Run the full analysis pipeline on a listing.

        Args:
            data: Listing data dict
            category: Category (auto-detected if not provided)
            images: Pre-fetched image bytes (optional)

        Returns:
            PipelineResult with final recommendation
        """
        start_time = datetime.now()
        self.stats["total_analyzed"] += 1

        # Detect category if not provided
        if not category:
            category = self.detect_category(data)

        agent = self.get_agent(category)

        # Parse price for Tier 0
        try:
            price_str = str(data.get("TotalPrice", data.get("ItemPrice", "0")))
            price = float(price_str.replace("$", "").replace(",", ""))
        except:
            price = 0

        # ============================================================
        # TIER 0: Rule-based filtering
        # ============================================================
        tier0_start = datetime.now()
        tier0_reason, tier0_rec = self.tier0.filter(data, category, agent)
        tier0_time = int((datetime.now() - tier0_start).total_seconds() * 1000)

        if tier0_rec:
            self.stats["tier0_filtered"] += 1
            logger.info(f"[TIER0] {tier0_rec}: {tier0_reason}")

            return PipelineResult(
                recommendation=tier0_rec,
                confidence=95 if tier0_rec == "PASS" else 80,
                reasoning=tier0_reason,
                profit=0,
                max_buy=0,
                market_price=0,
                category=category,
                tier0_result=(tier0_reason, tier0_rec),
                tier0_time_ms=tier0_time,
                total_time_ms=tier0_time,
            )

        # ============================================================
        # TIER 1: Cheap AI assessment
        # ============================================================
        tier1_start = datetime.now()
        try:
            tier1_result = await self.tier1.analyze(data, category, agent, images)
            tier1_dict = tier1_result.to_dict()
        except NotImplementedError:
            # Tier 1 not yet integrated - return placeholder
            logger.warning("[TIER1] Not yet integrated with main.py - using placeholder")
            tier1_dict = {
                "Recommendation": "RESEARCH",
                "confidence": 50,
                "reasoning": "Tier 1 not yet integrated",
                "Profit": 0,
                "maxBuy": 0,
                "marketprice": 0,
            }
            tier1_result = None
        tier1_time = int((datetime.now() - tier1_start).total_seconds() * 1000)

        tier1_rec = tier1_dict.get("Recommendation", "PASS")

        # Update stats
        if tier1_rec == "BUY":
            self.stats["tier1_buy"] += 1
        elif tier1_rec == "RESEARCH":
            self.stats["tier1_research"] += 1
        else:
            self.stats["tier1_pass"] += 1

        # ============================================================
        # TIER 2: Premium verification (only for BUY/RESEARCH)
        # ============================================================
        tier2_ran = False
        tier2_override = False
        tier2_dict = None
        tier2_time = 0

        if self.tier2.should_verify(tier1_dict, category):
            tier2_start = datetime.now()
            try:
                tier2_result = await self.tier2.verify(tier1_dict, data, category, agent, images)
                tier2_dict = tier2_result.to_dict()
                tier2_ran = True
                self.stats["tier2_verified"] += 1

                if not tier2_result.agrees_with_tier1:
                    tier2_override = True
                    self.stats["tier2_overrides"] += 1
                    log_override(tier1_dict, tier2_result, data, category)

            except NotImplementedError:
                logger.warning("[TIER2] Not yet integrated with main.py")
                tier2_dict = tier1_dict  # Keep Tier 1 result

            tier2_time = int((datetime.now() - tier2_start).total_seconds() * 1000)

        # ============================================================
        # Final result
        # ============================================================
        final_dict = tier2_dict if tier2_ran else tier1_dict
        total_time = int((datetime.now() - start_time).total_seconds() * 1000)

        return PipelineResult(
            recommendation=final_dict.get("Recommendation", "PASS"),
            confidence=final_dict.get("confidence", 50),
            reasoning=final_dict.get("reasoning", ""),
            profit=final_dict.get("Profit", 0),
            max_buy=final_dict.get("maxBuy", 0),
            market_price=final_dict.get("marketprice", 0),
            category=category,
            tier1_result=tier1_dict,
            tier2_result=tier2_dict,
            tier2_ran=tier2_ran,
            tier2_override=tier2_override,
            tier0_time_ms=tier0_time,
            tier1_time_ms=tier1_time,
            tier2_time_ms=tier2_time,
            total_time_ms=total_time,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics"""
        return {
            **self.stats,
            "tier0_filter_rate": (
                self.stats["tier0_filtered"] / self.stats["total_analyzed"]
                if self.stats["total_analyzed"] > 0
                else 0
            ),
            "tier2_override_rate": (
                self.stats["tier2_overrides"] / self.stats["tier2_verified"]
                if self.stats["tier2_verified"] > 0
                else 0
            ),
        }
