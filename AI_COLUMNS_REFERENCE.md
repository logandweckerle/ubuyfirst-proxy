# AI Columns Reference - uBuyFirst Response Fields

All fields returned by the AI analysis for each category, plus server-added fields.

---

## Gold

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / No | Does this listing qualify for analysis |
| Recommendation | BUY / PASS | Final recommendation |
| verified | Yes / No / Unknown | Karat verification from photos |
| karat | 10K / 14K / 18K / 22K / 24K | Purity (slash-separated for mixed lots) |
| itemtype | Ring / Chain / Bracelet / Earrings / Pendant / Watch / Scrap / Plated / MixedLot / BeadNecklace / PearlNecklace / PearlEarrings / CameoBrooch | Item classification |
| weightSource | scale / stated / estimate | How weight was determined |
| weight | number (grams) | Total weight |
| mixedCalc | breakdown string or "NA" | Mixed lot calculation (e.g., "1.2g@18K=$77 + 3.9g@10K=$139") |
| stoneDeduction | "2.5g pearl" / "0" / "NA" | Weight deducted for stones/pearls/cameo |
| watchDeduction | "3g movement+crystal" / "0" / "NA" | Weight deducted for watch internals |
| goldweight | number (grams) | Weight after ALL deductions |
| meltvalue | number ($) | Calculated melt value |
| maxBuy | number ($) | meltvalue x 0.90 (our ceiling) |
| sellPrice | number ($) | meltvalue x 0.96 (refiner payout) |
| Profit | number ($) | sellPrice - listingPrice |
| confidence | 0-100 integer | Confidence score (scale=75 base, estimate=50 max) |
| confidenceBreakdown | string | Score breakdown (e.g., "Base 60 + scale 15 + karat 10 = 85") |
| fakerisk | High / Medium / Low | Risk of item being fake/plated |
| reasoning | string | DETECTION | CALC | PROFIT | DECISION |

---

## Silver

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / No | Does this listing qualify |
| Recommendation | BUY / PASS | Final recommendation |
| verified | Yes / No / Unknown | Purity verification from photos |
| itemtype | Flatware / Hollowware / Weighted / Jewelry / Plated / NotSilver / Beaded | Item classification |
| weightSource | scale / stated / estimate | How weight was determined |
| weight | number (grams) | Total weight |
| stoneDeduction | "4g turquoise" / "0" / "NA" | Weight deducted for stones |
| silverweight | number (grams) | Weight after deduction |
| pricepergram | number ($/g) | Listing price / silverweight |
| meltvalue | number ($) | silverweight x sterling rate |
| maxBuy | number ($) | meltvalue x 0.70 (our ceiling) |
| sellPrice | number ($) | meltvalue x 0.82 (refiner payout) |
| Profit | number ($) | sellPrice - listingPrice |
| confidence | 0-100 integer | Confidence score (scale=85, stated=70, estimate=45) |
| confidenceBreakdown | string | Score breakdown |
| reasoning | string | DETECTION | STONES | CALC | PROFIT | DECISION |

---

## Coin Scrap (Junk Silver / Constitutional)

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / Maybe / No | Does this listing qualify |
| Recommendation | BUY / RESEARCH / PASS | Final recommendation |
| coinType | "90% junk silver" / "40% silver" / "silver eagle" / "mixed" | Type of coins |
| faceValue | string (e.g., "$5.00") | Total face value |
| silverOz | number | Total silver troy ounces |
| meltvalue | number ($) | Total melt value |
| maxBuy | number ($) | melt x 0.90 |
| Profit | number ($) | maxBuy - listingPrice |
| reasoning | string | Coin type | Count | Face value | Melt calculation | Profit |

---

## LEGO

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / No | Does this listing qualify |
| Recommendation | BUY / PASS / RESEARCH | Final recommendation |
| SetNumber | string (e.g., "75192") | LEGO set number |
| SetName | string | Name of the set |
| Theme | Star Wars / Harry Potter / Marvel / Technic / Creator / City / Other | LEGO theme |
| Retired | Yes / No / Unknown | Whether set is retired |
| SetCount | string (e.g., "1") | Number of sets in listing |
| marketprice | number string or "Unknown" | Estimated market value |
| maxBuy | number string or "NA" | 65% of market price |
| Margin | string (e.g., "+150" or "-50") | maxBuy minus listing price |
| confidence | High / Medium / Low | Confidence level |
| fakerisk | High / Medium / Low | Risk of counterfeit |
| pcMatch | Yes / No | PriceCharting database match found |
| pcProduct | string | Matched product name |
| pcConfidence | string | PriceCharting match confidence |
| reasoning | string | DETECTION | CONCERNS | CALC | DECISION |

---

