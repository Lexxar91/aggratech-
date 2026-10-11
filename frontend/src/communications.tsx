import { useContext, useState } from "react";
import { download, send } from "./api";
import type { Schema } from "./api";
import {
  Action,
  Badge,
  Check,
  Empty,
  Field,
  Form,
  Heading,
  Link,
  Loading,
  LoadError,
  Notice,
  Section,
  SessionContext,
  checked,
  date,
  formatNames,
  money,
  number,
  optional,
  statusNames,
  useLoad,
  value,
} from "./ui";

export function Sharing({
  consentName = "contact_consent",
}: {
  consentName?: string;
}) {
  return (
    <>
      <div className="checks">
        <Check name="share_email" label="Email" />
        <Check name="share_phone" label="Телефон" />
        <Check name="share_messengers" label="Мессенджеры" />
      </div>
      <Check
        name={consentName}
        label="Разрешаю доступ к выбранным контактам (contacts-v1)"
        required
      />
      <p className="muted">
        Разрешение получает только эта компания. Остальные работодатели доступа
        не получают.
      </p>
    </>
  );
}
export function selectedContacts(data: FormData): Schema<"Acceptance"> {
  return {
    allowed_fields: (["email", "phone", "messengers"] as const).filter(
      (field) => checked(data, `share_${field}`),
    ),
    consent_version: "contacts-v1",
  };
}
export function Contacts({ candidateId }: { candidateId: string }) {
  const { data, error, reload } = useLoad<Schema<"SharedContacts">>(
    `/candidates/${candidateId}/contacts`,
  );
  if (error)
    return (
      <Notice>
        Контакты недоступны: {error}{" "}
        <Action onClick={reload}>Проверить разрешение снова</Action>
      </Notice>
    );
  if (!data) return <Loading />;
  return (
    <Section title="Разрешённые контакты">
      {data.email && (
        <p>
          Email: <a href={`mailto:${data.email}`}>{data.email}</a>
        </p>
      )}
      {data.phone && <p>Телефон: {data.phone}</p>}
      {data.messengers &&
        Object.entries(data.messengers).map(([name, address]) => (
          <p key={name}>
            {name}: {address}
          </p>
        ))}
    </Section>
  );
}

export function OfferFields({
  initial,
  formatPrefix = "format_",
  dateName = "start_date_required",
}: {
  initial?: Partial<Schema<"Offer">>;
  formatPrefix?: string;
  dateName?: string;
}) {
  return (
    <>
      <div className="fields">
        <Field
          name="description"
          label="Описание задач / предложения"
          type="textarea"
          value={initial?.description}
          required
        />
        <Field
          name="salary_from"
          label="Зарплата от, ₽/месяц до налогов"
          type="number"
          value={initial?.salary_from}
          min={0.01}
          required
        />
        <Field
          name="salary_to"
          label="Зарплата до, ₽/месяц до налогов"
          type="number"
          value={initial?.salary_to}
          min={0.01}
          required
        />
        <Field
          name="location"
          label="Город для офиса/гибрида"
          value={initial?.location}
        />
        <Field
          name="desired_start_date"
          label="Желаемая дата начала"
          type="date"
          value={initial?.desired_start_date}
        />
        <Field
          name="conditions"
          label="Условия работы"
          type="textarea"
          value={initial?.conditions}
          required
        />
        <Field
          name="representative_contact"
          label="Связь с работодателем"
          value={initial?.representative_contact}
          required
        />
      </div>
      <div className="checks">
        {Object.entries(formatNames).map(([format, label]) => (
          <Check
            key={format}
            name={`${formatPrefix}${format}`}
            label={label}
            checked={(initial?.work_formats ?? ["remote"]).includes(
              format as keyof typeof formatNames,
            )}
          />
        ))}
      </div>
      <Check
        name={dateName}
        label="Дата начала обязательна"
        checked={initial?.start_date_required}
      />
    </>
  );
}
export function readOffer(
  data: FormData,
  formatPrefix = "format_",
  dateName = "start_date_required",
): Schema<"Offer"> {
  return {
    description: value(data, "description"),
    salary_from: number(data, "salary_from"),
    salary_to: number(data, "salary_to"),
    currency: "RUB",
    salary_basis: "gross",
    location: optional(data, "location"),
    desired_start_date: optional(data, "desired_start_date"),
    start_date_required: checked(data, dateName),
    conditions: value(data, "conditions"),
    representative_contact: value(data, "representative_contact"),
    work_formats: (
      Object.keys(formatNames) as (keyof typeof formatNames)[]
    ).filter((f) => checked(data, `${formatPrefix}${f}`)),
  };
}
function OfferDetails({ offer }: { offer: Schema<"Offer"> }) {
  return (
    <>
      <p className="salary">{money(offer.salary_from, offer.salary_to)}</p>
      <p className="preserve-lines">{offer.description}</p>
      <dl className="details">
        <div>
          <dt>Формат работы</dt>
          <dd>{offer.work_formats.map((f) => formatNames[f]).join(", ")}</dd>
        </div>
        <div>
          <dt>Город</dt>
          <dd>{offer.location ?? "По договорённости"}</dd>
        </div>
        <div>
          <dt>Начало</dt>
          <dd>
            {offer.desired_start_date ?? "По договорённости"}
            {offer.start_date_required && " (обязательно)"}
          </dd>
        </div>
        <div>
          <dt>Условия</dt>
          <dd className="preserve-lines">{offer.conditions}</dd>
        </div>
        <div>
          <dt>Представитель компании</dt>
          <dd>{offer.representative_contact}</dd>
        </div>
      </dl>
    </>
  );
}

