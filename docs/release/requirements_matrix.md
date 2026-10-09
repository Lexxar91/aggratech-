# Требования и фактическая трассировка RC

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
по mTLS. Только контроллер управляет daemon и запускает фиксированный Python-образ
с allowlist ограничений. Задача не получает сеть, секреты, банк, БД, проверяющий
код или host mounts. CLI matching работает на in-memory DTO, без инфраструктуры.
Системные PDF/презентация не содержат закрытых материалов.

OpenAPI экспортируется непосредственно из приложения RC. Версия API остаётся
0.1.0; сдаваемый снимок определяется `rc_manifest.json`, версиями алгоритмов,
хешами исходников и ID образов. Commit/push не используются для фиксации RC.
