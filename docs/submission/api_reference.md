# API и зависимости

Aggratech · справочник для проверки и интеграции

Снимок OpenAPI 0.1.0 · 11 октября 2026 года

## 01 / Как пользоваться API

API и веб-интерфейс доступны с одного адреса: http://localhost:18000. Основной префикс — /api/v1. Полная машиночитаемая спецификация: docs/release/openapi.json; интерактивная версия после запуска — /docs. Каталог ниже содержит все 83 операции на 70 путях, включая служебные проверки готовности. Имена полей сохранены как в API, чтобы пример можно было повторить.

### Вход и права

Регистрация создаёт только candidate или employer. Email подтверждается одноразовой ссылкой из письма; Mailpit доступен на localhost:18025. При входе сервер возвращает access_token, который передаётся как Authorization: Bearer <access_token>. Refresh-сессия использует защищённую cookie. Браузерный клиент обрабатывает её автоматически. Для прямых запросов используйте access token; наличие сессии само по себе не разрешает чтение контактов. Logout и отзыв сессии прекращают доступ.

Роль и принадлежность проверяются сервером на каждом действии. UUID в URL не даёт права на чужой объект. Кандидат управляет своим профилем, прохождением и согласиями; компания — своими потребностями, предложениями и вакансиями. Карточки и PDF работодателя фильтруются по текущей приватности.

### Форматы и ошибки

Тела запросов — JSON, если операция не является скачиванием PDF. Даты с временем передаются в ISO 8601 с часовым поясом. Денежные диапазоны вакансий и предложений — RUB за месяц до налогов; обе границы обязательны и упорядочены. Дополнительные поля закрытых входных схем отклоняются.

| Код | Смысл |
|---|---|
| 200 / 201 / 202 / 204 | Успешный ответ согласно операции; 202 не означает, что оценивание уже завершено |
| 401 | Нет действующей сессии или access token |
| 403 | Действие недоступно роли либо нарушены условия доступа |
| 404 | Объект отсутствует или недоступен пользователю |
| 409 | Конфликт состояния, повтор несовместимого действия или устаревшая версия |
| 422 | Неверное поле или тело запроса |

Каталог перечисляет ответы, объявленные в OpenAPI. Не все доменные 4xx отдельно объявлены у каждой операции: фактический код зависит от состояния и проверок доступа. Их не следует трактовать как исчерпывающий список только из таблицы. Ошибка в поле содержит путь и причину; служебные идентификаторы ошибок нужны интеграции, а интерфейс переводит их в понятный текст.

### Пример регистрации

```json
{
  "email": "new-candidate@example.com",
  "password": "StrongExample2026!",
  "role": "candidate"
}
```

Это POST /api/v1/auth/register. Пример содержит вымышленный адрес и не создаёт учётную запись при чтении документа. Для входа используйте POST /api/v1/auth/login с email и password, затем заголовок Authorization. Значения токенов и реальные пароли в документацию не включены.

### Важные особенности клиентов

В проверке уровня обычный интерфейс явно передаёт mode=credit и не выбирает форму. Технический контракт CycleInput сохраняет прежние параметры и default demo для совместимости; внешнему клиенту нельзя полагаться на этот default для обычного прохождения. Допуск банка всегда проверяет сервер. Это описание существующего API, а не изменение пользовательского процесса.

Отправка решения должна предварительно сохранить актуальный текст, а затем зафиксировать соответствующую часть. Зафиксированное решение нельзя заменить поздним черновиком. Оценивание асинхронно: читайте состояние цикла до терминального результата, а технический сбой не считайте отрицательным доказательством навыка.

При отправке приглашения нужен idempotency_key: повтор того же запроса возвращает прежний результат; несовместимый payload с тем же ключом отклоняется. Потребность обязательна, вакансия не требуется. При отклике выбираются allowed_fields и consent_version=contacts-v1. Отзыв одного источника согласия не отменяет остальные.

Закрытые ответы, эталоны и скрытые тесты не входят в публичные DTO. Наличие смыслового текста вариантов ответа в разрешённом задании не является выдачей правильного ответа. Контакты читаются только при действующем разрешении и также проверяются при выдаче PDF.

## 02 / Каталог операций

В строке указаны метод и путь, схема тела запроса, параметры и объявленные ответы. Ссылки на именованные схемы раскрываются в исходном OpenAPI; входные поля дополнительно приведены в главе 03. Path-параметры обязательны; query-параметры обязательны только при соответствующей пометке.

### Регистрация и сессии

