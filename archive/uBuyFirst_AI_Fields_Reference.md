# uBuyFirst AI Fields to Send - Complete Reference
**Last Updated:** January 2, 2026

---

## Summary

**Total Fields Available:** 85+
**Notable MISSING Fields:** ItemId, ViewUrl, CheckoutUrl, Item Number

---

## All Available Fields (Alphabetical)

| Field Name | Category-Specific | Notes |
|------------|-------------------|-------|
| Age | No | |
| Age Level | No | |
| Alias | No | ✓ Currently enabled - identifies search panel |
| Antique | No | |
| Auction Price | No | |
| Authenticity | No | |
| AutoPay | No | |
| Base Metal | No | Also category-specific for Bracelets & Charms |
| Best Offer | No | |
| Best Offer Count | No | |
| Bids | No | |
| Brand | No | |
| Category ID | No | |
| Category Name | No | |
| Commit To Buy | No | |
| Composition | No | |
| Condition | No | ✓ Currently enabled |
| Condition Description | No | ✓ Currently enabled |
| Dispatch Days | No | |
| Ebay Website | No | |
| Features | No | |
| Feedback Rating | No | Seller feedback % |
| Feedback Score | No | Seller feedback count |
| Fineness | No | Gold fineness (24K, 22K, etc.) |
| Found Time | No | |
| From Country | No | |
| Game | No | For video games |
| Item Length | No | |
| Item Price | No | Price without shipping |
| LEGO Character | No | |
| LEGO Set Name | No | |
| LEGO Set Number | No | |
| LEGO Subtheme | No | |
| LEGO Theme | No | |
| Listing Type | No | Auction/BIN |
| Location | No | |
| Main Stone | No | Also category-specific |
| Main Stone Creation | No | Natural/Lab/Synthetic |
| Main Stone Treatment | No | Also category-specific |
| Material | No | Also category-specific |
| Metal | No | Also category-specific |
| Metal Purity | No | Also category-specific |
| Model | No | |
| MPN | No | Manufacturer Part Number |
| Number of Pieces | No | For LEGO |
| Packaging | No | |
| Pattern | No | Silver pattern name |
| Payment | No | |
| Posted Time | No | When listing was posted |
| Product Reference ID | No | ⚠️ Might be useful - needs testing |
| Quantity | No | eBay quantity available |
| Release Year | No | |
| Retired | No | For LEGO |
| Returns | No | |
| Ring Size | No | |
| Seller Business | No | Business/Individual |
| Seller Country | No | |
| Seller Name | No | |
| Seller Registration | No | |
| Seller Store | No | |
| Set | No | |
| Ship Additional Item | No | |
| Shipping | No | |
| Shipping Days | No | |
| Shipping Delivery | No | |
| Shipping Type | No | |
| Signed | No | |
| Sold Time | No | |
| Status | No | |
| Store Name | No | |
| Style | No | Also category-specific |
| Sub Search | No | |
| Term | No | Search term that matched |
| Time Left | No | |
| Title | No | ✓ Currently enabled |
| Title Match | No | |
| To Country | No | |
| Total Price | No | ✓ Currently enabled - includes shipping |
| Type | No | Also category-specific |
| UPC | No | ✓ Currently enabled |
| Variation | No | |
| VAT Number | No | |
| Vintage | No | |
| Year Manufactured | No | |
| Year Retired | No | For LEGO |

---

## Category-Specific Fields (Bracelets & Charms - 261988)

These fields only appear for specific eBay categories:

| Field Name | Category |
|------------|----------|
| Main Stone | Bracelets & Charms - 261988 |
| Metal | Bracelets & Charms - 261988 |
| Metal Purity | Bracelets & Charms - 261988 |
| Style | Bracelets & Charms - 261988 |
| Type | Bracelets & Charms - 261988 |
| Base Metal | Bracelets & Charms - 261988 |
| Material | Bracelets & Charms - 261988 |
| Main Stone Treatment | Bracelets & Charms - 261988 |

---

## Currently Enabled Fields (Based on Screenshots)

- ✓ Alias
- ✓ Condition
- ✓ Condition Description
- ✓ Title
- ✓ Total Price
- ✓ UPC

---

## MISSING Fields (Not Available)

**Critical for Discord links - NOT in the list:**
- ❌ ItemId / Item Number
- ❌ ViewUrl / View URL
- ❌ CheckoutUrl / Checkout URL
- ❌ eBay Item ID
- ❌ Listing URL

**Workaround needed:** Must extract from image URLs or request uBuyFirst add this field.

---

## Fields to Consider Enabling

### For Better Analysis:
| Field | Why |
|-------|-----|
| Feedback Rating | Seller quality indicator |
| Feedback Score | Seller experience level |
| Posted Time | Fresh vs stale listing |
| From Country | Shipping/authenticity concerns |
| Seller Business | Pro vs casual seller |
| Best Offer | Negotiation opportunity |

### For Item Specifics Completeness Analysis:
Enable ALL item-specific fields to calculate "completeness score":
- Metal, Metal Purity, Base Metal
- Main Stone, Main Stone Creation, Main Stone Treatment
- Material, Composition, Fineness
- Style, Type, Pattern
- Signed, Antique, Vintage

---

## Potential ItemId Sources to Test

1. **Product Reference ID** - Might contain eBay item number
2. **UPC** - Already enabled, but this is product barcode not listing ID
3. **Image URLs** - Contains `set_id` parameter (e.g., `set_id=8800005007`)

---

## Recommendation

Contact uBuyFirst support to request adding **ItemId** or **ViewUrl** to the available fields list. This is essential for:
- Discord notification links
- Direct checkout from alerts
- Tracking/analytics

---

*Document generated from uBuyFirst SKU Manager screenshots*