## TCG (Pokemon / MTG / Yu-Gi-Oh / One Piece / Lorcana)

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / No | Does this listing qualify |
| Recommendation | BUY / PASS / RESEARCH | Final recommendation |
| TCG | Pokemon / YuGiOh / MTG / OnePiece / Lorcana / Other | Which TCG |
| ProductType | BoosterBox / ETB / Bundle / CollectionBox / Pack / Case / Other | Product type |
| SetName | string | Name of the set |
| ItemCount | string (e.g., "1" or "6") | Number of items |
| marketprice | number string or "Unknown" | Estimated market value |
| maxBuy | number string or "NA" | 65% of market price |
| Margin | string (e.g., "+50" or "-20") | maxBuy minus listing price |
| confidence | High / Medium / Low | Confidence level |
| fakerisk | High / Medium / Low | Risk of counterfeit/resealed |
| pcMatch | Yes / No | PriceCharting database match found |
| pcProduct | string | Matched product name |
| pcConfidence | string | PriceCharting match confidence |
| reasoning | string | DETECTION | CONCERNS | CALC | DECISION |

---

## Video Games

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / No | Does this listing qualify |
| Recommendation | BUY / PASS / RESEARCH | Final recommendation |
| console | NES / SNES / N64 / Genesis / PS1 / PS2 / etc. | Game console |
| gameTitle | string | Name of the game |
| condition | Loose / CIB / New / Unknown | Item condition |
| isLot | Yes / No | Whether listing is a lot |
| lotCount | string (e.g., "1") | Number of games |
| marketprice | number string | Estimated market value for condition |
| maxBuy | number string | 65% of market price |
| Margin | string (e.g., "+50" or "-20") | maxBuy minus listing price |
| confidence | High / Medium / Low | Confidence level |
| fakerisk | High / Medium / Low | Risk of counterfeit/repro |
| pcMatch | Yes / No | PriceCharting database match found |
| pcProduct | string | Matched product name |
| pcConfidence | string | PriceCharting match confidence |
| reasoning | string | DETECTION | CONCERNS | CALC | DECISION |

---

## Coral & Amber

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / No | Does this listing qualify |
| Recommendation | BUY / PASS / RESEARCH | Final recommendation |
| material | Coral / Amber / Unknown | Material type |
| age | Antique / Vintage / Modern / Unknown | Estimated age |
| color | Oxblood / Red / Salmon / Orange / Pink / White / Unknown | Color (coral) |
| itemtype | Carved / Graduated / Beaded / Cabochon / Other | Item type |
| origin | Italian / Mediterranean / Baltic / Japanese / Unknown | Geographic origin |
| weight | string (e.g., "29g") | Weight in grams |
| goldmount | Yes / No | Has gold/sterling mount or clasp |
| inclusions | Insect / Plant / None / Unknown / NA | Amber inclusions (NA for coral) |
| estimatedvalue | number string or "Unknown" | Estimated resale value |
| confidence | High / Medium / Low | Confidence level |
| fakerisk | High / Medium / Low | Risk of synthetic/fake |
| reasoning | string | MATERIAL | AGE | COLOR | TYPE | ORIGIN | WEIGHT | VALUE | DECISION |

---

## Costume Jewelry

| Field | Values | Description |
|-------|--------|-------------|
| Qualify | Yes / No | Does this listing qualify |
| Recommendation | BUY / PASS / RESEARCH | Final recommendation |
| itemtype | Trifari / Lot / Cameo / Bakelite / Designer / Other | Item classification |
| pieceCount | string | Number of pieces |
| pricePerPiece | string | Calculated price per piece |
| designer | string | Specific designer or "Various" / "None" |
| designerTier | 1 / 2 / 3 / 4 / Unknown | Designer value tier |
| hasTrifari | Yes / No / Maybe | Contains Trifari pieces |
| trifariCollection | string | Trifari collection (e.g., "Jelly Belly", "Crown") |
| qualityScore | number | Lot quality score (sum of indicators) |
| positiveIndicators | string | Good things identified |
| negativeIndicators | string | Concerns identified |
| estimatedvalue | number string | Estimated resale value |
| EV | string (e.g., "+25" or "-10") | Expected profit |
| confidence | High / Medium / Low | Confidence level |
| reasoning | string | DETECTION | QUALITY | DECISION |

---

## Server-Added Fields (All Categories)

These fields are added by the server after AI analysis:

| Field | Values | Description |
|-------|--------|-------------|
| category | gold / silver / coin_scrap / lego / tcg / videogames / coral / costume | Detected category |
| serverConfidence | 0-100 integer | Server-calculated confidence (gold/silver only) |
| serverScoreBreakdown | string | Server score breakdown (gold/silver only) |
| freshness_minutes | number | Minutes since listing posted |
| freshness_score | string | Freshness rating |
| seller_score | 0-100 | Seller profile score |
| seller_type | string | Seller classification |
| seller_recommendation | string | Priority recommendation |
| tier2_override | true/false | Whether Tier 2 review triggered |
| tier2_reason | string | Why Tier 2 was triggered |
| tier2_status | PENDING / etc. | Tier 2 review status |
| pcMatch | Yes / No | PriceCharting match (tcg/lego/videogames) |
| pcProduct | string | Matched product name |
| pcConfidence | string | Match confidence |