| Операция | Вход | Объявленные ответы |
|---|---|---|
| POST /api/v1/auth/register | Registration | 201: UserView; 422: HTTPValidationError |
| POST /api/v1/auth/login | Credentials | 200: AccessView; 422: HTTPValidationError |
| POST /api/v1/auth/refresh | без тела | 200: AccessView |
| POST /api/v1/auth/logout | без тела | 200: MessageView |
| GET /api/v1/auth/me | без тела | 200: UserView |
| POST /api/v1/auth/verify-email | ActionRequest | 200: MessageView; 422: HTTPValidationError |
| POST /api/v1/auth/resend-verification | EmailRequest | 202: MessageView; 422: HTTPValidationError |
| POST /api/v1/auth/password-reset/request | EmailRequest | 202: MessageView; 422: HTTPValidationError |
| POST /api/v1/auth/password-reset/confirm | ResetConfirmation | 200: MessageView; 422: HTTPValidationError |

### Профиль и доступ кандидата

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /api/v1/candidate/profile | без тела | 200: ProfileView |
| PATCH /api/v1/candidate/profile | ProfileInput | 200: ProfileView; 422: HTTPValidationError |
| GET /api/v1/candidate/contacts | без тела | 200: ContactsView |
| PATCH /api/v1/candidate/contacts | ContactsInput | 200: ContactsView; 422: HTTPValidationError |
| PATCH /api/v1/candidate/privacy | Privacy | 200: ProfileView; 422: HTTPValidationError |
| GET /api/v1/candidate/profile.pdf | без тела | 200: объект |
| GET /api/v1/candidate/blocks | без тела | 200: список BlockView |
| PUT /api/v1/candidate/blocks/{employer_id} | без тела; employer_id (path, обяз.) | 204; 422: HTTPValidationError |
| DELETE /api/v1/candidate/blocks/{employer_id} | без тела; employer_id (path, обяз.) | 204; 422: HTTPValidationError |
| DELETE /api/v1/candidate/contact-grants/{employer_id} | без тела; employer_id (path, обяз.) | 204; 422: HTTPValidationError |

### Кабинет работодателя

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /api/v1/candidates/{candidate_id} | без тела; candidate_id (path, обяз.) | 200: SafeCard; 422: HTTPValidationError |
| GET /api/v1/candidates/{candidate_id}/profile.pdf | без тела; candidate_id (path, обяз.) | 200: объект; 422: HTTPValidationError |
| GET /api/v1/candidates/{candidate_id}/contacts | без тела; candidate_id (path, обяз.) | 200: SharedContacts; 422: HTTPValidationError |
| GET /api/v1/employer/profile | без тела | 200: EmployerView |
| PATCH /api/v1/employer/profile | EmployerInput | 200: EmployerView; 422: HTTPValidationError |
| GET /api/v1/employers | без тела | 200: список CompanyCard |
| GET /api/v1/catalog/specializations | без тела | 200: список NamedItem |
| GET /api/v1/catalog/grades | без тела | 200: список NamedItem |
| GET /api/v1/catalog/skills | без тела | 200: список NamedItem |
| GET /api/v1/catalog/technologies | без тела | 200: список NamedItem |
| GET /api/v1/catalog/categories | без тела | 200: список CategoryItem |
| GET /api/v1/employer/need-templates | без тела | 200: список object |
| GET /api/v1/employer/recommendations/{snapshot_id} | без тела; snapshot_id (path, обяз.) | 200: SnapshotView; 422: HTTPValidationError |

### Проверка навыков и история

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /api/v1/assessment/availability | без тела | 200: AssessmentAvailability |
| GET /api/v1/assessment/survey | без тела | 200: SurveyInput / null |
| PUT /api/v1/assessment/survey | SurveyInput | 200: SurveyInput; 422: HTTPValidationError |
| GET /api/v1/assessment/cycles | без тела | 200: список CycleView |
| POST /api/v1/assessment/cycles | CycleInput | 200: CycleView; 422: HTTPValidationError |
| GET /api/v1/assessment/cycles/{cycle_id} | без тела; cycle_id (path, обяз.) | 200: CycleView; 422: HTTPValidationError |
| PUT /api/v1/assessment/cycles/{cycle_id}/answers/{family} | SaveAnswer; cycle_id (path, обяз.), family (path, обяз.) | 200: CycleView; 422: HTTPValidationError |
| POST /api/v1/assessment/cycles/{cycle_id}/answers/{family}/fix | SaveAnswer; cycle_id (path, обяз.), family (path, обяз.) | 200: CycleView; 422: HTTPValidationError |
| POST /api/v1/assessment/cycles/{cycle_id}/submit/{phase} | без тела; cycle_id (path, обяз.), phase (path, обяз.) | 200: CycleView; 422: HTTPValidationError |
| POST /api/v1/assessment/cycles/{cycle_id}/start-b | без тела; cycle_id (path, обяз.) | 200: CycleView; 422: HTTPValidationError |
| POST /api/v1/assessment/cycles/{cycle_id}/publish | без тела; cycle_id (path, обяз.) | 200: ResultView; 422: HTTPValidationError |
| POST /api/v1/assessment/cycles/{cycle_id}/appeals | AppealInput; cycle_id (path, обяз.) | 200: AppealView; 422: HTTPValidationError |
| GET /api/v1/assessment/appeals | без тела | 200: список AppealView |

