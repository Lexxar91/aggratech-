# Требования и фактическая трассировка RC

Дополнение v3 от 11.10.2026: текущие 28 карточек и методика описаны в
[документе интеграции](../09_bank_v3_integration.md), действия/навыки/семейства —
в [трассировке](../../bank/v3_traceability.md). Python 3.14 и SQL/PLpgSQL
действительно исполняются в отдельных контейнерах. Допуск v3 выполнен на
принятии источника пользователем и полном актуальном техническом отчёте;
статистическая калибровка этим не доказывается. Таблица RC v1 ниже историческая.

| Требование v3 | Реализация | Фактическое подтверждение |
|---|---|---|
| Все 28 карточек, 5 A + 2 B, связанные Python/SQL | bank/private/v3.json, v3_traceability.md | 504 строки / 28764 проверки полного runner-прогона passed |
| Исполнение Python и SQL/PLpgSQL | v3_python.py, v3_sql.py, fake-адаптеры | PostgreSQL 18.6, native bind и настоящие конкурентные соединения Y3; альтернативы прошли |
| Пакеты A/B/C/D, навыки и подтверждение | v3_grading.py, v3_models.py | отдельные требования навыков, минимум связанного семейства, критические нарушения; регрессии passed |
| Нечисловые состояния, таймер без autosubmit | assessment service/jobs, runtime_bank | incomplete/environment_error/invalid_item/review_required не превращаются в 0; legacy сохранён |
| Настоящий допуск и его происхождение | v3_admission.py, operator acceptance | текущий bank/grader/source/runtime hash, полный отчёт, разрешение пользователя; v1 not_admitted |
| React credit → публикация → matching → согласие/PDF | assessment/matching/communications | 1 passed: Junior/X и Middle/Y, черновик/restart, actual credit matching, зарплата, email-only согласие/PDF и отзыв; технические аккаунты, без fixture-категорий/ручных баллов |

## Историческая трассировка RC v1

Ниже техническая трассировка продукта, не независимое review банка.
Три содержательные таблицы вакансий остаются в `bank/vacancy_mappings.json`;
их review — не проведено, чек-лист содержит три незаполненные строки.

| Требование | Реализация | Подтверждение/граница |
|---|---|---|
| R01 Две роли, email и сохраняемая сессия | auth, candidate_profile, employer | test_auth_profiles, test_auth_email; commit перед HTTP-ответом |
| R02 Приватность и PDF с кириллицей | candidate_profile/access.py, pdf.py | auth/profile и browser; новые ответы учитывают отзыв |
| R03 Отдельное исполнение Python | runner/server.py, sandbox.py; worker mTLS | runner integration + verify_isolation; docker-limited, не VM |
| R04 12 семейств/24 версии, X/Y 4A+2B | bank/private/full.json, blueprints.json | bank_quality; технический passed не зачётный допуск |
| R05 Собственные тесты X4/Y4 и структурированные SQL | candidate_tests, structured_evaluator | test_stage3_bank, test_bank_materials; закрытые материалы не экспортируются |
| R06 Циклы, сроки, история, публикация, cooldown, апелляции | assessment/service.py, policy.py, jobs.py, admin.py | stage4 grading/cycles/browser; credit пока закрыт |
| R07 Объяснимый matching, три шаблона, сравнение/приватность | matching, fsp | matching/API tests; реальная приёмка ожидает допуска |
| R08 Общий API/CLI, B0/B1/B2, labels после выдачи | matching/engine.py, metrics.py, tools/matching_check.py | matching и stage7 tests; offline CLI, фиксированный as_of |
| R09 120 кандидатов/12 потребностей/6 работодателей | fixtures/validation/stage7, validation | 40/80 и 4/8; синтетика, не реальные люди |
| R10 Приглашения, 6 статусов, 7 суток, атомарное согласие | invitations, candidate_profile/access.py | test_invitations; live на подтверждённых профилях ещё заблокирован |
| R11 Вакансии, RUB-зарплата, отклики и несколько источников | vacancies, migration 0006 | test_vacancies + автоматизированный browser; независимый отзыв |
| R12 Допуск банка и независимое review | bank_checker, runtime_bank | хеши проверяются; review и admission пока не получены |

## Архитектурный снимок

FastAPI обслуживает один origin и статический браузерный клиент; PostgreSQL хранит
профили, циклы, потребности, снимки выдачи, приглашения, вакансии, отклики и аудит.
Транзакция завершается до отправки HTTP-ответа. Очередь в PostgreSQL обрабатывает
отдельный worker; повторные задания и конкурентные действия защищены версиями,
уникальностью и блокировками. SMTP только Mailpit. Контакты — отдельный DTO;
права вычисляются по текущему общему согласию/блокировке и союзу действующих источников.

API не имеет Docker socket или runner mTLS-ключа; worker вызывает контроллер
по mTLS. Только контроллер управляет daemon и запускает фиксированные Python/SQL-образы
с allowlist ограничений. Задача не получает сеть, секреты, банк, БД, проверяющий
код или host mounts. CLI matching работает на in-memory DTO, без инфраструктуры.
Системные PDF/презентация не содержат закрытых материалов.

OpenAPI экспортируется непосредственно из приложения RC. Версия API остаётся
0.1.0; сдаваемый снимок определяется `rc_manifest.json`, версиями алгоритмов,
хешами исходников и ID образов. Commit/push не используются для фиксации RC.
