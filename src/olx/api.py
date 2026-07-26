import json
import time
from urllib.parse import urlencode

from olx.errors import SchemaError
from olx.models import Filters
from olx.transport import fetch

PAGE_DELAY_SECONDS = 1.0

BASE_URL = "https://www.olx.ua/api/v1/offers/"


def build_search_url(query: str, filters: Filters, *, offset: int = 0, limit: int = 40) -> str:
    # sort_by=created_at:desc обязателен для скорости реакции (AC-4). Без сортировки
    # выдача идёт по релевантности, и свежее объявление попадает на первую страницу
    # только через 5-17 минут (замер по проду: медиана 14 мин, 0/8 в срок). С этой
    # сортировкой недавние объявления оказываются в топе выдачи сразу. Продвинутые
    # объявления OLX всё равно закрепляет сверху, но органика свежих 20 минут входит
    # в первые 40 позиций, которые читает быстрый режим.
    params: dict[str, str | int] = {
        "offset": offset,
        "limit": limit,
        "query": query,
        "sort_by": "created_at:desc",
    }
    if filters.price_from is not None:
        params["filter_float_price:from"] = filters.price_from
    if filters.price_to is not None:
        params["filter_float_price:to"] = filters.price_to
    if filters.city_id is not None:
        params["city_id"] = filters.city_id
    if filters.category_id is not None:
        params["category_id"] = filters.category_id
    if filters.state is not None:
        params["filter_enum_state[0]"] = filters.state.value
    if filters.owner_type is not None:
        # Не private_business: отвечает 200 и молча не фильтрует (S-05).
        params["owner_type"] = filters.owner_type.value

    return f"{BASE_URL}?{urlencode(params)}"


def search_raw(
    query: str, filters: Filters, *, offset: int = 0, limit: int = 40, proxy: str | None = None
) -> dict:
    url = build_search_url(query, filters, offset=offset, limit=limit)
    raw = fetch(url, proxy=proxy)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SchemaError(f"Ответ {url} не является JSON: {e}") from e


def _has_constraints(filters: Filters) -> bool:
    return any(
        value is not None
        for value in (
            filters.price_from,
            filters.price_to,
            filters.city_id,
            filters.category_id,
            filters.state,
            filters.owner_type,
        )
    )


def _raw_matches(item: dict, filters: Filters) -> bool:
    from olx.parse import matches_filters, parse_listing

    # SchemaError не глушим: поломка формата должна падать, а не выглядеть как
    # «страница не прошла фильтр» (R-8).
    return matches_filters(parse_listing(item), filters)


def search_all_pages(
    query: str, filters: Filters, *, max_pages: int, limit: int = 40, proxy: str | None = None
) -> list[dict]:
    items: list[dict] = []
    seen_ids: set = set()
    for page in range(max_pages):
        raw = search_raw(query, filters, offset=page * limit, limit=limit, proxy=proxy)
        data = raw.get("data")
        if not isinstance(data, list):
            raise SchemaError(f"'data' не список, а {type(data).__name__}")
        if not data:
            break
        # Выдача живая: между запросами страниц объявления сдвигаются между узлами
        # (contracts.md, S-07), и одно и то же id может попасть на две соседние
        # offset-страницы. Дедуп -- не оптимизация, а условие "без дублей на выходе".
        # Одно объявление может попасть на две соседние offset-страницы: выдача
        # сдвигается между запросами (S-07).
        fresh = []
        for item in data:
            item_id = item.get("id")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            fresh.append(item)

        # Исчерпав результаты, OLX не отдаёт пустую страницу, а добивает её
        # посторонними объявлениями в обход своих же фильтров. Поэтому конец выдачи
        # виден не по len(data) < limit и не по total_elements, а по странице,
        # где ничего не прошло проверку.
        if not _has_constraints(filters):
            items.extend(fresh)
        else:
            matching = [it for it in fresh if _raw_matches(it, filters)]
            items.extend(matching)
            if not matching:
                break
        if len(data) < limit:
            break
        if page + 1 < max_pages:
            time.sleep(PAGE_DELAY_SECONDS)
    return items