### Потребности и подбор

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /api/v1/catalog/matching-dictionary | без тела | 200: object |
| GET /api/v1/employer/needs | без тела | 200: список Need |
| POST /api/v1/employer/needs | NeedInput | 200: Need; 422: HTTPValidationError |
| GET /api/v1/employer/needs/{need_id} | без тела; need_id (path, обяз.) | 200: Need; 422: HTTPValidationError |
| PATCH /api/v1/employer/needs/{need_id} | NeedInput; need_id (path, обяз.) | 200: Need; 422: HTTPValidationError |
| POST /api/v1/employer/needs/{need_id}/recommendations | без тела; need_id (path, обяз.) | 200: SnapshotView; 422: HTTPValidationError |
| GET /api/v1/employer/needs/{need_id}/recommendations | без тела; need_id (path, обяз.) | 200: список object; 422: HTTPValidationError |
| PUT /api/v1/employer/needs/{need_id}/candidates/{candidate_id} | MarkInput; need_id (path, обяз.), candidate_id (path, обяз.) | 200: MarkInput; 422: HTTPValidationError |

### Предложения и согласия

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /api/v1/employer/invitations | без тела | 200: список InvitationView |
| POST /api/v1/employer/invitations | SendInput | 200: InvitationView; 422: HTTPValidationError |
| GET /api/v1/employer/invitations/{identifier} | без тела; identifier (path, обяз.) | 200: InvitationView; 422: HTTPValidationError |
| POST /api/v1/employer/invitations/{identifier}/withdraw | без тела; identifier (path, обяз.) | 200: InvitationView; 422: HTTPValidationError |
| GET /api/v1/candidate/invitations | без тела | 200: список InvitationView |
| GET /api/v1/candidate/invitations/{identifier} | без тела; identifier (path, обяз.) | 200: InvitationView; 422: HTTPValidationError |
| POST /api/v1/candidate/invitations/{identifier}/accept | Acceptance; identifier (path, обяз.) | 200: InvitationView; 422: HTTPValidationError |
| POST /api/v1/candidate/invitations/{identifier}/reject | без тела; identifier (path, обяз.) | 200: InvitationView; 422: HTTPValidationError |

### Связь с ФСП

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /api/v1/candidate/fsp/achievements | без тела | 200: FspView |
| POST /api/v1/candidate/fsp/link | LinkInput | 200: FspView; 422: HTTPValidationError |
| DELETE /api/v1/candidate/fsp/link | без тела | 200: FspView |
| POST /api/v1/candidate/fsp/sync | без тела | 200: FspView |

### Вакансии

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /api/v1/employer/vacancies | без тела | 200: список VacancyView |
| POST /api/v1/employer/vacancies | VacancyInput | 200: VacancyView; 422: HTTPValidationError |
| PATCH /api/v1/employer/vacancies/{identifier} | VacancyPatch; identifier (path, обяз.) | 200: VacancyView; 422: HTTPValidationError |
| GET /api/v1/employer/vacancies/{identifier} | без тела; identifier (path, обяз.) | 200: VacancyView; 422: HTTPValidationError |
| POST /api/v1/employer/vacancies/{identifier}/close | без тела; identifier (path, обяз.) | 200: VacancyView; 422: HTTPValidationError |
| GET /api/v1/vacancies | без тела | 200: список VacancyView |
| GET /api/v1/vacancies/{identifier} | без тела; identifier (path, обяз.) | 200: VacancyView; 422: HTTPValidationError |

### Отклики

