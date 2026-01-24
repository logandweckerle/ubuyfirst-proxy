"""
Video Games Agent - Handles video game listing analysis
Includes WATA graded game support.
"""

import re
from .base import BaseAgent


# WATA Grade Multipliers (sealed games)
# WATA grades sealed video games on a scale similar to CGC comics
# Format: WATA 9.4 A++ (grade + seal rating)
WATA_GRADE_MULTIPLIERS = {
    10.0: 100.0,   # WATA 10 = 100x+ (extremely rare, unicorn)
    9.8: 50.0,    # WATA 9.8 = ~50x (near perfect)
    9.6: 20.0,    # WATA 9.6 = ~20x (excellent)
    9.4: 10.0,    # WATA 9.4 = ~10x (very good)
    9.2: 5.0,     # WATA 9.2 = ~5x
    9.0: 3.0,     # WATA 9.0 = ~3x
    8.5: 2.0,     # WATA 8.5 = ~2x
    8.0: 1.5,     # WATA 8.0 = ~1.5x
    7.5: 1.2,     # WATA 7.5 = ~1.2x
    7.0: 1.0,     # WATA 7.0 = ~raw sealed
}

# VGA (Video Game Authority) - another grading service
VGA_GRADE_MULTIPLIERS = {
    100: 100.0,   # VGA 100 = 100x+ (perfect, extremely rare)
    95: 30.0,     # VGA 95+ = ~30x
    90: 15.0,     # VGA 90+ = ~15x
    85: 8.0,      # VGA 85+ = ~8x
    80: 4.0,      # VGA 80+ = ~4x
    75: 2.0,      # VGA 75+ = ~2x
    70: 1.5,      # VGA 70+ = ~1.5x
}


def extract_game_grade_info(title: str) -> dict:
    """
    Extract grading info from video game listing title.
    Returns dict with: grader, grade, seal_rating, is_graded
    """
    title_lower = title.lower()
    result = {"grader": None, "grade": None, "seal_rating": None, "is_graded": False}

    # WATA patterns: "WATA 9.4", "WATA 9.4 A++", "WATA9.6", "WATA 9.8 A+"
    wata_match = re.search(r'\bwata[\s\-]?(\d+\.?\d?)\s*([ab]\+{0,2})?', title_lower)
    if wata_match:
        result["grader"] = "WATA"
        result["grade"] = float(wata_match.group(1))
        result["seal_rating"] = wata_match.group(2).upper() if wata_match.group(2) else None
        result["is_graded"] = True
        return result

    # VGA patterns: "VGA 85", "VGA 85+", "VGA85"
    vga_match = re.search(r'\bvga[\s\-]?(\d+)\+?', title_lower)
    if vga_match:
        result["grader"] = "VGA"
        result["grade"] = float(vga_match.group(1))
        result["is_graded"] = True
        return result

    # CGC Games patterns: "CGC 9.4", "CGC 9.6"
    cgc_match = re.search(r'\bcgc[\s\-]?(\d+\.?\d?)', title_lower)
    if cgc_match and ('game' in title_lower or 'nintendo' in title_lower or 'sega' in title_lower
                      or 'playstation' in title_lower or 'ps1' in title_lower or 'ps2' in title_lower):
        result["grader"] = "CGC"
        result["grade"] = float(cgc_match.group(1))
        result["is_graded"] = True
        return result

    return result


