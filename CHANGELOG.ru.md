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
- Добавлен опциональный файл per-container метрик `075_container-metrics.alloy` (`prometheus.exporter.cadvisor`, серии `container_cpu_*`/`container_memory_*`/`container_network_*`): Docker API через socket-proxy (реюз `RU_3OPS_DISCOVERY_DOCKER_HOST`), провенанс §6.1 из allowlisted container-labels (`name` → `container`, сырые `container_label_*` отбрасываются), root-cgroup-статистика отключена; требует host cgroup namespace (`cgroup: host`, привилегированный overlay §14.3).
- Референсная конфигурация реализует все базовые scrape-профили §8.2 (`fast-v1`/`normal-v1`/`slow-v1`) для доменов metrics и blackbox: общий relabel несёт валидацию и провенанс, тонкая пара фильтр+scrape на профиль — маршрутизацию; имена профильных компонентов выводятся из полного имени профиля.
- Домен blackbox расширен модулями `tcp_connect` и `icmp` с покомпонентной композицией цели пробы (URL / `host:port` / голый host); сериям проб добавлен label `module`; ICMP-пробы работают без дополнительных привилегий контейнера, для hardened-сред задокументирован выход.
- Добавлен модуль `tls_connect` — все четыре обещанных семейства проб (HTTP, TCP, ICMP, TLS) отгружены референсом; модуль проверяет TLS handshake и отдаёт метрики срока действия сертификата, верификация цепочки доверия задокументирована как кастомизация окружения (`ca_file`).
- Реализованы database-профили §8.4 (`basic-v1`/`standard-v1`/`extended-v1`): профиль управляет объёмом сбора экспортёра (набором коллекторов), а не каденцией скрейпа; `standard-v1` соответствует дефолтам экспортёров, значение вне allowlist отбрасывает цель (fail-closed); маппинг профилей на коллекторы по типам СУБД задокументирован в §8.4.
- В allowlist snmp-модулей (§10.6) добавлен `system` (идентичность и аптайм безагентных устройств: `sysUpTime`, `sysName`); одна запись device-файла — один модуль, устройству с несколькими модулями соответствует несколько записей. Vendor-модули (например `cisco_device`) остаются за пределами референса: список открытый, расширение — свойство деплоя.
- Ревью-фиксы референса (поведенческие): opt-out `logs.enabled=false` исключает контейнер до `loki.source.docker`, а не построчно в тейлере; обязательные `metrics.port`, `blackbox.port` и `metrics.job` проверяются fail-closed presence-keep — контейнер без экспонированных TCP-портов больше не проходит `keepequal` и не скрейпится на порт 80, а отсутствие `metrics.job` отбрасывает target вместо подстановки имени scrape-компонента; snmp-запись без `name` получает имя из `address` вместо отказа всего экспортёра.
- Домен database: серии несут `host`; идентичность серии — `database.instance`, затем глобальный `instance`, затем `secret-id` (fallback); `database.name`/`user`/`sslmode` объявлены инвентарными (источник параметров подключения — только `.dsn`). Overlay 070 добавляет провенанс `host`/`collector` к сериям `node_*`; snmp-серии несут label `device` с именем устройства.
- Профиль `mixed-v1`: JSON- и logfmt-стадии сделаны взаимоисключающими (строка не проходит оба парсера), стадиям добавлены `pipeline_name`.
- Расширен §13.5: гарантия отсутствия SSRF ограничена доменами metrics/database, `blackbox.address` и неаутентифицированный OTLP-приёмник задокументированы как исключения с рекомендациями; задокументированы семантика пустого значения label, резерв `version`/`stream-policy`, поведение при пересоздании коллектора (positions/WAL), требования Loki к structured metadata и аутентификация backend'ов (Mimir/Grafana Cloud).
- Новые статические гейты: покрытие таблиц labels §10.x против конфига (таблица `LABELS_UNREAD`), провенанс `host`/`collector` по всем путям серий, парные коллизии overlay-файлов, защита от фантомных записей gap-таблиц модулей (удалена мёртвая запись `cisco_device`); `tools/materialize` очищает переиспользуемый каталог от устаревших файлов.