export function InvitationOffer({
  needId,
  candidateId,
}: {
  needId: string;
  candidateId: string;
}) {
  const need = useLoad<Schema<"Need">>(`/employer/needs/${needId}`);
  const company = useLoad<Schema<"EmployerView">>("/employer/profile");
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  if (need.error || company.error)
    return (
      <LoadError
        error={need.error || company.error}
        retry={() => {
          need.reload();
          company.reload();
        }}
      />
    );
  if (!need.data || !company.data) return <Loading />;
  return (
    <>
      <Heading
        title="Пригласить кандидата"
        subtitle="Личное предложение без обязательной вакансии."
      />
      <Link to="invitations">Приглашения</Link>
      <Notice>
        Предложение действует семь суток. Снимок условий неизменяемый: для
        нового предложения отзовите прежнее.
      </Notice>
      <Section title="Условия предложения">
        <Form
          label="Отправить приглашение"
          onSubmit={async (data) => {
            const result: Schema<"InvitationView"> = await send(
              "/employer/invitations",
              {
                need_id: needId,
                candidate_id: candidateId,
                idempotency_key: idempotencyKey,
                offer: readOffer(data, "offer_", "offer_date_required"),
              },
            );
            location.hash = `#invitations/${result.id}`;
          }}
        >
          <OfferFields
            initial={{
              description: need.data.task_description,
              salary_from: need.data.salary_from,
              salary_to: need.data.salary_to,
              work_formats: need.data.work_formats,
              location: need.data.location,
              desired_start_date: need.data.desired_start_date,
              start_date_required: need.data.start_date_required,
              conditions: need.data.additional_wishes,
              representative_contact: company.data.representative_contact,
            }}
            formatPrefix="offer_"
            dateName="offer_date_required"
          />
        </Form>
      </Section>
    </>
  );
}
interface InvitationSnapshot {
  company_name: string;
  offer: Schema<"Offer">;
  need_version: number;
  notice: string;
}
export function InvitationsPage({ id }: { id?: string }) {
  const candidate = useContext(SessionContext).user?.role === "candidate";
  const prefix = candidate ? "/candidate" : "/employer";
  const { data, error, reload } = useLoad<
    Schema<"InvitationView">[] | Schema<"InvitationView">
  >(`${prefix}/invitations${id ? `/${id}` : ""}`);
  if (error) return <LoadError error={error} retry={reload} />;
  if (!data) return <Loading />;
  if (Array.isArray(data))
    return (
      <>
        <Heading
          title={candidate ? "Предложения от компаний" : "Отправленные приглашения"}
          subtitle={candidate ? "Условия работы и история общения с компаниями." : "Предложения кандидатам и их решения."}
        />
        {!data.length && (
          <Empty>
            {candidate ? "Предложений пока нет. Опубликуйте результат и включите видимость профиля." : "Вы ещё не отправили приглашения. Откройте подборку и предложите кандидату условия работы."}
          </Empty>
        )}
        <div className="card-grid">
          {data.map((row) => (
            <Section
              key={row.id}
              title={String(row.offer_snapshot.company_name ?? "Компания")}
            >
              <Badge>{statusNames[row.status]}</Badge>
              <p>Действует до {date(row.expires_at)}</p>
              <Link to={`invitations/${row.id}`}>Открыть предложение</Link>
            </Section>
          ))}
        </div>
      </>
    );
  const row = data,
    snapshot = row.offer_snapshot as unknown as InvitationSnapshot;
  return (
    <>
      <Heading title="Приглашения" subtitle={snapshot.company_name}>
        <Badge>{statusNames[row.status]}</Badge>
      </Heading>
      <Link to="invitations">Все приглашения</Link>
      <Section title={snapshot.company_name}>
        <p>Действует до {date(row.expires_at)}</p>
        <OfferDetails offer={snapshot.offer} />
        <Notice>
          Условия предложения сохранены на момент отправки. Последующие изменения задачи поиска их не меняют.
        </Notice>
      </Section>
      {["sent", "viewed"].includes(row.status) &&
        (candidate ? (
          <Section title="Ваше решение">
            <Form
              label="Принять приглашение"
              onSubmit={async (form) => {
                await send(
                  `${prefix}/invitations/${id}/accept`,
                  selectedContacts(form),
                );
                reload();
              }}
            >
              <p>
                Принятие означает готовность продолжить общение. Выберите
                контакты для этой компании.
              </p>
              <Sharing />
            </Form>
            <Action
              danger
              onClick={async () => {
                await send(`${prefix}/invitations/${id}/reject`, {});
                reload();
              }}
            >
              Отклонить приглашение
            </Action>
          </Section>
        ) : (
          <Action
            danger
            onClick={async () => {
              await send(`${prefix}/invitations/${id}/withdraw`, {});
              reload();
            }}
          >
            Отозвать приглашение
          </Action>
        ))}
      {candidate ? (
        <div className="actions">
          {row.contact_access && (
            <Action
              danger
              onClick={async () => {
                await send(
                  `/candidate/contact-grants/${row.employer_id}`,
                  undefined,
                  "DELETE",
                );
                reload();
              }}
            >
              Закрыть контакты этой компании
            </Action>
          )}
          <Action
            onClick={async () => {
              await send(
                `/candidate/blocks/${row.employer_id}`,
                undefined,
                "PUT",
              );
              reload();
            }}
          >
            Запретить приглашения от компании
          </Action>
        </div>
      ) : (
        <>
          <Contacts
            key={String(row.contact_access)}
            candidateId={row.candidate_id}
          />
          <Action
            onClick={() =>
              download(`/candidates/${row.candidate_id}/profile.pdf`)
            }
          >
            PDF кандидата
          </Action>
        </>
      )}
    </>
  );
}

