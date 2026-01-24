"""
Tier 1: Cheap AI Assessment

First-pass AI analysis using cost-effective models.
Goal: Quick assessment with ~80% accuracy, filtering obvious cases.

Models used (by category):
- Gold/Silver: GPT-4o-mini (math-focused, works well)
- Video Games: GPT-4o-mini or Gemini Flash (title matching)
- TCG/Pokemon: GPT-4o-mini or Gemini Flash (pattern matching)
- Watches: GPT-4o-mini (complex valuation)
- LEGO: GPT-4o-mini (set number extraction)

Cost: ~$0.005-0.02 per call
Latency: 1-3 seconds
"""

import json
import re
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Tier1Model(Enum):
    """Available models for Tier 1 analysis"""
    GPT4O_MINI = "gpt-4o-mini"
    GEMINI_FLASH = "gemini-1.5-flash"
    CLAUDE_HAIKU = "claude-3-haiku-20240307"


@dataclass
class Tier1Result:
    """Result from Tier 1 analysis"""
    recommendation: str  # BUY, RESEARCH, PASS
    confidence: int  # 0-100
    reasoning: str
    profit: float
    max_buy: float
    market_price: float
    weight: Optional[float] = None
    weight_source: str = "estimate"  # "scale", "stated", "estimate"
    karat: Optional[str] = None
    item_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    raw_response: Dict = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "Recommendation": self.recommendation,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "Profit": self.profit,
            "maxBuy": self.max_buy,
            "marketprice": self.market_price,
            "weight": self.weight,
            "weight_source": self.weight_source,
            "karat": self.karat,
            "itemtype": self.item_type,
            "brand": self.brand,
            "model": self.model,
        }


