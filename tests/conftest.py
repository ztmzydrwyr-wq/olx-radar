import os

import pytest

LIVE_ENV = "OLX_LIVE_TESTS"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "telegram: шлёт настоящее сообщение владельцу в Telegram"
    )
    config.addinivalue_line("markers", "network: ходит на реальный olx.ua")


def pytest_collection_modifyitems(config, items):
    if os.environ.get(LIVE_ENV) == "1":
        return

    # По умолчанию живые тесты пропускаются. Причины разные, обе весомые:
    # telegram-тесты при каждом прогоне засыпали владельцу чат тестовыми карточками,
    # а network-тесты дёргают olx.ua — набор гоняется десятки раз в день, и это
    # уже не «бытовой профиль нагрузки» из R-1.
    skip = pytest.mark.skip(reason=f"живой тест; включить: {LIVE_ENV}=1")
    for item in items:
        if "telegram" in item.keywords or "network" in item.keywords:
            item.add_marker(skip)
