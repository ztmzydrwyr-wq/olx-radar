import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from olx import notify
from olx.config import settings
from olx.models import Filters, Listing, NotifyMode, PollMode, Watch

# Ссылка собрана по реальному шаблону CDN (контракты, п.1.2), но id файла
# заведомо несуществующий -- Telegram не сможет её скачать. Это не гипотетический
# случай: OLX может сменить формат шаблона, и sendPhoto обязан деградировать,
# а не терять уведомление.
BROKEN_PHOTO_URL = "https://ireland.apollo.olxcdn.com:443/v1/files/does-not-exist-test-id/image;s=800x600"
GOOD_PHOTO_URL = "https://telegram.org/img/t_logo.png"


def _listing(**overrides) -> Listing:
    base = dict(
        id=900000001,
        url="https://www.olx.ua/d/obyavlenie/test-ID900000001.html",
        title="[ТЕСТ T-10] Айфон 13 Про, чохол в подарок — не бита",
        description="",
        price=15100,
        currency="UAH",
        negotiable=False,
        arranged=False,
        city_id=268,
        city_name="Київ",
        region_id=1,
        business=False,
        state=None,
        status="active",
        created_at=datetime.now(UTC),
        pushed_at=None,
        refreshed_at=None,
        photo_url=GOOD_PHOTO_URL,
        category_id=85,
        seller_id=1,
        seller_name="Тест",
    )
    base.update(overrides)
    return Listing(**base)


def _watch() -> Watch:
    return Watch(
        id=1,
        query="iphone 13",
        filters=Filters(),
        poll_mode=PollMode.FAST,
        notify_mode=NotifyMode.NEW,
    )


@pytest.mark.telegram
async def test_send_listing_delivers_via_send_photo():
    await asyncio.sleep(1)
    listing = _listing(title="[ТЕСТ T-10] карточка через sendPhoto, не реальная находка")
    await notify.send_listing(listing, _watch(), reason="new")


@pytest.mark.telegram
async def test_send_photo_rejects_broken_url_and_send_listing_falls_back():
    await asyncio.sleep(1)

    # Проверяем сам факт отказа Telegram отдельно от send_listing, иначе тест
    # "не упал" ничего не доказывает -- он прошёл бы и если бы sendPhoto молча
    # съел битую ссылку.
    async with httpx.AsyncClient(timeout=30.0) as client:
        ok = await notify._send_photo(
            client,
            settings.telegram_owner_id,
            BROKEN_PHOTO_URL,
            "[ТЕСТ T-10] проверка отказа sendPhoto",
        )
    assert ok is False

    listing = _listing(
        id=900000002,
        title="[ТЕСТ T-10] карточка с битым фото — должна дойти текстом",
        photo_url=BROKEN_PHOTO_URL,
    )
    await notify.send_listing(listing, _watch(), reason="pushup")


@pytest.mark.telegram
async def test_send_listing_without_photo_uses_send_message():
    await asyncio.sleep(1)
    listing = _listing(
        id=900000003,
        title="[ТЕСТ T-10] карточка без фото вообще",
        photo_url=None,
        price=None,
        arranged=True,
    )
    await notify.send_listing(listing, _watch(), reason="new")


@pytest.mark.telegram
async def test_send_alert_delivers():
    await asyncio.sleep(1)
    await notify.send_alert("[ТЕСТ T-10] send_alert — проверка канала, реальных находок нет")


def test_caption_keeps_cyrillic_and_marks_pushup():
    listing = _listing(price=None)
    caption = notify._caption(listing, _watch(), reason="pushup")
    assert "Айфон" in caption
    assert "Переподнято" in caption
    assert "Договорная" in caption


def test_caption_marks_new():
    listing = _listing()
    caption = notify._caption(listing, _watch(), reason="new")
    assert "Новое" in caption
    assert "15 100 UAH" in caption


def test_caption_escapes_html_in_title():
    listing = _listing(title="<script>alert(1)</script> & тест")
    caption = notify._caption(listing, _watch(), reason="new")
    assert "<script>" not in caption
    assert "&lt;script&gt;" in caption
