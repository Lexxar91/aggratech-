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
  Loading,
  LoadError,
  Notice,
  Section,
  checked,
  formatNames,
  optional,
  useFeedback,
  useLoad,
  value,
} from "./ui";
import { Result } from "./assessment";

export function CandidateProfile() {
  const profile = useLoad<Schema<"ProfileView">>("/candidate/profile");
  const contacts = useLoad<Schema<"ContactsView">>("/candidate/contacts");
  const technologies = useLoad<Schema<"NamedItem">[]>("/catalog/technologies");
  const feedback = useFeedback();
  const error = profile.error || contacts.error || technologies.error;
  if (error)
    return (
      <LoadError
        error={error}
        retry={() => {
          profile.reload();
          contacts.reload();
          technologies.reload();
        }}
      />
    );
  if (!profile.data || !contacts.data || !technologies.data) return <Loading />;
  const p = profile.data,
    c = contacts.data,
    techs = technologies.data;
  return (
    <>
      <Heading
        title="Кабинет кандидата"
        subtitle="Расскажите о себе и выберите, чем делиться с работодателями."
      >
        <Action onClick={() => download("/candidate/profile.pdf")}>
          Скачать мой PDF
        </Action>
      </Heading>
      {p.assessment && <Result result={p.assessment} />}
      <div className="profile-layout">
        <Section title="Ручной профиль">
          <Notice>
            Опыт и технологии заявлены самостоятельно. Зарплата — рубли в месяц
            до налогов.
          </Notice>
          <Form
            label="Сохранить профиль"
            onSubmit={async (data) => {
              const payload: Schema<"ProfileInput"> = {
                display_name: value(data, "display_name"),
                summary: value(data, "summary"),
                experience: value(data, "experience"),
                salary_min: optional(data, "salary_min"),
                salary_max: optional(data, "salary_max"),
                salary_basis: "gross",
                available_from: optional(data, "available_from"),
                work_preferences: {
                  location: optional(data, "location"),
                  formats: (
                    Object.keys(formatNames) as (keyof typeof formatNames)[]
                  ).filter((f) => checked(data, `format_${f}`)),
                },
                technology_ids: techs
                  .filter((t) => checked(data, `tech_${t.id}`))
                  .map((t) => t.id),
                confirm_preferences: checked(data, "confirm_preferences"),
                consent_version: checked(data, "consent") ? "profile-v1" : null,
              };
              await send("/candidate/profile", payload, "PATCH");
              feedback("Профиль сохранён.");
              profile.reload();
            }}
          >
            <div className="fields">
              <Field name="display_name" label="Имя" value={p.display_name} />
              <Field
                name="summary"
                label="Описание"
                value={p.summary}
                type="textarea"
              />
              <Field
                name="experience"
                label="Опыт"
                value={p.experience}
                type="textarea"
              />
              <Field
                name="salary_min"
                label="Зарплата от"
                value={p.salary_min}
                type="number"
                min={0}
              />
              <Field
                name="salary_max"
                label="Зарплата до"
                value={p.salary_max}
                type="number"
                min={0}
              />
              <Field
                name="available_from"
                label="Доступен с"
                value={p.available_from}
                type="date"
              />
              <Field
                name="location"
                label="Город"
                value={p.work_preferences.location}
              />
            </div>
            <h3>Формат работы</h3>
            <div className="checks">
              {Object.entries(formatNames).map(([f, title]) => (
                <Check
                  key={f}
                  name={`format_${f}`}
                  label={title}
                  checked={(p.work_preferences.formats ?? []).includes(
                    f as keyof typeof formatNames,
                  )}
                />
              ))}
            </div>
            <h3>Технологии</h3>
            <div className="checks">
              {techs.map((t) => (
                <Check
                  key={t.id}
                  name={`tech_${t.id}`}
                  label={t.name}
                  checked={p.technology_ids.includes(t.id)}
                />
              ))}
            </div>
            <Check
              name="confirm_preferences"
              label="Подтверждаю актуальность предпочтений"
              checked={!!p.preferences_confirmed_at}
            />
            <Check
              name="consent"
              label="Согласен на хранение профиля и публикацию карточки по выбранным настройкам (profile-v1)"
              checked={!!p.consented_at}
            />
          </Form>
        </Section>
        <div className="stack">
          <Section title="Закрытые контакты">
            <p className="muted">
              Они доступны только компаниям, которым вы разрешили выбранные поля
              через приглашение или отклик.
            </p>
            <Form
              label="Сохранить контакты"
              onSubmit={async (data) => {
                await send(
                  "/candidate/contacts",
                  {
                    email: value(data, "contact_email"),
                    phone: value(data, "phone"),
                    messengers: value(data, "telegram")
                      ? { telegram: value(data, "telegram") }
                      : {},
                  },
                  "PATCH",
                );
                feedback("Контакты сохранены.");
                contacts.reload();
              }}
            >
              <Field
                name="contact_email"
                label="Контактный email"
                value={c.email}
                type="email"
                required
              />
              <Field name="phone" label="Телефон" value={c.phone} />
              <Field
                name="telegram"
                label="Telegram"
                value={c.messengers?.telegram ?? ""}
              />
            </Form>
          </Section>
          <Section title="Приватность">
            <Form
              label="Сохранить приватность"
              onSubmit={async (data) => {
                await send(
                  "/candidate/privacy",
                  {
                    visible_to_employers: checked(data, "visible_to_employers"),
                    show_name: checked(data, "show_name"),
                  },
                  "PATCH",
                );
                feedback("Приватность сохранена.");
                profile.reload();
              }}
            >
              <Check
                name="visible_to_employers"
                label="Карточка видна работодателям после согласия"
                checked={p.privacy.visible_to_employers}
              />
              <Check
                name="show_name"
                label="Показывать имя в карточке"
                checked={p.privacy.show_name}
              />
              <p className="muted">
                Настройки применяются также к PDF. Видимая карточка сама по себе
                не открывает контакты.
              </p>
            </Form>
          </Section>
        </div>
      </div>
      <CompanyBlocks />
    </>
  );
}

