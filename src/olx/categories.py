from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from olx.errors import ConfigError

TREE_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "olx-categories.json"


@lru_cache(maxsize=1)
def _tree() -> dict[int, dict]:
    # /list и /export зовут label() на каждый запрос -- без этой проверки владелец
    # получил бы голый FileNotFoundError из недр pathlib вместо понятной причины
    # и команды на исправление.
    if not TREE_PATH.exists():
        raise ConfigError(
            f"Справочник категорий не найден: {TREE_PATH}. "
            "Прогоните python scripts/refresh_categories.py"
        )
    raw = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def name(category_id: int) -> str | None:
    node = _tree().get(category_id)
    return node["name"] if node else None


def path(category_id: int) -> list[str]:
    """От корня к листу: ['Нерухомість', 'Квартири', 'Довгострокова оренда квартир']."""
    tree = _tree()
    parts: list[str] = []
    current = tree.get(category_id)
    # Ограничение на глубину -- страховка от цикла в чужих данных: справочник
    # обновляется скриптом из вёрстки OLX, целостность за нас никто не гарантирует.
    for _ in range(10):
        if current is None:
            break
        parts.append(current["name"])
        parent = current.get("parentId")
        current = tree.get(parent) if parent else None
    return list(reversed(parts))


def label(category_id: int) -> str:
    parts = path(category_id)
    if not parts:
        return f"раздел #{category_id}"
    # В кнопку Telegram влезает немного, а различает разделы именно хвост пути:
    # «Продаж квартир» и «Довгострокова оренда квартир» отличаются только им.
    return " › ".join(parts[-2:]) if len(parts) > 1 else parts[0]


def children(category_id: int | None) -> list[dict]:
    tree = _tree()
    if category_id is None:
        return sorted(
            (n for n in tree.values() if not n.get("parentId")), key=lambda n: n["name"]
        )
    node = tree.get(category_id)
    if not node:
        return []
    return [tree[c] for c in node.get("children") or [] if c in tree]
