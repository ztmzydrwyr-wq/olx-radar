import time

import httpx
import pytest

from olx import transport
from olx.errors import BlockedError

SEARCH_URL = "https://www.olx.ua/api/v1/offers/?offset=0&limit=40&query=iphone%2013"


@pytest.mark.network
def test_fetch_returns_bytes_with_impersonation():
    body = transport.fetch(SEARCH_URL)
    assert isinstance(body, bytes)
    assert len(body) > 0


@pytest.mark.network
def test_fetch_without_impersonation_is_blocked():
    # "Без impersonate" проверяем через голый httpx, а не через curl_cffi без
    # kwarg-а: живая проверка (сделана при реализации) показала, что curl_cffi
    # не блокируется CloudFront даже без явного impersonate="chrome" -- сама
    # библиотека уже несёт нестандартный TLS-стек. Заблокированный уровень —
    # именно httpx (S-01+02, Level 1: 403, тело 919 байт) -- он и доказывает,
    # что подмена отпечатка в fetch() условие работы, а не украшение.
    time.sleep(2)
    response = httpx.get(SEARCH_URL, timeout=30)
    assert response.status_code == 403

    with pytest.raises(BlockedError):
        transport._raise_for_status(response.status_code, SEARCH_URL)