function CompanyBlocks() {
  const companies = useLoad<Schema<"CompanyCard">[]>("/employers");
  const blocks = useLoad<Schema<"BlockView">[]>("/candidate/blocks");
  if (companies.error || blocks.error)
    return (
      <LoadError
        error={companies.error || blocks.error}
        retry={() => {
          companies.reload();
          blocks.reload();
        }}
      />
    );
  if (!companies.data || !blocks.data) return <Loading />;
  return (
    <Section title="Блокировки компаний">
      {!companies.data.length && <Empty>Компаний пока нет.</Empty>}
      {companies.data.map((company) => {
        const blocked = blocks.data!.some((b) => b.employer_id === company.id);
        return (
          <div className="list-row" key={company.id}>
            <span>{company.company_name || "Компания без названия"}</span>
            <Action
              onClick={async () => {
                await send(
                  `/candidate/blocks/${company.id}`,
                  undefined,
                  blocked ? "DELETE" : "PUT",
                );
                blocks.reload();
              }}
            >
              {blocked ? "Разблокировать" : "Заблокировать"}
            </Action>
          </div>
        );
      })}
    </Section>
  );
}

export function EmployerProfile() {
  const {
    data: p,
    error,
    reload,
  } = useLoad<Schema<"EmployerView">>("/employer/profile");
  const feedback = useFeedback();
  if (error) return <LoadError error={error} retry={reload} />;
  if (!p) return <Loading />;
  return (
    <>
      <Heading
        title="Кабинет работодателя"
        subtitle="Профиль компании, потребности и общение с кандидатами."
      />
      <Section title="Профиль компании">
        <Form
          label="Сохранить компанию"
          onSubmit={async (data) => {
            await send(
              "/employer/profile",
              {
                company_name: value(data, "company_name"),
                description: value(data, "description"),
                industry: value(data, "industry"),
                representative_contact: value(data, "representative_contact"),
              },
              "PATCH",
            );
            feedback("Компания сохранена.");
            reload();
          }}
        >
          <div className="fields">
            <Field
              name="company_name"
              label="Название компании"
              value={p.company_name}
            />
            <Field name="industry" label="Отрасль" value={p.industry} />
            <Field
              name="description"
              label="Описание компании"
              value={p.description}
              type="textarea"
            />
            <Field
              name="representative_contact"
              label="Контакт представителя"
              value={p.representative_contact}
            />
          </div>
        </Form>
      </Section>
      <Notice warning>
        Подтверждённая подборка использует только опубликованные результаты
        из допущенного банка. Демонстрационные прохождения в неё не включаются.
      </Notice>
    </>
  );
}

export function FspPage() {
  const { data, error, reload } = useLoad<Schema<"FspView">>(
    "/candidate/fsp/achievements",
  );
  if (error) return <LoadError error={error} retry={reload} />;
  if (!data) return <Loading />;
  return (
    <>
      <Heading
        title="ФСП mock"
        subtitle="Привязка демонстрационных достижений с проверкой принадлежности."
      />
      <Notice warning>
        {data.notice} Источник: {data.source}. Это не настоящий реестр.
      </Notice>
      <Section title="Привязка">
        <Badge>{data.status}</Badge>
        <Form
          label="Привязать"
          onSubmit={async (form) => {
            await send("/candidate/fsp/link", {
              external_id: value(form, "external_id"),
              claim_code: value(form, "claim_code"),
            });
            reload();
          }}
        >
          <Field
            name="external_id"
            label="ID участника demo"
            value={data.external_id}
            required
          />
          <Field name="claim_code" label="Код принадлежности demo" required />
        </Form>
        <div className="actions">
          <Action
            disabled={!data.external_id}
            onClick={async () => {
              await send("/candidate/fsp/sync", {});
              reload();
            }}
          >
            Синхронизировать mock
          </Action>
          <Action
            disabled={!data.external_id}
            onClick={async () => {
              await send("/candidate/fsp/link", undefined, "DELETE");
              reload();
            }}
          >
            Отозвать связь
          </Action>
        </div>
      </Section>
      <Section title="Достижения">
        {!data.achievements?.length && (
          <Empty>
            Нет данных ФСП. Это не уменьшает остальные компоненты оценки
            подбора.
          </Empty>
        )}
        {(data.achievements ?? []).map((item, index) => (
          <div className="list-row" key={index}>
            <strong>
              {String(item.title ?? "Демонстрационное достижение")}
            </strong>
            <span>
              {String(item.date ?? "")} · {String(item.result ?? "")}
            </span>
            <Badge>Демонстрационная запись</Badge>
          </div>
        ))}
      </Section>
    </>
  );
}