class Tier1Analyzer:
    """
    Tier 1 AI Analysis

    Responsibilities:
    1. Select appropriate model for category
    2. Build prompt with agent context
    3. Call AI with images (optional)
    4. Parse and validate response
    5. Apply agent-specific validation rules
    """

    # Default model selection by category
    DEFAULT_MODELS = {
        "gold": Tier1Model.GPT4O_MINI,
        "silver": Tier1Model.GPT4O_MINI,
        "watch": Tier1Model.GPT4O_MINI,
        "videogames": Tier1Model.GPT4O_MINI,
        "tcg": Tier1Model.GPT4O_MINI,
        "lego": Tier1Model.GPT4O_MINI,
        "costume": Tier1Model.GPT4O_MINI,
    }

    def __init__(self, openai_client=None, anthropic_client=None, google_client=None):
        """
        Initialize Tier 1 analyzer with AI clients.

        Args:
            openai_client: OpenAI API client
            anthropic_client: Anthropic API client
            google_client: Google Generative AI client
        """
        self.openai_client = openai_client
        self.anthropic_client = anthropic_client
        self.google_client = google_client

    def get_model_for_category(self, category: str, agent=None) -> Tier1Model:
        """
        Get the appropriate Tier 1 model for a category.

        Agents can override this via get_tier1_model() method.
        """
        # Check if agent has custom model selection
        if agent and hasattr(agent, 'get_tier1_model'):
            return agent.get_tier1_model()

        return self.DEFAULT_MODELS.get(category, Tier1Model.GPT4O_MINI)

    async def analyze(
        self,
        data: Dict[str, Any],
        category: str,
        agent=None,
        images: List[Dict] = None,
        include_images: bool = True,
    ) -> Tier1Result:
        """
        Run Tier 1 AI analysis on a listing.

        Args:
            data: Listing data dict
            category: Detected category
            agent: Category agent instance
            images: Pre-fetched images in Claude format
            include_images: Whether to include images in prompt

        Returns:
            Tier1Result with recommendation and details
        """
        model = self.get_model_for_category(category, agent)

        # Get system prompt from agent (full context)
        if agent and hasattr(agent, 'get_full_prompt'):
            system_prompt = agent.get_full_prompt()
        elif agent and hasattr(agent, 'get_prompt'):
            system_prompt = agent.get_prompt()
        else:
            system_prompt = self._get_default_prompt(category)

        # Build the user prompt with listing data
        user_prompt = self._build_prompt("", data)

        # Settings based on category
        is_precious_metal = category in ('gold', 'silver')
        image_detail = "high" if is_precious_metal else "low"
        max_tokens = 800 if is_precious_metal else 500

        # Call AI based on model type
        try:
            if model == Tier1Model.GPT4O_MINI:
                response = await self._call_openai(
                    prompt=user_prompt,
                    images=images if include_images else None,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    image_detail=image_detail
                )
            elif model == Tier1Model.GEMINI_FLASH:
                response = await self._call_gemini(user_prompt, images if include_images else None)
            elif model == Tier1Model.CLAUDE_HAIKU:
                response = await self._call_anthropic(
                    prompt=user_prompt,
                    images=images if include_images else None,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens
                )
            else:
                raise ValueError(f"Unknown model: {model}")
        except Exception as e:
            logger.error(f"[TIER1] AI call failed: {e}")
            # Return conservative result on error
            return Tier1Result(
                recommendation="RESEARCH",
                confidence=30,
                reasoning=f"AI analysis failed: {str(e)}",
                profit=0,
                max_buy=0,
                market_price=0
            )

        # Parse response
        result = self._parse_response(response)

        # Apply agent validation
        if agent and hasattr(agent, 'validate_response'):
            validated = agent.validate_response(result.to_dict())
            result = self._dict_to_result(validated)

        return result

    def _build_prompt(self, base_prompt: str, data: Dict[str, Any]) -> str:
        """Build the full prompt with listing data"""
        title = data.get("Title", "").replace("+", " ")
        price = data.get("TotalPrice", data.get("ItemPrice", "Unknown"))
        condition = data.get("Condition", "Unknown")
        description = data.get("description", "")

        return f"""
{base_prompt}

=== LISTING TO ANALYZE ===
Title: {title}
Price: {price}
Condition: {condition}
Description: {description[:500] if description else 'Not provided'}

Analyze this listing and return your recommendation as JSON.
"""

    def _get_default_prompt(self, category: str) -> str:
        """Get a default prompt if agent doesn't provide one"""
        return f"""
Analyze this {category} listing for arbitrage potential.
Return JSON with: Recommendation (BUY/RESEARCH/PASS), confidence (0-100),
reasoning, maxBuy, marketprice, Profit.
"""

    async def _call_openai(
        self,
        prompt: str,
        images: List[Dict] = None,
        system_prompt: str = None,
        max_tokens: int = 500,
        image_detail: str = "low"
    ) -> Dict:
        """
        Call OpenAI GPT-4o-mini for Tier 1 analysis.

        Args:
            prompt: User message prompt
            images: List of image dicts in Claude format (will be converted)
            system_prompt: System prompt for the model
            max_tokens: Maximum tokens for response
            image_detail: "low" or "high" for image processing

        Returns:
            Parsed JSON response dict
        """
        if not self.openai_client:
            raise ValueError("OpenAI client not configured")

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Build user message content
        if images:
            content = [{"type": "text", "text": prompt}]
            for img in images[:6]:  # Max 6 images
                if img.get("type") == "image":
                    # Convert Claude format to OpenAI format
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['source']['media_type']};base64,{img['source']['data']}",
                            "detail": image_detail
                        }
                    })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=messages
            )

            raw_response = response.choices[0].message.content
            if raw_response:
                raw_response = raw_response.strip()
                return self._parse_json_response(raw_response)
            else:
                logger.error("[TIER1] OpenAI returned empty response")
                return {"Recommendation": "RESEARCH", "reasoning": "Empty AI response"}

        except Exception as e:
            logger.error(f"[TIER1] OpenAI error: {e}")
            raise

    async def _call_gemini(self, prompt: str, images: List[bytes] = None) -> Dict:
        """Call Google Gemini API - placeholder for future implementation"""
        if not self.google_client:
            raise ValueError("Google client not configured")
        # TODO: Implement Gemini API call
        raise NotImplementedError("Gemini client integration pending")

    async def _call_anthropic(
        self,
        prompt: str,
        images: List[Dict] = None,
        system_prompt: str = None,
        max_tokens: int = 500
    ) -> Dict:
        """
        Call Anthropic Claude Haiku for Tier 1 analysis (fallback).

        Args:
            prompt: User message prompt
            images: List of image dicts in Claude format
            system_prompt: System prompt for the model
            max_tokens: Maximum tokens for response

        Returns:
            Parsed JSON response dict
        """
        if not self.anthropic_client:
            raise ValueError("Anthropic client not configured")

        # Build message content
        if images:
            content = [{"type": "text", "text": prompt}]
            content.extend(images[:5])  # Max 5 images for Claude
        else:
            content = prompt

        try:
            response = await self.anthropic_client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=max_tokens,
                system=system_prompt or "",
                messages=[{"role": "user", "content": content}]
            )

            raw_response = response.content[0].text.strip()
            return self._parse_json_response(raw_response)

        except Exception as e:
            logger.error(f"[TIER1] Anthropic error: {e}")
            raise

    def _parse_json_response(self, raw_response: str) -> Dict:
        """
        Parse JSON from AI response, handling common issues.

        Args:
            raw_response: Raw text response from AI

        Returns:
            Parsed JSON dict
        """
        # Clean up response
        text = raw_response.strip()

        # Remove markdown code blocks if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Skip first line (```json) and last line (```)
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in response
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Return error response
        logger.error(f"[TIER1] Failed to parse JSON: {text[:200]}")
        return {
            "Recommendation": "RESEARCH",
            "reasoning": "Failed to parse AI response",
            "confidence": 30
        }

    def _parse_response(self, response: Dict) -> Tier1Result:
        """Parse AI response into Tier1Result"""
        return Tier1Result(
            recommendation=response.get("Recommendation", "PASS"),
            confidence=response.get("confidence", 50),
            reasoning=response.get("reasoning", ""),
            profit=float(response.get("Profit", 0) or 0),
            max_buy=float(response.get("maxBuy", 0) or 0),
            market_price=float(response.get("marketprice", 0) or 0),
            weight=response.get("weight"),
            weight_source=response.get("weight_source", "estimate"),
            karat=response.get("karat"),
            item_type=response.get("itemtype"),
            brand=response.get("brand"),
            model=response.get("model"),
            raw_response=response,
        )

    def _dict_to_result(self, d: Dict) -> Tier1Result:
        """Convert a dict back to Tier1Result"""
        return Tier1Result(
            recommendation=d.get("Recommendation", "PASS"),
            confidence=d.get("confidence", 50),
            reasoning=d.get("reasoning", ""),
            profit=float(d.get("Profit", 0) or 0),
            max_buy=float(d.get("maxBuy", 0) or 0),
            market_price=float(d.get("marketprice", 0) or 0),
            weight=d.get("weight"),
            weight_source=d.get("weight_source", "estimate"),
            karat=d.get("karat"),
            item_type=d.get("itemtype"),
            brand=d.get("brand"),
            model=d.get("model"),
            raw_response=d,
        )
