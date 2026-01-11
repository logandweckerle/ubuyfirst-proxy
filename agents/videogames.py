"""
Video Games Agent - Handles video game listing analysis
"""

from .base import BaseAgent


class VideoGamesAgent(BaseAgent):
    """Agent for video game analysis"""

    category_name = "videogames"

    # High fake risk consoles (reproductions common, especially Pokemon!)
    HIGH_FAKE_RISK = ["snes", "gba", "ds", "3ds", "game boy", "gameboy", "nes", "nintendo ds", "nintendo 3ds"]

    # Consoles to exclude (too new, overvalued, not worth targeting)
    EXCLUDED_CONSOLES = ["switch", "nintendo switch", "ps5", "playstation 5", "series x", "series s"]

    # Accessories/controllers - rarely worth buying, often fakes
    ACCESSORY_KEYWORDS = ["controller", "remote", "dualshock", "joycon", "joy-con", "wiimote",
                         "memory card", "adapter", "cable", "charger", "headset", "microphone"]

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for video games.
        """
        title = data.get("Title", "").lower()

        # Reproduction keywords = instant PASS
        repro_keywords = ["reproduction", "repro", "custom", "homebrew", "bootleg", "copy"]
        for kw in repro_keywords:
            if kw in title:
                return (f"REPRODUCTION - '{kw}' detected", "PASS")

        # Excluded consoles (too new, overvalued market)
        for console in self.EXCLUDED_CONSOLES:
            if console in title:
                return (f"EXCLUDED CONSOLE - '{console}' games are too new/overvalued", "PASS")

        # Controllers/accessories - not worth targeting, high fake rate
        for accessory in self.ACCESSORY_KEYWORDS:
            if accessory in title:
                # Exception: if it's a lot with games, let it through
                if 'game' not in title and 'lot' not in title:
                    return (f"ACCESSORY - '{accessory}' detected, not targeting accessories", "PASS")

        # High fake risk consoles with Pokemon = always suspect
        if 'pokemon' in title or 'pokémon' in title:
            for console in self.HIGH_FAKE_RISK:
                if console in title:
                    # Don't instant PASS, but flag for RESEARCH (handled in validate)
                    pass  # Let it through but validation will catch it

        return (None, None)

    def get_prompt(self) -> str:
        """Get the video games analysis prompt"""
        return """
=== VIDEO GAME ANALYZER ===

We buy video games to resell. Target: 65% of market price or under.

=== CONDITION TIERS (Critical!) ===
| Condition | Description | Value Multiplier |
| Loose | Cart/disc only | 1x (base) |
| CIB | Complete In Box | 2-3x loose |
| New/Sealed | Factory sealed | 5-10x loose (rare games) |

=== CONSOLE DETECTION ===
Nintendo: NES, SNES, N64, GameCube, Wii, Switch, Game Boy, GBA, DS, 3DS
Sega: Genesis, Saturn, Dreamcast, Game Gear
Sony: PS1, PS2, PS3, PS4, PS5, PSP, Vita
Microsoft: Xbox, Xbox 360, Xbox One, Series X/S

=== FAKE/REPRODUCTION WARNING ===

HIGH RISK (reproductions common):
- SNES, GBA, DS, Game Boy (especially Pokemon!)
- NES (popular titles)

WARNING SIGNS:
- Ships from China/Hong Kong
- Price too good on valuable games
- Perfect condition on 20+ year old games
- "Reproduction", "Repro", "Custom"

=== PRICING GUIDANCE ===

Without PriceCharting data, estimate:
| Category | CIB Value |
| Common (sports, movie) | $5-15 |
| Popular (Mario, Zelda) | $30-100+ |
| Rare/valuable | $100+ (RESEARCH) |

If PriceCharting data is provided, USE THOSE PRICES.

=== LOT DETECTION (CRITICAL!) ===
If multiple games in listing:
1. Count total games visible in images
2. IDENTIFY EACH GAME by title if possible (check images/description)
3. List identifiable games in "lotItems" field
4. Calculate total value by summing individual game values
5. Large lots (10+): Always RESEARCH

LOT VALUATION:
- Try to identify specific game titles from photos
- Look for visible game spines, cases, cartridges
- Sum up individual values for accurate lot pricing
- If games are identifiable, calculate EACH game's value

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "console": "NES"/"SNES"/"N64"/"Genesis"/"PS1"/"PS2"/etc,
  "gameTitle": name of game,
  "condition": "Loose"/"CIB"/"New"/"Unknown",
  "isLot": "Yes"/"No",
  "lotCount": number of games,
  "lotItems": ["Game Title 1", "Game Title 2"] (if lot - list identifiable games),
  "marketprice": estimated market value,
  "maxBuy": 65% of market,
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [console, game, condition] | CONCERNS: [fakes or none] | CALC: Market ~$X, 65% = $Y, list $Z = profit | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate video game response"""

        # Parse profit/margin robustly (handles strings, integers, symbols)
        def parse_number(val):
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return float(val)
            # Handle string formats: "-50", "$-50", "(-50)", "+50", "$50"
            s = str(val).replace("$", "").replace(",", "").replace("(", "-").replace(")", "").replace("+", "").strip()
            try:
                return float(s)
            except:
                return 0

        # Check both Margin and Profit fields (for compatibility)
        profit = parse_number(response.get("Profit", response.get("Margin", "0")))
        market_price = parse_number(response.get("marketprice", "0"))

        # Ensure negative or zero profit = PASS
        if profit <= 0 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: No profit margin = PASS"

        # Thin margin (< $15 profit) = PASS for video games
        if profit < 15 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: Thin margin (${profit:.0f}) = PASS"

        # HIGH FAKE RISK CONSOLES: ALWAYS force to RESEARCH, never BUY
        # Check both the console field AND the title for high-risk keywords
        console = str(response.get("console", "")).lower()
        title = str(response.get("reasoning", "")).lower()  # Use reasoning which contains title info

        for risky in self.HIGH_FAKE_RISK:
            if risky in console or risky in title:
                if response.get("Recommendation") == "BUY":
                    response["Recommendation"] = "RESEARCH"
                    response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: {risky.upper()} = high fake risk, verify authenticity"
                    break

        # LOTS: Always RESEARCH, never BUY (too hard to value individual items)
        is_lot = str(response.get("isLot", "")).lower() == "yes"
        lot_count = parse_number(response.get("lotCount", 0))
        if (is_lot or lot_count > 1) and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Game lots require manual verification"

        # High fake risk + BUY = RESEARCH (any console)
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        return response
