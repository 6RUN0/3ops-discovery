# 3ops Discovery Manifest

**Статус:** Draft  
**Версия спецификации:** `0.3.0`  
**Namespace:** `ru.3ops.discovery.*`  
**История изменений:** [CHANGELOG.ru.md](../CHANGELOG.ru.md)

## 1. Назначение

`3ops Discovery` - декларативный mini-framework для автоматического обнаружения и настройки telemetry targets на основе Docker labels.

Контейнер описывает:

- какие сигналы нужно собирать;
- какой тип integration/exporter использовать;
- откуда забирать метрики или логи;
- как именовать target;
- где реализация должна искать секреты;
- какие дополнительные labels добавлять к telemetry.

Реализация:

1. обнаруживает контейнеры через Docker API;
2. фильтрует targets по labels;
3. нормализует metadata;
4. создаёт pipeline сбора метрик и логов;
5. отправляет метрики в хранилище, принимающее Prometheus remote_write (Prometheus, VictoriaMetrics, Mimir);
6. отправляет логи в Loki или VictoriaLogs;
7. не получает секреты непосредственно из Docker labels.

Контракт задаёт labels, поведение и результат в хранилище. Какой агент собирает телеметрию и как он настроен, контракт не задаёт: реализации перечислены в разделе [14](#14-реализации). Эталонная реализация - Grafana Alloy (раздел [14.4](#144-эталонная-реализация-alloy)).

## 2. Базовая модель

```text
Docker labels контейнера
    |
    v
домен (раздел 10)
    |
    v
реализация домена (раздел 14)
    |
    v
выходной протокол (раздел 14.2)
    |
    v
хранилище
```

Labels относят контейнер к доменам. Каждый домен на хосте обслуживает одна реализация; она собирает данные домена и отправляет их по выходному протоколу в хранилище: метрики - по Prometheus remote_write, логи - протоколом, который принимает хранилище логов. Домен snmp и хост-домены берут цели не из labels: snmp - из файла устройств, хост-домены - с самого хоста (раздел [10](#10-домены)).

## 3. Namespace и соглашение об именах

Все labels mini-framework начинаются с:

```text
ru.3ops.discovery.
```

Общий формат:

```text
ru.3ops.discovery.<domain>.<key>
```

Глобальные ключи могут не содержать `<domain>`:

```text
ru.3ops.discovery.enabled
ru.3ops.discovery.version
```

### 3.1. Правила именования

- Точки используются для иерархии.
- Имена ключей пишутся в lowercase.
- Составные имена внутри одного ключа используют дефис: `secret-id`.
- Один смысл не должен иметь несколько вариантов написания.
- Пароли, токены, приватные ключи и полные DSN запрещено хранить в labels.
- Значения labels всегда являются строками.

Пример:

```yaml
labels:
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.database.type: "postgres"
  ru.3ops.discovery.database.secret-id: "postgres-orders"
```

## 4. Нормализация ключей labels

Два ключа labels, которые совпадают после замены `.` и `-` на `_`, запрещены: из таких вариантов контракт объявляет только один.

Правило нужно, потому что реализации нормализуют ключи. Пример - Docker service discovery в Prometheus: label контейнера попадает в правила relabeling как meta-label, а точки, дефисы и другие неподходящие символы в его имени заменяются на `_`. Docker label

```text
ru.3ops.discovery.database.secret-id
```

становится частью имени meta-label как:

```text
ru_3ops_discovery_database_secret_id
```

Из-за этого следующие labels конфликтуют после нормализации:

```text
ru.3ops.discovery.database.secret-id
ru.3ops.discovery.database.secret.id
```

Использовать нужно только первый вариант.

## 5. Глобальные labels

### `ru.3ops.discovery.enabled`

Обязательный флаг участия контейнера в discovery для доменов metrics, database и blackbox: без `enabled == true` контейнер не попадает в pipeline этих доменов.

Объявление и чтение - разные вещи, и совпадают они не везде. Для доменов otel и ipmi label объявляется по тому же правилу, но реализации его не читают: у otel приёмник OTLP общий и статичный и не может соотнести push с объявившим контейнером (раздел [10.5](#105-domain-otel)), а у ipmi доменного pipeline нет вовсе: внешний exporter скрейпится как цель домена metrics (раздел [10.7](#107-domain-ipmi)). Для этих двух доменов `enabled` - инвентарное объявление намерения, а не управляющий флаг; требовать от реализации его чтения контракт не может.

Исключение: домен `logs` собирает stdout/stderr всех контейнеров по умолчанию и не требует этого label (см. раздел [10.3.1](#1031-политика-сбора-по-умолчанию)). Домен `snmp` управляется файлом устройств, а не Docker-labels (раздел [10.6](#106-domain-snmp)), поэтому глобальный `enabled` к нему неприменим.

Допустимые значения:

```text
true
false
```

### `ru.3ops.discovery.version`

Версия контракта labels.

Пример:

```yaml
ru.3ops.discovery.version: "0.2"
```

Если label отсутствует, применяется версия контракта, которую реализация принимает по умолчанию.

В версии `0.2` label зарезервирован: реализация обрабатывает все контейнеры по правилам `0.2`, каким бы ни было его значение. Валидация версии появится вместе с первым изменением, меняющим семантику labels (раздел [7](#7-версионирование-контракта)).

### `ru.3ops.discovery.instance`

Логическое имя экземпляра.

Используется как основной `instance` label, если domain-specific значение отсутствует.

Пример:

```yaml
ru.3ops.discovery.instance: "orders-postgres"
```

### `ru.3ops.discovery.environment`

Окружение. Перечень открытый и конфигурацией не валидируется (при недоверенных соседях по хосту его ограничивают allowlist-правилом, раздел [13.5](#135-доверие-к-labels)); рекомендуемые значения:

```text
production
staging
testing
development
```

### `ru.3ops.discovery.team`

Команда или владелец сервиса.

Пример:

```yaml
ru.3ops.discovery.team: "payments"
```

## 6. Common telemetry labels

### 6.1. Labels, добавляемые реализацией

Реализация должна добавлять к метрикам и логам следующие labels, если они доступны:

```text
instance
environment
team
container
compose_project
compose_service
host
collector
```

Значение `collector` - имя реализации из реестра раздела [14](#14-реализации): по нему видно, какая реализация собрала ряд или строку.

Необходимо избегать дублирования семантически одинаковых labels:

```text
env и environment
service и service_name
container и container_name
```

Рекомендуемые канонические имена:

```text
environment
service_name
instance
container
team
compose_project
compose_service
```

Логовый путь добавляет к этому набору `service_name`, `log_profile` и `source`; полный перечень допустимых индексируемых полей логов - раздел [6.2](#62-поля-логов), который нормирует кардинальность, а не состав. Единого места с перечнем эмитируемых labels нет по построению: метрики и логи имеют разные наборы, и раздел [6.2](#62-поля-логов) - нормативный источник для логов.

Label `container` берётся из метаданных Docker engine, `host` - из параметра деплоя `RU_3OPS_DISCOVERY_HOSTNAME`, по умолчанию hostname коллектора; ни один из них не задаётся labels контейнера, поэтому контейнер не может подменить их значения. Остальные labels декларируются самим контейнером (см. раздел [13.5](#135-доверие-к-labels)). Для логов набор дополнительно ограничен allowlist из раздела [6.2](#62-поля-логов).

Label `instance` относится к метрикам; для логов его аналогом служит `service_name` (см. раздел [10.3.5](#1035-labels)). Аналогия неполная и на неё нельзя опираться как на правило: `service_name` выводится только из `logs.service`, тогда как глобальный `instance` на логи не распространяется.

Идентичность серий по доменам. Dashboards и alert rules опираются именно на эти значения, поэтому они часть контракта, а не деталь реализации:

| Домен | `job` | `instance` | Дополнительно |
|---|---|---|---|
| metrics | из `metrics.job` (обязателен) | адрес target; переопределяется `instance` | — |
| database | тип СУБД (`database.type`) | `database.instance`, иначе глобальный `instance`, иначе `secret-id` | — |
| blackbox | константа `blackbox` | адрес пробы (`blackbox.address` или адрес контейнера) | `module` — тип пробы |
| snmp | константа `snmp` | адрес устройства | `device` — имя устройства; `snmp_profile` — имя профиля раздела [8.5](#85-snmp-профили) |
| host-metrics | константа `integrations/unix` - метка экспортёра | hostname коллектора | - |
| container-metrics | константа `integrations/cadvisor` - метка экспортёра | hostname коллектора | `container` - имя контейнера; `compose_project`, `compose_service` - из меток Compose |

В доменах host-metrics и container-metrics `job` и `instance` - осознанный пробел: `job` - константа экспортёра, а не значение из меток, `instance` - hostname коллектора (умолчание экспортёра, параметром `RU_3OPS_DISCOVERY_HOSTNAME` не задаётся). Совпадает с `host`, только пока параметр не задан или пуст; запросы, которые связывают эти домены с остальными, связывают их по `host`, а не по `instance`. Цель у этих доменов одна на коллектор, адреса цели у неё нет.

Домен blackbox — задокументированное исключение из правила раздела [5](#5-глобальные-labels) о глобальном `instance`: для пробы instance'ом является сама цель пробы, поэтому глобальное значение здесь не применяется и не переопределяет адрес. Объявленный `instance` у контейнера с blackbox-пробой относится к его собственным метрикам, а не к пробам.

### 6.2. Поля логов

Поля записи лога делятся на два класса: индексируемые задают поток, и по ним хранилище строит индекс; неиндексируемые хранятся при строке без индекса. Индексируемыми разрешено делать только низкокардинальные поля:

```text
service_name
environment
team
container
compose_project
compose_service
log_profile
host
collector
source
```

Индексируемые поля формируются только из discovery metadata и labels контейнера. Поля, извлечённые из содержимого строки, в индексируемые не продвигаются: содержимое подконтрольно приложению, и такое продвижение открывает подмену labels и неограниченную кардинальность потоков. По умолчанию `level` индексируемым не становится (его нет в allowlist выше, поле остаётся в списке ниже); развёртывание вправе продвигать его только при нормализации значения к ограниченному набору и с расширением allowlist.

Следующие поля должны оставаться в строке или в неиндексируемых полях:

```text
level
status
request_id
trace_id
user_id
session_id
client_ip
email
full_path
pid
```

Хранилища называют классы по-своему:

| Хранилище | Индексируемые поля | Неиндексируемые поля |
|---|---|---|
| Loki | stream labels | structured metadata |
| VictoriaLogs | stream fields | обычные поля записи |

Неиндексируемые поля не влияют на кардинальность, но размер их значений контролирует приложение. Размер ограничивают лимиты хранилища.

#### 6.2.1. Loki

Для фильтрации по уровню Loki 3.x самостоятельно вычисляет `detected_level` из содержимого строки и structured metadata.

Размер structured metadata ограничивает лимит Loki `max_structured_metadata_size`.

Structured metadata требует Loki 3.x со схемой v13 (TSDB) и включённым `allow_structured_metadata`. На более старой схеме push с metadata отклоняется целиком: профили с парсингом молча перестают доставлять строки, тогда как `raw-v1` продолжает работать - при частичной потере логов это первое, что стоит проверить.

## 7. Версионирование контракта

Версия контракта передаётся через:

```yaml
ru.3ops.discovery.version: "0.2"
```

Правила:

- patch-изменения не меняют смысл существующих labels;
- minor-изменения могут добавлять новые необязательные labels;
- major-изменения могут менять семантику или удалять поля;
- начиная с первого изменения, меняющего семантику labels, реализация должна явно задавать поддерживаемые версии (в `0.2` проверка зарезервирована, см. раздел [5](#5-глобальные-labels)).

Label версионирует смысл labels, а не текст спецификации: его major и minor сдвигаются по правилам выше, а не вслед за major.minor из шапки документа. Patch-изменения по определению не меняют семантику labels, поэтому label содержит только major и minor. Формат - `<major>.<minor>`, обе части десятичные без ведущих нулей: `^\d+\.\d+$`. Значения `0.2.0`, `v0.2` и `0.2-rc1` контракту не соответствуют; версия спецификации в шапке этого документа задаётся полным SemVer и с этим label не совпадает по формату намеренно.

Значение label сдвигается только вместе с изменением смысла labels. Новый необязательный label меняет смысл набора labels, поэтому сдвигает значение на следующую minor-версию. Minor-версия текста спецификации, которая смысл labels не меняет, значение label не трогает: контейнеры с `ru.3ops.discovery.version: "0.2"` остаются корректными.

Поведение при неподдерживаемой версии в `0.2` не определено, потому что проверка зарезервирована: реализация обязана принимать любое значение и не имеет права отбрасывать по нему target. Когда проверка появится, она обязана подчиняться правилу домена logs (раздел [10.3.4](#1034-неизвестный-профиль)): логи не теряются ни при какой версии, а отбрасывание по версии допустимо только для доменов с fail-closed-семантикой.

## 8. Профили

### 8.1. Общие правила

Профиль - имя заранее определённого и версионированного набора настроек. Allowlist профилей каждого домена задаёт манифест (разделы [8.2](#82-scrape-профили)-[8.5](#85-snmp-профили) и [10](#10-домены)).

- Значение `*.profile` выбирается только из allowlist, заданного манифестом; реализация домена обязана поддерживать весь allowlist своего домена.
- Label не является DSL или языком программирования pipeline: произвольные значения и списки стадий не поддерживаются.
- Имя профиля обязано содержать версию: суффикс `-vN`, полное имя из символов `[a-z0-9-]`.
- Изменение профиля может повлиять на labels, cardinality, timestamps, alert rules и Grafana queries, поэтому несовместимые изменения требуют нового имени профиля.

Пример версионирования:

```text
orders-api-v1
orders-api-v2
```

Запрещённый вариант:

```yaml
ru.3ops.discovery.logs.profile: "json,logfmt,raw"
```

### 8.2. Scrape-профили

Каденцию скрейпа цели задаёт профиль из ограниченного набора версионированных профилей. Произвольные interval/timeout из labels не поддерживаются.

Базовые профили:

```text
fast-v1:
  interval: 15s
  timeout: 10s

normal-v1:
  interval: 30s
  timeout: 10s

slow-v1:
  interval: 60s
  timeout: 15s
```

Выбираются через labels `ru.3ops.discovery.metrics.profile` и `ru.3ops.discovery.blackbox.profile`; по умолчанию `normal-v1`.

### 8.3. Log-профили

Log-профиль описывает полный конвейер обработки:

```text
parser
multiline
timestamp
labels
structured metadata
redaction
drop rules
message normalization
```

Перечень описывает объём понятия log-профиля, а не обязательства каждого профиля: базовые профили ниже реализуют parser, multiline и structured metadata. Стадии timestamp в базовых профилях нет: временем записи служит docker-таймстамп строки (момент записи приложением в stdout/stderr); таймстамп из содержимого строки не разбирается.

Базовые профили:

```text
raw-v1
  Не применять структурный parser.
  Сохранить исходную строку.

generic-json-v1
  Best-effort JSON parsing.
  При ошибке сохранить исходную строку.

generic-logfmt-v1
  Best-effort logfmt parsing.
  При ошибке сохранить исходную строку.

mixed-v1
  Попытаться определить JSON или logfmt для каждой строки.
  Неопознанные строки сохранить raw.

app-type-1-v1
  Условное имя-пример специализированного pipeline;
  реальные профили именуются по семейству приложений.

nginx-json-v1
  Пример специализированного pipeline для JSON access logs;
  базовым профилем не является (как и app-type-1-v1).

java-stacktrace-v1
  Multiline pipeline для Java stack traces.

python-stacktrace-v1
  Multiline pipeline для Python tracebacks.
```

Извлекаемые поля. Набор полей, попадающих в structured metadata, — часть определения профиля, а не деталь реализации: обещание версионирования из раздела [8.1](#81-общие-правила) означает, что две независимые реализации одного имени профиля дают одинаковые метаданные. Иначе `generic-json-v1` у одного вендора и у другого — разные вещи под одним именем.

| Профиль | Поля в structured metadata |
|---|---|
| `raw-v1` | — |
| `generic-json-v1` | `level`, `status`, `trace_id`, `request_id` |
| `generic-logfmt-v1` | `level`, `status`, `trace_id`, `request_id` |
| `mixed-v1` | `level`, `status`, `trace_id`, `request_id` (обе ветви) |
| `java-stacktrace-v1` | — |
| `python-stacktrace-v1` | — |

Наборы `generic-json-v1` и `generic-logfmt-v1` совпадают намеренно: профили отличаются форматом входа, а не составом извлекаемого. Отсутствующее в строке поле просто не появляется — это не ошибка разбора.

Предпосылка multiline-профилей. `java-stacktrace-v1` и `python-stacktrace-v1` опознают начало записи по префиксу времени в формате ISO-8601 (`2026-07-27T12:00:00` или с пробелом вместо `T`) в начале строки. Приложение, не печатающее такой префикс, не даёт НИ ОДНОЙ строки, опознанной как начало: весь поток склеивается в блоки по `max_lines` (128), границы которых к содержимому отношения не имеют. Это ограничение профиля, а не сбой: приложению без ISO-8601-префикса подходит `raw-v1` или специализированный профиль с собственным якорем. Raw-fallback раздела [10.3.3](#1033-raw-fallback) здесь не помогает — он рассчитан на ошибку парсера, а склейка ошибкой не является.

### 8.4. Database-профили

```text
basic-v1
standard-v1
extended-v1
```

Профили позволяют контролировать нагрузку и не принимать произвольные настройки из labels. Выбираются через `ru.3ops.discovery.database.profile`; по умолчанию `standard-v1`.

Database-профиль управляет объёмом сбора - какие ряды выдаются для СУБД, - а не каденцией скрейпа: scrape-профили раздела [8.2](#82-scrape-профили) относятся только к доменам `metrics` и `blackbox`. Каденция домена database фиксирована и профилем не выбирается: `interval: 60s`, `timeout: 10s`. Величина задана контрактом, и реализация задаёт её явно: наблюдаемое потребителем значение не может быть умолчанием стороннего продукта, которое сдвинется при его обновлении. Значение вне allowlist отбрасывает цель целиком (fail-closed) - как в доменах metrics и blackbox. Домен `logs` - единственное исключение и единственный домен, где неизвестный профиль цель не отбрасывает: логи не теряются, применяется `raw-v1` (раздел [10.3.4](#1034-неизвестный-профиль)). Правило fail-closed действует для всех доменов, кроме logs.

Состав профиля задан в рядах. Для пар тип/профиль, которые есть в каталоге рядов [`docs/series/database.yaml`](series/database.yaml) (раздел [14.3](#143-каталог-рядов) называет отсутствующие), каталог перечисляет ряды, которые профиль обязан выдавать (`present`), и ряды, которые он обязан выключать (`absent`). Например, postgres на `basic-v1` не выдаёт `pg_settings_max_connections`, а на `extended-v1` выдаёт `pg_long_running_transactions` и `pg_database_wraparound_age_datfrozenxid_seconds`. Несовместимое изменение состава рядов требует нового имени профиля (раздел [8.1](#81-общие-правила)).

Для всех пар, включая отсутствующие в каталоге, профили различаются семействами рядов. `up`, `<тип>_up` и ряды о работе самого экспортёра (длительность и успех скрейпа) выдаются на любом профиле, и правила ниже их не ограничивают.

- `postgres`: `basic-v1` не выдаёт `pg_settings_*`; `extended-v1` добавляет к `standard-v1` семейства `pg_database_wraparound_*`, `pg_long_running_transactions*`, `pg_process_idle_seconds*` (при наличии простаивающих соединений) и `pg_statio_user_indexes_*` (при наличии пользовательских индексов).
- `mysql`/`mariadb`: `basic-v1` из рядов о сервере выдаёт только ряды групп server status и server variables (`SHOW GLOBAL STATUS`, `SHOW GLOBAL VARIABLES`): `mysql_global_status_*`, `mysql_global_variables_*` и производные от них `mysql_version_info`, `mysql_transaction_isolation`, `mysql_galera_*`; `extended-v1` добавляет к `standard-v1` семейства `mysql_engine_innodb_*`, `mysql_info_schema_processlist_*` (при наличии потоков сервера, кроме соединения экспортёра) и `mysql_info_schema_auto_increment_column*` (при наличии таблиц со столбцом `AUTO_INCREMENT`).
- `redis`: `basic-v1` выдаёт только ряды `redis_*`; `extended-v1` добавляет к `standard-v1` ряды списка клиентов `redis_connected_client_*` (`CLIENT LIST`) и `redis_total_system_memory_bytes`.
- `mongodb`: `basic-v1` из рядов о сервере выдаёт только ряды diagnostic data (`getDiagnosticData`); `extended-v1` выдаёт те же ряды, что `standard-v1`.

Нагрузка монотонна: basic <= standard <= extended. Неравенство нестрогое: соседние профили одного типа могут выдавать одни и те же ряды. Любой профиль, включая `extended-v1`, работает на СУБД без расширений и специальных настроек сервера.

### 8.5. SNMP-профили

Domain-wide allowlist версионированных snmp-профилей. Дифференциатор - увеличенный `timeout` (30s) под медленные устройства; [§8.2](#82-scrape-профили) общий для `metrics`/`blackbox` и такого таймаута не даёт, поэтому snmp-профили вынесены отдельным семейством. Allowlist содержит один профиль; он действует на все устройства файла сразу: поля профиля у записи устройства нет.

SNMP-профили:

```text
snmp-standard-v1:
  interval: 60s
  timeout: 30s
```

Per-device выбор и >1 профиля — документированное будущее.

## 9. Secret contract

Label содержит только логический идентификатор:

```yaml
ru.3ops.discovery.database.secret-id: "postgres-orders"
```

Реализация строит путь:

```text
/run/alloy-secrets/postgres-orders.dsn
```

Содержимое файла:

```text
postgresql://alloy_monitor:secret@postgres-orders:5432/postgres?sslmode=disable
```

Формат содержимого `.dsn` зависит от типа БД:

| Тип | Формат |
|---|---|
| `postgres` | `postgresql://<user>:<password>@<host>:<port>/<db>?sslmode=...` |
| `mysql`, `mariadb` | `<user>:<password>@(<host>:<port>)/` (go-sql-driver DSN) |
| `redis` | `<host>:<port>` в `.dsn`; пароль — в отдельном файле `<secret-id>.redispass` |
| `mongodb` | `mongodb://<user>:<password>@<host>:<port>` |

Redis - исключение: адрес (`host:port`) несекретен и хранится в `.dsn`, а пароль - в отдельном файле секрета `<secret-id>.redispass`.

Требования:

- файл доступен только пользователю, от имени которого работает реализация;
- каталог монтируется read-only;
- реализация скрывает значение файла с credentials: в её API и экспортах вместо значения стоит маркер;
- `secret-id` проверяется регулярным выражением;
- `secret-id` не должен содержать `/`, `..`, пробелы и shell-символы.

Допустимый шаблон:

```regex
^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$
```

Контракт общий для доменов на Docker-labels; различается только доменный суффикс файла (snmp — файловый провайдер — исключение, см. [§10.6.1](#1061-snmp-auth)):

```text
database  /run/alloy-secrets/<secret-id>.dsn   (+ <secret-id>.redispass для type=redis)
snmp      /run/alloy-secrets/snmp_auths.yaml  (исключение, единый файл — см. §10.6.1)
ipmi      /run/alloy-secrets/<secret-id>.ipmi
```

Каталог `/run/alloy-secrets` — значение по умолчанию; он настраивается переменной `RU_3OPS_DISCOVERY_SECRETS_DIR` (раздел [14.1](#141-параметры-окружения)).

Правила валидации идентификатора и read-only монтирования одинаковы для всех доменов; сокрытие значения обязательно для файлов с credentials (адресный `.dsn` redis несекретен по построению, см. выше, и его значение не скрывается). Требования к защите от path traversal описаны в разделе [13.4](#134-secret-path-traversal).

Пространство `secret-id` - единый trust domain в пределах хоста: контракт не привязывает контейнер к конкретному секрету, и любой контейнер с валидным label может сослаться на любой существующий файл секрета. В каталог секретов хоста следует выкладывать только секреты, предназначенные контейнерам этого хоста; для разграничения команд используйте соглашение о префиксах `secret-id`. Префиксы - только соглашение для операторов: реализация их не проверяет, и технически каждый файл секрета на хосте доступен каждому контейнеру этого хоста. Следствие той же модели доверия: контейнер может определить существование файла секрета, объявив соответствующий `secret-id` и наблюдая появление exporter; содержимое секрета при этом не раскрывается. Привязка `secret-id` к identity контейнера - вне рамок версии `0.2` (раздел [16](#16-out-of-scope)).

Отсутствующий файл секрета: радиус поражения. `secret-id` приходит из Docker-label, то есть из недоверенного входа, поэтому важно, насколько далеко распространяется отказ при ссылке на несуществующий файл. Контракт не обещает, что отказ останется в пределах одного контейнера: радиус зависит от реализации и может захватить другие цели того же коллектора (радиус эталона - раздел [14.4.4](#1444-выполнение-контракта-эталоном)).

Практическое следствие: право запускать контейнеры на хосте может включать право остановить сбор с других целей на этом коллекторе. Мониторинг здоровья реализации обязателен и контрактом не заменяется.

Границы сокрытия секретов. Сокрытие обязательно в API и экспортах реализации, но сообщение об ошибке загрузки может процитировать фрагмент прочитанного значения (например `host:port` чужой БД). Практическое следствие: логи самого коллектора чувствительны и требуют того же обращения, что и секреты: их не следует отправлять туда, куда не отправляют секреты (см. раздел [13.2](#132-разрешено-хранить)).

Домен snmp — единственное задокументированное исключение из соглашения «один файл на `<auth-id>`»: его секрет — единый файл `snmp_auths.yaml` с именованными профилями внутри YAML (map `auths:`), а не отдельный файл на каждый `auth-id`. Регулярное выражение `secret-id` выше нормирует имена секрет-файлов доменов на Docker-labels и НЕ ограничивает ссылку-имя профиля `auth` файлового провайдера (раздел [10.6.1](#1061-snmp-auth)).

## 10. Домены

Определены следующие базовые домены:

```text
metrics
database
logs
blackbox
otel
snmp
ipmi
```

Один контейнер может одновременно объявлять несколько доменов.

Хост-домены:

```text
host-metrics
container-metrics
host-logs
```

Хост-домены не управляются метками, по умолчанию выключены и требуют deployment-привилегий.

### 10.1. Domain: metrics

Используется, когда приложение уже публикует Prometheus-compatible endpoint.

#### 10.1.1. Labels

| Label | Обязательный | Значение |
|---|---:|---|
| `ru.3ops.discovery.metrics.enabled` | Да | `true` |
| `ru.3ops.discovery.metrics.type` | Да | `prometheus` |
| `ru.3ops.discovery.metrics.port` | Да | Порт metrics endpoint |
| `ru.3ops.discovery.metrics.path` | Нет | По умолчанию `/metrics` |
| `ru.3ops.discovery.metrics.scheme` | Нет | `http` или `https`, по умолчанию `http` |
| `ru.3ops.discovery.metrics.job` | Да | Значение `job` |
| `ru.3ops.discovery.metrics.profile` | Нет | Scrape-профиль из allowlist; по умолчанию `normal-v1` |

Произвольные значения interval/timeout в labels не поддерживаются: параметры scrape задаются только выбором профиля (см. раздел [8.2](#82-scrape-профили)).

`metrics.scheme: https` предполагает сертификат, которому коллектор доверяет через системный trust store: канала доставки CA-материала у label-контракта нет (labels переносят только строки - та же модель, что у blackbox-модуля `tls_connect`, раздел [10.4](#104-domain-blackbox)), поэтому endpoint с self-signed сертификатом заскрейплен не будет. TLS-доверие для внутренних CA - кастомизация окружения: отдельная scrape-пара с `tls_config` (раздел [14.4.1](#1441-кастомизация)).

#### 10.1.2. Пример RabbitMQ

```yaml
services:
  rabbitmq:
    image: rabbitmq:4-management
    expose:
      - "15692"

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.instance: "rabbitmq-main"
      ru.3ops.discovery.environment: "production"

      ru.3ops.discovery.metrics.enabled: "true"
      ru.3ops.discovery.metrics.type: "prometheus"
      ru.3ops.discovery.metrics.port: "15692"
      ru.3ops.discovery.metrics.path: "/metrics"
      ru.3ops.discovery.metrics.job: "rabbitmq"
      ru.3ops.discovery.metrics.profile: "fast-v1"
```

Профиль задаёт каденцию скрейпа этой цели; реализация домена metrics поддерживает все базовые профили раздела [8.2](#82-scrape-профили).

### 10.2. Domain: database

Используется для СУБД, не публикующих Prometheus endpoint самостоятельно.

Поддерживаемые базовые типы:

```text
postgres
mysql
mariadb
redis
mongodb
```

Реализация домена database поддерживает каждый базовый тип.

`type` обозначает wire-протокол и exporter, а не вендора СУБД. Протокол-совместимые сборки метятся базовым типом, отдельный тип для них не вводится: Percona Server for MySQL и Percona XtraDB Cluster - `type: mysql`; Percona Server for MongoDB - `type: mongodb` (так же, как managed-СУБД вида RDS/Aurora MySQL). MariaDB - исключение: это самостоятельный тип, разделяющий mysql-exporter, потому что операторы воспринимают её как отдельный продукт.

`database.port` (и стандартный порт при его отсутствии) - селектор target, а не параметр подключения: значение сверяется с реальными приватными портами контейнера (fail-closed: target с несуществующим портом отбрасывается), тогда как адрес подключения экспортёра целиком определяется `.dsn` (раздел [9](#9-secret-contract)). Расхождение порта в label и в DSN контракт обнаруживать не требует.

Стандартные порты по типам (действуют, если `database.port` не задан):

| Тип | Порт |
|---|---|
| `postgres` | 5432 |
| `mysql` | 3306 |
| `mariadb` | 3306 |
| `redis` | 6379 |
| `mongodb` | 27017 |

#### 10.2.1. Labels

| Label | Обязательный | Значение |
|---|---:|---|
| `ru.3ops.discovery.database.enabled` | Да | `true` |
| `ru.3ops.discovery.database.type` | Да | Тип СУБД |
| `ru.3ops.discovery.database.port` | Нет | Стандартный порт по типу |
| `ru.3ops.discovery.database.instance` | Нет | Логическое имя БД |
| `ru.3ops.discovery.database.name` | Нет | Имя базы для подключения |
| `ru.3ops.discovery.database.user` | Нет | Monitoring user |
| `ru.3ops.discovery.database.secret-id` | Да | Логический идентификатор секрета (раздел [9](#9-secret-contract)) |
| `ru.3ops.discovery.database.sslmode` | Нет | Настройка TLS/SSL |
| `ru.3ops.discovery.database.profile` | Нет | Профиль сбора из allowlist; по умолчанию `standard-v1` |

`database.name`, `database.user` и `database.sslmode` - инвентарные labels (раздел [13.2](#132-разрешено-хранить)): для подключения реализация их не использует, все параметры подключения берутся только из `.dsn`; при расхождении label и DSN действует DSN. Идентичность серии: `instance` = `database.instance`, иначе глобальный `ru.3ops.discovery.instance` (раздел [5](#5-глобальные-labels)), иначе `secret-id` (синтезированный fallback); `job` = `database.type`.

#### 10.2.2. PostgreSQL example

```yaml
services:
  postgres-orders:
    image: postgres:18
    expose:
      - "5432"

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.environment: "production"
      ru.3ops.discovery.team: "orders"

      ru.3ops.discovery.database.enabled: "true"
      ru.3ops.discovery.database.type: "postgres"
      ru.3ops.discovery.database.port: "5432"
      ru.3ops.discovery.database.instance: "orders-db"
      ru.3ops.discovery.database.name: "postgres"
      ru.3ops.discovery.database.user: "alloy_monitor"
      ru.3ops.discovery.database.secret-id: "postgres-orders"
      ru.3ops.discovery.database.sslmode: "disable"
      ru.3ops.discovery.database.profile: "standard-v1"
```

#### 10.2.3. MariaDB example

```yaml
services:
  mariadb-billing:
    image: mariadb:latest
    expose:
      - "3306"

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.environment: "production"
      ru.3ops.discovery.team: "billing"

      ru.3ops.discovery.database.enabled: "true"
      ru.3ops.discovery.database.type: "mariadb"
      ru.3ops.discovery.database.port: "3306"
      ru.3ops.discovery.database.instance: "billing-db"
      ru.3ops.discovery.database.secret-id: "mariadb-billing"
```

### 10.3. Domain: logs

Используется для автоматического сбора и обработки Docker stdout/stderr.

#### 10.3.1. Политика сбора по умолчанию

Логи всех обнаруженных Docker-контейнеров собираются по умолчанию.

```text
label отсутствует:
  собирать stdout/stderr как raw

ru.3ops.discovery.logs.enabled=true:
  собирать stdout/stderr

ru.3ops.discovery.logs.enabled=false:
  явно исключить контейнер из сбора логов
```

Для логов `ru.3ops.discovery.enabled` не обязателен. Это сделано специально, чтобы контейнер без manifest-labels всё равно был виден в хранилище логов.

Строки контейнера с `ru.3ops.discovery.logs.enabled=false` не доставляются в хранилище. Как этого добиться, выбирает реализация: она может не открывать поток такого контейнера или читать поток и отбрасывать строки до отправки.

#### 10.3.2. `logs.profile`

`ru.3ops.discovery.logs.profile` — это имя заранее определённого pipeline-профиля из allowlist (см. разделы [8.1](#81-общие-правила) и [8.3](#83-log-профили)).

Пример:

```yaml
ru.3ops.discovery.logs.profile: "app-type-1-v1"
```

Значение не должно быть произвольным списком стадий: реализация выбирает профиль только из allowlist раздела [8.3](#83-log-профили).

#### 10.3.3. Raw fallback

Для любого профиля исходная строка должна сохраняться, если parser не смог её разобрать.

```text
profile=generic-json-v1
  JSON parse success → извлечь поля
  JSON parse error   → отправить raw

profile=app-type-1-v1
  profile match success → применить pipeline
  no match              → отправить raw

profile=raw-v1
  всегда отправлять raw
```

Pipeline не должен удалять нераспознанные строки без отдельной явно заданной политики.

#### 10.3.4. Неизвестный профиль

Если контейнер указывает профиль, которого нет в allowlist, реализация должна:

1. продолжить сбор логов;
2. применить `raw-v1`;
3. записать диагностическое сообщение в собственный лог коллектора;
4. по возможности увеличить внутреннюю метрику ошибок конфигурации discovery.

Неизвестный профиль не должен приводить к потере логов контейнера.

#### 10.3.5. Labels

| Label | Обязательный | Значение |
|---|---:|---|
| `ru.3ops.discovery.logs.enabled` | Нет | По умолчанию `true`; `false` отключает сбор |
| `ru.3ops.discovery.logs.profile` | Нет | По умолчанию `raw-v1` |
| `ru.3ops.discovery.logs.service` | Нет | Значение `service_name` |
| `ru.3ops.discovery.logs.stream-policy` | Нет | Профиль обработки stdout/stderr |
| `ru.3ops.discovery.logs.redaction-profile` | Нет | Идентификатор политики редактирования |
| `ru.3ops.discovery.logs.drop-profile` | Нет | Идентификатор политики фильтрации шума |

Отключение сбора — единственная в контракте fail-OPEN проверка, и это осознанно. Опт-аут срабатывает строго на литерале `false`; любое другое значение (`False`, `0`, `no`, опечатка) сбор НЕ отключает, и логи продолжают собираться. Направление отказа выбрано в пользу правила раздела [10.3.4](#1034-неизвестный-профиль): опечатка в label не должна приводить к тихой потере логов, а лишний сбор виден и обратим. Для всех остальных labels действует fail-closed (раздел [11](#11-validation-rules)).

Для версии `0.2` рекомендуется использовать один composite profile. Дополнительные `stream-policy`, `redaction-profile` и `drop-profile` зарезервированы для расширения и не обязательны к реализации: их семейства профилей в разделе [8](#8-профили) не определены.

#### 10.3.6. Примеры

Приложение с logfmt:

```yaml
services:
  orders-api:
    image: example/orders-api:latest

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.instance: "orders-api"
      ru.3ops.discovery.environment: "production"
      ru.3ops.discovery.team: "orders"

      ru.3ops.discovery.logs.profile: "generic-logfmt-v1"
      ru.3ops.discovery.logs.service: "orders-api"
```

Смешанный поток:

```yaml
services:
  legacy-worker:
    image: example/legacy-worker:latest

    labels:
      ru.3ops.discovery.logs.profile: "mixed-v1"
      ru.3ops.discovery.logs.service: "legacy-worker"
```

Профиль `mixed-v1` разбирает строку так (ветки взаимно исключающие, порядок применения на результат не влияет):

1. JSON parser — к строкам, начинающимся с `{`;
2. logfmt parser — к строкам, содержащим `level=`, `msg=` или `status=` в начале строки или после пробела, И не выглядящим как JSON;
3. остальные строки сохраняются raw.

Взаимное исключение ветвей нормативно, а не оптимизация: строка вида `{"msg":"raised level=high"}` подходит под обе эвристики, и без исключения результат зависел бы от порядка стадий — logfmt перезаписал бы значения, извлечённые JSON-парсером. Требование к якорю (`level=` в начале строки или после пробела, а не в любом месте) отсекает совпадения внутри слов и значений.

Определение формата является best-effort и не должно приводить к удалению исходной строки. Эвристики допускают ложные срабатывания: строка свободного текста, содержащая `level=` или `status=`, попадёт в logfmt parser; при ошибке разбора она сохраняется raw.

#### 10.3.7. Явное исключение контейнера

```yaml
services:
  load-generator:
    labels:
      ru.3ops.discovery.logs.enabled: "false"
```

Это рекомендуется только для:

```text
генераторов нагрузки
временных тестовых контейнеров
очень шумных sidecar
контейнеров с дублирующимися логами
```

### 10.4. Domain: blackbox

Используется для HTTP, TCP, ICMP и TLS checks.

#### 10.4.1. Labels

| Label | Обязательный | Значение |
|---|---:|---|
| `ru.3ops.discovery.blackbox.enabled` | Да | `true` |
| `ru.3ops.discovery.blackbox.module` | Да | Например `http_2xx`, `tcp_connect`, `icmp`, `tls_connect` |
| `ru.3ops.discovery.blackbox.scheme` | Нет | `http` или `https`; по умолчанию `http` |
| `ru.3ops.discovery.blackbox.address` | Нет | Хост проверки без схемы и без порта; по умолчанию адрес контейнера |
| `ru.3ops.discovery.blackbox.port` | Да | Порт проверки |
| `ru.3ops.discovery.blackbox.path` | Нет | HTTP path |
| `ru.3ops.discovery.blackbox.profile` | Нет | Scrape-профиль из allowlist; по умолчанию `normal-v1` |

Значение `module` должно входить в allowlist модулей blackbox exporter, заданный конфигурацией реализации. Произвольные модули из labels не принимаются.

`blackbox.address` содержит ТОЛЬКО хост (`example.com` или IP): ни схемы, ни порта, ни пути. Цель пробы собирается реализацией из `address`, `scheme`, `port` и `path` по-разному для каждого модуля, поэтому порт, записанный в сам `address`, привёл бы к цели с двумя портами. Формат цели пробы зависит от модуля: HTTP-модули получают URL `scheme://host:port/path`, TCP- и TLS-модули - `host:port`, ICMP-модули - только host. Каждая серия blackbox-проб несёт label `module` с именем использованного модуля.

Для ICMP-модулей значение `blackbox.port` в саму пробу не входит (у ICMP нет порта), но label остаётся обязательным и проходит ту же валидацию: объявленный порт должен совпадать с реальным экспонированным портом контейнера, иначе target отбрасывается. Правило действует и при внешнем `blackbox.address`: порт сверяется с приватными портами самого контейнера, поэтому проба с `address: example.com` и `port: 443` из контейнера, не экспонирующего порт 443, молча отбрасывается. Последствия `blackbox.address` для модели доверия — раздел [13.5](#135-доверие-к-labels).

ICMP-пробы не требуют дополнительных привилегий в типовой Docker-среде: стандартного набора capabilities (`NET_RAW`) либо непривилегированных ICMP-сокетов (Docker по умолчанию открывает `net.ipv4.ping_group_range` для всех групп) достаточно. В hardened-средах, где одновременно отброшен `NET_RAW` и сужен `ping_group_range`, ICMP-пробы работать не будут; выход - вернуть `cap_add: [NET_RAW]` или расширить `sysctls: net.ipv4.ping_group_range` у контейнера коллектора.

Модуль `tls_connect` проверяет успешность TLS handshake и отдаёт метрики срока действия сертификата (`probe_ssl_earliest_cert_expiry`, `probe_tls_version_info`), но намеренно не верифицирует цепочку доверия: у label-контракта нет канала доставки CA-материала в коллектор - labels переносят только строки. Проверка цепочки для внутренних CA - свойство конкретного окружения: она выполняется отдельным модулем с `ca_file` в конфигурации blackbox exporter, что выходит за рамки контракта.

#### 10.4.2. Example

```yaml
labels:
  ru.3ops.discovery.enabled: "true"

  ru.3ops.discovery.blackbox.enabled: "true"
  ru.3ops.discovery.blackbox.module: "http_2xx"
  ru.3ops.discovery.blackbox.scheme: "http"
  ru.3ops.discovery.blackbox.port: "8080"
  ru.3ops.discovery.blackbox.path: "/health"
  ru.3ops.discovery.blackbox.profile: "fast-v1"
```

### 10.5. Domain: otel

Используется для сервисов, отправляющих OTLP telemetry.

Приёмник слушает конвенциональные порты OTLP: `4317` (gRPC) и `4318` (HTTP). Значения зафиксированы контрактом и переменной окружения не параметризуются - в отличие от endpoint'ов раздела [14.1](#141-параметры-окружения), это не deployment-величина, а адрес, который отправители знают заранее: смена порта потребовала бы изменить конфигурацию каждого клиента. Развёртывание, которому нужен другой порт, меняет конфигурацию приёмника в реализации - это кастомизация, а не параметр.

#### 10.5.1. Labels

| Label | Обязательный | Значение |
|---|---:|---|
| `ru.3ops.discovery.otel.enabled` | Да | `true` |
| `ru.3ops.discovery.otel.protocol` | Да | `grpc` или `http` |
| `ru.3ops.discovery.otel.service` | Нет | Имя сервиса |
| `ru.3ops.discovery.otel.traces` | Нет | `true`/`false` |
| `ru.3ops.discovery.otel.metrics` | Нет | `true`/`false` |
| `ru.3ops.discovery.otel.logs` | Нет | `true`/`false` |

Этот домен в основном документирует ожидаемое поведение приложения. Реализация обычно поднимает общий OTLP receiver, а не отдельный receiver на каждый контейнер.

Флаг `otel.enabled` поэтому носит декларативный характер: он не управляет приёмом OTLP (receiver общий и статичен), а фиксирует намерение сервиса и используется для инвентаризации. Остальные labels домена декларативны по той же причине. Трейсы в `0.2` вне периметра: trace-экспорт отклоняется с явной ошибкой на стороне клиента, а не принимается молча.

OTLP-путь - исключение из провенанса раздела [6.1](#61-labels-добавляемые-реализацией): общий receiver статичен и не имеет Docker-метаданных, поэтому не производит provenance-labels `environment`/`team`/`container`. В индексируемые поля продвигается только allowlist-набор resource-атрибутов OTLP (раздел [6.2](#62-поля-логов)); остальную идентификацию задаёт само отправляющее приложение через resource-атрибуты.

### 10.6. Domain: snmp

Единственный домен, не управляемый Docker-labels: внешнее сетевое оборудование (коммутаторы, роутеры) не имеет контейнера, поэтому targets перечисляются в файле, а не открываются через discovery. Домен opt-in: по умолчанию выключен, и развёртывание включает его вместе с файлом устройств и файлом auth-профилей (раздел [10.6.1](#1061-snmp-auth)).

Файл устройств (`snmp_targets.yaml`) - список записей; каждое значение хранится строкой:

| Поле | Обязательный | Значение |
|---|---|---|
| `name` | нет | Человекочитаемое имя устройства (провенанс); при отсутствии вместо него используется `address`. Значение попадает в серии label'ом `device` (`instance` несёт адрес) |
| `address` | да | `host:port` SNMP-агента (проверяется присутствие) |
| `module` | да | Модуль snmp_exporter из allowlist, заданного конфигурацией реализации, например `if_mib` (интерфейсы) и `system` (идентичность и аптайм устройства: `sysUpTime`, `sysName`); перечень открытый, как в blackbox [10.4](#104-domain-blackbox). Одна запись - один модуль; устройству с несколькими модулями соответствует несколько записей с разными `name` |
| `auth` | да | Имя auth-профиля из [10.6.1](#1061-snmp-auth) (presence-проверка; резолвится экспортёром) |
| `environment` | нет | Provenance-label (пропускается как non-reserved) |
| `team` | нет | Provenance-label (пропускается как non-reserved) |

Поле устройства называется `auth` - ссылка по имени на auth-профиль (раздел [10.6.1](#1061-snmp-auth)); хранить такие имена вне секретов разрешает раздел [13.2](#132-разрешено-хранить). Секрет (SNMP community / SNMPv3 credentials) живёт только в `snmp_auths.yaml` (раздел [10.6.1](#1061-snmp-auth)), никогда в файле устройств.

Домен [10.7](#107-domain-ipmi) (ipmi) структурно похож, но в этой фазе остаётся доменом на Docker-labels (Out of scope для файлового провайдера).

#### 10.6.1. SNMP-auth

Auth-модель домена: именованные профили в `snmp_auths.yaml`, на которые устройство ссылается по имени через поле `auth`.

**Allowlist версий:** SNMPv2c и SNMPv3. В файле версия задаётся полем `version` - ЧИСЛОМ, а не строкой `v2c`/`v3`: `version: 2` означает v2c, `version: 3` - v3. Проверка только advisory: секрет-файл разбирает экспортёр, а discovery его не инспектирует. Единственная точка контроля в репозитории - статический валидатор auth-фикстуры (`tools/snmp_fixtures.py`, `validate_auths`): `version in {2, 3}` (НЕ диапазон экспортёра 1..3: SNMPv1 запрещён контрактом).

**Поля профиля по версии** (имена и типы — по `snmp_exporter` v0.29.0, struct `Auth`):

- `version: 2` (v2c): `community`.
- `version: 3` (v3): `username` и `security_level`, плюс поля, обязательные для выбранного уровня.

**Обязательные поля v3 по `security_level`** (сверх `username`):

```text
noAuthNoPriv:
authNoPriv: password | auth_protocol
authPriv: password | auth_protocol | priv_password | priv_protocol
```

**Enum-ы полей v3:**

```text
security_level: noAuthNoPriv | authNoPriv | authPriv
auth_protocol:  MD5 | SHA | SHA224 | SHA256 | SHA384 | SHA512
priv_protocol:  DES | AES | AES192 | AES192C | AES256 | AES256C
```

Экспортёр принимает и `context_name`; контракт его не использует.

**Размещение секрета:** файл устройств хранит только ИМЯ профиля; credentials лежат только в `snmp_auths.yaml`, значение которого реализация скрывает как секрет (раздел [9](#9-secret-contract)), и никогда в labels и не в списке устройств. Усиливает [13.1](#131-запрещено-хранить-в-docker-labels) (SNMP communities запрещены в labels); раздел [9](#9-secret-contract) трактует это как исключение из соглашения "один файл на `<auth-id>`". Проверяется только ПРИСУТСТВИЕ `auth`: формат имени не навязывается.

**Известное ограничение:** реализация, которая сохраняет встроенные auth-профили экспортёра, оставляет доступными небезопасный `public_v2` (community `public`, v2c) и `public_v1` (`version: 1`, вне allowlist `{2, 3}`); `auth: "public_v2"` разрешается успешно, потому что проверяется только присутствие имени, а не то, есть ли оно среди профилей. Сверку по имени контракт не требует (имена auth зависят от развёртывания) - задокументированный риск, как и односторонний module-гейт.

**Неизвестное имя auth** (опечатка, имени нет среди профилей) даёт ошибку на стороне экспортёра во время scrape, а НЕ drop на этапе discovery: discovery проверяет только присутствие `auth` и с секрет-файлом не сверяется. Задокументировано; отдельный e2e не добавляется.

### 10.7. Domain: ipmi

BMC/IPMI-мониторинг через внешний `ipmi_exporter` (или другой adapter). ipmi не самостоятельный механизм, а **частный случай домена [metrics](#101-domain-metrics)**: внешний exporter опрашивает BMC по IPMI и публикует Prometheus-endpoint, а коллектор скрейпит этот endpoint как обычный metrics-target. IPMI-специфичной конфигурации в коллекторе контракт не требует.

#### 10.7.1. Labels

```text
ru.3ops.discovery.ipmi.enabled
ru.3ops.discovery.ipmi.address
ru.3ops.discovery.ipmi.module
ru.3ops.discovery.ipmi.secret-id
ru.3ops.discovery.ipmi.profile
```

Labels описывают намерение (адрес BMC, модуль exporter, секрет, профиль), но роль коллектора сводится к тому, чтобы скрейпить HTTP-endpoint внешнего exporter: доменного pipeline в коллекторе, как у snmp ([10.6](#106-domain-snmp)), здесь нет. Все ipmi-labels в `0.2` - декларативные/инвентарные (ни одна реализация и ни один доменный pipeline их не читает); `ipmi.profile` ссылается на scrape-профили раздела [8.2](#82-scrape-профили): собственного семейства профилей у ipmi нет. Файл секрета: `/run/alloy-secrets/<secret-id>.ipmi` по общему контракту раздела [9](#9-secret-contract); credentials BMC потребляет сам exporter, а не коллектор.

Рекомендуемый путь - пометить контейнер `ipmi_exporter` labels домена [metrics](#101-domain-metrics) и скрейпить его metrics-pipeline коллектора.

## 11. Validation rules

Минимальные проверки перед созданием pipeline:

- `enabled == true` — кроме домена logs (см. раздел [10.3.1](#1031-политика-сбора-по-умолчанию)); для доменов otel и ipmi проверка неприменима: их labels декларативны и pipeline по ним не создаётся (раздел [5](#5-глобальные-labels));
- `version` поддерживается (в `0.2` проверка зарезервирована — см. раздел [5](#5-глобальные-labels));
- `domain.enabled == true`;
- `type` входит в allowlist;
- `port` является числом 1..65535;
- `profile` входит в allowlist профилей домена (раздел [8](#8-профили)) — кроме домена logs, где неизвестный профиль не отбрасывает контейнер, а приводит к `raw-v1` (раздел [10.3.4](#1034-неизвестный-профиль));
- `secret-id` соответствует allowlist regex;
- `path` начинается с `/`;
- `scheme` входит в allowlist.

Неизвестное значение `type` приводит к отбрасыванию target целиком (fail-closed) и по возможности отражается в собственном логе коллектора.

Пустое значение любого label эквивалентно отсутствию label: действует значение по умолчанию соответствующего домена, а пустые значения не попадают в серии.

У обязательных labels значения по умолчанию нет, поэтому для них то же правило означает отбрасывание: пустой обязательный label = отсутствующий обязательный label = target отбрасывается (fail-closed). Это не частный случай, а следствие: реализация обязана проверять присутствие непустого значения отдельно, потому что сравнение пустого объявленного порта с пустым портом из метаданных контейнера проходит успешно и цель проскакивает. Проверка присутствия обязательна для `metrics.port`, `metrics.job` и `blackbox.port`.

Проверка `port` выполняется fail-closed сверкой объявленного порта с реальными приватными портами контейнера: нечисловое, выходящее за диапазон или несуществующее значение приводит к отбрасыванию target.

Файловый провайдер snmp проверяет свои аналоги так же fail-closed: запись с `module` вне allowlist, без `auth` или без `address` отбрасывается построчно, остальные записи файла продолжают собираться. Сверка `port` с портами контейнера не применяется (контейнера нет). Синтаксически сломанный файл устройств целиком - другой режим отказа, не построчный: построчная проверка к нему неприменима, и его поведение задаёт реализация.

## 12. Lifecycle

### 12.1. Добавление target

1. Контейнер запускается с `ru.3ops.discovery.enabled=true` (домен logs - исключение: сбор по умолчанию, раздел [10.3.1](#1031-политика-сбора-по-умолчанию)).
2. Реализация обнаруживает контейнер и проверяет labels домена (раздел [11](#11-validation-rules)); контейнер, не прошедший проверку, target не становится.
3. Появляется target: реализация начинает скрейпить метрики или читать логи контейнера.
4. Метрики или логи начинают поступать в хранилище.

От запуска контейнера до появления target проходит до одного интервала `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` (раздел [14.1](#141-параметры-окружения)) плюс время обработки; первые ряды метрик приходят после первого скрейпа target по интервалу его профиля (раздел [8.2](#82-scrape-профили)).

### 12.2. Удаление target

1. Контейнер останавливается или удаляется.
2. Target пропадает: реализация прекращает его сбор не позже чем через один интервал `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` плюс время обработки.
3. Новые данные перестают поступать.
4. Исторические данные остаются в хранилище до окончания retention.

### 12.3. Изменение labels

Docker не позволяет изменять labels работающего контейнера. Изменения вступают в силу только после пересоздания контейнера с новыми labels.

## 13. Security requirements

Логи самого коллектора - чувствительные данные. Реализация пишет в них диагностику загрузки конфигурации, а она может содержать фрагменты прочитанных значений, включая скрытые (границы сокрытия - раздел [9](#9-secret-contract)). Домен logs по умолчанию собирает stdout/stderr всех контейнеров, включая контейнер самого коллектора (раздел [10.3.1](#1031-политика-сбора-по-умолчанию)): это осознанный выбор в пользу наблюдаемости коллектора, а не недосмотр. Если хранилище логов доверено меньше, чем каталог секретов, сбор логов коллектора отключают явным `ru.3ops.discovery.logs.enabled=false` на его контейнере.

### 13.1. Запрещено хранить в Docker labels

```text
пароли
API tokens
полные DSN
TLS private keys
SSH keys
SNMP communities
JWT
cookie/session values
```

### 13.2. Разрешено хранить

```text
secret-id
имя auth-профиля (snmp)
имя monitoring user
имя базы
порт
protocol
job
instance
environment
team
имя профиля (scrape/log/database)
metrics path
```

### 13.3. Docker socket

Реализация обращается к Docker API только на чтение: обнаруживает контейнеры, читает их метаданные и логи. Логи и метаданные контейнеров она получает только через Docker API; получать их из файлов `/var/lib/docker` запрещено. Для доступа к Docker API необходимо учитывать:

- read-only mount `/var/run/docker.sock` не делает Docker API строго read-only;
- доступ к Docker socket фактически является высокопривилегированным;
- рекомендуется socket proxy с разрешёнными только read endpoints;
- интерфейс коллектора не должен публиковаться наружу без аутентификации.

Socket proxy сужает привилегию, но не устраняет её. Allowlist прокси работает по секциям API, а не по отдельным путям: разрешив `/containers`, он разрешает ВСЕ GET-запросы этой секции, включая `/containers/{id}/json` (переменные окружения контейнера, то есть пароли, переданные через `environment`), `/containers/{id}/archive?path=/` (чтение произвольного файла из любого контейнера) и `/containers/{id}/export`. Иначе discovery работать не может: логи контейнеров читаются через ту же секцию. Практический вывод: коллектор с доступом к прокси равнозначен читателю секретов всех контейнеров хоста, и прокси следует держать во внутренней сети, недоступной нагрузкам: он снижает риск компрометации демона, а не риск чтения чужих данных.

Требование "коллектор не должен быть доступен из недоверенной Docker-сети" выполнимо не полностью, и это свойство модели, а не недосмотр конфигурации. Скрейп контейнера означает общую с ним сеть, поэтому коллектор всегда сосед тех, кого собирает: HTTP-сервер коллектора (его метрики и интерфейс) и opt-in OTLP-приёмник видны каждому контейнеру этой сети. Разделение сетей проблему не решает: чтобы скрейпить контейнер, коллектор обязан находиться в его сети. Практический вывод: недоверенные нагрузки отделяются не сетью, а отдельным коллектором; в общей сети следует исходить из того, что интерфейс коллектора доступен соседям, а с ним и конфигурация, которую он показывает (скрытые значения в ней заменены маркером, раздел [9](#9-secret-contract)).

### 13.4. Secret path traversal

`secret-id` обязательно валидируется до формирования пути (см. раздел [9](#9-secret-contract)).

Плохой пример:

```text
../../etc/shadow
```

Хороший пример:

```text
postgres-orders
```

### 13.5. Доверие к labels

Labels декларируются самим контейнером, поэтому право запускать контейнеры на хосте означает право объявлять любые значения `job`, `instance`, `team`, `environment`, `service_name`, `compose_project` и `compose_service` — в том числе чужие. Границы этого доверия:

- для доменов metrics и database SSRF исключён двумя условиями сразу, и второе так же обязательно, как первое. Адрес scrape строится только из IP-адреса самого контейнера в его Docker-сети и его приватного порта (для database - из файла секрета, который labels не выбирают за пределами `secret-id`), поэтому labels не могут перенаправить сбор на другой хост. Ответ scrape - тоже недоверенный вход: контейнер, ответивший `302` на link-local адрес, увёл бы туда следующий запрос от имени коллектора. Поэтому реализация не следует HTTP-редиректам при scrape; реализация, которая им следует, гарантию не даёт;
- домен blackbox - осознанное исключение: `blackbox.address` (раздел [10.4.1](#1041-labels)) направляет пробу на произвольный хост, а результат (`probe_success`, статус, срок сертификата) виден в метриках: контейнер получает oracle достижимости сети от имени коллектора. Порт пробы ограничен приватными портами самого контейнера, но контейнер сам объявляет свои expose-порты, поэтому при недоверенных соседях `blackbox.address` следует ограничивать allowlist-правилом;
- opt-in OTLP-приёмник домена otel слушает без аутентификации и не производит provenance-labels (раздел [10.5](#105-domain-otel)): сетевой доступ к его портам равен праву писать телеметрию с произвольной идентичностью; приёмник следует держать во внутренней сети или закрывать аутентифицирующим reverse-proxy;
- `container` добавляется из метаданных Docker engine, `host` - из параметра деплоя `RU_3OPS_DISCOVERY_HOSTNAME`, по умолчанию hostname коллектора; labels не задают ни один из них (раздел [6.1](#61-labels-добавляемые-реализацией));
- поэтому серии и потоки логов с подменёнными `job`/`team`/`service_name` всё равно несут честные `container` и `host` отправителя: они не сливаются с данными настоящего владельца и остаются отличимыми, но alert rules и dashboards, фильтрующие только по `team`/`job` без учёта `container`, увидят и подделанные данные;
- поля из содержимого логов не продвигаются в индексируемые поля (раздел [6.2](#62-поля-логов));
- при недоверенных соседях по хосту значения `team`/`environment`/`service_name` следует дополнительно ограничивать allowlist-правилами; контракт таких правил не задаёт;
- ограничение объёма telemetry контракт не задаёт: контейнер может создавать нагрузку объёмом логов и числом opt-in targets; защита — rate limits на стороне backend (лимиты Loki, ограничения remote_write endpoint).

## 14. Реализации

Реализация - агент со своей конфигурацией, который выполняет контракт для одного или нескольких доменов раздела [10](#10-домены). Имя реализации - значение метки `collector` (раздел [6.1](#61-labels-добавляемые-реализацией)).

| Реализация | Домены | Агент | Каталог |
|---|---|---|---|
| `alloy` | `metrics`, `database`, `logs`, `blackbox`, `otel`, `snmp`, `ipmi`, `host-metrics`, `container-metrics`, `host-logs` | Grafana Alloy, версия закреплена в разделе [14.4](#144-эталонная-реализация-alloy) | [`alloy/`](../alloy/), [`alloy-optional/`](../alloy-optional/) |

Домены одного хоста можно распределить между реализациями, но каждый домен на хосте обслуживает ровно один коллектор. Два коллектора одного домена (две разные реализации или два экземпляра одной) дают дубли рядов и строк, которые хранилище не отличит от настоящих данных, поэтому такое развёртывание - ошибка. Признак ошибки - ряды или потоки логов, различающиеся только значением `collector` или `host`, либо два запущенных коллектора одного домена на хосте; второй признак нужен, когда метки дублей совпадают целиком.

Реализация обязана для каждого своего домена:

- понимать метки и выполнять поведение разделов 3-11;
- выдавать ряды каталога рядов (раздел [14.3](#143-каталог-рядов));
- выполнять требования безопасности раздела [13](#13-security-requirements);
- понимать параметры окружения раздела [14.1](#141-параметры-окружения), относящиеся к её доменам и выходам.

Расхождения эталона с контрактом, которые допускают гейты, перечислены с причинами в одном месте: [`tests/static/asymmetries.py`](../tests/static/asymmetries.py).

### 14.1. Параметры окружения

Значения, зависящие от развёртывания, задаются переменными окружения; если переменная не задана, действует значение по умолчанию. Реализация обязана понимать параметры своих доменов и выходов. Префикс `RU_3OPS_DISCOVERY_` = 3ops Discovery.

| Переменная | Назначение | Default |
|---|---|---|
| `RU_3OPS_DISCOVERY_DOCKER_HOST` | Адрес Docker daemon | `unix:///var/run/docker.sock` |
| `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` | Интервал обновления списка targets | `30s` |
| `RU_3OPS_DISCOVERY_HOSTNAME` | Значение label `host` (раздел 6.1) | `hostname коллектора` |
| `RU_3OPS_DISCOVERY_SECRETS_DIR` | Каталог файлов секретов (см. [9](#9-secret-contract)) | `/run/alloy-secrets` |
| `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL` | Endpoint метрик (протокол Prometheus remote_write) | `http://prometheus:9090/api/v1/write` |
| `RU_3OPS_DISCOVERY_LOKI_PUSH_URL` | Endpoint логов (Loki push API) | `http://loki:3100/loki/api/v1/push` |
| `RU_3OPS_DISCOVERY_HOST_ROOTFS_PATH` | Точка монтирования корневой файловой системы хоста (домен `host-metrics`) | `/rootfs` |
| `RU_3OPS_DISCOVERY_HOST_PROCFS_PATH` | Точка монтирования procfs хоста (домен `host-metrics`) | `/host/proc` |
| `RU_3OPS_DISCOVERY_HOST_SYSFS_PATH` | Точка монтирования sysfs хоста (домен `host-metrics`) | `/host/sys` |
| `RU_3OPS_DISCOVERY_SNMP_TARGETS_FILE` | Путь к файлу устройств snmp (не секрет; домен `snmp`) | `/etc/alloy/snmp_targets.yaml` |

Параметры scrape-профилей (interval/timeout) переменными окружения не настраиваются: они являются частью контракта (см. [8.2](#82-scrape-профили)), а не deployment-конфигурацией.

### 14.2. Выходные протоколы и хранилища

Метрики реализация отправляет по протоколу Prometheus remote_write на адрес `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL`. Подходит любое хранилище, принимающее remote_write: Prometheus, Mimir, VictoriaMetrics, Thanos, Grafana Cloud.

Для логов контракт задаёт не протокол, а результат в хранилище: индексируемые и неиндексируемые поля раздела [6.2](#62-поля-логов) и поля профилей раздела [8.3](#83-log-профили). Протокол выбирает реализация (Loki push, нативный приём хранилища, OTLP) и объявляет хранилища, которые поддерживает. Через Loki push логи принимают и Loki, и VictoriaLogs: адрес в обоих случаях задаёт `RU_3OPS_DISCOVERY_LOKI_PUSH_URL`.

VictoriaLogs без флага `-loki.disableMessageParsing` разбирает JSON-строку, пришедшую через Loki push, на поля: в хранилище появляются поля сверх разделов 6.2 и 8.3, а `_msg` хранит уже не исходную строку. Развёртывание, которому нужны ровно поля контракта, запускает VictoriaLogs с этим флагом.

Учётные данные в URL (`https://user:pass@host`) не встраиваются: значение переменной - обычная строка и может попасть в интерфейс и логи коллектора. Если хранилище требует аутентификации, реализация берёт учётные данные из файла секрета, а не из URL.

Гарантий доставки строже at-least-once контракт не задаёт: перезапуск или пересоздание коллектора может повторно отправить историю логов и потерять неотправленные метрики. Сохранять состояние коллектора между пересозданиями - задача реализации.

### 14.3. Каталог рядов

Каталог рядов - нормативное машиночитаемое приложение к манифесту: имена и метки рядов каждого домена, одинаковые у всех реализаций этого домена. Он лежит в [`docs/series/`](series/): по файлу `<домен>.yaml` на каждый домен таблицы идентичности раздела [6.1](#61-labels-добавляемые-реализацией).

```yaml
domain: database
cells:
  postgres/basic-v1:
    identity: [job, instance, host, collector, container, compose_project, compose_service]
    present: [up, pg_up, pg_stat_activity_count]
    absent: [pg_settings_max_connections]
```

Ячейка - профиль или модуль домена: в `metrics` - `scrape`, в `database` - `<тип>/<профиль>`, в `blackbox` и `snmp` - имя модуля, в `host-metrics` - `node`, в `container-metrics` - `cadvisor`. `present` - ряды, которые реализация обязана выдавать, `identity` - метки, которые обязан нести каждый из них. `absent` - ряды, которые профиль обязан выключать; ключ допустим только в домене `database`, так раздел [8.4](#84-database-профили) выражается в рядах. Неизвестный ключ и пустой `present` - ошибка загрузки каталога: ячейка без обязательных рядов проходила бы любую проверку.

Каталог - нижняя граница: ряды и метки сверх него разрешены. Он фиксирует только имена рядов и меток, значения - нет. Смену смысла ряда при том же имени каталог не ловит: единицы и тип ряда (counter или gauge) в него не входят.

Каталог снимается с e2e-стека эталонной реализации на закреплённой версии (раздел [14.4](#144-эталонная-реализация-alloy)) и вычитывается сопровождающим. Пересборка нужна при каждой смене закреплённой версии и при обновлении любого экспортёра у второй реализации. Расхождение реализации с каталогом разрешается либо правкой каталога - это изменение контракта и запись в CHANGELOG, - либо строкой с причиной в [`tests/static/asymmetries.py`](../tests/static/asymmetries.py). Там же перечислены пары тип/профиль домена `database`, которых нет в каталоге: ни один e2e-контейнер их не запускает.

У логов рядов нет, отдельного каталога для них тоже нет: поля записей задают разделы [6.2](#62-поля-логов) и [8.3](#83-log-профили).

### 14.4. Эталонная реализация: Alloy

Эталонная реализация - конфигурация Grafana Alloy: базовые файлы в каталоге [`alloy/`](../alloy/), опциональные в [`alloy-optional/`](../alloy-optional/) (раздел [14.4.3](#1443-опциональные-файлы)). Все `*.alloy`-файлы каталога образуют одну конфигурацию и запускаются вместе:

```sh
alloy run --stability.level=experimental alloy/
```

Флаг `--stability.level=experimental` нужен блоку `foreach` в файле 030 (experimental в Alloy v1.21). Синтаксическая проверка без запуска:

```sh
docker run --rm -v "$PWD/alloy:/etc/alloy:ro" grafana/alloy:v1.21.2 \
  validate --stability.level=experimental /etc/alloy
```

Политика версии Alloy. Тег в команде выше нормативен: контракт проверен именно на нём, и он же обязан стоять в `noxfile.ALLOY_IMAGE` (сверяется статическим гейтом в обе стороны). Диапазон совместимых версий контракт не объявляет - не потому, что версии не важны, а потому что честно проверена ровно одна: обновление тега - изменение контракта и проходит те же гейты (`alloy fmt`, `validate` для всех комбинаций, e2e). Нижняя граница не указана намеренно: `foreach` экспериментален, а у экспериментальных блоков upstream не гарантирует ни стабильности синтаксиса, ни наличия в следующей версии.

Конфигурации без экспериментальных возможностей эталон не предлагает: `foreach` находится в базовом файле [`030_database.alloy`](../alloy/030_database.alloy), поэтому флаг `--stability.level=experimental` обязателен для всего эталона, а не только для домена database. Развёртывание, которому экспериментальные возможности недопустимы, исключает файл 030 целиком - вместе с доменом database; остальные домены от `foreach` не зависят.

| Файл | Содержимое |
|---|---|
| [`010_discovery.alloy`](../alloy/010_discovery.alloy) | `discovery.docker`: opt-in discovery для metrics/database и discovery всех контейнеров для логов |
| [`020_metrics.alloy`](../alloy/020_metrics.alloy) | Домен metrics: общий relabel (валидация + провенанс) и пара `discovery.relabel`/`prometheus.scrape` на каждый профиль раздела [8.2](#82-scrape-профили) |
| [`030_database.alloy`](../alloy/030_database.alloy) | Домен database: `foreach`-pipeline на тип СУБД, DSN из файла секрета, объём сбора по `database.profile` (раздел [8.4](#84-database-профили)) |
| [`035_blackbox.alloy`](../alloy/035_blackbox.alloy) | Домен blackbox: общий `discovery.relabel` + `prometheus.exporter.blackbox` (модули `http_2xx`/`tcp_connect`/`icmp`/`tls_connect`) и пара фильтр+scrape на каждый профиль раздела [8.2](#82-scrape-профили) |
| [`040_logs.alloy`](../alloy/040_logs.alloy) | Домен logs: relabel-правила и `loki.source.docker` |
| [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) | Profile dispatcher: `loki.process` с базовыми log-профилями |
| [`090_outputs.alloy`](../alloy/090_outputs.alloy) | Выходы: `prometheus.remote_write` и `loki.write` |

Порядок файлов, устройство профильных пар, fan-out targets по портам, хранение состояния и подключение хранилищ описаны в [`alloy/README.md`](../alloy/README.md).

#### 14.4.1. Кастомизация

Alloy сливает все `*.alloy`-файлы каталога в один граф компонентов (верхний уровень, нерекурсивно); имена компонентов уникальны глобально. Переопределить компонент базы нельзя: два объявления с одинаковым именем — ошибка загрузки, а не override. Кастомизация выполняется тремя способами:

- **overlay-каталог** - дополнительные файлы, добавляемые к базовому каталогу при материализации (раздел [14.4.3](#1443-опциональные-файлы)); базовый `alloy/` остаётся валидным и полным без них;
- **extension points** - стабильные экспорты базы, на которые overlay вправе ссылаться (раздел [14.4.2](#1442-extension-points));
- **env-параметризация** - deployment-значения через `RU_3OPS_DISCOVERY_*` (раздел [14.1](#141-параметры-окружения)).

Соглашения против коллизий: файлы репозитория используют числовые префиксы `0xx`, пользовательские overlay — `1xx` и выше; пользовательские имена компонентов — префикс `ext_`. Критерий границы base/optional: базовый `alloy/` содержит ровно то, что управляется discovery по Docker-labels; статичное, host-level или требующее deployment-привилегий выносится в optional.

Привилегированные overlay получают deployment-привилегии уровня хоста и наблюдают хост или все его контейнеры целиком, вне discovery-скоупа: [`070_host-metrics`](../alloy-optional/070_host-metrics.alloy) (host procfs/sysfs/rootfs), [`080_host-logs`](../alloy-optional/080_host-logs.alloy) (systemd journal), [`075_container-metrics`](../alloy-optional/075_container-metrics.alloy) (host cgroup namespace + `/sys/fs/cgroup:ro`; host PID namespace не требуется и не выдаётся). Выдача таких привилегий — осознанное deployment-решение, не дефолт. Формулировка «привилегии уровня хоста» конкретна: `070` монтирует корень файловой системы хоста (`/:/rootfs:ro`) ради `node_filesystem_*`, а это чтение ВСЕГО — `/etc/shadow`, приватных ключей SSH, слоёв `/var/lib/docker` вместе с содержимым остальных контейнеров. Смонтировать меньше нельзя: метрики файловых систем требуют видеть точки монтирования. Единственное, что референс маскирует отдельно, — сокет Docker (`/dev/null` поверх `/rootfs/var/run/docker.sock`), чтобы привилегия чтения не превратилась в привилегию управления демоном; всё остальное read-only и доступно. `080` даёт чтение системного журнала, `075` — статистику всех контейнеров хоста, включая не участвующие в discovery.

#### 14.4.2. Extension points

Публичный API базовой конфигурации: стабильные экспорты, на которые overlay-файл вправе ссылаться. Стабильны в пределах minor-версии контракта; переименование — ломающее изменение.

| Экспорт | Компонент |
|---|---|
| `prometheus.remote_write.default.receiver` | [`090_outputs.alloy`](../alloy/090_outputs.alloy) |
| `loki.write.default.receiver` | [`090_outputs.alloy`](../alloy/090_outputs.alloy) |
| `loki.process.docker_profiles.receiver` | [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) |
| `discovery.docker.containers.targets` | [`010_discovery.alloy`](../alloy/010_discovery.alloy) |
| `discovery.docker.docker_logs.targets` | [`010_discovery.alloy`](../alloy/010_discovery.alloy) |

#### 14.4.3. Опциональные файлы

Каталог [`alloy-optional/`](../alloy-optional/) — overlay-файлы, добавляемые к базовому каталогу при материализации. Базовый `alloy/` валиден без них.

| Файл | Содержимое |
|---|---|
| [`060_otel.alloy`](../alloy-optional/060_otel.alloy) | Opt-in OTLP receiver: `otelcol.receiver.otlp` → метрики в `prometheus.remote_write`, логи в `loki.write` через allowlist-processor |
| [`070_host-metrics.alloy`](../alloy-optional/070_host-metrics.alloy) | Opt-in host-метрики: `prometheus.exporter.unix` (серии `node_*`) -> `prometheus.remote_write`; rootfs/procfs/sysfs через `RU_3OPS_DISCOVERY_HOST_*`; провенанс [§6.1](#61-labels-добавляемые-реализацией): `host`/`collector` добавляет `discovery.relabel` перед scrape |
| [`075_container-metrics.alloy`](../alloy-optional/075_container-metrics.alloy) | Opt-in per-container метрики: `prometheus.exporter.cadvisor` (серии `container_cpu_*`/`container_memory_*`/`container_network_*`; `container_fs_*` вне периметра) -> `prometheus.remote_write`. Docker API - через `docker_host` (реюз `RU_3OPS_DISCOVERY_DOCKER_HOST`, socket-proxy: GET-allowlist разделов `CONTAINERS`/`INFO`/`VERSION`/`PING` достаточен); при недоступном Docker API вывод практически пуст (`docker_only`). Провенанс [§6.1](#61-labels-добавляемые-реализацией): allowlisted container-labels -> `environment`/`team`/`compose_*`, `name` -> `container`; сырые `container_label_*`/`id`/`name` отбрасываются; `instance` = hostname коллектора, `job` = `integrations/cadvisor` (метка экспортёра; оба - осознанные gap'ы). Кардинальность: `store_container_labels = false` + allowlist, root-cgroup-статистика отключена, `disabled_metrics`/`enabled_metrics` - tunable. Привилегии деплоя (host cgroup namespace) - раздел [14.4.1](#1441-кастомизация); per-container opt-out не поддерживается. |
| [`080_host-logs.alloy`](../alloy-optional/080_host-logs.alloy) | Opt-in host-логи: `loki.source.journal` (systemd journal) -> `loki.write`; статические labels `host`/`collector`/`source` (в [§6.2](#62-поля-логов) allowlist) |
| [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) | Домен snmp (opt-in overlay): файловый провайдер (`local.file` + `encoding.from_yaml`), `prometheus.exporter.snmp` (модули `if_mib`/`system`, профиль `snmp-standard-v1`), auth из inline `config`-секрета (`local.file` `is_secret`) через merge. Включается только вместе с device/auth-файлами (top-level `local.file` без файла unhealthy). |

#### 14.4.4. Выполнение контракта эталоном

Разделы контракта формулируют требования без имени реализации. Здесь по разделам собрано, как их выполняет Alloy; новых требований этот список не добавляет.

- [§2](#2-базовая-модель): граф компонентов эталона - Docker labels -> `discovery.docker` -> `discovery.relabel` -> `foreach` / `prometheus.scrape` / `loki.source.docker` -> `prometheus.remote_write` / `loki.write`.
- [§4](#4-нормализация-ключей-labels): `discovery.docker` отдаёт label контейнера как `__meta_docker_container_label_<имя>`, заменяя в имени точки, дефисы и прочие неподходящие символы на `_`; label `ru.3ops.discovery.database.secret-id` конфигурация читает как `__meta_docker_container_label_ru_3ops_discovery_database_secret_id`.
- [§5](#5-глобальные-labels): label `ru.3ops.discovery.version` эталон не читает и обрабатывает все контейнеры по правилам `0.2`.
- [§6.1](#61-labels-добавляемые-реализацией): `collector` равен `alloy`; каждый файл, выдающий ряды или потоки, кроме [`060_otel.alloy`](../alloy-optional/060_otel.alloy), вычисляет `host` как `coalesce(sys.env("RU_3OPS_DISCOVERY_HOSTNAME"), constants.hostname)`, поэтому незаданный или пустой параметр даёт hostname контейнера Alloy. OTLP-путь - исключение из провенанса (раздел [10.5](#105-domain-otel)): его ряды и потоки не несут ни `host`, ни `collector`.
- [§6.2](#62-поля-логов): логи уходят через `loki.write` по Loki push API, и в Loki, и в VictoriaLogs; индексируемые поля становятся stream labels, неиндексируемые - structured metadata (`stage.structured_metadata` в [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy)). `level` эталон в stream labels не продвигает, значения structured metadata не усекает.
- [§8.1](#81-общие-правила): имена профильных компонентов выводятся из имени профиля механически ([`alloy/README.md`](../alloy/README.md#layered-profile-pairs)), отсюда алфавит `[a-z0-9-]`.
- [§8.2](#82-scrape-профили): у одного `prometheus.scrape` общие `scrape_interval` и `scrape_timeout`, поэтому каждый профиль получает свою пару `discovery.relabel`/`prometheus.scrape` ([`020_metrics.alloy`](../alloy/020_metrics.alloy)); scrape-компонент на пользовательское значение не создаётся.
- [§8.4](#84-database-профили): профили отображаются на коллекторы экспортёров ([`030_database.alloy`](../alloy/030_database.alloy)):
  - `postgres`: `basic-v1` - умолчания экспортёра без `pg_settings` (`disable_settings_metrics`); `standard-v1` - умолчания экспортёра; `extended-v1` - `enabled_collectors` из 11 коллекторов, включённых по умолчанию в закреплённом форке экспортёра (`database`, `locks`, `replication`, `replication_slot`, `roles`, `stat_bgwriter`, `stat_database`, `stat_progress_vacuum`, `stat_user_tables`, `statio_user_tables`, `wal`), и четырёх дополнительных (`database_wraparound`, `long_running_transactions`, `process_idle`, `statio_user_indexes`): непустой список заменяет набор по умолчанию, а не дополняет его.
  - `mysql`/`mariadb`: `basic-v1` - `global_status`, `global_variables`; `standard-v1` - шесть коллекторов по умолчанию, закреплённых явно в `set_collectors`; `extended-v1` - они же плюс `engine_innodb_status`, `info_schema.processlist`, `auto_increment.columns`.
  - `redis`: `basic-v1` - `redis_metrics_only`; в закреплённой версии флаг убирает только `redis_exporter_build_info` из внутреннего реестра экспортёра, который Alloy не отдаёт, а рядов вне `redis_*` Alloy не выдаёт и без него (`include_exporter_metrics = false`), поэтому по рядам `basic-v1` совпадает со `standard-v1`; `standard-v1` - умолчания экспортёра; `extended-v1` - умолчания плюс `export_client_list` и `incl_system_metrics`.
  - `mongodb`: `basic-v1` - только diagnostic data (`serverStatus`, `enable_diagnostic_data`); `standard-v1` и `extended-v1` - `collect_all` и явные флаги `enable_*`, равные тем, что включает `collect_all`: без них первый скрейп каждого экспортёра неполон. `extended-v1` равен `standard-v1`, потому что умолчание mongodb-экспортёра уже максимальное.
- [§8.5](#85-snmp-профили): файловый провайдер даёт один `prometheus.exporter.snmp` и один `prometheus.scrape`, поэтому профиль `snmp-standard-v1` действует на весь домен.
- [§9](#9-secret-contract): файл секрета читает `local.file` по пути `coalesce(sys.env("RU_3OPS_DISCOVERY_SECRETS_DIR"), "/run/alloy-secrets")` + `/<secret-id>.<суффикс>`; сокрытие даёт `is_secret = true`, и в API Alloy и экспортах компонентов значение отдаётся как `(secret)`. Адресный `.dsn` redis читается с `is_secret = false`: аргумент `redis_addr` экспортёра принимает обычную строку, а не секрет; пароль из `.redispass` передаётся через `redis_password`.
- [§9](#9-secret-contract), граница сокрытия: при несовпадении типа и содержимого файла сообщение об ошибке загрузки конфигурации Alloy может процитировать фрагмент прочитанного значения. Это поведение Alloy, и конфигурацией его не изменить.
- [§9](#9-secret-contract), радиус отказа: в домене database отсутствующий файл секрета уносит ВЕСЬ `foreach`-блок своего типа СУБД. Контейнер с валидным по регулярному выражению `secret-id` без файла за ним роняет вычисление блока целиком, и легитимные базы ТОГО ЖЕ типа перестают собираться вместе с ним; базы других типов живут в собственных блоках и не затрагиваются. Отказ обратим: после удаления контейнера блок восстанавливается сам. Прочтение "`local.file` создаётся на каждую итерацию, значит и отказ поитерационный" неверно: это проверено воспроизведением, а не выведено из устройства `foreach`. Разграничение по типам - не защита, а побочный эффект структуры конфигурации; здоровье компонентов Alloy требует мониторинга. Top-level `local.file` (файловый провайдер snmp, раздел [10.6](#106-domain-snmp)) локализации не имеет вовсе: его путь задаёт оператор, и отсутствие файла роняет граф каскадом, поэтому overlay 037 загружается только вместе со своими файлами.
- [§10](#10-домены): хост-домены эталон поставляет опциональными файлами раздела [14.4.3](#1443-опциональные-файлы): host-metrics - [`070_host-metrics.alloy`](../alloy-optional/070_host-metrics.alloy), container-metrics - [`075_container-metrics.alloy`](../alloy-optional/075_container-metrics.alloy), host-logs - [`080_host-logs.alloy`](../alloy-optional/080_host-logs.alloy).
- [§10.2](#102-domain-database): каждый тип обслуживает экспортёр Alloy: `prometheus.exporter.postgres`, `prometheus.exporter.mysql` (он же для `mariadb`), `prometheus.exporter.redis`, `prometheus.exporter.mongodb`. Порт сверяется правилом `keepequal` с `__meta_docker_port_private`; расхождение порта в label и в DSN эталон не обнаруживает.
- [§10.3.1](#1031-политика-сбора-по-умолчанию): эталон исключает контейнер до источника: `discovery.relabel` отбрасывает цель с `logs.enabled=false`, и `loki.source.docker` поток этого контейнера не открывает. Цепочка: `discovery.docker` (все контейнеры) -> `discovery.relabel` (исключает только `logs.enabled=false`) -> `loki.source.docker` -> `loki.process` (диспетчер профилей) -> `loki.write`.
- [§10.3.4](#1034-неизвестный-профиль): пункты 1-2 эталон выполняет allowlist-правилом в `discovery.relabel`, которое заменяет неизвестный профиль на `raw-v1`. Пункты 3-4 эталон не выполняет: на уровне relabel диагностическое сообщение и метрика недоступны.
- [§10.3.5](#1035-labels): labels `stream-policy`, `redaction-profile` и `drop-profile` эталон не читает.
- [§10.4](#104-domain-blackbox): allowlist модулей - `http_2xx`, `tcp_connect`, `icmp`, `tls_connect`; его задают keep-правило `discovery.relabel` и inline `config` компонента `prometheus.exporter.blackbox` ([`035_blackbox.alloy`](../alloy/035_blackbox.alloy)).
- [§10.5](#105-domain-otel): приёмник - `otelcol.receiver.otlp` в overlay [`060_otel.alloy`](../alloy-optional/060_otel.alloy); другой порт - правка этого overlay, кастомизация раздела [14.4.1](#1441-кастомизация). Выхода traces у приёмника нет, поэтому trace-экспорт отклоняется. Из resource-атрибутов OTLP в индексируемые поля продвигается только `service.name` -> `service_name`.
- [§10.6](#106-domain-snmp): домен поставляется overlay-файлом [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) (раздел [14.4.3](#1443-опциональные-файлы)), а не базовым: его top-level `local.file` без файла на диске становится unhealthy и каскадно роняет граф, поэтому overlay загружается только вместе с файлом устройств и файлом auth-профилей. Файл устройств `encoding.from_yaml` декодирует в `list(map(string))`. `prometheus.exporter.snmp` требует `name` у каждой записи, поэтому при отсутствии `name` конфигурация подставляет `address`. Allowlist модулей эталона - `if_mib` и `system`.
- [§10.6.1](#1061-snmp-auth): `snmp_auths.yaml` подаётся в `prometheus.exporter.snmp` как inline `config` из `local.file` с `is_secret = true` и сливается (`merge`) со встроенными auth-профилями экспортёра; конфигурация Alloy содержимое файла не инспектирует. Поэтому встроенные `public_v2` и `public_v1` эталона доступны, а `discovery.relabel` проверяет только присутствие `auth` (`keep auth != ""`) и свериться с секрет-файлом не может.
- [§10.7](#107-domain-ipmi): у Alloy нет нативного IPMI-компонента, в отличие от snmp со встроенным `prometheus.exporter.snmp`, поэтому ipmi-overlay эталон не поставляет. Отдельный overlay появится, только если Alloy получит нативный IPMI-компонент.
- [§11](#11-validation-rules): проверки `path`, `scheme`, `profile` и `secret-id` - правила `discovery.relabel`; метку с пустым значением relabel удаляет. Проверка `port` неявная: `keepequal` сверяет объявленный порт с `__meta_docker_port_private`. Сравнение двух пустых строк проходит, поэтому присутствие `metrics.port`, `metrics.job` и `blackbox.port` проверяют явные keep-правила с регулярным выражением `(.+)`. Файловый провайдер snmp ([`037_snmp.alloy`](../alloy-optional/037_snmp.alloy)) проверяет `module`, `auth` и `address` keep-правилами `discovery.relabel` поверх списка из `encoding.from_yaml`. Синтаксически сломанный файл устройств целиком ломает `from_yaml`, и Alloy удерживает последние валидные аргументы: targets не меняются (режим **fail-STALE**, а не fail-closed и не пустой список). На холодном старте последнего валидного значения нет, поэтому `discovery.relabel` unhealthy, а набор targets пуст (экспортёр стартует на нуле устройств, healthy-idle). Построчный drop (семантика) и fail-STALE всего файла (синтаксис) - два разных режима.
- [§12](#12-lifecycle): `discovery.docker` обнаруживает контейнер, `discovery.relabel` проверяет labels домена, для домена database `foreach` создаёт pipeline; target виден в UI Alloy. При удалении контейнера `foreach`-pipeline домена database удаляется, а статические scrape-компоненты остальных доменов просто теряют target.
- [§13.3](#133-docker-socket): к Docker API обращаются `discovery.docker` и `loki.source.docker`; логи `loki.source.docker` читает через секцию `/containers`. HTTP-сервер Alloy отдаёт `/metrics` и неаутентифицированный `/api/v0/web/components` со списком компонентов и их аргументами; значения с `is_secret` там заменены маркером `(secret)`. При нескольких сетях контейнера `discovery.docker` берёт только первую по алфавиту ([`alloy/README.md`](../alloy/README.md#per-port-fan-out-and-multiple-networks)).
- [§13.5](#135-доверие-к-labels): адрес scrape эталон строит из `__meta_docker_network_ip` и `__meta_docker_port_private`. `prometheus.scrape` по умолчанию следует редиректам, поэтому во всех `prometheus.scrape` эталона задано `follow_redirects = false`. Allowlist-правил для `blackbox.address`, `team`, `environment` и `service_name` эталон не содержит; при недоверенных соседях их добавляют в `discovery.relabel` соответствующего домена. OTLP-приёмник - overlay [`060_otel.alloy`](../alloy-optional/060_otel.alloy).

## 15. Использование

### 15.1. Docker Compose anchors

Для уменьшения дублирования можно использовать YAML anchors:

```yaml
x-3ops-discovery-common: &alloy-discovery-common
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.version: "0.2"
  ru.3ops.discovery.environment: "production"

services:
  rabbitmq:
    image: rabbitmq:4-management
    labels:
      <<: *alloy-discovery-common
      ru.3ops.discovery.instance: "rabbitmq-main"
      ru.3ops.discovery.team: "platform"

      ru.3ops.discovery.metrics.enabled: "true"
      ru.3ops.discovery.metrics.type: "prometheus"
      ru.3ops.discovery.metrics.port: "15692"
      ru.3ops.discovery.metrics.path: "/metrics"
      ru.3ops.discovery.metrics.job: "rabbitmq"

  postgres:
    image: postgres:18
    labels:
      <<: *alloy-discovery-common
      ru.3ops.discovery.instance: "orders-postgres"
      ru.3ops.discovery.team: "orders"

      ru.3ops.discovery.database.enabled: "true"
      ru.3ops.discovery.database.type: "postgres"
      ru.3ops.discovery.database.port: "5432"
      ru.3ops.discovery.database.secret-id: "postgres-orders"
```

Префикс `x-` в имени anchor-ключа обязателен и НЕ противоречит требованию
reverse-DNS для самих labels — правило действует в двух местах
противоположным образом:

- **Top-level ключ compose-файла** обязан быть либо известным ключом схемы
  (`services`, `networks`, `volumes`, ...), либо extension-ключом с префиксом
  `x-`. Ключ `ru.3ops.discovery-common` не является ни тем, ни другим, и
  `docker compose config` отвергает такой файл целиком
  (`additional properties ... not allowed`).
- **Ключ внутри `labels:`** обязан оставаться reverse-DNS (`ru.3ops.*`):
  для map-формы `labels:` compose трактует ключ с префиксом `x-` как
  extension и под своим именем до контейнера не доводит — все такие ключи
  сворачиваются в один служебный label `#extensions` со значением вида
  `map[x-ключ:значение]`. Discovery такой label не видит, а на контейнере
  остаётся мусорная метка. Именно поэтому пространство имён контракта —
  reverse-DNS, а не `x-`-префикс (раздел
  [4](#4-нормализация-ключей-labels)).

Anchor-ключ виден только парсеру YAML и не попадает ни в один контейнер —
его имя свободно, кроме обязательного `x-`.

### 15.2. Итоговый минимальный контракт

Для нативного Prometheus endpoint:

```yaml
labels:
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.version: "0.2"
  ru.3ops.discovery.instance: "rabbitmq-main"

  ru.3ops.discovery.metrics.enabled: "true"
  ru.3ops.discovery.metrics.type: "prometheus"
  ru.3ops.discovery.metrics.port: "15692"
  ru.3ops.discovery.metrics.path: "/metrics"
  ru.3ops.discovery.metrics.job: "rabbitmq"
```

Для PostgreSQL:

```yaml
labels:
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.version: "0.2"
  ru.3ops.discovery.instance: "orders-postgres"

  ru.3ops.discovery.database.enabled: "true"
  ru.3ops.discovery.database.type: "postgres"
  ru.3ops.discovery.database.port: "5432"
  ru.3ops.discovery.database.secret-id: "postgres-orders"
```

Для логов:

```yaml
labels:
  ru.3ops.discovery.version: "0.2"

  ru.3ops.discovery.logs.profile: "generic-logfmt-v1"
  ru.3ops.discovery.logs.service: "orders-api"
```

Без labels контейнер всё равно собирается как `raw-v1`.

Для явного отключения:

```yaml
labels:
  ru.3ops.discovery.logs.enabled: "false"
```

## 16. Out of scope

Версия `0.2` не описывает:

- автоматическое создание monitoring users в базах;
- автоматическую ротацию секретов;
- полноценный policy engine;
- автоматическое назначение Grafana dashboards;
- динамическое создание alert rules;
- Kubernetes annotations;
- динамическое конструирование log pipeline из списка стадий в label;
- привязку `secret-id` к identity контейнера (раздел [9](#9-secret-contract));
- multi-host global service discovery;
- service ownership registry;
- CMDB или inventory source of truth.

Эти возможности могут быть добавлены отдельными спецификациями.
