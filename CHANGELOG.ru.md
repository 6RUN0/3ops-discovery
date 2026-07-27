# Changelog

Все заметные изменения спецификации 3ops Discovery фиксируются в этом файле.

## 0.2.0 — Draft

- Docker stdout/stderr собираются по умолчанию для всех контейнеров.
- `ru.3ops.discovery.logs.enabled=false` используется как явный opt-out.
- `ru.3ops.discovery.logs.profile` теперь обозначает имя заранее определённого и версионированного pipeline-профиля.
- Профили вида `json,logfmt,raw` запрещены: label не является языком описания стадий.
- `raw` считается неявным fallback для любого профиля, если стадия парсинга не смогла разобрать строку.
- Добавлены базовые профили `raw-v1`, `generic-json-v1`, `generic-logfmt-v1`, `mixed-v1`.
- Добавлены правила версионирования log pipelines.
- Свободные значения `interval`/`timeout` в labels заменены версионированными профилями `metrics.profile`, `database.profile`, `blackbox.profile` из allowlist.
- Требование версии в имени распространено на все профили, не только на log-профили.
- Secret contract обобщён на домены `snmp` и `ipmi` (доменные суффиксы файлов секретов).
- Задокументировано исключение домена `logs` из требования `ru.3ops.discovery.enabled`.
- Референсная конфигурация Alloy вынесена в каталог `alloy/` (файлы с числовыми префиксами; единая точка интеграции с backend — `090_outputs.alloy`).
- Определён контракт переменных окружения `RU_3OPS_DISCOVERY_*` для deployment-специфичных параметров референсной конфигурации.
- Поля, извлечённые из содержимого логов, отправляются только в structured metadata, не в stream labels.
- Пространство `secret-id` задокументировано как единый trust domain хоста; привязка секрета к identity контейнера объявлена out of scope.
- Добавлен раздел 13.5 о границах доверия к labels.
- В референсной конфигурации реализованы relabel-валидации `path`/`scheme`/`profile` и схлопывание port fan-out для metrics и database.
- Домен database расширен на типы `mysql`/`mariadb`, `redis`, `mongodb`; серии всех exporter'ов несут provenance-labels (`environment`/`team`/`container`/`compose_*`/`collector`, синтезированные `job`/`instance`).
- Для redis формат секрета — `host:port` в `.dsn` плюс пароль в отдельном файле `<secret-id>.redispass` (аргумент `redis_addr` не принимает секрет).
- Добавлены multiline log-профили `python-stacktrace-v1` и `java-stacktrace-v1`: многострочные traceback склеиваются в одну запись.
- Введён overlay-каталог `alloy-optional/` и первый opt-in файл `060_otel.alloy` (OTLP receiver: метрики в `prometheus.remote_write`, логи в `loki.write` через allowlist-processor).
- Задокументирована модель кастомизации: extension points базы (раздел 14.4), опциональные файлы (14.5), соглашения против коллизий имён.
- Добавлены таблицы стандартных портов БД (10.2) и форматов секрет-файла по типам (9); зафиксировано исключение провенанса для OTLP-пути.
- Уточнено, что `database.type` обозначает wire-протокол, а не вендора: протокол-совместимые сборки (Percona Server for MySQL/MongoDB, XtraDB Cluster) метятся базовым типом `mysql`/`mongodb` без отдельного типа.
- Добавлен опциональный файл host-метрик `070_host-metrics.alloy` (`prometheus.exporter.unix`, серии `node_*`); rootfs/procfs/sysfs-пути параметризуются `RU_3OPS_DISCOVERY_HOST_ROOTFS_PATH`/`_PROCFS_PATH`/`_SYSFS_PATH`.
- Добавлен опциональный файл host-логов `080_host-logs.alloy` (`loki.source.journal` из systemd journal → `loki.write`) со статическими labels `host`/`collector`/`source`.
- Реализован домен blackbox (`035_blackbox.alloy`): HTTP-пробы по Docker-labels `ru.3ops.discovery.blackbox.*` через `prometheus.exporter.blackbox` (референс-модуль `http_2xx`, профиль `normal-v1`).
- Домен snmp (§8.5/§10.6/§10.6.1/§14.5): файловый провайдер устройств, auth-модель v2c/v3 (authPriv), opt-in overlay `037_snmp.alloy`, static-гейты и e2e с живым Net-SNMP агентом.
- Уточнён домен ipmi (§10.7): у Alloy нет нативного IPMI-компонента, поэтому домен переформулирован как частный случай `metrics` — скрейп Prometheus-endpoint внешнего `ipmi_exporter`; labels и суффикс секрета `.ipmi` сохранены (семантика контракта не изменилась).
