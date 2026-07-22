# Разворачивание на сервере

Проверено на Ubuntu 24.04, Python 3.12.

## Первая установка

```bash
sudo apt-get install -y python3-venv rsync    # PEP 668 запрещает ставить пакеты в системный python
mkdir -p /home/<user>/olx-monitor
```

С рабочей машины:

```bash
rsync -av --delete \
  --exclude .venv --exclude data --exclude .git --exclude __pycache__ \
  ./ <user>@СЕРВЕР:/home/<user>/olx-monitor/
scp .env proxies.txt <user>@СЕРВЕР:/home/<user>/olx-monitor/
```

На сервере:

```bash
cd /home/<user>/olx-monitor
python3 -m venv .venv
.venv/bin/pip install -e .
mkdir -p data

sudo cp deploy/olx-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now olx-monitor
```

## Проверка

```bash
systemctl status olx-monitor
journalctl -u olx-monitor -f
```

В Telegram бот должен отвечать на `/status`.

## Обновление

```bash
rsync -av --delete --exclude .venv --exclude data --exclude .git \
  ./ <user>@СЕРВЕР:/home/<user>/olx-monitor/
ssh <user>@СЕРВЕР 'cd /home/<user>/olx-monitor && .venv/bin/pip install -e . -q && sudo systemctl restart olx-monitor'
```

## Что где лежит

| Путь | Что |
|---|---|
| `/home/<user>/olx-monitor/.env` | секреты; в репозиторий не попадает |
| `/home/<user>/olx-monitor/data/olx.db` | база: запросы, объявления, история цен |
| `journalctl -u olx-monitor` | логи |

## Важное

**База данных живёт в `data/` и не переносится с рабочей машины.** В ней накопленная
история показов: если подложить чужую или удалить — монитор заново засеет выдачу
и замолчит до следующего действительно нового объявления.

**`ProtectHome=read-only` в юните — не украшение.** Процесс ходит в сеть по
недокументированному чужому API; ограничение записи всем, кроме `data/`, стоит
одной строки и снимает целый класс последствий, если что-то пойдёт не так.

**Один процесс на один токен бота.** Telegram отдаёт обновления только одному
получателю: если бот параллельно запущен на рабочей машине, сервер и она будут
перехватывать команды друг у друга через раз. Перед запуском на сервере локальный
процесс надо остановить.
