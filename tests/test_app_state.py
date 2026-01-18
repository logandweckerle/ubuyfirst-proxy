import pytest
import asyncio
from services.app_state import AppState


@pytest.fixture
def app_state():
    return AppState()


def test_increment_stat(app_state):
    app_state.increment_stat('total_requests', 1)
    assert app_state.stats['total_requests'] == 1


def test_increment_stat_non_existing_key(app_state):
    app_state.increment_stat('non_existing_key', 1)
    # Check that it does not affect other stats
    assert app_state.stats['total_requests'] == 0


def test_start_in_flight(app_state):
    key = 'request_1'
    assert asyncio.run(app_state.start_in_flight(key)) is True  # Should be a new request
    assert key in app_state.in_flight


def test_start_in_flight_already_exists(app_state):
    key = 'request_2'
    asyncio.run(app_state.start_in_flight(key))
    assert asyncio.run(app_state.start_in_flight(key)) is False  # Should already be in flight


def test_complete_in_flight(app_state):
    key = 'request_3'
    asyncio.run(app_state.start_in_flight(key))
    result = ('result_data',)
    asyncio.run(app_state.complete_in_flight(key, result))
    assert app_state.in_flight_results[key] == result


def test_check_in_flight(app_state):
    key = 'request_4'
    assert asyncio.run(app_state.start_in_flight(key)) is True
    # Simulating completion
    asyncio.run(app_state.complete_in_flight(key, ('result_data',)))
    result = asyncio.run(app_state.check_in_flight(key))
    assert result == ('result_data',)


def test_cleanup_in_flight(app_state):
    key = 'request_5'
    assert asyncio.run(app_state.start_in_flight(key)) is True
    asyncio.run(app_state.cleanup_in_flight(key, delay=0))  # Clean up immediately
    assert key not in app_state.in_flight
    assert key not in app_state.in_flight_results


def test_in_flight_lock_thread_safety(app_state):
    async def increment_and_complete():
        key = 'request_thread'
        await app_state.start_in_flight(key)
        await asyncio.sleep(0.1)
        await app_state.complete_in_flight(key, ('result_data',))

    async def concurrent_check():
        key = 'request_thread'
        result = await app_state.check_in_flight(key)
        assert result == ('result_data',)

    async def run_tasks():
        task1 = asyncio.create_task(increment_and_complete())
        task2 = asyncio.create_task(concurrent_check())
        await task1
        await task2

    asyncio.run(run_tasks())
