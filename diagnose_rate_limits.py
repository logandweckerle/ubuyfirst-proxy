"""
eBay Browse API Rate Limit Diagnostic Tool
Monitors API availability and tracks rate limit patterns.
"""
import asyncio
import httpx
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Stats tracking
stats = {
    "successful_calls": 0,
    "failed_calls": 0,
    "last_success": None,
    "last_failure": None,
    "success_times": [],
    "failure_times": [],
}

async def get_oauth_token():
    """Get OAuth token for Browse API"""
    client_id = os.getenv("EBAY_APP_ID")
    client_secret = os.getenv("EBAY_CERT_ID")

    if not client_id or not client_secret:
        print("ERROR: Missing EBAY_APP_ID or EBAY_CERT_ID")
        return None

    auth_url = "https://api.ebay.com/identity/v1/oauth2/token"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            auth_url,
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
            auth=(client_id, client_secret)
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            print(f"OAuth error: {response.status_code}")
            return None


async def test_api_call(token: str) -> tuple[bool, int]:
    """Make a single Browse API call and return (success, status_code)"""
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    params = {
        "q": "gold ring",
        "sort": "newlyListed",
        "limit": "1",
        "filter": "buyingOptions:{FIXED_PRICE},itemLocationCountry:US",
    }

    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers, params=params)
        return response.status_code == 200, response.status_code


async def monitor_rate_limits():
    """Monitor rate limits and report patterns"""
    print("=" * 60)
    print("eBay Browse API Rate Limit Diagnostic")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
    print("Testing every 15 seconds until we get successful calls...")
    print("-" * 60)

    token = await get_oauth_token()
    if not token:
        print("Failed to get OAuth token")
        return

    consecutive_successes = 0
    consecutive_failures = 0

    while True:
        now = datetime.now()
        success, status = await test_api_call(token)

        if success:
            stats["successful_calls"] += 1
            stats["last_success"] = now
            stats["success_times"].append(now)
            consecutive_successes += 1
            consecutive_failures = 0

            print(f"[{now.strftime('%H:%M:%S')}] [OK] SUCCESS #{stats['successful_calls']} "
                  f"(consecutive: {consecutive_successes})")

            # If we're getting successes, test more aggressively
            if consecutive_successes >= 3:
                print(f"\n*** RATE LIMITS CLEARED! Testing call rate... ***\n")
                await test_burst_rate(token)
                return
        else:
            stats["failed_calls"] += 1
            stats["last_failure"] = now
            stats["failure_times"].append(now)
            consecutive_failures += 1
            consecutive_successes = 0

            print(f"[{now.strftime('%H:%M:%S')}] [FAIL] FAILED (429) - attempt #{stats['failed_calls']} "
                  f"(waiting for reset...)")

        # Wait before next test
        await asyncio.sleep(15)


async def test_burst_rate(token: str):
    """Test how many calls we can make before hitting limits"""
    print("=" * 60)
    print("Testing sustainable call rate...")
    print("Making calls with increasing frequency to find the limit")
    print("=" * 60)

    # Test different intervals
    intervals = [10, 8, 6, 5, 4, 3, 2, 1]

    for interval in intervals:
        print(f"\n--- Testing {interval}s interval ---")
        successes = 0
        failures = 0

        for i in range(10):  # 10 calls per interval test
            success, status = await test_api_call(token)
            if success:
                successes += 1
                print(f"  Call {i+1}: [OK]")
            else:
                failures += 1
                print(f"  Call {i+1}: [FAIL] (429)")
                if failures >= 3:
                    print(f"  -> {interval}s interval: TOO FAST (hit limit after {successes} calls)")
                    break

            if i < 9:  # Don't wait after last call
                await asyncio.sleep(interval)

        if failures == 0:
            print(f"  -> {interval}s interval: SUSTAINABLE ({successes}/10 succeeded)")
        elif failures < 3:
            print(f"  -> {interval}s interval: MARGINAL ({successes}/10 succeeded)")

        # If we hit too many failures, the limit might be exhausted
        if failures >= 5:
            print(f"\nRate limit exhausted. Waiting 60s before continuing...")
            await asyncio.sleep(60)

    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"Total successful calls: {stats['successful_calls']}")
    print(f"Total failed calls: {stats['failed_calls']}")
    print("=" * 60)


async def main():
    try:
        await monitor_rate_limits()
    except KeyboardInterrupt:
        print("\n\nInterrupted. Final stats:")
        print(f"Successful: {stats['successful_calls']}")
        print(f"Failed: {stats['failed_calls']}")


if __name__ == "__main__":
    asyncio.run(main())
