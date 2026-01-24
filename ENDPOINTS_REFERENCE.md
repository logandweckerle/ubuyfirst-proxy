# uBuyFirst Endpoint URL Reference

All endpoint URL templates for configuring uBuyFirst AI webhooks.
Base URL: `http://localhost:8000/match_mydata`

---

## Common Parameters (All Categories)

These fields are used by every category:

| Parameter | Description |
|-----------|-------------|
| Title | Listing title |
| TotalPrice | Total price including shipping |
| ItemPrice | Item price only |
| Alias | Search alias (used for category detection) |
| Term | Search term that matched |
| TitleMatch | Which words matched |
| PostedTime | When listing was posted |
| Quantity | Number available |
| Returns | Returns accepted |
| BestOffer | Best offer enabled |
| ListingType | Auction/BuyItNow |
| Condition | Item condition |
| ConditionDescription | Seller's condition notes |
| Authenticity | Authenticity guarantee |
| CategoryID | eBay category ID |
| CategoryName | eBay category name |
| FromCountry | Item location country |
| FeedbackRating | Seller feedback % |
| FeedbackScore | Seller feedback count |
| SellerName | Seller username |
| SellerBusiness | Individual/Business |
| SellerStore | Has eBay store |
| SellerRegistration | Account registration date |
| SellerCountry | Seller country |
| EbayWebsite | Which eBay site |
| SoldTime | When sold (if already sold) |
| StoreName | eBay store name |
| ViewUrl | Listing URL |
| CheckoutUrl | Checkout URL |
| ItemId | eBay item ID |
| GalleryURL | Main listing image |

---

## Gold (Apple1)

Categories: 281, 162134, 3360, 262022, 10290, 39482, 91427, 139965, 110633

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&Authenticity={Authenticity}&BaseMetal={BaseMetal}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Composition={Composition}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&Fineness={Fineness}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&MainStone={MainStone}&MainStoneCreation={MainStoneCreation}&Material={Material}&Metal={Metal}&MetalPurity={MetalPurity}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&RingSize={RingSize}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Signed={Signed}&Style={Style}&Term={Term}&TitleMatch={TitleMatch}&Type={Type}&Antique={Antique}&Vintage={Vintage}&ItemLength={ItemLength}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&TotalCaratWeight={TotalCaratWeight}
```

Additional jewelry-specific fields:
- Metal, MetalPurity, Fineness, BaseMetal, Material
- MainStone, MainStoneCreation, TotalCaratWeight, Composition
- RingSize, Style, Type, Signed, Antique, Vintage, ItemLength

---

## Silver (Apple2)

Categories: 20081, 20096, 281, 262022, 262025, 2213, 3361, 37991, 37993, 20104, 110633, 20082

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&Authenticity={Authenticity}&BaseMetal={BaseMetal}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Composition={Composition}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&Fineness={Fineness}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&MainStone={MainStone}&MainStoneCreation={MainStoneCreation}&Material={Material}&Metal={Metal}&MetalPurity={MetalPurity}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Style={Style}&Term={Term}&TitleMatch={TitleMatch}&Type={Type}&Antique={Antique}&Vintage={Vintage}&ItemLength={ItemLength}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&TotalCaratWeight={TotalCaratWeight}
```

---

## Watches (Apple3)

Categories: 165144, 260325, 51020, 31387, 14324, 3937, 57717

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&Authenticity={Authenticity}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&Metal={Metal}&MetalPurity={MetalPurity}&Material={Material}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Style={Style}&Term={Term}&TitleMatch={TitleMatch}&Type={Type}&Antique={Antique}&Vintage={Vintage}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&Brand={Brand}&Movement={Movement}&CaseSize={CaseSize}&CaseMaterial={CaseMaterial}&BandMaterial={BandMaterial}&WatchShape={WatchShape}&Display={Display}
```

Additional watch-specific fields:
- Brand, Movement, CaseSize, CaseMaterial
- BandMaterial, WatchShape, Display

---

## Coral & Amber (Apple3)

Categories: 281, 262025, 20082

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&Material={Material}&Metal={Metal}&MetalPurity={MetalPurity}&MainStone={MainStone}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Style={Style}&Term={Term}&TitleMatch={TitleMatch}&Type={Type}&Antique={Antique}&Vintage={Vintage}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}
```

---

## Costume Jewelry (Apple3 / Apple1 on mini PC)

