import json
from pathlib import Path

import pytest

from olx import bot, storage, texts
from olx.bot import OwnerOnly, _fmt_watch, build_dispatcher
from olx.config import settings
from olx.models import Filters, NotifyMode, PollMode

SAMPLE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample-response.json"


class _User:
    def __init__(self, uid):
        self.id = uid


async def _handler(event, data):
    return "handled"


@pytest.mark.asyncio
async def test_owner_passes():
    mw = OwnerOnly()
    data = {"event_from_user": _User(settings.telegram_owner_id)}
    assert await mw(_handler, object(), data) == "handled"


@pytest.mark.asyncio
async def test_stranger_is_dropped_silently():
    mw = OwnerOnly()
    for user in (_User(1), _User(settings.telegram_owner_id + 1), None):
        data = {"event_from_user": user}
        assert await mw(_handler, object(), data) is None


def test_dispatcher_builds():
    assert build_dispatcher() is not None


def test_bot_renders_cards_through_the_texts_module():
    # Раскладка карточки проверяется в test_texts.py; здесь достаточно убедиться,
    # что bot.py не завёл собственный формат в обход общего.
    assert _fmt_watch is texts.watch_card


def test_wizard_step_totals_cover_the_optional_category_step():
    # Шаг с разделом появляется не всегда: 8 вопросов без него, 9 с ним. Если счётчик
    # разъедется, владелец увидит «Шаг 9 из 8».
    assert "Шаг 9 из 9" in texts.step(9, 9, "Уведомления", "тело")
    assert "Шаг 8 из 8" in texts.step(8, 8, "Уведомления", "тело")


# --- /resume: не поднимать сломанные SchemaError запросы молча (T-27) --------
#
# Схема watches не различает «на паузе по воле владельца» и «остановлен монитором
# из-за SchemaError» -- обе дают enabled=0, и storage.py трогать здесь нельзя.
# Вместо чтения причины из БД /resume перепроверяет каждый приостановленный запрос
# живым вызовом api.search_raw + parse_search_response -- тем же способом, каким
# монитор и находит поломку формата.


class _FakeMessage:
    def __init__(self):
        self.sent: list[str] = []

    async def answer(self, text, **kwargs):
        self.sent.append(text)


@pytest.fixture
def db(tmp_path):
    storage.init_db(tmp_path / "resume.db")


@pytest.fixture
def sample():
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_resume_reports_nothing_to_do_when_all_watches_are_active(db):
    storage.add_watch("q", Filters(), PollMode.FAST, NotifyMode.NEW)
    message = _FakeMessage()

    await bot.cmd_resume(message)

    assert message.sent == ["Всё уже в работе."]


@pytest.mark.asyncio
async def test_resume_reactivates_a_watch_that_parses_cleanly_again(db, sample, monkeypatch):
    watch = storage.add_watch("q", Filters(), PollMode.FAST, NotifyMode.NEW)
    storage.update_watch(watch.id, enabled=False)
    monkeypatch.setattr(bot.api, "search_raw", lambda *a, **kw: sample)

    await bot.cmd_resume(_FakeMessage())

    assert storage.list_watches(enabled_only=False)[0].enabled


@pytest.mark.asyncio
async def test_resume_keeps_a_schema_broken_watch_paused_and_warns(db, monkeypatch):
    watch = storage.add_watch("q", Filters(), PollMode.FAST, NotifyMode.NEW)
    storage.update_watch(watch.id, enabled=False)
    # {"results": []} -- ровно та форма, которую поймало бы SchemaError у монитора:
    # ключа "data" нет, значит формат ответа сломан, а не выдача пуста.
    monkeypatch.setattr(bot.api, "search_raw", lambda *a, **kw: {"results": []})

    message = _FakeMessage()
    await bot.cmd_resume(message)

    assert not storage.list_watches(enabled_only=False)[0].enabled
    assert any("не включил" in text.lower() for text in message.sent)


@pytest.mark.asyncio
async def test_resume_does_not_block_on_a_transient_network_failure(db, monkeypatch):
    # Сбой сети/блокировка при проверке -- не то же самое, что поломка формата.
    # /resume не должен держать честно приостановленный владельцем запрос из-за
    # того, что OLX именно сейчас недоступен.
    watch = storage.add_watch("q", Filters(), PollMode.FAST, NotifyMode.NEW)
    storage.update_watch(watch.id, enabled=False)

    def _boom(*a, **kw):
        raise ConnectionError("сеть недоступна")

    monkeypatch.setattr(bot.api, "search_raw", _boom)

    await bot.cmd_resume(_FakeMessage())

    assert storage.list_watches(enabled_only=False)[0].enabled