| Операция | Вход | Объявленные ответы |
|---|---|---|
| POST /api/v1/vacancies/{identifier}/applications | ApplicationInput; identifier (path, обяз.) | 200: ApplicationView; 422: HTTPValidationError |
| GET /api/v1/candidate/applications | без тела | 200: список ApplicationView |
| GET /api/v1/employer/vacancies/{identifier}/applications | без тела; identifier (path, обяз.) | 200: список ApplicationView; 422: HTTPValidationError |
| GET /api/v1/candidate/applications/{identifier} | без тела; identifier (path, обяз.) | 200: ApplicationView; 422: HTTPValidationError |
| GET /api/v1/employer/applications/{identifier} | без тела; identifier (path, обяз.) | 200: ApplicationView; 422: HTTPValidationError |
| POST /api/v1/applications/{identifier}/view | без тела; identifier (path, обяз.) | 200: ApplicationView; 422: HTTPValidationError |
| POST /api/v1/applications/{identifier}/accept | без тела; identifier (path, обяз.) | 200: ApplicationView; 422: HTTPValidationError |
| POST /api/v1/applications/{identifier}/reject | без тела; identifier (path, обяз.) | 200: ApplicationView; 422: HTTPValidationError |
| POST /api/v1/applications/{identifier}/withdraw | без тела; identifier (path, обяз.) | 200: ApplicationView; 422: HTTPValidationError |

### Готовность и диагностика

| Операция | Вход | Объявленные ответы |
|---|---|---|
| GET /health/live | без тела | 200: object |
| GET /health/ready | без тела | 200: объект |

## 03 / Поля входных схем

Ниже — все именованные схемы тел запросов, используемые операциями каталога, и их вложенные модели. «Да» означает обязательное поле в JSON; null допустим только если указан в типе. Ограничения длины, количества и точные типы остаются в OpenAPI. Сервер вычисляет поля результатов и назначает идентификаторы; их нельзя передать вместо доказательств навыка.

### Acceptance

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| allowed_fields | список email, phone, messengers | да | мин. элементов: 1; макс. элементов: 3 |
| consent_version | contacts-v1 | да | — |

### ActionRequest

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| token | string | да | мин. длина: 20; макс. длина: 256; формат: password |

### AppealInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| message | string | да | мин. длина: 10; макс. длина: 2000 |

### ApplicationInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| allowed_fields | список email, phone, messengers | да | мин. элементов: 1; макс. элементов: 3 |
| consent_version | contacts-v1 | да | — |
| message | string | нет | макс. длина: 4000; default:  |

### ContactsInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| email | string | да | формат: email |
| phone | string | нет | макс. длина: 32; default:  |
| messengers | object | нет | — |

### Credentials

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| email | string | да | формат: email |
| password | string | да | мин. длина: 12; макс. длина: 128; формат: password |

### CycleInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| grade | junior, middle | да | — |
| mode | demo, credit | нет | default: demo |
| form | X, Y / null | нет | — |

### EmailRequest

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| email | string | да | формат: email |

### EmployerInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| company_name | string | нет | макс. длина: 160; default:  |
| description | string | нет | макс. длина: 4000; default:  |
| industry | string | нет | макс. длина: 120; default:  |
| representative_contact | string | нет | макс. длина: 254; default:  |

### LinkInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| external_id | string | да | мин. длина: 1; макс. длина: 128 |
| claim_code | string | да | мин. длина: 1; макс. длина: 128 |

### MarkInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| saved | boolean | нет | default: False |
| hidden | boolean | нет | default: False |
| reason | string | нет | макс. длина: 500; default:  |

### NeedInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| need_id | string | нет | default: server |
| employer_id | string | нет | default: server |
| title | string | да | мин. длина: 1; макс. длина: 160 |
| specialization | backend | да | — |
| accepted_grades | список junior, middle | да | мин. элементов: 1; макс. элементов: 2 |
| required_stack | список RequiredTechnology | да | макс. элементов: 30 |
| preferred_stack | список string | да | макс. элементов: 30 |
| skill_priorities | object | да | — |
| required_verified_skills | список language_algorithms, sql_data, http_api, debug_reliability, security_validation | да | макс. элементов: 5 |
| work_formats | список remote, hybrid, office | да | мин. элементов: 1; макс. элементов: 3 |
| location | string / null | да | — |
| salary_from | integer / number | да | мин.: 0.0; макс.: 9999999999.0 |
| salary_to | integer / number | да | мин.: 0.0; макс.: 9999999999.0 |
| desired_start_date | string / null | да | — |
| start_date_required | boolean | да | — |
| role | string | нет | макс. длина: 120; default:  |
| team_description | string | нет | макс. длина: 4000; default:  |
| task_description | string | нет | макс. длина: 4000; default:  |
| additional_requirements | object | нет | — |
| additional_wishes | string | нет | макс. длина: 2000; default:  |
| urgency | urgent, normal, flexible | нет | default: normal |
| vacancy_id | string / null | нет | — |
| version | integer | нет | мин.: 1.0; default: 1 |
| template_code | string / null | нет | — |
| template_version | string / null | нет | — |
| salary_currency | RUB | нет | default: RUB |
| salary_basis | gross | нет | default: gross |

