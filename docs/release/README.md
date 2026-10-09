# Aggratech — release candidate этапа 9

Дата комплекта: 09.10.2026. Технические проверки RC выполнены;
полная приёмка **не завершена**. Банк `not_admitted`, человеческие проверки
не проведены, видео ещё нужно записать. Не использовать демо-категории
и синтетические JSON-баллы как подтверждённую квалификацию людей.

## Что передать жюри

- Исходники и `uv.lock`, `compose.yaml`, `Dockerfile`, `.env.example`.
- [Документация](export/documentation.pdf) и [презентация](export/presentation.pdf).
- [Отчёт валидации](validation_report.md) и [таблица требований](requirements_matrix.md).
- [Сценарий восьмиминутного демо](demo_script.md), [текст слайдов](slides.md).
- [OpenAPI](openapi.json), исходные документы [архитектуры](../05_architecture.md),
  [правил assessment](../02_assessment_algorithm.md) и [matching](../03_matching_and_invitation_algorithm.md).
- [Инструкции проверяющему и добровольцам](human_checks.md),
  [хеши материалов](materials_manifest.json), [манифест RC](rc_manifest.json).
- [Четыре артефакта CLI](cli/report.md) и [публичная сводка банка](bank-public-summary.json).
- [Контроль 120/12/6 и всех восьми потребностей](technical/report.md),
  [схемы и словарь CLI](cli-input/README.md).

Закрытые материалы банка необходимы приложению, но не входят в публичный
комплект PDF/CLI: не выкладывать `bank/private/`, служебный `report.json`,
персональные реестры, `.env`, токены и ключи. Содержимое release-каталога
не раздаётся через API/static. Полный комплект рецензента передаёт сама команда
уполномоченному проверяющему; публичная версия содержит только хеши и чек-листы.

## Чистый запуск на отдельном стенде

Нужны Docker Engine (Linux, cgroup v2, seccomp), Compose plugin и интернет
для первой сборки. Отдельная VM и Python на хосте не требуются.
Из корня проекта, с новыми volumes и свободными портами:

```bash
test -f .env || cp .env.example .env
C() {
  APP_HTTP_PORT=18108 MAILPIT_HTTP_PORT=18132 docker compose \
    -p aggratech-stage9-rc -f compose.yaml -f docs/release/compose.rc.yaml "$@"
}
C --profile check build --no-cache api runner-controller checks
C up -d --no-build --wait --wait-timeout 120
curl --fail http://127.0.0.1:18108/health/live
curl --fail http://127.0.0.1:18108/health/ready
C exec -T worker python -m app.tools.runner_check
C exec -T runner-controller python -m runner.verify_isolation
```

Приложение: http://127.0.0.1:18108; OpenAPI: http://127.0.0.1:18108/docs;
письма: http://127.0.0.1:18132. Миграции, ключ JWT и mTLS готовит Compose.
Override меняет только имена образов: другие проекты и данные не затрагиваются.
Проверка потребует свободного места для новых образов и volumes.
Не выполнять `down -v`; для повторного чистого запуска выбирать новый project name.

Регистрируйте две роли, подтверждайте письма в Mailpit, заполните профиль.
Включите видимость кандидата и скрытие имени/контактов; до явного согласия
работодатель не должен видеть контакты. Assessment доступен только как demo.
Подтверждённая подборка пока пуста: это действие gate, а не разрешение добавить seed.
Вакансия с RUB-зарплатой допускает ручной профиль без подтверждённого грейда;
кандидат выбирает контакты при отклике, затем может отозвать только этот источник.

## Итоговый пакет

```bash
C --profile check up -d --no-build --wait test-db
C --profile check run --rm --no-deps checks sh -c 'alembic upgrade head && pytest -q -p no:cacheprovider && ruff check . --no-cache && ruff format --check . --no-cache && mypy --cache-dir=/dev/null'
C exec -T worker python -m app.tools.bank_quality --output /tmp/bank-rc
```

Все HTTP и конкурентные проверки используют отдельную `aggratech_test`,
основная БД не очищается. Test-квалификации не становятся продуктовыми результатами.
`bank_quality` код 0 означает технический passed, а не зачётный допуск;
без независимого review `--require-admission` должен завершиться кодом 1.
Правильные решения и скрытые тесты не копировать в публичный комплект.

## Автономный CLI — три команды

Из корня проекта, после сборки `aggratech-rc:app`; каталог вывода должен быть пустым:

```bash
mkdir -p artifacts/jury-example artifacts/jury-run
docker run --rm --network none --read-only --tmpfs /tmp:size=32m --cap-drop ALL --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" -v "$PWD/artifacts/jury-example:/output" aggratech-rc:app python -m app.tools.matching_check --write-example /output
docker run --rm --network none --read-only --tmpfs /tmp:size=32m --cap-drop ALL --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" -v "$PWD/artifacts/jury-example:/input:ro" aggratech-rc:app python -m app.tools.matching_check --input /input/dataset.json --labels /input/labels.json --validate-only
docker run --rm --network none --read-only --tmpfs /tmp:size=32m --cap-drop ALL --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" -v "$PWD/artifacts/jury-example:/input:ro" -v "$PWD/artifacts/jury-run:/output" aggratech-rc:app python -m app.tools.matching_check --input /input/dataset.json --labels /input/labels.json --output /output
```

Пример содержит `as_of`; для воспроизводимости его не менять между B0/B1/B2.
Другой набор жюри готовится по `dataset.schema.json`, `labels.schema.json`
и словарю примера, без runtime-генерации тестов через LLM.
CLI формирует `rankings.json`, `metrics.json`, `report.md`, `run_manifest.json`.
Labels влияют только на метрики; при отсутствии полной разметки — «не измерено».
Вычислительная логика общая с API; CLI не подключается к БД, SMTP или runner.

## Экспорт и ограничения

PDF собраны из Markdown этого комплекта существующим ReportLab и встроенным
DejaVuSans. Команда воспроизведения: `.venv/bin/python docs/release/build_exports.py`
в разработочном окружении проекта; жюри готовые PDF не требует Python на хосте.
Числа слайдов берутся из фактического отчёта, а не целевых порогов.
Видео **не записано**; скриншоты и автоматический тест его не заменяют.
Не выполнены независимый запуск другим человеком и человеческая репетиция.

Docker-limited — ограниченная контейнерная изоляция для хакатонного демо,
не эквивалент VM/gVisor и не заявление о production-безопасности.
ФСП — mock с явным происхождением; Senior не оценивается.
Уже скачанные PDF и увиденные контакты невозможно отозвать удалённо.
