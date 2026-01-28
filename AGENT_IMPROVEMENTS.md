# Agent Improvement Analysis

Based on analysis of 287 matched buy/sell transactions (3,255 purchases, 1,049 sales).

## Summary Statistics
- **Total Profit from Matched Sales**: $58,524 (89.8% ROI)
- **Best ROI**: Watches at 239% (driven by Tag Heuer, Rolex)
- **Worst Category**: Gold watches at -24% ROI

---

## KEY FINDINGS

### 1. Price Range Performance (CRITICAL)
| Price Range | Win Rate | ROI | Recommendation |
|-------------|----------|-----|----------------|
| **$0-50** | **96%** | **508%** | AGGRESSIVE BUY |
| **$50-100** | **85%** | **272%** | STRONG BUY |
| $100-200 | 83% | 141% | BUY |
| $200-500 | 59% | 73% | CAUTIOUS |
| $500-1000 | 75% | 35% | RESEARCH |
| **$1000+** | **67%** | **8%** | AVOID AUTO-BUY |

**ACTION**: Lower buy thresholds for items under $100. Add caution flags for items over $500.

---

### 2. Gold Performance by Item Type
| Item Type | Count | Profit | ROI | Action |
|-----------|-------|--------|-----|--------|
| Ring | 42 | $11,143 | 91% | BOOST |
| Bracelet | 20 | $7,940 | 95% | BOOST |
| Pendant | 6 | $3,016 | 155% | BOOST |
| Necklace | 7 | $2,327 | 114% | BOOST |
| Brooch | 9 | $1,533 | 75% | NEUTRAL |
| **Watch** | **9** | **-$1,177** | **-24%** | **AVOID** |

**ACTION**: Gold watches should trigger RESEARCH not BUY. Add penalty to gold watch confidence.

---

### 3. Gold Performance by Karat
| Karat | Count | ROI | Action |
|-------|-------|-----|--------|
| **14K** | 66 | **103%** | BOOST |
| 18K | 18 | 48% | NEUTRAL |
| 10K | 5 | 33% | NEUTRAL |

**ACTION**: 14K items get confidence boost. 18K+ should be more cautious (often overpriced).

---

### 4. Silver Performance by Item Type
| Item Type | Count | Profit | ROI | Win Rate | Action |
|-----------|-------|--------|-----|----------|--------|
| **Cuff** | 33 | $5,089 | **136%** | **85%** | BOOST |
| **Necklace** | 14 | $3,971 | **260%** | **93%** | BOOST |
| Bracelet | 18 | $2,523 | 114% | 78% | BOOST |
| Brooch | 12 | $993 | 90% | 83% | NEUTRAL |
| Ring | 16 | $678 | 58% | 63% | NEUTRAL |
| **Lot** | **8** | **-$1,306** | **-44%** | **50%** | **AVOID** |

**ACTION**: Silver cuffs and necklaces are winners. Silver LOTS should be RESEARCH/PASS.

---

### 5. Watch Brand Performance
| Brand | Count | Profit | ROI | Action |
|-------|-------|--------|-----|--------|
| **Rolex** | 2 | $2,619 | **931%** | BOOST |
| **Tag Heuer** | 10 | $3,409 | **147%** | BOOST |
| Hamilton | 1 | $275 | 122% | NEUTRAL |
| **Omega** | **5** | **-$2,086** | **-56%** | **PENALTY** |

**ACTION**: Add Omega penalty. Rolex and Tag Heuer get confidence boost.

---

### 6. Loss Patterns to Avoid
| Pattern | Total Loss | Action |
|---------|------------|--------|
| **Omega watches** | -$1,907 | Add to high-risk |
| **"Mixed" lots** | -$850 | PASS on "mixed" |
| **James Avery** | -$328 | Add caution |
| **Silver lots** | -$1,306 | RESEARCH only |
| **Cameos** | -$192 | Already cautious |
| **iPhones** | -$571 | Reduce confidence |

---

### 7. Timing Analysis
| Hold Period | Win Rate | Avg Profit | Action |
|-------------|----------|------------|--------|
| **< 30 days** | **90%** | $271 | Quick flips win |
| 30-90 days | 87% | $140 | Good |
| 90+ days | 68% | $194 | More risk |

---

## AGENT UPDATES NEEDED

### gold.py
1. Add "gold watch" penalty: If gold + watch, confidence -20
2. Add 14K boost: +5 confidence
3. Add >$1000 RESEARCH override (already exists, verify active)
4. Reduce max buy threshold for gold watches

### silver.py
1. Add "lot" penalty: If "lot" in title, force RESEARCH
2. Add "cuff" boost: +10 confidence
3. Add "necklace" boost: +5 confidence
4. Flag "mixed" as PASS

### watch.py
1. Add Omega penalty: -15 confidence, force RESEARCH on gold Omega
2. Add Rolex boost: +15 confidence (but verify authenticity)
3. Add Tag Heuer boost: +10 confidence
4. Add chronograph boost: +5 (based on profit keywords)

### General
1. Under $100: Increase max_buy_pct by 5%
2. Over $500: Decrease max_buy_pct by 5%
3. Over $1000: Always RESEARCH

---

## TOP PROFIT KEYWORDS (add to boost list)
1. nantucket, diana, england (jewelry makers)
2. navajo, zuni, native (turquoise)
3. chronograph
4. autavia, viceroy (Tag Heuer)
5. trifari (vintage costume)
6. myron panteah (artist)

## KEYWORDS TO PENALIZE
1. omega (watch context)
2. lot, mixed, bulk
3. james avery (retail markup)
4. iphone, apple (electronics)
5. cameo (weight issues)