### Offer

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| description | string | да | мин. длина: 1; макс. длина: 4000 |
| salary_from | integer / number | да | мин.: 0.0; макс.: 9999999999.0 |
| salary_to | integer / number | да | мин.: 0.0; макс.: 9999999999.0 |
| currency | RUB | нет | default: RUB |
| salary_basis | gross | нет | default: gross |
| work_formats | список remote, hybrid, office | да | мин. элементов: 1; макс. элементов: 3 |
| location | string / null | нет | — |
| desired_start_date | string / null | нет | — |
| start_date_required | boolean | нет | default: False |
| conditions | string | да | мин. длина: 1; макс. длина: 4000 |
| representative_contact | string | да | мин. длина: 1; макс. длина: 500 |

### Privacy

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| visible_to_employers | boolean | нет | default: False |
| show_name | boolean | нет | default: False |

### ProfileInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| display_name | string | нет | макс. длина: 120; default:  |
| summary | string | нет | макс. длина: 4000; default:  |
| experience | string | нет | макс. длина: 8000; default:  |
| salary_min | number / string / null | нет | — |
| salary_max | number / string / null | нет | — |
| salary_basis | gross | нет | default: gross |
| available_from | string / null | нет | — |
| work_preferences | WorkPreferences | нет | — |
| technology_ids | список string | нет | макс. элементов: 30 |
| confirm_preferences | boolean | нет | default: False |
| consent_version | profile-v1 / null | нет | — |

### Registration

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| email | string | да | формат: email |
| password | string | да | мин. длина: 12; макс. длина: 128; формат: password |
| role | candidate, employer | да | — |

### RequiredTechnology

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| technology | string | да | — |
| verification_required | boolean | да | — |

### ResetConfirmation

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| token | string | да | мин. длина: 20; макс. длина: 256; формат: password |
| password | string | да | мин. длина: 12; макс. длина: 128; формат: password |

### SaveAnswer

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| revision | integer | да | мин.: 0.0 |
| step | base, transfer | да | — |
| answer | TaskAnswer | да | — |

### SendInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| need_id | string | да | формат: uuid |
| candidate_id | string | да | формат: uuid |
| idempotency_key | string | да | мин. длина: 1; макс. длина: 128 |
| offer | Offer | да | — |

### SurveyInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| industry | string | да | мин. длина: 1; макс. длина: 120 |
| specialization | backend | нет | default: backend |
| stack | список string | да | мин. элементов: 1; макс. элементов: 20 |
| experience_years | integer | да | мин.: 0.0; макс.: 50.0 |
| tools_policy | independent | нет | default: independent |
| instructions_accepted | True | да | — |

### TaskAnswer

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| source | string | нет | макс. длина: 32768; default:  |
| structured | object | нет | — |
| diagnosis | string | нет | макс. длина: 80; default:  |
| verification | список string | нет | макс. элементов: 5 |
| tests | список object | нет | макс. элементов: 3 |

### VacancyInput

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| description | string | да | мин. длина: 1; макс. длина: 4000 |
| salary_from | integer / number | да | мин.: 0.0; макс.: 9999999999.0 |
| salary_to | integer / number | да | мин.: 0.0; макс.: 9999999999.0 |
| currency | RUB | нет | default: RUB |
| salary_basis | gross | нет | default: gross |
| work_formats | список remote, hybrid, office | да | мин. элементов: 1; макс. элементов: 3 |
| location | string / null | нет | — |
| desired_start_date | string / null | нет | — |
| start_date_required | boolean | нет | default: False |
| conditions | string | да | мин. длина: 1; макс. длина: 4000 |
| representative_contact | string | да | мин. длина: 1; макс. длина: 500 |
| title | string | да | мин. длина: 1; макс. длина: 160 |
| need_id | string / null | нет | — |

