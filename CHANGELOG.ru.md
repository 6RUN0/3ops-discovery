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
