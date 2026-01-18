"""Test different eBay API options for latency comparison"""
import asyncio
import httpx
import os
from datetime import datetime, timezone

EBAY_APP_ID = os.getenv('EBAY_APP_ID', '')
FINDING_API_URL = 'https://svcs.ebay.com/services/search/FindingService/v1'

async def test_finding_api():
    """Test if Finding API still works and its latency"""
    if not EBAY_APP_ID:
        print('No EBAY_APP_ID set')
        return

    params = {
        'OPERATION-NAME': 'findItemsAdvanced',
        'SERVICE-VERSION': '1.0.0',
        'SECURITY-APPNAME': EBAY_APP_ID,
        'RESPONSE-DATA-FORMAT': 'JSON',
        'REST-PAYLOAD': 'true',
        'keywords': '14k gold',
        'sortOrder': 'StartTimeNewest',
        'paginationInput.entriesPerPage': '5',
        'itemFilter(0).name': 'ListingType',
        'itemFilter(0).value': 'FixedPrice',
        'itemFilter(1).name': 'LocatedIn',
        'itemFilter(1).value': 'US',
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(FINDING_API_URL, params=params)

            if response.status_code != 200:
                print(f'Finding API Error: {response.status_code}')
                print('Finding API was decommissioned Feb 2025')
                return

            data = response.json()
            search_result = data.get('findItemsAdvancedResponse', [{}])[0]
            ack = search_result.get('ack', ['Failure'])[0]

            if ack != 'Success':
                error = search_result.get('errorMessage', [{}])[0]
                print(f'Finding API returned: {ack}')
                print(f'Error: {error}')
                return

            search_items = search_result.get('searchResult', [{}])[0]
            items = search_items.get('item', [])

            now = datetime.now(timezone.utc)
            print(f'\nFinding API - 5 newest "14k gold" items:')
            print(f'Current UTC: {now.strftime("%H:%M:%S")}')
            print('-' * 60)

            for item in items[:5]:
                title = item.get('title', [''])[0][:40]
                listing_info = item.get('listingInfo', [{}])[0]
                start_time_str = listing_info.get('startTime', [None])[0]

                if start_time_str:
                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    age_seconds = (now - start_time).total_seconds()
                    age_minutes = age_seconds / 60
                    print(f'{age_minutes:6.1f} min ago | {title}')

            print('\nFinding API is still responding!')

    except Exception as e:
        print(f'Finding API error: {e}')


if __name__ == '__main__':
    asyncio.run(test_finding_api())
