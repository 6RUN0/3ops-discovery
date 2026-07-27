# 3ops Discovery Manifest

**Статус:** Draft  
**Версия спецификации:** `0.2.0`  
**Namespace:** `ru.3ops.discovery.*`  
**История изменений:** [CHANGELOG.ru.md](../CHANGELOG.ru.md)

## 1. Назначение

`3ops Discovery` — декларативный mini-framework для автоматического обнаружения и настройки telemetry targets в Grafana Alloy на основе Docker labels.

Контейнер описывает:

- какие сигналы нужно собирать;
- какой тип integration/exporter использовать;
- откуда забирать метрики или логи;
- как именовать target;
- где Alloy должен искать секреты;
- какие дополнительные labels добавлять к telemetry.

Alloy:

1. обнаруживает контейнеры через Docker API;
2. фильтрует targets по labels;
3. нормализует metadata;
4. создаёт scrape/exporter/logging pipeline;
5. отправляет метрики в Prometheus/VictoriaMetrics/Mimir;
6. отправляет логи в Loki;
7. не получает секреты непосредственно из Docker labels.

## 2. Базовая модель

```text
Docker labels
    ↓
discovery.docker
    ↓
discovery.relabel
    ↓
foreach / prometheus.scrape / loki.source.docker
    ↓
prometheus.remote_write / loki.write
```

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

## 4. Нормализация Docker labels в Alloy

Docker label:

```text
ru.3ops.discovery.database.secret-id
```

появляется в `discovery.docker` как:

```text
__meta_docker_container_label_ru_3ops_discovery_database_secret_id
```

Точки, дефисы и другие неподходящие символы преобразуются в `_`.

Из-за этого следующие labels конфликтуют после нормализации:

```text
ru.3ops.discovery.database.secret-id
ru.3ops.discovery.database.secret.id
```

Использовать нужно только первый вариант.

## 5. Глобальные labels

### `ru.3ops.discovery.enabled`

Обязательный флаг участия контейнера в discovery для доменов metrics, database, blackbox, otel и ipmi.

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

Если label отсутствует, применяется версия контракта, заданная Alloy-конфигурацией по умолчанию.

