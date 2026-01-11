"""
Base Agent class for all category agents.
Each category agent inherits from this and implements its own logic.
"""

from abc import ABC, abstractmethod
from enum import Enum
from config import SPOT_PRICES


class Tier1Model(Enum):
    """Available models for Tier 1 analysis"""
    GPT4O_MINI = "gpt-4o-mini"
    GEMINI_FLASH = "gemini-1.5-flash"
    CLAUDE_HAIKU = "claude-3-haiku-20240307"


class Tier2Model(Enum):
    """Available models for Tier 2 verification"""
    GPT4O = "gpt-4o"
    CLAUDE_SONNET = "claude-3-5-sonnet-20241022"


class BaseAgent(ABC):
    """Base class for category-specific agents"""

    category_name = "base"

    # Default model selections (can be overridden by subclasses)
    default_tier1_model = Tier1Model.GPT4O_MINI
    default_tier2_model = Tier2Model.GPT4O

    @abstractmethod
    def get_prompt(self) -> str:
        """Return the category-specific prompt"""
        pass

    @abstractmethod
    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering before AI analysis.
        Returns: (reason_string, "PASS") or (None, None) if should continue
        """
        pass

    def validate_response(self, response: dict) -> dict:
        """Validate and fix AI response. Override in subclasses."""
        return response

    def get_tier1_model(self) -> Tier1Model:
        """
        Get the recommended Tier 1 model for this category.
        Override in subclasses for category-specific model selection.

        Returns:
            Tier1Model enum value
        """
        return self.default_tier1_model

    def get_tier2_model(self) -> Tier2Model:
        """
        Get the recommended Tier 2 model for this category.
        Override in subclasses for category-specific model selection.

        Returns:
            Tier2Model enum value
        """
        return self.default_tier2_model

    def should_skip_tier2(self, tier1_result: dict) -> bool:
        """
        Determine if Tier 2 verification can be skipped.
        Override in subclasses for category-specific logic.

        Args:
            tier1_result: Result dict from Tier 1 analysis

        Returns:
            True if Tier 2 can be safely skipped
        """
        # Default: never skip Tier 2 for BUY/RESEARCH
        rec = tier1_result.get("Recommendation", "").upper()
        if rec in ("BUY", "RESEARCH"):
            return False
        # Skip Tier 2 for high-confidence PASS
        confidence = tier1_result.get("confidence", 0)
        return rec == "PASS" and confidence >= 90

    def get_business_context(self) -> str:
        """Shared business context for all categories"""
        gold_oz = SPOT_PRICES.get("gold_oz", 2650)
        silver_oz = SPOT_PRICES.get("silver_oz", 30)

        return f"""
# Logan's eBay Arbitrage Business - Analysis Context

You are analyzing eBay listings for a precious metals SCRAP/MELT arbitrage business.
We buy gold and silver to MELT for scrap value, not to resell as jewelry.

## CORE PRINCIPLE: SCRAP VALUE ONLY
- DIAMONDS = $0 (we cannot sell them, only the metal matters)
- GEMSTONES = $0 (deduct their weight, they add no value)
- PEARLS = $0 (deduct their weight! 8mm pearl = 1.7g, 10mm = 3g)
- DESIGNER NAMES = $0 (Tiffany, Cartier = same as generic, we're melting it)
- SINGLE EARRINGS = PASS (no resale market)

## GOLD BUYING RULES (Scrap Only)
- Target: 90% of melt value (hard ceiling)
- Current spot: ~${gold_oz:,.0f}/oz
- Diamonds/gemstones = $0 added value

## SILVER BUYING RULES
- Target: 75% of melt value (MAX ceiling)
- Sweet spot: 50-60% of melt = excellent deal
- Current spot: ~${silver_oz:.0f}/oz

## OUTPUT FORMAT
Return ONLY valid JSON. Negative margin = ALWAYS PASS.
"""

    def get_full_prompt(self) -> str:
        """Get complete prompt with business context"""
        return f"{self.get_business_context()}\n\n{self.get_prompt()}"