### VacancyPatch

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| version | integer | да | мин.: 1.0 |
| title | string / null | нет | — |
| description | string / null | нет | — |
| salary_from | integer / number / null | нет | — |
| salary_to | integer / number / null | нет | — |
| currency | RUB / null | нет | — |
| salary_basis | gross / null | нет | — |
| work_formats | список remote, hybrid, office / null | нет | — |
| location | string / null | нет | — |
| desired_start_date | string / null | нет | — |
| start_date_required | boolean / null | нет | — |
| conditions | string / null | нет | — |
| representative_contact | string / null | нет | — |
| need_id | string / null | нет | — |

### WorkPreferences

| Поле | Тип / значения | Обяз. | Ограничения |
|---|---|---|---|
| formats | список remote, hybrid, office | нет | макс. элементов: 3 |
| location | string / null | нет | — |

## 04 / Библиотеки и версии

Версии прямых Python-зависимостей сняты с pyproject.toml; версии frontend — с frontend/package.json. Транзитивные зависимости закреплены в uv.lock и frontend/package-lock.json. Эти файлы входят в репозиторий и задают точное дерево установки. Хеши источников версии записаны в manifest.json этого комплекта.

### Сервер

| Библиотека | Версия |
|---|---|
| alembic | 1.20.0 |
| asyncpg | 0.31.0 |
| fastapi | 0.142.2 |
| httpx | 0.28.1 |
| email-validator | 2.3.0 |
| pwdlib[argon2] | 0.3.1 |
| PyJWT | 2.15.1 |
| reportlab | 5.0.1 |
| pydantic | 2.13.5 |
| pydantic-settings | 2.15.0 |
| sqlalchemy | 2.0.54 |
| uvicorn | 0.54.0 |

### Проверки и упаковка Python

| Инструмент | Версия |
|---|---|
| mypy | 2.4.0 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |
| ruff | 0.16.10 |
| pypdf | 6.19.0 |
| playwright | 1.63.0 |
| hatchling | 1.32.4 |

### Клиент

| Библиотека | Версия |
|---|---|
| react | 19.2.0 |
| react-dom | 19.2.0 |

### Сборка и контроль клиента

| Инструмент | Версия |
|---|---|
| @eslint/js | 9.37.0 |
| @types/react | 19.2.2 |
| @types/react-dom | 19.2.2 |
| eslint | 9.37.0 |
| eslint-plugin-react-hooks | 5.2.0 |
| openapi-typescript | 7.10.1 |
| typescript | 5.9.3 |
| typescript-eslint | 8.46.0 |
| vite | 7.1.7 |

### Среда и образы

| Компонент | Версия / назначение |
|---|---|
| CPython | 3.14.4; сервер и Python-задания |
| Node.js | 22.22.1; только стадия сборки frontend |
| PostgreSQL продукта | 17; образ закреплён digest в compose.yaml |
| PostgreSQL SQL-заданий | 18-bookworm; отдельный изолированный runtime |
| Mailpit | 1.29.5; проверочная почта |
| Docker CLI контроллера | 28.5.2; образ закреплён в Dockerfile |

Точные SHA256 образов находятся в compose.yaml и Dockerfile. Версия Docker Engine/Compose на хосте зависит от компьютера эксперта; она не подменяется версией CLI внутри образа. Для первого запуска нужны Linux-контейнеры, cgroup v2 и seccomp.

### Шрифты и фирменные материалы

Оригинальный логотип ФСП взят из предоставленного каталога «ЛОГО ФСП». JetBrains Mono и TDAText подключены локально из предоставленных архивов, с кириллицей. Лицензии SIL Open Font License 1.1, copyright и источники находятся в frontend/src/assets/brand; в приложении — /assets/licenses/fsp/. В PDF встроены шрифты, поэтому установка на компьютере жюри не требуется.

Ни LLM-библиотеки, ни облачные модели в пользовательском оценивании и подборе не используются. Для работы не требуется API-ключ модели, платная подписка или GPU.

## 05 / Источники и проверка актуальности

Справочник сформирован по схеме docs/release/openapi.json. Это снимок контрактов, а не новый запрос к работающему стенду. Перед интеграцией сравните его с /openapi.json текущего приложения. При изменении контрактов нужно обновить соответствующий PDF; старые документы выпуска сохраняются как история.

Контрольный SHA256 схемы:

b0b7819e14574cbf9d4a700c7d698a0935ce952fd19a2102a1d2baab7600f929

Сборка, запуск, аккаунты, схемы архитектуры и результаты валидации описаны в 01_jury_guide.pdf. Обязательный состав сдачи и статус внешних действий — в 03_submission_checklist.pdf.