В версии `0.2` label зарезервирован: референсная конфигурация его не читает и обрабатывает все контейнеры по правилам `0.2`. Валидация версии появится вместе с первым изменением, меняющим семантику labels (раздел [7](#7-версионирование-контракта)).

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

### 6.1. Labels, добавляемые Alloy

Alloy должен добавлять к метрикам и логам следующие labels, если они доступны:

```text
instance
environment
team
container
compose_project
compose_service
host
collector="alloy"
```

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

Label `container` берётся из метаданных Docker engine, `host` — из hostname коллектора Alloy; ни один из них не задаётся labels контейнера, поэтому контейнер не может подменить их значения. Остальные labels декларируются самим контейнером (см. раздел [13.5](#135-доверие-к-labels)). Для логов набор дополнительно ограничен allowlist из раздела [6.2](#62-loki-label-cardinality).

Label `instance` относится к метрикам; для логов его аналогом служит `service_name` (см. раздел [10.3.5](#1035-labels)).

### 6.2. Loki label cardinality

В Loki labels разрешено помещать только низкокардинальные поля:

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

Stream labels формируются только из discovery metadata и labels контейнера. Поля, извлечённые из содержимого строки, в stream labels не продвигаются: содержимое подконтрольно приложению, и такое продвижение открывает подмену labels и неограниченную кардинальность стримов. Референс не продвигает `level` (его нет в allowlist выше, поле остаётся в списке ниже); кастомизация вправе продвигать `level` только при нормализации значения к ограниченному набору и с расширением allowlist.

Следующие поля должны оставаться в строке или structured metadata:

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

Для фильтрации по уровню Loki 3.x самостоятельно вычисляет `detected_level` из содержимого строки и structured metadata.

Structured metadata не индексируется и не влияет на кардинальность, но размер значений контролируется приложением. Ограничение размера обеспечивается лимитами Loki (`max_structured_metadata_size`); референсная конфигурация значения не усекает.

Structured metadata требует Loki 3.x со схемой v13 (TSDB) и включённым `allow_structured_metadata`. На более старой схеме push с metadata отклоняется целиком: профили с парсингом молча перестают доставлять строки, тогда как `raw-v1` продолжает работать — при частичной потере логов это первое, что стоит проверить.

## 7. Версионирование контракта

Версия контракта передаётся через:

```yaml
ru.3ops.discovery.version: "0.2"
```

Правила:

- patch-изменения не меняют смысл существующих labels;
- minor-изменения могут добавлять новые необязательные labels;
- major-изменения могут менять семантику или удалять поля;
- начиная с первого изменения, меняющего семантику labels, Alloy-конфигурация должна явно задавать поддерживаемые версии (в `0.2` проверка зарезервирована, см. раздел [5](#5-глобальные-labels)).

Label содержит только major и minor: patch-изменения по определению не меняют семантику labels и в контракте не отражаются.

## 8. Профили

### 8.1. Общие правила

Профиль — имя заранее определённого и версионированного набора настроек, описанного в конфигурации Alloy.

- Значение `*.profile` выбирается только из allowlist, заданного конфигурацией Alloy.
- Label не является DSL или языком программирования pipeline: произвольные значения и списки стадий не поддерживаются.
- Имя профиля обязано содержать версию: суффикс `-vN`, полное имя из символов `[a-z0-9-]` (имена профильных компонентов выводятся из него механически, раздел [14](#14-reference-implementation)).
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

Один `prometheus.scrape` component имеет общие `scrape_interval` и `scrape_timeout`, поэтому произвольные interval/timeout из labels не поддерживаются.

Вместо этого используется ограниченный набор версионированных профилей: на каждый профиль создаётся своя пара `discovery.relabel`/`prometheus.scrape` (см. [alloy/020_metrics.alloy](../alloy/020_metrics.alloy)). Произвольный scrape component на пользовательское значение не создаётся.

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

Перечень описывает объём понятия log-профиля, а не обязательства каждого профиля: базовые профили ниже реализуют parser, multiline и structured metadata. Стадия timestamp в референсе не реализована: временем записи служит docker-таймстамп строки (момент записи приложением в stdout/stderr); таймстамп из содержимого строки не разбирается.

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
  в референс не входит (как и app-type-1-v1).

java-stacktrace-v1
  Multiline pipeline для Java stack traces.

python-stacktrace-v1
  Multiline pipeline для Python tracebacks.
```

### 8.4. Database-профили

```text
basic-v1
standard-v1
extended-v1
```

Профили позволяют контролировать нагрузку и не принимать произвольные настройки из labels. Выбираются через `ru.3ops.discovery.database.profile`; по умолчанию `standard-v1`.

Database-профиль управляет объёмом сбора экспортёра — какие коллекторы опрашивают СУБД, — а не каденцией скрейпа: scrape-профили раздела [8.2](#82-scrape-профили) относятся только к доменам `metrics` и `blackbox`. Нагрузка монотонна: basic ≤ standard ≤ extended. `standard-v1` соответствует набору коллекторов экспортёра по умолчанию; несовместимое изменение набора требует нового имени профиля (раздел [8.1](#81-общие-правила)). Значение вне allowlist отбрасывает цель целиком (fail-closed), как и в остальных доменах с профилями.

Маппинг профилей на коллекторы в референсной конфигурации ([alloy/030_database.alloy](../alloy/030_database.alloy)); в extended-наборы входят только коллекторы, работающие на «ванильной» СУБД без расширений и специальных настроек сервера:

| Тип | `basic-v1` | `standard-v1` | `extended-v1` |
|---|---|---|---|
| `postgres` | дефолтные метрики без `pg_settings` | дефолты экспортёра | дефолты + `database_wraparound`, `long_running_transactions`, `process_idle`, `statio_user_indexes` |
| `mysql`/`mariadb` | `global_status`, `global_variables` | шесть дефолтных коллекторов (закреплены явно) | дефолтные + `engine_innodb_status`, `info_schema.processlist`, `auto_increment.columns` |
| `redis` | только `redis_*` серии (`redis_metrics_only`) | дефолты экспортёра | дефолты + client list + системная память |
| `mongodb` | только diagnostic data (`serverStatus`) | полный сбор (`collect_all`) | эквивалент `standard-v1`: дефолт mongodb-экспортёра уже максимальный |

### 8.5. SNMP-профили

Domain-wide allowlist версионированных snmp-профилей. Дифференциатор — увеличенный `timeout` (30s) под медленные устройства; §8.2 общий для `metrics`/`blackbox` и такого таймаута не даёт, поэтому snmp-профили вынесены отдельным семейством. Референс включает один профиль; применяется ко всему snmp-scrape (файловый провайдер даёт один экспортёр и один scrape).

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

Alloy строит путь:

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

Redis — исключение: аргумент `redis_addr` экспортёра принимает обычную строку, а не секрет, поэтому адрес (`host:port`, несекретный) хранится в `.dsn`, а пароль — в отдельном секрет-файле `<secret-id>.redispass`, читаемом через `redis_password`.

Требования:

- файл доступен только пользователю Alloy;
- каталог монтируется read-only;
- используется `local.file` с `is_secret = true`;
- `secret-id` проверяется регулярным выражением;
- `secret-id` не должен содержать `/`, `..`, пробелы и shell-символы.

Допустимый шаблон:

```regex
^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$
```

Контракт общий для доменов на Docker-labels; различается только доменный суффикс файла (snmp — файловый провайдер — исключение, см. §10.6.1):

```text
database  /run/alloy-secrets/<secret-id>.dsn   (+ <secret-id>.redispass для type=redis)
snmp      /run/alloy-secrets/snmp_auths.yaml  (исключение, единый файл — см. §10.6.1)
ipmi      /run/alloy-secrets/<secret-id>.ipmi
```

Каталог `/run/alloy-secrets` — значение по умолчанию; он настраивается переменной `RU_3OPS_DISCOVERY_SECRETS_DIR` (раздел [14.1](#141-параметры-окружения)).

Правила валидации идентификатора и read-only монтирования одинаковы для всех доменов; `is_secret = true` обязателен для файлов с credentials (исключение — адресный `.dsn` redis: он несекретен по построению, см. выше, и читается без `is_secret`). Требования к защите от path traversal описаны в разделе [13.4](#134-secret-path-traversal).

Пространство `secret-id` — единый trust domain в пределах хоста: контракт не привязывает контейнер к конкретному секрету, и любой контейнер с валидным label может сослаться на любой существующий файл секрета. В каталог секретов хоста следует выкладывать только секреты, предназначенные контейнерам этого хоста; для разграничения команд используйте соглашение о префиксах `secret-id`. Префиксы — только соглашение для операторов: конфигурация их не проверяет, и технически каждый файл секрета на хосте доступен каждому контейнеру этого хоста. Следствие той же модели доверия: контейнер может определить существование файла секрета, объявив соответствующий `secret-id` и наблюдая появление exporter; содержимое секрета при этом не раскрывается. Привязка `secret-id` к identity контейнера — вне рамок версии `0.2` (раздел [16](#16-out-of-scope)).

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

`metrics.scheme: https` предполагает сертификат, которому коллектор доверяет через системный trust store: канала доставки CA-материала у label-контракта нет (labels переносят только строки — та же модель, что у blackbox-модуля `tls_connect`, раздел [10.4](#104-domain-blackbox)), поэтому endpoint с self-signed сертификатом заскрейплен не будет. TLS-доверие для внутренних CA — кастомизация окружения: отдельная scrape-пара с `tls_config` (раздел [14.3](#143-кастомизация-референсной-конфигурации)).

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

Профиль выбирает одну из relabel/scrape-пар конфигурации Alloy; референсная конфигурация включает пары всех базовых профилей раздела [8.2](#82-scrape-профили) (см. раздел [14](#14-reference-implementation)).

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

Конкретная поддержка зависит от наличия соответствующего `prometheus.exporter.*` в используемой версии Alloy.

`type` обозначает wire-протокол и exporter, а не вендора СУБД. Протокол-совместимые сборки метятся базовым типом, отдельный тип для них не вводится: Percona Server for MySQL и Percona XtraDB Cluster — `type: mysql`; Percona Server for MongoDB — `type: mongodb` (так же, как managed-СУБД вида RDS/Aurora MySQL). MariaDB — исключение: это самостоятельный тип, разделяющий mysql-exporter, потому что операторы воспринимают её как отдельный продукт.

`database.port` (и стандартный порт при его отсутствии) — селектор target, а не параметр подключения: значение сверяется с реальными приватными портами контейнера (`keepequal`, fail-closed — target с несуществующим портом отбрасывается), тогда как адрес подключения экспортёра целиком определяется `.dsn` (раздел [9](#9-secret-contract)). Расхождение порта в label и в DSN конфигурацией не детектируется.

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

`database.name`, `database.user` и `database.sslmode` — инвентарные labels (раздел [13.2](#132-разрешено-хранить)): референс их не читает, все параметры подключения берутся только из `.dsn`; при расхождении label и DSN действует DSN. Идентичность серии: `instance` = `database.instance`, иначе глобальный `ru.3ops.discovery.instance` (раздел [5](#5-глобальные-labels)), иначе `secret-id` (синтезированный fallback); `job` = `database.type`.

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

Для логов `ru.3ops.discovery.enabled` не является обязательным условием. Это сделано специально, чтобы контейнер без manifest-labels всё равно был виден в Loki.

Рекомендуемая цепочка:

```text
discovery.docker
    ↓ все контейнеры
discovery.relabel
    ↓ исключить только logs.enabled=false
loki.source.docker
    ↓
loki.process
    ↓ profile dispatcher
Loki
```

#### 10.3.2. `logs.profile`

`ru.3ops.discovery.logs.profile` — это имя заранее определённого pipeline-профиля из allowlist (см. разделы [8.1](#81-общие-правила) и [8.3](#83-log-профили)).

Пример:

```yaml
ru.3ops.discovery.logs.profile: "app-type-1-v1"
```

Значение не должно быть произвольным списком стадий: Alloy выбирает профиль только из allowlist, определённого в конфигурации.

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
3. записать диагностическое сообщение в лог Alloy;
4. по возможности увеличить внутреннюю метрику ошибок конфигурации discovery.

Неизвестный профиль не должен приводить к потере логов контейнера.

Референсная конфигурация реализует пункты 1–2 allowlist-правилом в `discovery.relabel` (неизвестный профиль заменяется на `raw-v1`); диагностическое сообщение и метрика (пункты 3–4) на уровне relabel недоступны и в reference не реализованы.

#### 10.3.5. Labels

| Label | Обязательный | Значение |
|---|---:|---|
| `ru.3ops.discovery.logs.enabled` | Нет | По умолчанию `true`; `false` отключает сбор |
| `ru.3ops.discovery.logs.profile` | Нет | По умолчанию `raw-v1` |
| `ru.3ops.discovery.logs.service` | Нет | Значение `service_name` |
| `ru.3ops.discovery.logs.stream-policy` | Нет | Профиль обработки stdout/stderr |
| `ru.3ops.discovery.logs.redaction-profile` | Нет | Идентификатор политики редактирования |
| `ru.3ops.discovery.logs.drop-profile` | Нет | Идентификатор политики фильтрации шума |

Для версии `0.2` рекомендуется использовать один composite profile. Дополнительные `stream-policy`, `redaction-profile` и `drop-profile` зарезервированы для расширения и не обязательны к реализации: их семейства профилей в разделе [8](#8-профили) не определены, референс эти labels не читает.

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

Профиль `mixed-v1` может:

1. применить JSON parser к строкам, начинающимся с `{`;
2. применить logfmt parser к строкам, содержащим `level=`, `msg=` или `status=`;
3. сохранить остальные строки raw.

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
| `ru.3ops.discovery.blackbox.address` | Нет | Адрес проверки; по умолчанию адрес контейнера |
| `ru.3ops.discovery.blackbox.port` | Да | Порт проверки |
| `ru.3ops.discovery.blackbox.path` | Нет | HTTP path |
| `ru.3ops.discovery.blackbox.profile` | Нет | Scrape-профиль из allowlist; по умолчанию `normal-v1` |

Значение `module` должно входить в allowlist модулей blackbox exporter, заданный конфигурацией Alloy. Произвольные модули из labels не принимаются. Формат цели пробы зависит от модуля: HTTP-модули получают URL `scheme://host:port/path`, TCP- и TLS-модули — `host:port`, ICMP-модули — только host. Каждой серии blackbox-проб Alloy добавляет label `module` с именем использованного модуля.

Для ICMP-модулей значение `blackbox.port` в саму пробу не входит (у ICMP нет порта), но label остаётся обязательным и проходит ту же валидацию: объявленный порт должен совпадать с реальным экспонированным портом контейнера, иначе target отбрасывается. Правило действует и при внешнем `blackbox.address`: порт сверяется с приватными портами самого контейнера, поэтому проба `example.com:443` из контейнера, не экспонирующего порт 443, молча отбрасывается. Последствия `blackbox.address` для модели доверия — раздел [13.5](#135-доверие-к-labels).

ICMP-пробы не требуют дополнительных привилегий в типовой Docker-среде: стандартного набора capabilities (`NET_RAW`) либо непривилегированных ICMP-сокетов (Docker по умолчанию открывает `net.ipv4.ping_group_range` для всех групп) достаточно. В hardened-средах, где одновременно отброшен `NET_RAW` и сужен `ping_group_range`, ICMP-пробы работать не будут; выход — вернуть `cap_add: [NET_RAW]` или расширить `sysctls: net.ipv4.ping_group_range` у контейнера Alloy.

TLS-модуль референса (`tls_connect`) проверяет успешность TLS handshake и отдаёт метрики срока действия сертификата (`probe_ssl_earliest_cert_expiry`, `probe_tls_version_info`), но намеренно не верифицирует цепочку доверия: у label-контракта нет канала доставки CA-материала в Alloy — labels переносят только строки. Проверка цепочки для внутренних CA — свойство конкретного окружения: она выполняется отдельным модулем с `ca_file` в конфигурации blackbox exporter, что выходит за рамки референса.

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

#### 10.5.1. Labels

| Label | Обязательный | Значение |
|---|---:|---|
| `ru.3ops.discovery.otel.enabled` | Да | `true` |
| `ru.3ops.discovery.otel.protocol` | Да | `grpc` или `http` |
| `ru.3ops.discovery.otel.service` | Нет | Имя сервиса |
| `ru.3ops.discovery.otel.traces` | Нет | `true`/`false` |
| `ru.3ops.discovery.otel.metrics` | Нет | `true`/`false` |
| `ru.3ops.discovery.otel.logs` | Нет | `true`/`false` |

Этот домен в основном документирует ожидаемое поведение приложения. Alloy обычно поднимает общий OTLP receiver, а не отдельный receiver на каждый контейнер.

Флаг `otel.enabled` поэтому носит декларативный характер: он не управляет приёмом OTLP (receiver общий и статичен), а фиксирует намерение сервиса и используется для инвентаризации. Остальные labels домена декларативны по той же причине. Трейсы в `0.2` вне периметра: у референс-приёмника нет выхода traces, поэтому trace-экспорт отклоняется с явной ошибкой на стороне клиента, а не принимается молча.

OTLP-путь — исключение из провенанса раздела [6.1](#61-labels-добавляемые-alloy): общий receiver статичен и не имеет Docker-метаданных, поэтому не производит provenance-labels `environment`/`team`/`container`. В Loki-stream продвигается только allowlist-набор resource-атрибутов OTLP (раздел [6.2](#62-loki-label-cardinality); в референсной конфигурации — только `service.name` → `service_name`); остальную идентификацию задаёт само отправляющее приложение через resource-атрибуты.

### 10.6. Domain: snmp

Единственный домен, не управляемый Docker-labels: внешнее сетевое оборудование (коммутаторы, роутеры) не имеет контейнера, поэтому targets перечисляются в файле, а не открываются через discovery. Домен поставляется opt-in overlay-файлом [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) (раздел [14.5](#145-опциональные-файлы)), а не базовым доменом: его top-level `local.file` без файла на диске становится unhealthy и каскадно роняет граф, поэтому он загружается только вместе с device- и auth-файлами.

Файл устройств (`snmp_targets.yaml`) — список записей; каждое значение хранится строкой (`encoding.from_yaml` декодирует список в `list(map(string))`):

| Поле | Обязательный | Значение |
|---|---|---|
| `name` | нет | Человекочитаемое имя устройства (провенанс); при отсутствии референс подставляет `address` — exporter требует `name` у каждой записи. Значение попадает в серии label'ом `device` (`instance` несёт адрес) |
| `address` | да | `host:port` SNMP-агента (presence-проверка в relabel) |
| `module` | да | Модуль snmp_exporter из allowlist; в референсе — `if_mib` (интерфейсы) и `system` (идентичность и аптайм устройства: `sysUpTime`, `sysName`) — открытый пример-список, как в blackbox [10.4](#104-domain-blackbox). Одна запись — один модуль; устройству с несколькими модулями соответствует несколько записей с разными `name` |
| `auth` | да | Имя auth-профиля из [10.6.1](#1061-snmp-auth) (presence-проверка; резолвится экспортёром) |
| `environment` | нет | Provenance-label (пропускается как non-reserved) |
| `team` | нет | Provenance-label (пропускается как non-reserved) |

Поле устройства называется `auth` — ссылка-имя профиля из слитого `auths:`-map; хранить такие имена вне секретов разрешает раздел [13.2](#132-разрешено-хранить). Секрет (SNMP community / SNMPv3 credentials) живёт только в `snmp_auths.yaml` (раздел [10.6.1](#1061-snmp-auth)), никогда в файле устройств.

Домен [10.7](#107-domain-ipmi) (ipmi) структурно похож, но в этой фазе остаётся доменом на Docker-labels (Out of scope для файлового провайдера).

#### 10.6.1. SNMP-auth

Auth-модель домена: именованные профили в `snmp_auths.yaml`, на которые устройство ссылается по имени через поле `auth`.

**Allowlist версий:** `v2c`, `v3`. Проверка только advisory: версия живёт в секрет-файле, который парсит экспортёр; Alloy-конфигурация её не инспектирует. Единственная точка контроля в репозитории — статический валидатор auth-фикстуры: `version ∈ {2, 3}` (НЕ диапазон экспортёра 1..3 — SNMPv1 запрещён контрактом).

**Поля профиля по версии:**

- `v2c`: `community`.
- `v3`: `username`, `security_level`, `password`, `auth_protocol`, `priv_protocol`, `priv_password` (полный список и enum-ы — в разделе «Схема файлов» дизайна).

**Размещение секрета:** файл устройств хранит только ИМЯ профиля; credentials лежат только в `snmp_auths.yaml`, подаваемом как inline `config` из `local.file` с `is_secret = true`, — никогда в labels и не в списке устройств. Усиливает [13.1](#131-запрещено-хранить-в-docker-labels) (SNMP communities запрещены в labels); раздел [9](#9-secret-contract) трактует это как исключение из соглашения «один файл на `<auth-id>`». Relabel проверяет только ПРИСУТСТВИЕ `auth` (`keep auth != ""`) — формат имени не навязывается.

**Известное ограничение:** `merge` сохраняет встроенные defaults, включая небезопасный `public_v2` (community `public`, v2c) и `public_v1` (v1, вне allowlist `{v2c, v3}`); `auth: "public_v2"` резолвится успешно, потому что relabel проверяет присутствие, а не членство. Контроль по имени в референсе невозможен (имена auth зависят от деплоя) — задокументированный риск, как и односторонний module-гейт.

**Неизвестное имя auth** (опечатка, отсутствует в слитом `auths:`) → ошибка на стороне экспортёра во время scrape, а НЕ drop на этапе discovery (relabel не может свериться с секрет-файлом). Задокументировано; отдельный e2e не добавляется.

### 10.7. Domain: ipmi

BMC/IPMI-мониторинг через внешний `ipmi_exporter` (или другой adapter). У Alloy нет нативного IPMI-компонента — в отличие от snmp, где есть встроенный `prometheus.exporter.snmp`, — поэтому ipmi не самостоятельный механизм, а **частный случай домена [metrics](#101-domain-metrics)**: внешний exporter опрашивает BMC по IPMI и публикует Prometheus-endpoint, а Alloy скрейпит этот endpoint как обычный metrics-target. IPMI-специфичной конфигурации на стороне Alloy нет.

#### 10.7.1. Labels

```text
ru.3ops.discovery.ipmi.enabled
ru.3ops.discovery.ipmi.address
ru.3ops.discovery.ipmi.module
ru.3ops.discovery.ipmi.secret-id
ru.3ops.discovery.ipmi.profile
```

Labels описывают намерение (адрес BMC, модуль exporter, секрет, профиль), но роль Alloy сводится к тому, чтобы скрейпить HTTP-endpoint внешнего exporter: доменного pipeline на стороне Alloy, как у snmp ([10.6](#106-domain-snmp)), здесь нет. Все ipmi-labels в `0.2` — декларативные/инвентарные (ни референс, ни какой-либо доменный pipeline их не читает); `ipmi.profile` ссылается на scrape-профили раздела [8.2](#82-scrape-профили) — собственного семейства профилей у ipmi нет. Файл секрета: `/run/alloy-secrets/<secret-id>.ipmi` по общему контракту раздела [9](#9-secret-contract); credentials BMC потребляет сам exporter, а не Alloy.

Референс-конфигурация не поставляет ipmi-overlay (в отличие от `037_snmp.alloy`): рекомендуемый путь — пометить контейнер `ipmi_exporter` labels домена [metrics](#101-domain-metrics) и скрейпить его существующим metrics-pipeline. Отдельный overlay появится, только если Alloy получит нативный IPMI-компонент.

## 11. Validation rules

Минимальные проверки перед созданием pipeline:

- `enabled == true` — кроме домена logs (см. раздел [10.3.1](#1031-политика-сбора-по-умолчанию));
- `version` поддерживается (в `0.2` проверка зарезервирована — см. раздел [5](#5-глобальные-labels));
- `domain.enabled == true`;
- `type` входит в allowlist;
- `port` является числом 1..65535;
- `profile` входит в allowlist профилей домена (раздел [8](#8-профили));
- `secret-id` соответствует allowlist regex;
- `path` начинается с `/`;
- `scheme` входит в allowlist.

Неизвестное значение `type` приводит к отбрасыванию target целиком (fail-closed) и по возможности отражается в логах Alloy.

Пустое значение любого label эквивалентно отсутствию label: действует значение по умолчанию соответствующего домена (при релейблинге метка с пустым значением удаляется, поэтому пустые значения не попадают в серии).

Референсная конфигурация реализует проверки `path`, `scheme`, `profile` и `secret-id` relabel-правилами. Проверка `port` выполняется неявно и fail-closed: `keepequal` сопоставляет объявленный порт с реальными приватными портами контейнера, поэтому нечисловое, выходящее за диапазон или несуществующее значение приводит к отбрасыванию target.

Файловый провайдер snmp (overlay 037) проверяет свои аналоги теми же fail-closed keep-правилами `discovery.relabel` поверх `from_yaml`-списка: allowlist `module`, presence `auth` и presence `address` — семантически невалидная запись отбрасывается построчно. Проверка `port` через `keepequal` не применяется (контейнера нет). Отдельно действует режим **fail-STALE**: синтаксически сломанный ВЕСЬ файл устройств ломает `from_yaml`, и Alloy удерживает последние валидные аргументы (targets не меняются — это не fail-closed/пустой список). На холодном старте последнего валидного значения нет, поэтому `discovery.relabel` unhealthy, а набор targets пуст (экспортёр стартует на нуле устройств, healthy-idle). Построчный drop (семантика) и fail-STALE всего файла (синтаксис) — два разных режима.

## 12. Lifecycle

### 12.1. Добавление target

1. Контейнер запускается с `ru.3ops.discovery.enabled=true` (домен logs — исключение: сбор по умолчанию, раздел [10.3.1](#1031-политика-сбора-по-умолчанию)).
2. `discovery.docker` обнаруживает контейнер.
3. `discovery.relabel` проверяет domain labels.
4. Alloy создаёт соответствующий pipeline.
5. Target появляется в Alloy UI.
6. Метрики или логи начинают поступать в backend.

### 12.2. Удаление target

1. Контейнер останавливается или удаляется.
2. Target исчезает из Docker discovery.
3. Для домена database удаляется динамический `foreach`-pipeline; статические scrape-компоненты остальных доменов просто теряют target.
4. Новые telemetry samples перестают поступать.
5. Исторические данные остаются в backend до окончания retention.

### 12.3. Изменение labels

Docker не позволяет изменять labels работающего контейнера. Изменения вступают в силу только после пересоздания контейнера с новыми labels.

## 13. Security requirements

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

Если Alloy использует `/var/run/docker.sock`, необходимо учитывать:

- read-only mount не делает Docker API строго read-only;
- доступ к Docker socket фактически является высокопривилегированным;
- желательно использовать socket proxy с разрешёнными только read endpoints;
- Alloy не должен быть доступен из недоверенной Docker-сети;
- Alloy UI не должен публиковаться наружу без аутентификации.

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

- для доменов metrics и database SSRF исключён: адрес scrape строится только из `__meta_docker_network_ip` и приватного порта самого контейнера (для database — из файла секрета, который labels не выбирают за пределами `secret-id`), labels не могут перенаправить сбор на другой хост;
- домен blackbox — осознанное исключение: `blackbox.address` (раздел [10.4.1](#1041-labels)) направляет пробу на произвольный хост, а результат (`probe_success`, статус, срок сертификата) виден в метриках — контейнер получает oracle достижимости сети от имени Alloy. Порт пробы ограничен приватными портами самого контейнера, но контейнер сам объявляет свои expose-порты, поэтому при недоверенных соседях `blackbox.address` следует ограничивать allowlist-правилом в `discovery.relabel`;
- opt-in OTLP-приёмник (overlay `060_otel`) слушает без аутентификации и не производит provenance-labels (раздел [10.5](#105-domain-otel)): сетевой доступ к его портам равен праву писать телеметрию с произвольной идентичностью; приёмник следует держать во внутренней сети или закрывать аутентифицирующим reverse-proxy;
- `container` добавляется из метаданных Docker engine, `host` — из hostname коллектора Alloy; ни один не подделывается через labels (раздел [6.1](#61-labels-добавляемые-alloy));
- поэтому серии и стримы с подменёнными `job`/`team`/`service_name` всё равно несут честные `container` и `host` отправителя: они не сливаются с данными настоящего владельца и остаются отличимыми — но alert rules и dashboards, фильтрующие только по `team`/`job` без учёта `container`, увидят и подделанные данные;
- поля из содержимого логов не продвигаются в stream labels (раздел [6.2](#62-loki-label-cardinality));
- при недоверенных соседях по хосту значения `team`/`environment`/`service_name` следует дополнительно ограничивать allowlist-правилами в `discovery.relabel`; референсная конфигурация таких правил не содержит;
- ограничение объёма telemetry контракт не задаёт: контейнер может создавать нагрузку объёмом логов и числом opt-in targets; защита — rate limits на стороне backend (лимиты Loki, ограничения remote_write endpoint).

## 14. Reference implementation

Референсная конфигурация Alloy вынесена в каталог [`alloy/`](../alloy/) и разделена по файлам. Все `*.alloy`-файлы каталога образуют одну конфигурацию и запускаются вместе:

```sh
alloy run --stability.level=experimental alloy/
```

Флаг `--stability.level=experimental` необходим для блока `foreach` (experimental в Alloy v1.17). Синтаксическая проверка без запуска:

```sh
docker run --rm -v "$PWD/alloy:/etc/alloy:ro" grafana/alloy:v1.17.1 \
  validate --stability.level=experimental /etc/alloy
```

Числовой префикс в именах файлов задаёт порядок чтения (поток pipeline: discovery → домены → выходы). На работу Alloy порядок загрузки не влияет: все файлы каталога сливаются в один граф компонентов, и ссылки между файлами разрешаются независимо от порядка.

| Файл | Содержимое |
|---|---|
| [`010_discovery.alloy`](../alloy/010_discovery.alloy) | `discovery.docker`: opt-in discovery для metrics/database и discovery всех контейнеров для логов |
| [`020_metrics.alloy`](../alloy/020_metrics.alloy) | Домен metrics: общий relabel (валидация + провенанс) и пара `discovery.relabel`/`prometheus.scrape` на каждый профиль раздела 8.2 |
| [`030_database.alloy`](../alloy/030_database.alloy) | Домен database: `foreach`-pipeline на тип СУБД, DSN из файла секрета, объём сбора по `database.profile` (раздел 8.4) |
| [`035_blackbox.alloy`](../alloy/035_blackbox.alloy) | Домен blackbox: общий `discovery.relabel` + `prometheus.exporter.blackbox` (модули `http_2xx`/`tcp_connect`/`icmp`/`tls_connect`) и пара фильтр+scrape на каждый профиль раздела 8.2 |
| [`040_logs.alloy`](../alloy/040_logs.alloy) | Домен logs: relabel-правила и `loki.source.docker` |
| [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) | Profile dispatcher: `loki.process` с базовыми log-профилями |
| [`090_outputs.alloy`](../alloy/090_outputs.alloy) | Выходы: `prometheus.remote_write` и `loki.write` |

Профильные scrape-пары устроены слоисто: общий relabel домена несёт валидацию и провенанс, тонкая пара `discovery.relabel`/`prometheus.scrape` на профиль — только маршрутизацию на свой интервал. Имена профильных компонентов механически выводятся из полного имени профиля (`fast-v1` → `metrics_fast_v1`). Targets, объявившие профиль вне allowlist, сознательно не скрейпятся ни одной парой. Дополнительный профиль подключается копией тонкой пары (фильтр + scrape) с изменёнными regex profile-правила, `scrape_interval` и `scrape_timeout`.

Известное ограничение референсной конфигурации: `discovery.docker` создаёт отдельный target на каждый exposed TCP-порт контейнера. Fan-out по портам схлопывается `keepequal`-правилами (metrics, database, blackbox); логи не страдают — `loki.source.docker` дедуплицирует targets по container ID и читает контейнер ровно один раз. Контейнер, подключённый к нескольким Docker-сетям, дублирующихся targets не даёт: по умолчанию (`match_first_network = true`) discovery создаёт targets только для одной сети — первой по алфавиту имён. Риск мультисети в другом: выбор сети детерминированный, но произвольный, и если первая по имени сеть недостижима для Alloy, targets доменов metrics/database/blackbox указывают на недостижимый адрес (цель видна как `up == 0`); сбор логов от сетевой достижимости не зависит — строки читаются через Docker API. Контейнеры с telemetry рекомендуется подключать к одной сети, видимой Alloy.

Позиции чтения логов (`positions.yml`) и WAL `prometheus.remote_write` живут в `--storage.path` Alloy. Без persistent-тома пересоздание контейнера Alloy (обновление образа, `up --force-recreate`) приводит к повторной отправке доступной истории логов контейнеров и потере неотправленного WAL метрик; обычный рестарт процесса безопасен (writable-слой контейнера сохраняется). Для production-деплоя каталог `--storage.path` следует выносить на persistent-том; гарантий доставки строже at-least-once контракт не задаёт.

### 14.1. Параметры окружения

Deployment-специфичные значения настраиваются переменными окружения через `coalesce(sys.env("..."), <default>)`; при отсутствии переменной действует значение по умолчанию. Префикс `RU_3OPS_DISCOVERY_` = 3ops Discovery.

| Переменная | Назначение | Default |
|---|---|---|
| `RU_3OPS_DISCOVERY_DOCKER_HOST` | Адрес Docker daemon | `unix:///var/run/docker.sock` |
| `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` | Интервал обновления списка targets | `30s` |
| `RU_3OPS_DISCOVERY_SECRETS_DIR` | Каталог файлов секретов (см. [9](#9-secret-contract)) | `/run/alloy-secrets` |
| `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL` | Endpoint метрик (протокол Prometheus remote_write) | `http://prometheus:9090/api/v1/write` |
| `RU_3OPS_DISCOVERY_LOKI_PUSH_URL` | Endpoint логов (Loki push API) | `http://loki:3100/loki/api/v1/push` |
| `RU_3OPS_DISCOVERY_HOST_ROOTFS_PATH` | Точка маунта host root FS для `prometheus.exporter.unix` (опциональный файл 070) | `/rootfs` |
| `RU_3OPS_DISCOVERY_HOST_PROCFS_PATH` | Точка маунта procfs для host-exporter | `/host/proc` |
| `RU_3OPS_DISCOVERY_HOST_SYSFS_PATH` | Точка маунта sysfs для host-exporter | `/host/sys` |
| `RU_3OPS_DISCOVERY_SNMP_TARGETS_FILE` | Путь к файлу устройств snmp (не секрет; overlay 037) | `/etc/alloy/snmp_targets.yaml` |

Параметры scrape-профилей (interval/timeout) переменными окружения не настраиваются: они являются частью контракта (см. [8.2](#82-scrape-профили)), а не deployment-конфигурацией.

Не встраивайте учётные данные в URL endpoints (`https://user:pass@host`): значение переменной — обычная строка и может появиться в Alloy UI и логах. Для аутентификации используйте блоки `basic_auth`/`authorization` внутри `endpoint` с секретом из `local.file` (`is_secret = true`).

### 14.2. Backends

Файл `090_outputs.alloy` — единственная точка интеграции с хранилищами; замена backend не затрагивает discovery- и pipeline-файлы. Alloy не ограничен парой Prometheus + Loki:

- `prometheus.remote_write` работает с любым remote_write-совместимым хранилищем: Mimir, VictoriaMetrics, Thanos, Grafana Cloud.
- `loki.write` — с любым endpoint, реализующим Loki push API.
- Для OTLP-backends (Tempo, vendor APM) потоки конвертируются через `otelcol.receiver.prometheus` / `otelcol.receiver.loki` и экспортируются `otelcol.exporter.otlp`.

Заменой одного URL дело ограничивается только для неаутентифицированных endpoint. Mimir и Grafana Cloud требуют аутентификацию и/или заголовок `X-Scope-OrgID`: помимо переменных раздела [14.1](#141-параметры-окружения) потребуется добавить в `090_outputs.alloy` блоки `basic_auth`/`authorization`/`headers` — с секретом из `local.file`, а не в URL (см. предупреждение в 14.1).

Это не полный production-конфиг, а базовая структура реализации manifest. Пояснения к неочевидным местам (дедупликация targets по container ID, keep-правило для `secret-id`, соответствие scrape-профилям) находятся в комментариях самих файлов.

### 14.3. Кастомизация референсной конфигурации

Alloy сливает все `*.alloy`-файлы каталога в один граф компонентов (верхний уровень, нерекурсивно); имена компонентов уникальны глобально. Переопределить компонент базы нельзя: два объявления с одинаковым именем — ошибка загрузки, а не override. Кастомизация выполняется тремя способами:

- **overlay-каталог** — дополнительные файлы, добавляемые к базовому каталогу при материализации (раздел [14.5](#145-опциональные-файлы)); базовый `alloy/` остаётся валидным и полным без них;
- **extension points** — стабильные экспорты базы, на которые overlay вправе ссылаться (раздел [14.4](#144-extension-points));
- **env-параметризация** — deployment-значения через `RU_3OPS_DISCOVERY_*` (раздел [14.1](#141-параметры-окружения)).

Соглашения против коллизий: файлы репозитория используют числовые префиксы `0xx`, пользовательские overlay — `1xx` и выше; пользовательские имена компонентов — префикс `ext_`. Критерий границы base/optional: базовый `alloy/` содержит ровно то, что управляется discovery по Docker-labels; статичное, host-level или требующее deployment-привилегий выносится в optional.

Привилегированные overlay получают deployment-привилегии уровня хоста и наблюдают хост или все его контейнеры целиком, вне discovery-скоупа: `070_host-metrics` (host procfs/sysfs/rootfs), `080_host-logs` (systemd journal), `075_container-metrics` (host cgroup namespace + `/sys/fs/cgroup:ro`; host PID namespace не требуется и не выдаётся). Выдача таких привилегий — осознанное deployment-решение, не дефолт.

### 14.4. Extension points

Публичный API базовой конфигурации: стабильные экспорты, на которые overlay-файл вправе ссылаться. Стабильны в пределах minor-версии контракта; переименование — ломающее изменение.

| Экспорт | Компонент |
|---|---|
| `prometheus.remote_write.default.receiver` | `090_outputs.alloy` |
| `loki.write.default.receiver` | `090_outputs.alloy` |
| `loki.process.docker_profiles.receiver` | `050_log-profiles.alloy` |
| `discovery.docker.containers.targets` | `010_discovery.alloy` |
| `discovery.docker.docker_logs.targets` | `010_discovery.alloy` |

### 14.5. Опциональные файлы

Каталог [`alloy-optional/`](../alloy-optional/) — overlay-файлы, добавляемые к базовому каталогу при материализации. Базовый `alloy/` валиден без них.

| Файл | Содержимое |
|---|---|
| [`060_otel.alloy`](../alloy-optional/060_otel.alloy) | Opt-in OTLP receiver: `otelcol.receiver.otlp` → метрики в `prometheus.remote_write`, логи в `loki.write` через allowlist-processor |
| [`070_host-metrics.alloy`](../alloy-optional/070_host-metrics.alloy) | Opt-in host-метрики: `prometheus.exporter.unix` (серии `node_*`) → `prometheus.remote_write`; rootfs/procfs/sysfs через `RU_3OPS_DISCOVERY_HOST_*`; провенанс §6.1: `host`/`collector` добавляет `discovery.relabel` перед scrape |
| [`075_container-metrics.alloy`](../alloy-optional/075_container-metrics.alloy) | Opt-in per-container метрики: `prometheus.exporter.cadvisor` (серии `container_cpu_*`/`container_memory_*`/`container_network_*`; `container_fs_*` вне периметра) → `prometheus.remote_write`. Docker API — через `docker_host` (реюз `RU_3OPS_DISCOVERY_DOCKER_HOST`, socket-proxy: GET-allowlist разделов `CONTAINERS`/`INFO`/`VERSION`/`PING` достаточен); при недоступном Docker API вывод практически пуст (`docker_only`). Провенанс §6.1: allowlisted container-labels → `environment`/`team`/`compose_*`, `name` → `container`; сырые `container_label_*`/`id`/`name` отбрасываются; `instance` = hostname коллектора, `job` = `integrations/cadvisor` (метка экспортёра; оба — осознанные gap'ы). Кардинальность: `store_container_labels = false` + allowlist, root-cgroup-статистика отключена, `disabled_metrics`/`enabled_metrics` — tunable. Привилегии деплоя (host cgroup namespace) — раздел [14.3](#143-кастомизация-референсной-конфигурации); per-container opt-out не поддерживается. |
| [`080_host-logs.alloy`](../alloy-optional/080_host-logs.alloy) | Opt-in host-логи: `loki.source.journal` (systemd journal) → `loki.write`; статические labels `host`/`collector`/`source` (в §6.2 allowlist) |
| [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) | Домен snmp (opt-in overlay): файловый провайдер (`local.file` + `encoding.from_yaml`), `prometheus.exporter.snmp` (модули `if_mib`/`system`, профиль `snmp-standard-v1`), auth из inline `config`-секрета (`local.file` `is_secret`) через merge. Включается только вместе с device/auth-файлами (top-level `local.file` без файла unhealthy). |

## 15. Использование

### 15.1. Docker Compose anchors

Для уменьшения дублирования можно использовать YAML anchors:

```yaml
ru.3ops.discovery-common: &alloy-discovery-common
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
