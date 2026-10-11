import { useRef, useState } from "react";
import { download, get, send } from "./api";
import type { Schema } from "./api";
import {
  Action,
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
  checked,
  date,
  formatNames,
  money,
  number,
  optional,
  skillNames,
  useFeedback,
  useLoad,
  value,
} from "./ui";

interface Dictionary {
  skills: Record<string, string>;
  technologies: Record<string, string[]>;
  verified_technology_evidence: Record<string, string>;
}
interface Template {
  code: string;
  version: string;
  title: string;
  task_description: string;
  accepted_grades: ("junior" | "middle")[];
  skill_priorities: Schema<"Need">["skill_priorities"];
}
type Need = Schema<"Need">;
export function NeedsPage({ id }: { id?: string }) {
  const needs = useLoad<Need[]>("/employer/needs");
  const templates = useLoad<Template[]>("/employer/need-templates");
  const dictionary = useLoad<Dictionary>("/catalog/matching-dictionary");
  const error = needs.error || templates.error || dictionary.error;
  if (error)
    return (
      <LoadError
        error={error}
        retry={() => {
          needs.reload();
          templates.reload();
          dictionary.reload();
        }}
      />
    );
  if (!needs.data || !templates.data || !dictionary.data) return <Loading />;
  const current = needs.data.find((need) => need.need_id === id);
  if (id && !current) return <Notice warning>Потребность недоступна.</Notice>;
  return (
    <>
      <Heading
        title="Потребности и подбор"
        subtitle="Задайте требования и получите объяснение каждого результата."
      />
      <Notice warning>
        Найдите специалистов по навыкам, уровню и условиям работы.
      </Notice>
      <div className="need-layout">
        <div>
          <NeedEditor
            key={`${id ?? "new"}-${current?.version}`}
            current={current}
            templates={templates.data}
            dictionary={dictionary.data}
            reload={needs.reload}
          />
          {id && <SnapshotHistory needId={id} />}
        </div>
        <Section title="Мои потребности">
          {!needs.data.length && <Empty>Потребностей пока нет.</Empty>}
          {needs.data.map((need) => (
            <div className="list-row" key={need.need_id}>
              <a href={`#needs/${need.need_id}`}>{need.title}</a>
            </div>
          ))}
          <Link to="needs">Новая потребность</Link>
        </Section>
      </div>
    </>
  );
}
function NeedEditor({
  current,
  templates,
  dictionary,
  reload,
}: {
  current?: Need;
  templates: Template[];
  dictionary: Dictionary;
  reload: () => void;
}) {
  const ref = useRef<HTMLFormElement>(null);
  const [initial, setInitial] = useState<Partial<Need>>(
    current ?? {
      accepted_grades: ["junior", "middle"],
      work_formats: ["remote"],
    },
  );
  const [formKey, setFormKey] = useState(0);
  const feedback = useFeedback();
  const technologyCodes = Object.keys(dictionary.technologies);
  const skillCodes = Object.keys(
    dictionary.skills,
  ) as Need["required_verified_skills"];
  function payload(
    data: FormData,
  ): Omit<Schema<"NeedInput">, "need_id" | "employer_id"> {
    return {
      title: value(data, "title"),
      role: value(data, "role"),
      team_description: value(data, "team_description"),
      task_description: value(data, "task_description"),
      specialization: "backend",
      accepted_grades: (["junior", "middle"] as const).filter((g) =>
        checked(data, `grade_${g}`),
      ),
      required_stack: technologyCodes
        .filter((t) => checked(data, `required_${t}`))
        .map((technology) => ({
          technology,
          verification_required: checked(data, `verified_${technology}`),
        })),
      preferred_stack: technologyCodes.filter((t) =>
        checked(data, `preferred_${t}`),
      ),
      skill_priorities: Object.fromEntries(
        skillCodes
          .filter((s) => checked(data, `priority_${s}`))
          .map((s) => [s, number(data, `weight_${s}`)]),
      ) as Need["skill_priorities"],
      required_verified_skills: skillCodes.filter((s) =>
        checked(data, `skill_required_${s}`),
      ),
      work_formats: (
        Object.keys(formatNames) as (keyof typeof formatNames)[]
      ).filter((f) => checked(data, `format_${f}`)),
      location: optional(data, "location"),
      salary_from: number(data, "salary_from"),
      salary_to: number(data, "salary_to"),
      desired_start_date: optional(data, "desired_start_date"),
      start_date_required: checked(data, "start_date_required"),
      additional_wishes: value(data, "additional_wishes"),
      additional_requirements: value(data, "min_experience_years")
        ? { required_experience_years: number(data, "min_experience_years") }
        : {},
      urgency: value(data, "urgency") as Need["urgency"],
      vacancy_id: optional(data, "vacancy_id"),
      version: current?.version ?? 1,
      template_code: initial.template_code ?? null,
      template_version: initial.template_version ?? null,
      salary_currency: "RUB",
      salary_basis: "gross",
    };
  }
  function applyTemplate(template?: Template) {
    const data = new FormData(ref.current!);
    setInitial({
      ...payload(data),
      salary_from: value(data, "salary_from")
        ? number(data, "salary_from")
        : undefined,
      salary_to: value(data, "salary_to")
        ? number(data, "salary_to")
        : undefined,
      ...(template
        ? {
            title: template.title,
            task_description: template.task_description,
            accepted_grades: template.accepted_grades,
            skill_priorities: template.skill_priorities,
          }
        : {}),
      template_code: template?.code ?? null,
      template_version: template?.version ?? null,
    });
    setFormKey((k) => k + 1);
    feedback(
      template
        ? "Шаблон применён. Все поля можно редактировать."
        : "Привязка шаблона снята.",
    );
  }
  return (
    <Section
      title={
        current
          ? "Редактирование потребности"
          : "Новая потребность"
      }
    >
      <div className="template-grid">
        {templates.map((template) => (
          <Action key={template.code} onClick={() => applyTemplate(template)}>
            Шаблон: {template.title}
          </Action>
        ))}
        <Action onClick={() => applyTemplate()}>Без шаблона</Action>
      </div>
      <Form
        key={formKey}
        formRef={ref}
        label="Сохранить потребность"
        onSubmit={async (data) => {
          const saved: Need = await send(
            `/employer/needs${current ? `/${current.need_id}` : ""}`,
            payload(data),
            current ? "PATCH" : "POST",
          );
          feedback("Потребность сохранена.");
          reload();
          location.hash = `#needs/${saved.need_id}`;
        }}
      >
        <div className="fields">
          <Field name="title" label="Название" value={initial.title} required />
          <Field name="role" label="Роль в команде" value={initial.role} />
          <Field
            name="team_description"
            label="Команда"
            value={initial.team_description}
            type="textarea"
          />
          <Field
            name="task_description"
            label="Задачи"
            value={initial.task_description}
            type="textarea"
          />
          <Field
            name="salary_from"
            label="Бюджет от, RUB/месяц gross"
            type="number"
            min={0}
            value={initial.salary_from}
            required
          />
          <Field
            name="salary_to"
            label="Бюджет до"
            type="number"
            min={0}
            value={initial.salary_to}
            required
          />
        </div>
        <h3>Подходящие категории</h3>
        <div className="checks">
          {(["junior", "middle"] as const).map((g) => (
            <Check
              key={g}
              name={`grade_${g}`}
              label={g === "junior" ? "Junior" : "Middle"}
              checked={initial.accepted_grades?.includes(g)}
            />
          ))}
        </div>
        <h3>Стек</h3>
        <p className="muted">
          Заявленная технология учитывается отдельно от проверенного навыка.
          Подтверждение доступно для Python, SQL и HTTP/API.
        </p>
        <div className="stack-grid">
          {technologyCodes.map((code) => {
            const required = initial.required_stack?.find(
              (t) => t.technology === code,
            );
            return (
              <fieldset key={code} className="choice">
                <legend>{code}</legend>
                <Check
                  name={`required_${code}`}
                  label="Обязательно"
                  checked={!!required}
                />
                <Check
                  name={`preferred_${code}`}
                  label="Желательно"
                  checked={initial.preferred_stack?.includes(code)}
                />
                {dictionary.verified_technology_evidence[code] && (
                  <Check
                    name={`verified_${code}`}
                    label="Требуется независимое подтверждение"
                    checked={required?.verification_required}
                  />
                )}
              </fieldset>
            );
          })}
        </div>
        <h3>Приоритеты навыков</h3>
        <div className="stack-grid">
          {skillCodes.map((code) => (
            <fieldset key={code} className="choice">
              <legend>{dictionary.skills[code]}</legend>
              <Check
                name={`priority_${code}`}
                label="Учитывать в приоритетах"
                checked={!!initial.skill_priorities?.[code]}
              />
              <Field
                name={`weight_${code}`}
                label="Вес"
                value={initial.skill_priorities?.[code] ?? 1}
              >
                <option value="1">1 — обычный</option>
                <option value="2">2 — повышенный</option>
              </Field>
              <Check
                name={`skill_required_${code}`}
                label="Наличие проверенного навыка обязательно"
                checked={initial.required_verified_skills?.includes(code)}
              />
            </fieldset>
          ))}
        </div>
        <h3>Условия и фильтры</h3>
        <div className="checks">
          {Object.entries(formatNames).map(([f, label]) => (
            <Check
              key={f}
              name={`format_${f}`}
              label={label}
              checked={initial.work_formats?.includes(
                f as keyof typeof formatNames,
              )}
            />
          ))}
        </div>
        <div className="fields">
          <Field
            name="location"
            label="Город для офиса/гибрида"
            value={initial.location}
          />
          <Field
            name="desired_start_date"
            label="Желаемая дата начала"
            type="date"
            value={initial.desired_start_date}
          />
          <Field
            name="urgency"
            label="Срочность"
            value={initial.urgency ?? "normal"}
          >
            <option value="normal">Обычная</option>
            <option value="urgent">Срочно</option>
            <option value="flexible">Гибкие сроки</option>
          </Field>
          <Field
            name="min_experience_years"
            label="Минимум лет опыта (самоописание)"
            type="number"
            min={0}
            max={50}
            value={initial.additional_requirements?.required_experience_years}
          />
          <Field
            name="vacancy_id"
            label="ID вакансии (необязательно)"
            value={initial.vacancy_id}
          />
          <Field
            name="additional_wishes"
            label="Дополнительные пожелания (текст не влияет на оценку)"
            type="textarea"
            value={initial.additional_wishes}
          />
        </div>
        <Check
          name="start_date_required"
          label="Дата начала обязательна"
          checked={initial.start_date_required}
        />
      </Form>
      {current && (
        <Action
          onClick={async () => {
            const snapshot: Schema<"SnapshotView"> = await send(
              `/employer/needs/${current.need_id}/recommendations`,
              {},
            );
            location.hash = `#recommendations/${snapshot.id}`;
          }}
        >
          Создать подборку
        </Action>
      )}
    </Section>
  );
}
function SnapshotHistory({ needId }: { needId: string }) {
  const { data, error, reload } = useLoad<Schema<"SnapshotView">[]>(
    `/employer/needs/${needId}/recommendations`,
  );
  if (error) return <LoadError error={error} retry={reload} />;
  if (!data) return <Loading />;
  return (
    <Section title="История подборок">
      {!data.length && (
        <Empty>Создайте первую подборку после сохранения потребности.</Empty>
      )}
      {data.map((snapshot) => (
        <div key={snapshot.id} className="list-row">
          <Link to={`recommendations/${snapshot.id}`}>
            Подборка от {date(snapshot.as_of)}
          </Link>
        </div>
      ))}
    </Section>
  );
}
export function RecommendationsPage({ id }: { id: string }) {
  const {
    data: snapshot,
    error,
    reload,
  } = useLoad<Schema<"SnapshotView">>(`/employer/recommendations/${id}`);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<
    Schema<"SnapshotEntry">[] | null
  >(null);
  if (error) return <LoadError error={error} retry={reload} />;
  if (!snapshot) return <Loading />;
  async function compare() {
    const fresh: Schema<"SnapshotView"> = await get(
      `/employer/recommendations/${id}`,
    );
    const rows = (fresh.entries ?? []).filter((row) =>
      selected.includes(row.candidate_id),
    );
    setComparison(null);
    if (
      rows.length !== 2 ||
      rows.some((row) => !row.available || !row.recommendation || !row.card)
    )
      throw new Error("Одна из карточек больше недоступна. Обновите подборку.");
    const [a, b] = rows;
    if (
      a.recommendation!.grade !== b.recommendation!.grade ||
      a.recommendation!.group !== b.recommendation!.group
    )
      throw new Error(
        "Выберите кандидатов одного уровня из одного списка подборки.",
      );
    if (
      a.recommendation!.assessment_scope.method_version !==
        b.recommendation!.assessment_scope.method_version ||
      a.recommendation!.assessment_scope.format !==
        b.recommendation!.assessment_scope.format
    )
      throw new Error("Эти результаты нельзя сравнить по баллам. Выберите другую пару кандидатов.");
    setComparison(rows);
  }
  return (
    <>
      <Heading
        title="Подборка"
        subtitle={`Подборка от ${date(snapshot.as_of)}`}
      />
      <Link to={`needs/${snapshot.need_id}`}>Потребность</Link>
      <Notice>
        Подбор учитывает проверенные навыки и ваши требования. Контакты открываются только с согласия кандидата.
      </Notice>
      {!snapshot.entries?.length && (
        <Empty>
          По этим условиям пока нет кандидатов. Попробуйте расширить требования или изменить условия работы.
        </Empty>
      )}
      {(["junior", "middle"] as const).flatMap((grade) =>
        (["eligible", "needs_clarification"] as const).map((group) => {
          const rows = (snapshot.entries ?? []).filter(
            (row) =>
              row.available &&
              row.recommendation?.grade === grade &&
              row.recommendation?.group === group,
          );
          return rows.length ? (
            <section key={`${grade}-${group}`}>
              <h2>
                {grade.toUpperCase()} ·{" "}
                {group === "eligible"
                  ? "Основная группа"
                  : "Требуется уточнение"}
              </h2>
              <div className="card-grid">
                {rows.map((row) => (
                  <RecommendationCard
                    key={row.candidate_id}
                    row={row}
                    needId={snapshot.need_id}
                    selected={selected.includes(row.candidate_id)}
                    toggle={() =>
                      setSelected((ids) =>
                        ids.includes(row.candidate_id)
                          ? ids.filter((x) => x !== row.candidate_id)
                          : [...ids, row.candidate_id],
                      )
                    }
                    reload={() => {
                      setComparison(null);
                      reload();
                    }}
                  />
                ))}
              </div>
            </section>
          ) : null;
        }),
      )}
      {(snapshot.entries ?? [])
        .filter((row) => !row.available)
        .map((row) => (
          <Section key={row.candidate_id} title="Недоступная карточка">
            <p>Карточка недоступна.</p>
            {row.hidden && (
              <Action
                onClick={async () => {
                  await send(
                    `/employer/needs/${snapshot.need_id}/candidates/${row.candidate_id}`,
                    { saved: row.saved, hidden: false },
                    "PUT",
                  );
                  reload();
                }}
              >
                Отменить скрытие
              </Action>
            )}
          </Section>
        ))}
      <div className="actions">
        <Action disabled={selected.length !== 2} onClick={compare}>
          Сравнить две выбранные карточки
        </Action>
        <Action
          onClick={() => {
            setComparison(null);
            reload();
          }}
        >
          Обновить подборку
        </Action>
      </div>
      <p className="muted">
        Выбрано {selected.length} из 2. Для сравнения нужны один уровень, одна
        группа требований.
      </p>
      {comparison && (
        <Section title="Сравнение">
          <div className="table-scroll">
            <table className="comparison-table">
              <thead>
                <tr>
                  <th scope="col">Показатель</th>
                  {comparison.map((row) => (
                    <th key={row.candidate_id} scope="col">
                      {String(row.card!.display_name)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {["score", "skills", "technologies", "explanations"].map(
                  (field) => (
                    <tr key={field}>
                      <th scope="row">
                        {
                          {
                            score: "Баллы подбора",
                            skills: "Навыки",
                            technologies: "Стек",
                            explanations: "Объяснение",
                          }[field]
                        }
                      </th>
                      {comparison.map((row) => (
                        <td key={row.candidate_id}>
                          {field === "score"
                            ? row.recommendation!.score
                            : field === "explanations"
                              ? row.recommendation!.explanations.join(" ")
                              : field === "skills"
                                ? Object.entries(
                                    row.recommendation!.skills,
                                  ).map(([code, evidence]) => (
                                    <p key={code}>
                                      {skillNames[code] ?? code}:{" "}
                                      {evidence.score ?? "Нет данных"}/100
                                    </p>
                                  ))
                                : Object.entries(
                                    row.recommendation!.technologies,
                                  ).map(([code, state]) => (
                                    <p key={code}>
                                      {code}:{" "}
                                      {
                                        {
                                          verified: "Проверено",
                                          self_reported: "Заявлено",
                                          absent: "Нет доказательств",
                                        }[state]
                                      }
                                    </p>
                                  ))}
                        </td>
                      ))}
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </>
  );
}
function RecommendationCard({
  row,
  needId,
  selected,
  toggle,
  reload,
}: {
  row: Schema<"SnapshotEntry">;
  needId: string;
  selected: boolean;
  toggle: () => void;
  reload: () => void;
}) {
  const [reason, setReason] = useState("");
  const rec = row.recommendation!;
  const card = row.card as unknown as Schema<"SafeCard">;
  return (
    <Section title={card.display_name}>
      <p>{card.summary}</p>
      <p className="score">
        {rec.score}
        <small> баллов подбора</small>
      </p>
      <p>{money(card.salary_min, card.salary_max)}</p>
      <p className="muted">
        Проверены навыки Python, SQL и HTTP/API.
      </p>
      {rec.missing_conditions.length > 0 && (
        <Notice warning>
          Нужно уточнить: {rec.missing_conditions.map(condition => ({salary: "зарплата", location: "город", work_format: "формат работы", work_formats: "формат работы", available_from: "дата выхода", availability: "дата выхода", experience: "опыт"} as Record<string, string>)[condition] ?? "условия работы").join(", ")}
        </Notice>
      )}
      <details>
        <summary>Почему кандидат в подборке</summary>
        {rec.explanations.map((text, index) => (
          <p key={index}>{text}</p>
        ))}
        <ul>{Object.entries(rec.components).map(([key, score]) => <li key={key}>{({T: "Навыки", K: "Технологии", F: "Достижения ФСП", U: "Актуальность", P: "Поправка на условия"} as Record<string, string>)[key] ?? "Показатель"}: {score}</li>)}</ul>
      </details>
      <label className="check">
        <input
          type="checkbox"
          name={`compare_${row.candidate_id}`}
          checked={selected}
          onChange={toggle}
        />
        Сравнить
      </label>
      <div className="actions">
        <Action
          onClick={async () => {
            await send(
              `/employer/needs/${needId}/candidates/${row.candidate_id}`,
              { saved: !row.saved, hidden: false },
              "PUT",
            );
            reload();
          }}
        >
          {row.saved ? "Убрать из сохранённых" : "Сохранить"}
        </Action>
        <Link to={`offer/${needId}/${row.candidate_id}`}>Пригласить</Link>
        <Action
          onClick={() =>
            download(`/candidates/${row.candidate_id}/profile.pdf`)
          }
        >
          PDF
        </Action>
      </div>
      <label className="field">
        Причина скрытия (необязательно)
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <Action
        onClick={async () => {
          await send(
            `/employer/needs/${needId}/candidates/${row.candidate_id}`,
            { saved: row.saved, hidden: true, reason },
            "PUT",
          );
          reload();
        }}
      >
        Скрыть для этой потребности
      </Action>
    </Section>
  );
}