Categories: 20081, 11116, 281, 262022, 262016, 261650, 10968

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&Material={Material}&MainStone={MainStone}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Style={Style}&Term={Term}&TitleMatch={TitleMatch}&Type={Type}&Vintage={Vintage}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&Brand={Brand}
```

---

## LEGO (Apple4 / Apple2 on mini PC)

Categories: 19006

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&UPC={UPC}&Brand={Brand}&Theme={Theme}
```

Additional LEGO-specific fields:
- UPC, Brand, Theme

---

## Sealed TCG (Apple4 / Apple2 on mini PC)

Categories: 261337, 261044, 261045, 183454, 183453, 183456, 2536

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&UPC={UPC}&Game={Game}&Set={Set}&Language={Language}&Character={Character}&Rarity={Rarity}
```

Additional TCG-specific fields:
- UPC, Game, Set, Language, Character, Rarity

---

## PSA Graded (Apple4 / Apple3 on mini PC)

Categories: 183454, 183050, 2536, 212, 213

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&UPC={UPC}&Game={Game}&Grade={Grade}&Graded={Graded}&Professional Grader={Professional Grader}
```

Additional PSA-specific fields:
- UPC, Game, Grade, Graded, Professional Grader

---

## Video Games (Apple3 / Apple1 on mini PC)

Categories: 139973, 139971, 54968

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&UPC={UPC}&Platform={Platform}&Game Name={Game Name}&Rating={Rating}&Genre={Genre}&Region Code={Region Code}
```

Additional video game-specific fields:
- UPC, Platform, Game Name, Rating, Genre, Region Code

---

## Knives (Apple4 / Apple3 on mini PC)

Categories: 1401, 13956, 966

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&Type={Type}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&Brand={Brand}&Blade Material={Blade Material}&Handle Material={Handle Material}&Blade Length={Blade Length}
```

Additional knife-specific fields:
- Brand, Blade Material, Handle Material, Blade Length, Type

---

## Pens (Apple4 on both)

Categories: 1401, 13956, 966

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&Brand={Brand}&Type={Type}&Ink Color={Ink Color}
```

---

## Allen Bradley Industrial (Apple4 on both)

No specific eBay category - uses all categories.

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&Brand={Brand}&MPN={MPN}&UPC={UPC}
```

---

## Textbooks (Apple4 on both)

Categories: 267

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&UPC={UPC}&Subject={Subject}&Author={Author}&ISBN={ISBN}&Publisher={Publisher}&Format={Format}
```

Additional textbook-specific fields:
- UPC, Subject, Author, ISBN, Publisher, Format

---

## Hot Wheels (Apple4 on both)

Categories: 2619, 222

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&Brand={Brand}&Scale={Scale}&Year of Manufacture={Year of Manufacture}&Vehicle Type={Vehicle Type}&Color={Color}&Series={Series}
```

Additional Hot Wheels-specific fields:
- Brand, Scale, Year of Manufacture, Vehicle Type, Color, Series

---

## Coin Scrap (Apple2 on main PC)

Categories: 39482, 39489, 145410, 163116

```
http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&Alias={Alias}&BestOffer={BestOffer}&CategoryID={CategoryID}&CategoryName={CategoryName}&Condition={Condition}&ConditionDescription={ConditionDescription}&FeedbackRating={FeedbackRating}&FeedbackScore={FeedbackScore}&Fineness={Fineness}&FromCountry={FromCountry}&ItemPrice={ItemPrice}&ListingType={ListingType}&Composition={Composition}&PostedTime={PostedTime}&Quantity={Quantity}&Returns={Returns}&SellerBusiness={SellerBusiness}&SellerName={SellerName}&Term={Term}&TitleMatch={TitleMatch}&SellerStore={SellerStore}&SellerRegistration={SellerRegistration}&SellerCountry={SellerCountry}&EbayWebsite={EbayWebsite}&SoldTime={SoldTime}&StoreName={StoreName}&ViewUrl={ViewUrl}&CheckoutUrl={CheckoutUrl}&ItemId={ItemId}&GalleryURL={GalleryURL}&Denomination={Denomination}&Year={Year}&Certification={Certification}
```

Additional coin-specific fields:
- Composition, Fineness, Denomination, Year, Certification

---

## Notes

- All URLs use GET method with query parameters
- Parameters with spaces in names (e.g., `Game Name`) use URL encoding
- uBuyFirst substitutes `{FieldName}` with actual listing values
- If a field is empty/unavailable, uBuyFirst sends an empty string
- The server auto-detects category from the Alias and Title fields
- For mini PC, replace `localhost` with `192.168.40.3` (main PC IP) if proxying to main PC for AI analysis