def get_game_grade_multiplier(grader: str, grade: float) -> float:
    """Get price multiplier for graded games based on grader and grade"""
    if grader == "WATA":
        for g in sorted(WATA_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return WATA_GRADE_MULTIPLIERS[g]
        return 0.8  # Below WATA 7.0

    elif grader == "VGA":
        for g in sorted(VGA_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return VGA_GRADE_MULTIPLIERS[g]
        return 0.8  # Below VGA 70

    elif grader == "CGC":
        # CGC games similar to WATA but slightly less premium
        for g in sorted(WATA_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return WATA_GRADE_MULTIPLIERS[g] * 0.85  # 85% of WATA value
        return 0.7

    return 1.0


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

    # Annual sports games - nearly worthless
    SPORTS_GAMES = ["madden", "nba 2k", "nba live", "fifa", "nhl ", "mlb ", "wwe 2k",
                   "pes ", "pro evolution", "nba 2k", "mlb the show"]

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for video games.
        """
        title = data.get("Title", "").lower()

        # === WATA/VGA GRADED GAMES = HIGH PRIORITY ===
        # Graded sealed games can be extremely valuable - always flag for research
        grade_info = extract_game_grade_info(title)
        if grade_info["is_graded"]:
            grader = grade_info["grader"]
            grade = grade_info["grade"]
            seal_rating = grade_info.get("seal_rating", "")
            multiplier = get_game_grade_multiplier(grader, grade)

            seal_str = f" {seal_rating}" if seal_rating else ""
            if multiplier >= 10.0:
                return (f"HIGH-VALUE {grader} GRADED GAME ({grade}{seal_str}) - multiplier ~{multiplier:.0f}x at ${price:.0f} = HIGH PRIORITY", "RESEARCH")
            elif multiplier >= 3.0:
                return (f"{grader} GRADED GAME ({grade}{seal_str}) - multiplier ~{multiplier:.1f}x at ${price:.0f} = RESEARCH", "RESEARCH")
            else:
                return (f"{grader} GRADED GAME ({grade}{seal_str}) - lower grade but graded = RESEARCH", "RESEARCH")

        # === REPRODUCTIONS/BOOTLEGS ===
        repro_keywords = ["reproduction", "repro", "custom", "homebrew", "bootleg",
                         "copy", "fake", "counterfeit", "pirate", "unlicensed"]
        for kw in repro_keywords:
            if kw in title:
                return (f"REPRODUCTION - '{kw}' detected", "PASS")

        # === EXCLUDED CONSOLES (too new/overvalued) ===
        for console in self.EXCLUDED_CONSOLES:
            if console in title:
                return (f"EXCLUDED CONSOLE - '{console}' games are too new/overvalued", "PASS")

        # === CONTROLLERS/ACCESSORIES ===
        for accessory in self.ACCESSORY_KEYWORDS:
            if accessory in title:
                # Exception: if it's a lot with games, let it through
                if 'game' not in title and 'lot' not in title:
                    return (f"ACCESSORY - '{accessory}' detected, not targeting accessories", "PASS")

        # === DISC/MANUAL/CASE ONLY ===
        partial_keywords = ["disc only", "disk only", "manual only", "case only",
                          "box only", "no game", "no disc", "artwork only",
                          "cover art only", "insert only", "replacement case"]
        for kw in partial_keywords:
            if kw in title:
                return (f"PARTIAL ITEM - '{kw}' (incomplete = low value)", "PASS")

        # === SPORTS GAMES (annual, nearly worthless) ===
        for sport in self.SPORTS_GAMES:
            if sport in title:
                # Check for vintage sports which might have value
                vintage_years = ["1990", "1991", "1992", "1993", "1994", "1995",
                               "1996", "1997", "1998", "1999"]
                is_vintage = any(year in title for year in vintage_years)
                if not is_vintage:
                    return (f"SPORTS GAME - '{sport}' (annual releases = minimal value)", "PASS")

        # === DEMO/PROMO/RENTAL COPIES ===
        promo_keywords = ["demo disc", "demo disk", "not for resale", "nfr",
                        "promo copy", "promotional", "rental copy", "blockbuster",
                        "hollywood video", "sample", "press kit", "review copy"]
        for kw in promo_keywords:
            if kw in title:
                # Some demos are collectible, but most are not
                if price < 30:
                    return (f"DEMO/PROMO - '{kw}' at ${price:.0f} (usually low value)", "PASS")

        # === STRATEGY GUIDES (not games) ===
        guide_keywords = ["strategy guide", "game guide", "player's guide",
                        "official guide", "prima guide", "bradygames", "hint book"]
        for kw in guide_keywords:
            if kw in title:
                return (f"STRATEGY GUIDE - '{kw}' (not a game)", "PASS")

        # === CONSOLE ONLY (no games) ===
        console_only_keywords = ["console only", "system only", "no games",
                                "unit only", "console bundle", "for parts",
                                "not working", "broken", "as-is", "as is"]
        for kw in console_only_keywords:
            if kw in title:
                return (f"CONSOLE/BROKEN - '{kw}' (not targeting hardware)", "PASS")

        # === GREATEST HITS/BUDGET RELEASES (lower value) ===
        budget_keywords = ["greatest hits", "player's choice", "platinum hits",
                         "nintendo selects", "playstation hits", "essentials",
                         "best of", "budget", "value pack"]
        is_budget = any(kw in title for kw in budget_keywords)
        if is_budget and price > 30:
            # Budget releases at higher prices = overpriced
            return (f"BUDGET RELEASE - Greatest Hits/Player's Choice at ${price:.0f} (overpriced)", "PASS")

        # === MOVIE/SHOVELWARE GAMES ===
        shovelware_keywords = ["movie game", "based on movie", "nickelodeon",
                             "disney game", "dreamworks", "illumination",
                             "barbie", "dora", "sesame street", "leapfrog"]
        for kw in shovelware_keywords:
            if kw in title and price > 15:
                return (f"SHOVELWARE - '{kw}' (licensed games = low demand)", "PASS")

        # === EMPTY CASES/DISPLAY ONLY ===
        empty_keywords = ["empty case", "display only", "display case",
                        "no game included", "case and manual", "case & manual"]
        for kw in empty_keywords:
            if kw in title:
                return (f"EMPTY/DISPLAY - '{kw}' (no game)", "PASS")

        # === LOW VALUE PRICE CHECK ===
        if price < 10:
            return (f"TOO CHEAP - ${price:.0f} (no margin after fees)", "PASS")

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
| WATA/VGA Graded | Professionally graded sealed | 10-100x+ (see below) |

=== GRADED GAMES (WATA/VGA/CGC) ===
Professionally graded sealed games can be EXTREMELY valuable!

WATA GRADES (most common):
| Grade | Multiplier | Notes |
| WATA 9.8+ | 50x+ | Near perfect, very rare |
| WATA 9.4-9.6 | 10-20x | Excellent condition |
| WATA 9.0-9.2 | 3-5x | Good condition |
| WATA 8.0-8.5 | 1.5-2x | Acceptable |
| Below 8.0 | ~1x | Similar to raw sealed |

WATA SEAL RATINGS: A++, A+, A, B+ (higher = more pristine seal)

VGA GRADES (older grading service):
| Grade | Multiplier |
| VGA 95+ | 30x+ |
| VGA 85-90 | 8-15x |
| VGA 75-80 | 2-4x |

GRADED GAME RULES:
- ALL graded games = RESEARCH (verify authenticity)
- High-grade vintage (WATA 9.4+) = extremely valuable, verify slab
- Check for slab authenticity (fakes exist!)

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
  "condition": "Loose"/"CIB"/"New"/"Graded",
  "isLot": "Yes"/"No",
  "lotCount": number of games,
  "lotItems": ["Game Title 1", "Game Title 2"] (if lot - list identifiable games),
  // GRADED GAME FIELDS (if graded):
  "isGraded": "Yes"/"No",
  "grader": "WATA"/"VGA"/"CGC"/null,
  "grade": numeric grade (e.g., 9.4),
  "sealRating": "A++"/"A+"/"A"/"B+"/null (WATA only),
  "gradeMultiplier": multiplier applied (e.g., 10 for WATA 9.4),
  "rawValue": estimated raw sealed value,
  "marketprice": estimated value (for graded = rawValue x multiplier),
  "maxBuy": 65% of market,
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [console, game, condition, grader grade] | GRADED: [multiplier calc] | CALC: Market ~$X, 65% = $Y, list $Z = profit | DECISION: [why]"
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

        # === GRADED GAME VALIDATION ===
        is_graded = str(response.get("isGraded", "No")).lower() == "yes"
        condition = str(response.get("condition", "")).lower()
        grader = response.get("grader", "")

        if is_graded or condition == "graded" or grader in ["WATA", "VGA", "CGC"]:
            # ALL graded games = RESEARCH (verify authenticity, check slab)
            if response.get("Recommendation") == "BUY":
                response["Recommendation"] = "RESEARCH"
                grader_str = grader if grader else "Unknown"
                grade = response.get("grade", "?")
                response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: {grader_str} graded game = RESEARCH (verify slab authenticity)"

            # High-value graded games (>$500) get extra warning
            if market_price > 500:
                response["reasoning"] = response.get("reasoning", "") + f" | WARNING: High-value graded (${market_price:.0f}) - verify slab & cert number"

        return response
