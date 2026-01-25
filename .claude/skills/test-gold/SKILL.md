---
name: test-gold
description: Test gold analysis with sample listings to verify instant BUY/PASS logic
allowed-tools: Bash
---

# Test Gold Analysis

Run quick tests against the running server to verify gold/silver analysis works:

## Test 1: Instant BUY (should return BUY)
```bash
curl -s -X POST http://localhost:8000/match_mydata -H "Content-Type: application/json" -d '{"Title": "14K 12 grams Byzantine bracelet", "TotalPrice": "180", "response_type": "json"}' | python -c "import sys,json; d=json.load(sys.stdin); print(f'Test 1 - Instant BUY: {d.get(\"Recommendation\")} (expected: BUY)'); print(f'  Profit: {d.get(\"Profit\")}, instantBuy: {d.get(\"instantBuy\")}')"
```

## Test 2: Instant PASS - Overpriced (should return PASS)
```bash
curl -s -X POST http://localhost:8000/match_mydata -H "Content-Type: application/json" -d '{"Title": "14K 10 grams chain necklace", "TotalPrice": "1500", "response_type": "json"}' | python -c "import sys,json; d=json.load(sys.stdin); print(f'Test 2 - Overpriced: {d.get(\"Recommendation\")} (expected: PASS)'); print(f'  Reason: {d.get(\"reasoning\", \"\")[:80]}...')"
```

## Test 3: Weighted Sterling (should apply 15% weight factor)
```bash
curl -s -X POST http://localhost:8000/match_mydata -H "Content-Type: application/json" -d '{"Title": "Sterling Silver Weighted Candlestick 300 Grams", "TotalPrice": "50", "response_type": "json", "Alias": "silver"}' | python -c "import sys,json; d=json.load(sys.stdin); print(f'Test 3 - Weighted Silver: {d.get(\"Recommendation\")}'); print(f'  Silver weight: {d.get(\"silverweight\")}g (should be ~45g = 15% of 300)')"
```

Run all three tests and report results. All tests should pass for the system to be working correctly.