export function VacanciesPage() {
  const employer = useContext(SessionContext).user?.role === "employer";
  const { data, error, reload } = useLoad<Schema<"VacancyView">[]>(
    employer ? "/employer/vacancies" : "/vacancies",
  );
  if (error) return <LoadError error={error} retry={reload} />;
  if (!data) return <Loading />;
  return (
    <>
      <Heading
        title={employer ? "Мои вакансии" : "Вакансии"}
        subtitle="Прозрачные условия и зарплата до отправки контактов."
      >
        {employer && (
          <Link primary to="vacancy-edit">
            Создать вакансию
          </Link>
        )}
      </Heading>
      {!data.length && <Empty>Вакансий пока нет.</Empty>}
      <div className="card-grid">
        {data.map((row) => (
          <Section key={row.id} title={row.title}>
            <p className="muted">{row.company_name || "Компания"}</p>
            <Badge>{statusNames[row.status]}</Badge>
            <p className="salary">{money(row.salary_from, row.salary_to)}</p>
            <p className="excerpt">{row.description}</p>
            <div className="tags">
              {row.work_formats.map((f) => (
                <Badge key={f}>{formatNames[f]}</Badge>
              ))}
            </div>
            <Link to={`vacancy/${row.id}`}>{row.title}</Link>
          </Section>
        ))}
      </div>
    </>
  );
}
export function VacancyPage({ id }: { id: string }) {
  const { user } = useContext(SessionContext);
  const {
    data: row,
    error,
    reload,
  } = useLoad<Schema<"VacancyView">>(
    `${user?.role === "employer" ? "/employer" : ""}/vacancies/${id}`,
  );
  if (error) return <LoadError error={error} retry={reload} />;
  if (!row) return <Loading />;
  return (
    <>
      <Heading title={row.title} subtitle={row.company_name}>
        <Badge>{statusNames[row.status]}</Badge>
      </Heading>
      <Link to="vacancies">Все вакансии</Link>
      <Section title="Условия вакансии">
        <OfferDetails offer={row} />
      </Section>
      {user?.role === "employer" ? (
        <div className="actions">
          <Link to={`applications/${id}`}>Отклики на вакансию</Link>
          {row.status === "published" && (
            <>
              <Link to={`vacancy-edit/${id}`}>Редактировать вакансию</Link>
              <Action
                danger
                onClick={async () => {
                  await send(`/employer/vacancies/${id}/close`, {});
                  reload();
                }}
              >
                Закрыть вакансию
              </Action>
            </>
          )}
        </div>
      ) : !user ? (
        <Link to="login">Войти для отклика</Link>
      ) : row.status === "closed" ? (
        <Notice>Новые отклики не принимаются.</Notice>
      ) : (
        <Section title="Откликнуться">
          <Notice>
            Отклик не подтверждает квалификацию. Повторная подача сохраняет
            первую запись и не восстанавливает отозванный доступ.
          </Notice>
          <Form
            label="Подать отклик"
            onSubmit={async (form) => {
              const result: Schema<"ApplicationView"> = await send(
                `/vacancies/${id}/applications`,
                {
                  ...selectedContacts(form),
                  message: value(form, "application_message"),
                },
              );
              location.hash = `#application/${result.id}`;
            }}
          >
            <Field
              name="application_message"
              label="Сообщение работодателю"
              type="textarea"
            />
            <Sharing consentName="application_consent" />
          </Form>
        </Section>
      )}
    </>
  );
}
export function VacancyEditor({ id }: { id?: string }) {
  const {
    data: rows,
    error,
    reload,
  } = useLoad<Schema<"VacancyView">[]>("/employer/vacancies");
  if (error) return <LoadError error={error} retry={reload} />;
  if (!rows) return <Loading />;
  const row = rows.find((item) => item.id === id);
  if (id && !row) return <Notice warning>Вакансия недоступна.</Notice>;
  if (row?.status === "closed")
    return <Notice>Вакансия закрыта. Редактирование недоступно.</Notice>;
  return (
    <>
      <Heading title={row ? "Редактирование вакансии" : "Создание вакансии"} />
      <Link to="vacancies">Все вакансии</Link>
      <Section title="Содержание и условия">
        <Notice>
          Зарплатный диапазон в рублях обязателен. Отправленные отклики
          сохраняют прежние условия.
        </Notice>
        <Form
          label={row ? "Сохранить вакансию" : "Опубликовать вакансию"}
          onSubmit={async (data) => {
            const payload = {
              ...readOffer(data),
              title: value(data, "title"),
              ...(row ? { version: row.version } : {}),
            };
            const saved: Schema<"VacancyView"> = await send(
              row ? `/employer/vacancies/${id}` : "/employer/vacancies",
              payload,
              row ? "PATCH" : "POST",
            );
            location.hash = `#vacancy/${saved.id}`;
          }}
        >
          <Field
            name="title"
            label="Название вакансии"
            value={row?.title}
            required
          />
          <OfferFields initial={row} />
        </Form>
      </Section>
    </>
  );
}
export function ApplicationsPage({ vacancyId }: { vacancyId?: string }) {
  const candidate = useContext(SessionContext).user?.role === "candidate";
  const { data, error, reload } = useLoad<Schema<"ApplicationView">[]>(
    candidate
      ? "/candidate/applications"
      : `/employer/vacancies/${vacancyId}/applications`,
  );
  if (error) return <LoadError error={error} retry={reload} />;
  if (!data) return <Loading />;
  return (
    <>
      <Heading
        title={candidate ? "Мои отклики" : "Отклики на вакансию"}
        subtitle="История и сохранённые условия каждой подачи."
      />
      <Link to="vacancies">Вакансии</Link>
      {!data.length && <Empty>Откликов пока нет.</Empty>}
      {data.map((row) => (
        <div className="panel list-row" key={row.id}>
          <a href={`#application/${row.id}`}>{row.vacancy_snapshot.title}</a>
          <Badge>{statusNames[row.status]}</Badge>
          <small>{date(row.submitted_at)}</small>
        </div>
      ))}
    </>
  );
}
export function ApplicationPage({ id }: { id: string }) {
  const candidate = useContext(SessionContext).user?.role === "candidate";
  const {
    data: row,
    error,
    reload,
  } = useLoad<Schema<"ApplicationView">>(
    `/${candidate ? "candidate" : "employer"}/applications/${id}`,
  );
  if (error) return <LoadError error={error} retry={reload} />;
  if (!row) return <Loading />;
  return (
    <>
      <Heading
        title={`Отклик: ${statusNames[row.status]}`}
        subtitle="Условия сохранены на момент подачи отклика."
      />
      <Section title={row.vacancy_snapshot.title}>
        <p>{row.vacancy_snapshot.company_name}</p>
        <OfferDetails offer={row.vacancy_snapshot} />
        <p>Сообщение: {row.message || "Не указано"}</p>
      </Section>
      {candidate ? (
        <Section title="Разрешение на контакты">
          <p>
            {row.contact_access
              ? `Этот отклик разрешает: ${row.allowed_fields.join(", ")}`
              : "У этого отклика нет действующего разрешения."}
          </p>
          {row.status !== "withdrawn" && (
            <Action
              danger
              onClick={async () => {
                await send(`/applications/${id}/withdraw`, {});
                reload();
              }}
            >
              Отозвать отклик
            </Action>
          )}
          <p className="muted">
            Отзыв этого отклика не отменяет согласия других откликов и
            приглашений.
          </p>
        </Section>
      ) : (
        <>
          {row.candidate_card ? (
            <Section title={row.candidate_card.display_name}>
              <p>{row.candidate_card.summary}</p>
              <Notice>
                {row.candidate_card.assessment?.verified
                  ? `Уровень — ${row.candidate_card.assessment.grade === "middle" ? "Middle" : "Junior"}`
                  : "Результат проверки навыков не опубликован."}
              </Notice>
              <Action
                onClick={() =>
                  download(`/candidates/${row.candidate_id}/profile.pdf`)
                }
              >
                PDF кандидата
              </Action>
            </Section>
          ) : (
            <Notice>{row.card_notice ?? "Карточка недоступна."}</Notice>
          )}
          {["submitted", "viewed"].includes(row.status) && (
            <div className="actions">
              {row.status === "submitted" && (
                <Action
                  onClick={async () => {
                    await send(`/applications/${id}/view`, {});
                    reload();
                  }}
                >
                  Отметить просмотр
                </Action>
              )}
              <Action
                onClick={async () => {
                  await send(`/applications/${id}/accept`, {});
                  reload();
                }}
              >
                Принять отклик
              </Action>
              <Action
                danger
                onClick={async () => {
                  await send(`/applications/${id}/reject`, {});
                  reload();
                }}
              >
                Отклонить отклик
              </Action>
            </div>
          )}
          <Contacts key={row.version} candidateId={row.candidate_id} />
        </>
      )}
      <Link to={candidate ? "applications" : `applications/${row.vacancy_id}`}>
        История откликов
      </Link>
    </>
  );
}
