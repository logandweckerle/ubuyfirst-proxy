---
name: test-watch
description: Test watch analysis to verify hallucination guards and market caps work
allowed-tools: Bash
---

# Test Watch Analysis

Run tests to verify watch validation is working correctly:

## Test 1: Premium brand should get RESEARCH (not auto-BUY)
```bash
curl -s -X POST http://localhost:8000/match_mydata -H "Content-Type: application/json" -d '{"Title": "Rolex Datejust 36mm Automatic Watch", "TotalPrice": "3000", "response_type": "json", "Alias": "watch"}' | python -c "import sys,json; d=json.load(sys.stdin); print(f'Test 1 - Premium Rolex: {d.get(\"Recommendation\")} (expected: RESEARCH)'); print(f'  Reasoning: {d.get(\"reasoning\", \"\")[:100]}...')"
```

## Test 2: Entry-level brand should not get BUY
```bash
curl -s -X POST http://localhost:8000/match_mydata -H "Content-Type: application/json" -d '{"Title": "Seiko Automatic Watch Vintage", "TotalPrice": "100", "response_type": "json", "Alias": "watch"}' | python -c "import sys,json; d=json.load(sys.stdin); print(f'Test 2 - Entry Seiko: {d.get(\"Recommendation\")} (expected: RESEARCH or PASS, not BUY)')"
```

## Test 3: Gold watch with weight should calculate melt
```bash
curl -s -X POST http://localhost:8000/match_mydata -H "Content-Type: application/json" -d '{"Title": "14K Gold Watch 25 grams vintage", "TotalPrice": "500", "response_type": "json", "Alias": "watch"}' | python -c "import sys,json; d=json.load(sys.stdin); print(f'Test 3 - Gold Watch: {d.get(\"Recommendation\")}'); print(f'  Melt value: {d.get(\"meltvalue\", \"NA\")}')"
```

Run all tests and verify watch validation is preventing hallucinated BUY signals.
