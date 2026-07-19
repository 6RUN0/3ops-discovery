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

Обязательный флаг участия контейнера в discovery для доменов metrics, database, blackbox, otel, snmp и ipmi.

Исключение: домен `logs` собирает stdout/stderr всех контейнеров по умолчанию и не требует этого label (см. раздел [10.3.1](#1031-политика-сбора-по-умолчанию)).

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

### `ru.3ops.discovery.instance`

Логическое имя экземпляра.

Используется как основной `instance` label, если domain-specific значение отсутствует.

Пример:

```yaml
ru.3ops.discovery.instance: "orders-postgres"
```

### `ru.3ops.discovery.environment`

Окружение:

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

Stream labels формируются только из discovery metadata и labels контейнера. Поля, извлечённые из содержимого строки, в stream labels не продвигаются: содержимое подконтрольно приложению, и такое продвижение открывает подмену labels и неограниченную кардинальность стримов. Продвижение `level` в label допустимо только при нормализации значения к ограниченному набору.

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

## 7. Версионирование контракта

Версия контракта передаётся через:

```yaml
ru.3ops.discovery.version: "0.2"
```

Правила:

- patch-изменения не меняют смысл существующих labels;
- minor-изменения могут добавлять новые необязательные labels;
- major-изменения могут менять семантику или удалять поля;
- Alloy-конфигурация должна явно задавать поддерживаемые версии.

Label содержит только major и minor: patch-изменения по определению не меняют семантику labels и в контракте не отражаются.

## 8. Профили

### 8.1. Общие правила

Профиль — имя заранее определённого и версионированного набора настроек, описанного в конфигурации Alloy.

- Значение `*.profile` выбирается только из allowlist, заданного конфигурацией Alloy.
- Label не является DSL или языком программирования pipeline: произвольные значения и списки стадий не поддерживаются.
- Имя профиля обязано содержать версию.
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
  Специализированный pipeline для JSON access logs.

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

Контракт общий для всех доменов с секретами; различается только доменный суффикс файла:

```text
database  /run/alloy-secrets/<secret-id>.dsn
snmp      /run/alloy-secrets/<auth-id>.snmp
ipmi      /run/alloy-secrets/<secret-id>.ipmi
```

Правила валидации идентификатора, read-only монтирования и `is_secret` одинаковы для всех доменов. Требования к защите от path traversal описаны в разделе [13.4](#134-secret-path-traversal).

Пространство `secret-id` — единый trust domain в пределах хоста: контракт не привязывает контейнер к конкретному секрету, и любой контейнер с валидным label может сослаться на любой существующий файл секрета. В каталог секретов хоста следует выкладывать только секреты, предназначенные контейнерам этого хоста; для разграничения команд используйте соглашение о префиксах `secret-id`. Префиксы — только соглашение для операторов: конфигурация их не проверяет, и технически каждый файл секрета на хосте доступен каждому контейнеру этого хоста. Следствие той же модели доверия: контейнер может определить существование файла секрета, объявив соответствующий `secret-id` и наблюдая появление exporter; содержимое секрета при этом не раскрывается. Привязка `secret-id` к identity контейнера — вне рамок версии `0.2` (раздел [16](#16-out-of-scope)).

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

Профиль `fast-v1` требует соответствующей relabel/scrape-пары в конфигурации Alloy; референсная конфигурация включает только пару `normal-v1` (см. раздел [14](#14-reference-implementation)).

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

Для версии `0.2` рекомендуется использовать один composite profile. Дополнительные `redaction-profile` и `drop-profile` зарезервированы для расширения и не обязательны к реализации.

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
| `ru.3ops.discovery.blackbox.module` | Да | Например `http_2xx`, `tcp_connect` |
| `ru.3ops.discovery.blackbox.scheme` | Нет | `http` или `https` |
| `ru.3ops.discovery.blackbox.address` | Нет | Адрес проверки; по умолчанию адрес контейнера |
| `ru.3ops.discovery.blackbox.port` | Да | Порт проверки |
| `ru.3ops.discovery.blackbox.path` | Нет | HTTP path |
| `ru.3ops.discovery.blackbox.profile` | Нет | Scrape-профиль из allowlist; по умолчанию `normal-v1` |

Значение `module` должно входить в allowlist модулей blackbox exporter, заданный конфигурацией Alloy. Произвольные модули из labels не принимаются.

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

Флаг `otel.enabled` поэтому носит декларативный характер: он не управляет приёмом OTLP (receiver общий и статичен), а фиксирует намерение сервиса и используется для инвентаризации.

### 10.6. Domain: snmp

Используется для внешних устройств или management interfaces.

#### 10.6.1. Labels

```text
ru.3ops.discovery.snmp.enabled
ru.3ops.discovery.snmp.address
ru.3ops.discovery.snmp.module
ru.3ops.discovery.snmp.auth-id
ru.3ops.discovery.snmp.profile
```

Секреты SNMP community/SNMPv3 хранятся вне labels и выбираются через `auth-id`. Файл секрета: `/run/alloy-secrets/<auth-id>.snmp` по общему контракту раздела [9](#9-secret-contract).

### 10.7. Domain: ipmi

Используется для BMC/IPMI targets через внешний `ipmi_exporter` или другой adapter.

#### 10.7.1. Labels

```text
ru.3ops.discovery.ipmi.enabled
ru.3ops.discovery.ipmi.address
ru.3ops.discovery.ipmi.module
ru.3ops.discovery.ipmi.secret-id
ru.3ops.discovery.ipmi.profile
```

Файл секрета: `/run/alloy-secrets/<secret-id>.ipmi` по общему контракту раздела [9](#9-secret-contract).

Alloy не обязан напрямую реализовывать IPMI. Он может скрейпить Prometheus endpoint внешнего exporter.

## 11. Validation rules

Минимальные проверки перед созданием pipeline:

- `enabled == true` — кроме домена logs (см. раздел [10.3.1](#1031-политика-сбора-по-умолчанию));
- `version` поддерживается;
- `domain.enabled == true`;
- `type` входит в allowlist;
- `port` является числом 1..65535;
- `profile` входит в allowlist профилей домена (раздел [8](#8-профили));
- `secret-id` соответствует allowlist regex;
- `path` начинается с `/`;
- `scheme` входит в allowlist.

Неизвестный тип должен быть проигнорирован и отражён в логах Alloy.

Референсная конфигурация реализует проверки `path`, `scheme`, `profile` и `secret-id` relabel-правилами. Проверка `port` выполняется неявно и fail-closed: `keepequal` сопоставляет объявленный порт с реальными приватными портами контейнера, поэтому нечисловое, выходящее за диапазон или несуществующее значение приводит к отбрасыванию target.

## 12. Lifecycle

### 12.1. Добавление target

1. Контейнер запускается с `ru.3ops.discovery.enabled=true`.
2. `discovery.docker` обнаруживает контейнер.
3. `discovery.relabel` проверяет domain labels.
4. Alloy создаёт соответствующий pipeline.
5. Target появляется в Alloy UI.
6. Метрики или логи начинают поступать в backend.

### 12.2. Удаление target

1. Контейнер останавливается или удаляется.
2. Target исчезает из Docker discovery.
3. Динамический `foreach` component удаляется.
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
auth-id
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

- SSRF исключён: адрес scrape строится только из `__meta_docker_network_ip` и приватного порта самого контейнера, labels не могут перенаправить сбор на другой хост;
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
| [`020_metrics.alloy`](../alloy/020_metrics.alloy) | Домен metrics: relabel-правила и `prometheus.scrape` (профиль `normal-v1`) |
| [`030_database.alloy`](../alloy/030_database.alloy) | Домен database: `foreach`-pipeline для postgres, DSN из файла секрета |
| [`040_logs.alloy`](../alloy/040_logs.alloy) | Домен logs: relabel-правила и `loki.source.docker` |
| [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) | Profile dispatcher: `loki.process` с базовыми log-профилями |
| [`090_outputs.alloy`](../alloy/090_outputs.alloy) | Выходы: `prometheus.remote_write` и `loki.write` |

Референсная конфигурация включает только scrape-пару `normal-v1`: targets, объявившие другой профиль, ею сознательно не скрейпятся. Дополнительный профиль подключается копией пары из `020_metrics.alloy` с изменёнными regex profile-правила, `scrape_interval` и `scrape_timeout`.

Известное ограничение референсной конфигурации: `discovery.docker` создаёт отдельный target на каждую комбинацию контейнер+сеть+порт. Fan-out по портам схлопывается `keepequal`-правилами (metrics, database), но контейнер, подключённый к нескольким Docker-сетям, даёт дублирующиеся targets: для metrics — двойной scrape одного endpoint, для database — дублирующиеся exporters с одинаковыми сериями. Контейнеры с telemetry рекомендуется подключать к одной сети, видимой Alloy. Логи от этого не страдают: `loki.source.docker` дедуплицирует targets по container ID.

### 14.1. Параметры окружения

Deployment-специфичные значения настраиваются переменными окружения через `coalesce(sys.env("..."), <default>)`; при отсутствии переменной действует значение по умолчанию. Префикс `RU_3OPS_DISCOVERY_` = 3ops Discovery.

| Переменная | Назначение | Default |
|---|---|---|
| `RU_3OPS_DISCOVERY_DOCKER_HOST` | Адрес Docker daemon | `unix:///var/run/docker.sock` |
| `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` | Интервал обновления списка targets | `30s` |
| `RU_3OPS_DISCOVERY_SECRETS_DIR` | Каталог файлов секретов (см. [9](#9-secret-contract)) | `/run/alloy-secrets` |
| `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL` | Endpoint метрик (протокол Prometheus remote_write) | `http://prometheus:9090/api/v1/write` |
| `RU_3OPS_DISCOVERY_LOKI_PUSH_URL` | Endpoint логов (Loki push API) | `http://loki:3100/loki/api/v1/push` |

Параметры scrape-профилей (interval/timeout) переменными окружения не настраиваются: они являются частью контракта (см. [8.2](#82-scrape-профили)), а не deployment-конфигурацией.

Не встраивайте учётные данные в URL endpoints (`https://user:pass@host`): значение переменной — обычная строка и может появиться в Alloy UI и логах. Для аутентификации используйте блоки `basic_auth`/`authorization` внутри `endpoint` с секретом из `local.file` (`is_secret = true`).

### 14.2. Backends

Файл `090_outputs.alloy` — единственная точка интеграции с хранилищами; замена backend не затрагивает discovery- и pipeline-файлы. Alloy не ограничен парой Prometheus + Loki:

- `prometheus.remote_write` работает с любым remote_write-совместимым хранилищем: Mimir, VictoriaMetrics, Thanos, Grafana Cloud.
- `loki.write` — с любым endpoint, реализующим Loki push API.
- Для OTLP-backends (Tempo, vendor APM) потоки конвертируются через `otelcol.receiver.prometheus` / `otelcol.receiver.loki` и экспортируются `otelcol.exporter.otlp`.

Это не полный production-конфиг, а базовая структура реализации manifest. Пояснения к неочевидным местам (дедупликация targets по container ID, keep-правило для `secret-id`, соответствие scrape-профилям) находятся в комментариях самих файлов.

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
