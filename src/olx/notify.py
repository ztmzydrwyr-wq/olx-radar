from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Literal

import httpx
from loguru import logger

from olx.config import settings
from olx.errors import OlxError
from olx.models import Listing, Watch

TELEGRAM_API = "https://api.telegram.org/bot{token}"
REQUEST_TIMEOUT = 30.0

# Подпись под фото в Telegram ограничена 1024 символами, и превышение -- это отказ
# всего sendPhoto, а не обрезка. Остальное в подписи занимает ~250, берём запас.
DESCRIPTION_LIMIT = 600

_BR_TAG = re.compile(r"<br\s*/?>\s*", re.IGNORECASE)


class _DescriptionTextParser(HTMLParser):
    """Извлекает текст из HTML, который возвращает OLX в description."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self._parts)


class NotifyError(OlxError):
    """Telegram отверг и sendPhoto, и sendMessage -- уведомление не ушло никуда."""


def _api_url(method: str) -> str:
    return f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/{method}"


def _price_line(listing: Listing) -> str:
    if listing.price is None:
        return "Договорная"
    price = f"{listing.price:,}".replace(",", " ")
    line = f"{price} {listing.currency or ''}".strip()
    return f"{line} (торг)" if listing.negotiable else line


def _short_description(text: str) -> str:
    # API OLX возвращает description как HTML: чаще всего <br />, иногда также
    # сущности и другие теги. Telegram не поддерживает <br>, а экранирование
    # без предварительной очистки показывает этот тег в сообщении буквально.
    # Сначала превращаем переносы в \n, затем оставляем только текст и лишь
    # после этого экранируем результат при сборке HTML-подписи.
    text = _BR_TAG.sub("\n", text)
    parser = _DescriptionTextParser()
    parser.feed(text)
    parser.close()
    text = parser.text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= DESCRIPTION_LIMIT:
        return text
    cut = text[:DESCRIPTION_LIMIT]
    # Рвём по последнему пробелу, чтобы обрезка не приходилась на середину слова.
    space = cut.rfind(" ")
    return (cut[:space] if space > DESCRIPTION_LIMIT // 2 else cut).rstrip(" ,.;:-") + "…"


def _caption(listing: Listing, watch: Watch, *, reason: Literal["new", "pushup"]) -> str:
    # title/city/query/description приходят с OLX или введены владельцем в боте --
    # не наша разметка, экранируем перед вставкой в текст с parse_mode=HTML.
    title = html.escape(listing.title)
    city = html.escape(listing.city_name)
    query = html.escape(watch.query)
    # Один и тот же listing может прийти по нескольким watch (дедуп в contracts.md
    # намеренно попарный) -- без имени запроса непонятно, почему пришла карточка.
    mark = "🔄 Переподнято" if reason == "pushup" else "🆕 Новое"

    body = [
        f"{mark} · запрос «{query}»",
        "",
        f"<b>{title}</b>",
        "",
        f"💰 {_price_line(listing)}",
        f"📍 {city}",
        f"🕐 {listing.created_at:%d.%m.%Y %H:%M}",
    ]
    if listing.description.strip():
        body += ["", html.escape(_short_description(listing.description))]
    body += ["", f'<a href="{listing.url}">Открыть на OLX</a>']
    return "\n".join(body)


async def _send_photo(
    client: httpx.AsyncClient, chat_id: int, photo_url: str, caption: str
) -> bool:
    response = await client.post(
        _api_url("sendPhoto"),
        data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML", "photo": photo_url},
    )
    return response.status_code == 200


async def _send_message(client: httpx.AsyncClient, chat_id: int, text: str) -> None:
    response = await client.post(
        _api_url("sendMessage"),
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
    )
    if response.status_code != 200:
        raise NotifyError(
            f"Telegram sendMessage вернул {response.status_code}: {response.text[:300]}"
        )


async def send_listing(listing: Listing, watch: Watch, *, reason: Literal["new", "pushup"]) -> None:
    caption = _caption(listing, watch, reason=reason)
    chat_id = settings.telegram_owner_id

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if listing.photo_url is not None:
            if await _send_photo(client, chat_id, listing.photo_url, caption):
                return
            # Ссылка на фото -- шаблон, подставленный в parse.py (контракты, п.1.2).
            # OLX может сменить его формат или файл может исчезнуть -- само
            # уведомление из-за этого теряться не должно.
            logger.warning(f"sendPhoto для {listing.id} отклонён Telegram, фоллбэк на sendMessage")
        await _send_message(client, chat_id, caption)


async def send_alert(text: str) -> None:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        await _send_message(client, settings.telegram_owner_id, text)
