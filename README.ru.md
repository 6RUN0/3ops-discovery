# 3ops Discovery

Декларативный контракт автоматического обнаружения и настройки telemetry
targets в [Grafana Alloy](https://grafana.com/docs/alloy/) на основе
Docker labels. Приложение объявляет, как его собирать, метками вида
`ru.3ops.discovery.*` на своём контейнере — Alloy подхватывает их сам, без
правки конфигурации коллектора.

```yaml
services:
  orders-api:
    image: example/orders-api:latest
    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.metrics.enabled: "true"
      ru.3ops.discovery.metrics.type: "prometheus"
      ru.3ops.discovery.metrics.port: "8000"
      ru.3ops.discovery.metrics.job: "orders-api"
```

Namespace — reverse-DNS от домена `3ops.ru`. Префикс намеренно **не**
`x-`: Docker Compose трактует `x-`-ключ в `labels:`-маппинге как
extension и молча выбрасывает его, а reverse-DNS-ключ проходит и в
map-, и в list-форме.

## Что в репозитории

Репозиторий — это сам контракт, его референсная реализация и гейты,
которые связывают одно с другим и не дают им разойтись.

| Путь | Назначение |
|---|---|
| `docs/manifest.ru.md` | Нормативный контракт (русскоязычный). Единственный источник истины: имена меток, домены, профили, secret-контракт, требования безопасности, пин версии Alloy. |
| `alloy/*.alloy` | Референсная конфигурация Alloy: discovery, metrics, database, logs, log-profiles, outputs. |
| `tests/static/` | Статические гейты: сверяют нормативные факты манифеста с фактической конфигурацией в обе стороны. |
| `tests/e2e/` | End-to-end стек (`docker compose`): метрики и логи реально доходят до Prometheus и Loki; alloy/prometheus/loki мониторят сами себя через контракт (dogfooding). |
| `tools/materialize.py` | Сборка каталога конфигурации (base ∪ optional) для `alloy_check` и e2e. |
| `LICENSE` | Лицензия MIT. |

Манифест русскоязычный по замыслу; код, комментарии и коммиты —
английские.

## Требования

- [uv](https://docs.astral.sh/uv/) — единственный менеджер окружения.
- Python 3.13+.
- Docker — для гейтов `alloy_check` и `e2e`.
- Системные бинарники для `docs_lint`: `rumdl`, `typos`, `lychee`.

## Гейты качества

Всё запускается через `uv run nox`.

| Команда | Что делает | Нужен Docker / сеть |
|---|---|:---:|
| `uv run nox` | Гейты по умолчанию: `lint` + `docs_lint` + `alloy_check` + `tests`. | да |
| `uv run nox -s lint tests` | Полностью офлайн: pre-commit + статические гейты. | нет |
| `uv run nox -s lint` | pre-commit на всех файлах. | нет |
| `uv run nox -s docs_lint` | `rumdl` + `typos` + `lychee`. | сеть |
| `uv run nox -s alloy_check` | `alloy fmt -t` + `validate` для каждой комбинации каталогов внутри запиненного образа. | Docker |
| `uv run nox -s tests` | Статические гейты манифест↔конфиг + юниты мини-приложения. | нет |
| `uv run nox -s e2e` | Проверки доставки на живом compose-стеке (минуты). | Docker |
| `uv run nox -s preflight` | Всё сразу. | да |

Образ Alloy запинен **манифестом** (раздел 14); `noxfile.ALLOY_IMAGE`
обязан совпадать — это проверяет статический тест.

## Как это держится вместе

Статические гейты извлекают нормативные факты из `docs/manifest.ru.md`
(по якорям: номер раздела + позиция) и из `alloy/*.alloy` (regex-сканером),
затем сверяют их. Реструктуризация манифеста ломает гейты громко.
Расхождения, разрешённые сознательно, перечислены единой таблицей в
`tests/static/asymmetries.py`. Контрактные значения (интервалы скрейпа,
имена меток, дефолты) правятся только в манифесте — никогда «чтобы тест
позеленел».

## Основы контракта

- **Домены:** `metrics`, `database`, `logs`, `blackbox`, `otel`, `snmp`,
  `ipmi` — под ключами `ru.3ops.discovery.<domain>.<key>`.
- **Секреты** передаются не значением, а логическим идентификатором
  (`ru.3ops.discovery.database.secret-id`); сами секреты в labels и в git
  не попадают.
- **Env-параметризация** развёртывания — через префикс
  `RU_3OPS_DISCOVERY_*` (например `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL`),
  зеркалящий namespace меток.

Полное описание — в [`docs/manifest.ru.md`](docs/manifest.ru.md).

## Соглашения

- Conventional Commits, без AI-атрибуции в trailer'ах.
- Версии внешних артефактов (пакеты, образы, ревизии хуков) пинуются по
  живым источникам, не по памяти.
- Никаких секретов в git, даже фейковых: `*.dsn` и подобные генерируются
  фикстурами во временные gitignore-каталоги.
