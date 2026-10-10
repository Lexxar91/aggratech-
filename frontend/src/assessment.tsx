import { useEffect, useRef, useState } from "react";
import { send } from "./api";
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
  date,
  errorText,
  list,
  number,
  statusNames,
  skillNames,
  useFeedback,
  useLoad,
  value,
} from "./ui";

type Cycle = Schema<"CycleView">;
export function Result({ result }: { result: Schema<"ResultView"> }) {
  return (
    <Section title="Результат">
      <div className="result-header">
        <Badge>{statusNames[result.outcome] ?? result.outcome}</Badge>
        <Badge>{result.grade.toUpperCase()}</Badge>
      </div>
      <p>{result.label}</p>
      {!result.verified && (
        <Notice warning>
          Демонстрационный / неподтверждённый результат. Не является
          подтверждением квалификации и не включается в подтверждённую подборку.
        </Notice>
      )}
      {result.total !== null && (
        <p className="score">
          {result.total}
          <small> / 100 · суммарный показатель</small>
        </p>
      )}
      <div className="skill-grid">
        {(result.skills ?? []).map((skill) => (
          <div key={skill.skill} className="metric">
            <span>{skillNames[skill.skill] ?? skill.skill}</span>
            <strong>{skill.score ?? "Нет данных"}</strong>
            <small>
              {(
                {
                  met: "Порог выполнен",
                  not_met: "Ниже порога",
                  not_checked: "Недостаточно данных",
                  below: "Ниже порога",
                  insufficient: "Недостаточно данных",
                } as Record<string, string>
              )[skill.status] ?? skill.status}{" "}
              · семейств: {skill.families}
            </small>
          </div>
        ))}
      </div>
      <p className="muted">
        Область оценки: {result.scope}. Методика: {result.methodology}. Дата:{" "}
        {date(result.assessed_at)}
      </p>
      {result.limitations && <Notice>{result.limitations}</Notice>}
      {!!result.requirements?.length && (
        <details>
          <summary>Основания по проверяемым действиям</summary>
          {result.requirements.map((item, index) => (
            <p key={`${item.task_id}-${index}`}>
              <strong>{item.task_id}</strong> · {item.action}: {item.passed === true ? "выполнено" : item.passed === false ? "не выполнено" : "нет завершённого доказательства"} ({item.status})
            </p>
          ))}
        </details>
      )}
    </Section>
  );
}

export function AssessmentPage({ id }: { id?: string }) {
  return id ? <AssessmentCycle id={id} /> : <AssessmentStart />;
}
function AssessmentStart() {
  const survey = useLoad<Schema<"SurveyInput"> | null>("/assessment/survey");
  const cycles = useLoad<Cycle[]>("/assessment/cycles");
  const appeals = useLoad<Schema<"AppealView">[]>("/assessment/appeals");
  const availability = useLoad<Schema<"AssessmentAvailability">>("/assessment/availability");
  const error = survey.error || cycles.error || appeals.error || availability.error;
  if (error)
    return (
      <LoadError
        error={error}
        retry={() => {
          survey.reload();
          cycles.reload();
          appeals.reload();
          availability.reload();
        }}
      />
    );
  if (!cycles.data || !appeals.data || !availability.data) return <Loading />;
  return (
    <>
      <Heading
        title="Проверка навыков Backend"
        subtitle="Опрос, два этапа и прозрачный результат."
      />
      <div className="actions">
        <Link to="profile">К профилю</Link>
      </div>
      <Notice warning={!availability.data.credit_available}>{availability.data.message}</Notice>
      <Section title="Как проходит проверка">
        <div className="steps">
          <div>
            <strong>01 / Опрос</strong>
            <p>Выберите Junior или Middle и подтвердите правила.</p>
          </div>
          <div>
            <strong>02 / Этап A · 30 минут</strong>
            <p>{availability.data.a_tasks} заданий. Сначала первоначальное решение, затем перенос.</p>
          </div>
          <div>
            <strong>03 / Этап B · 15 минут</strong>
            <p>Два задания. Начните в течение 24 часов после A.</p>
          </div>
        </div>
        <p>
          Таймер продолжает идти при закрытии страницы. Разрешены редактор,
          собственный код и справочная документация; ответы самостоятельные.
          Черновики сохраняйте кнопкой до ухода со страницы. Технический сбой
          можно обжаловать.
        </p>
        <p className="muted">
          Повтор того же грейда — через 7 дней, смена опубликованного — через 30
          дней; не более двух завершённых циклов за 30 дней. Для новой попытки
          нужны непоказанные семейства. Ограничения проверяет сервер.
        </p>
      </Section>
      <Section title="Опрос и выбор грейда">
        <Form
          label={availability.data.credit_available ? "Начать прохождение" : "Начать демо-цикл"}
          onSubmit={async (data) => {
            const input: Schema<"SurveyInput"> = {
              industry: value(data, "industry"),
              stack: list(data, "stack"),
              experience_years: number(data, "experience_years"),
              specialization: "backend",
              tools_policy: "independent",
              instructions_accepted: true,
            };
            await send("/assessment/survey", input, "PUT");
            const cycle: Cycle = await send("/assessment/cycles", {
              grade: value(data, "grade"),
              mode: value(data, "mode"),
              form: value(data, "form") || null,
            });
            location.hash = `#assessment/${cycle.id}`;
          }}
        >
          <div className="fields">
            <Field
              name="industry"
              label="Отрасль"
              value={survey.data?.industry ?? "IT"}
              required
            />
            <Field
              name="stack"
              label="Стек через запятую"
              value={survey.data?.stack.join(", ") ?? "Python, SQL, HTTP"}
              required
            />
            <Field
              name="experience_years"
              label="Опыт, лет"
              type="number"
              value={survey.data?.experience_years ?? 0}
              min={0}
              max={50}
              required
            />
            <Field name="grade" label="Грейд" value="junior">
              <option value="junior">Junior</option>
              <option value="middle">Middle</option>
            </Field>
            <Field name="mode" label="Режим" value={availability.data.credit_available ? "credit" : "demo"}>
              {availability.data.credit_available && <option value="credit">Зачётный</option>}
              {availability.data.demo_available && <option value="demo">Демонстрационный, без подтверждения квалификации</option>}
              {!availability.data.demo_available && <option value="">Прохождение недоступно</option>}
            </Field>
            <Field name="form" label="Форма" value="">
              <option value="">Любая доступная</option>
              <option value="X">X</option>
              <option value="Y">Y</option>
            </Field>
          </div>
          <Check
            name="instructions_accepted"
            label="Правила прочитаны, подтверждаю самостоятельность"
            required
          />
        </Form>
      </Section>
      <Section title="История">
        {!cycles.data.length && (
          <Empty>Прохождений пока нет. Начните с опроса.</Empty>
        )}
        {cycles.data.map((cycle) => (
          <div className="list-row" key={cycle.id}>
            <a href={`#assessment/${cycle.id}`}>
              {cycle.grade} · {cycle.mode} · {cycle.state} ·{" "}
              {statusNames[cycle.result.outcome]}
            </a>
            <small>{date(cycle.created_at)}</small>
          </div>
        ))}
      </Section>
      <Section title="Апелляции">
        {!appeals.data.length && <Empty>Апелляций пока нет.</Empty>}
        {appeals.data.map((appeal) => (
          <div className="list-row" key={appeal.id}>
            <Link to={`assessment/${appeal.cycle_id}`}>Прохождение</Link>
            <p>
              {appeal.state}: {appeal.resolution ?? "Решение ожидается"}
            </p>
          </div>
        ))}
      </Section>
    </>
  );
}

function Timer({
  deadline,
  start = false,
}: {
  deadline: string;
  start?: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(
    0,
    Math.floor((new Date(deadline).getTime() - now) / 1000),
  );
  const display = `${Math.floor(seconds / 3600)
    .toString()
    .padStart(2, "0")}:${Math.floor((seconds / 60) % 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
  return (
    <div
      className="timer"
      role="timer"
      aria-label={start ? "До срока начала B" : "До срока сдачи"}
    >
      <span>{start ? "Начните B в течение" : "Осталось времени"}</span>
      <strong>{display}</strong>
      <small>
        Серверный срок: {date(deadline)}.{" "}
        {seconds === 0 && "Обновите состояние: срок истёк."}
      </small>
    </div>
  );
}
function AssessmentCycle({ id }: { id: string }) {
  const {
    data: cycle,
    error,
    reload,
  } = useLoad<Cycle>(`/assessment/cycles/${id}`);
  const feedback = useFeedback();
  useEffect(() => {
    if (!cycle || !["grading_A", "grading_B", "grading"].includes(cycle.state))
      return;
    const timer = setInterval(reload, 4000);
    return () => clearInterval(timer);
  }, [cycle, reload]);
  if (error) return <LoadError error={error} retry={reload} />;
  if (!cycle) return <Loading />;
  const deadline =
    cycle.state === "A"
      ? cycle.a_deadline
      : cycle.state === "B"
        ? cycle.b_deadline
        : cycle.state === "B_ready"
          ? cycle.b_start_deadline
          : null;
  return (
    <>
      <Heading
        title="Проверка навыков Backend"
        subtitle={`${cycle.grade} · ${cycle.mode} · ${statusNames[cycle.state] ?? cycle.state}`}
      />
      <div className="actions">
        <Link to="assessment">Все прохождения</Link>
        <Link to="profile">К профилю</Link>
        <Action onClick={reload}>Обновить состояние</Action>
      </div>
      <Notice warning={cycle.mode === "demo"}>
        {cycle.mode === "demo" ? "Демонстрационный цикл: результат не подтверждает квалификацию." : "Зачётный цикл: результат рассчитывается по допущенным материалам и указанной версии методики."}
      </Notice>
      {deadline && (
        <Timer deadline={deadline} start={cycle.state === "B_ready"} />
      )}
      {cycle.technical_issue && (
        <Notice warning>
          Технический сбой оценивания: оценки за сбой не выставлены. Подайте
          апелляцию для восстановления проверки того же цикла.
        </Notice>
      )}
      {cycle.tasks.map((task) => (
        <Task
          key={`${task.family}-${task.step}`}
          task={task}
          cycleId={id}
          refresh={reload}
        />
      ))}
      {["A", "B"].includes(cycle.state) && (
        <Section title={`Завершение этапа ${cycle.state}`}>
          <p>
            {cycle.result.methodology === "backend-assessment-v3-packages-1" ? "Сначала зафиксируйте первоначальное решение и перенос каждого задания. Черновики не являются отправленными ответами; истечение времени завершает сеанс без оценки неотправленного решения." : "Будут отправлены сохранённые черновики. Перед сдачей сохраните все изменения; после сдачи этап редактировать нельзя."}
          </p>
          <Action
            onClick={async () => {
              await send(`/assessment/cycles/${id}/submit/${cycle.state}`, {});
              reload();
            }}
          >
            {cycle.result.methodology === "backend-assessment-v3-packages-1" ? `Сдать ${cycle.state}` : `Сдать ${cycle.state} с сохранёнными черновиками`}
          </Action>
        </Section>
      )}
      {cycle.state === "B_ready" && (
        <Section title="Этап B готов">
          <p>
            Можно сделать перерыв 5–10 минут или начать сразу. После начала у
            вас будет 15 минут.
          </p>
          <Action
            onClick={async () => {
              await send(`/assessment/cycles/${id}/start-b`, {});
              reload();
            }}
          >
            Начать B (15 минут)
          </Action>
        </Section>
      )}
      {cycle.state.includes("grading") && (
        <Notice>
          Ответы проверяются. Страница обновляет состояние автоматически.
        </Notice>
      )}
      <Result result={cycle.result} />
      {cycle.state === "completed" && cycle.result.outcome === "confirmed" && (
        <Action
          onClick={async () => {
            await send(`/assessment/cycles/${id}/publish`, {});
            feedback("Выбор результата сохранён.");
          }}
        >
          {cycle.mode === "demo"
            ? "Опубликовать демо-результат в своём профиле"
            : "Опубликовать категорию"}
        </Action>
      )}
      <Section title="Сообщить о проблеме">
        <Form
          label="Отправить апелляцию"
          onSubmit={async (data) => {
            await send(`/assessment/cycles/${id}/appeals`, {
              message: value(data, "message"),
            });
            feedback("Апелляция зарегистрирована.");
          }}
        >
          <Field
            name="message"
            label="Апелляция: опишите проблему"
            type="textarea"
            required
          />
        </Form>
      </Section>
    </>
  );
}

function Task({
  task,
  cycleId,
  refresh,
}: {
  task: Schema<"PublicTask">;
  cycleId: string;
  refresh: () => void;
}) {
  const ref = useRef<HTMLFormElement>(null);
  const [revision, setRevision] = useState(task.revision);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const feedback = useFeedback();
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function answer(): Schema<"TaskAnswer"> {
    const data = new FormData(ref.current!);
    try {
      return {
        source: String(data.get("source") ?? ""),
        diagnosis: value(data, "diagnosis"),
        verification: list(data, "verification"),
        structured: JSON.parse(
          value(data, "structured") || "{}",
        ) as Schema<"TaskAnswer">["structured"],
        tests: JSON.parse(
          value(data, "tests") || "[]",
        ) as Schema<"TaskAnswer">["tests"],
      };
    } catch {
      throw new Error(
        "Проверьте JSON структурированного ответа и собственных тестов.",
      );
    }
  }
  async function save(fix: boolean) {
    setBusy(true);
    try {
      const result: Cycle = await send(
        `/assessment/cycles/${cycleId}/answers/${task.family}${fix ? "/fix" : ""}`,
        { revision, step: task.step, answer: answer() },
        fix ? "POST" : "PUT",
      );
      setRevision(
        result.tasks.find((t) => t.family === task.family)?.revision ??
          revision,
      );
      setDirty(false);
      if (fix) refresh();
      else feedback("Черновик сохранён.");
    } catch (cause) {
      feedback(errorText(cause), true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      ref={ref}
      id={`task-${task.family}`}
      className="panel task"
      onChange={() => setDirty(true)}
      onSubmit={(event) => {
        event.preventDefault();
        void save(true);
      }}
    >
      <h3>
        {task.family} · {task.step}{task.title ? ` · ${task.title}` : ""}
      </h3>
      <p className="preserve-lines">{task.condition}</p>
      {task.common_contract && <details><summary>Обязательные общие контракты и адаптеры</summary><p className="preserve-lines">{task.common_contract}</p></details>}
      <p>{task.diagnosis_prompt}</p>
      {task.input !== null && <details open>
        <summary>Данные задания</summary>
        <pre>{JSON.stringify(task.input, null, 2)}</pre>
      </details>}
      {task.finalized ? (
        <Notice>Ответ зафиксирован.</Notice>
      ) : (
        <fieldset disabled={busy}>
          {task.task_id ? <Field name="source" label={task.language === "sql" ? "SQL: solution.sql" : "Python: solution.py"} type="textarea" value={task.draft.source} /> : task.python_required && (
            <>
              <Field
                name="source"
                label="Python: функция solve(data)"
                type="textarea"
                value={task.draft.source}
              />
              <Field
                name="diagnosis"
                label={`Диагноз: ${task.diagnosis_options.join(", ")}`}
                value={task.draft.diagnosis}
              />
              <Field
                name="verification"
                label={`Проверенные случаи через запятую: ${task.verification_options.join(", ")}`}
                value={(task.draft.verification ?? []).join(", ")}
              />
            </>
          )}
          {task.structured_condition && (
            <>
              <p>{task.structured_condition}</p>
              <pre>
                {JSON.stringify(
                  {
                    input: task.structured_input,
                    options: task.answer_options,
                  },
                  null,
                  2,
                )}
              </pre>
              <Field
                name="structured"
                label="Структурированный ответ (JSON)"
                type="textarea"
                value={JSON.stringify(task.draft.structured, null, 2)}
              />
            </>
          )}
          {task.candidate_test_contract && (
            <>
              <p>{task.candidate_test_contract}</p>
              <Field
                name="tests"
                label="Собственные тесты (JSON)"
                type="textarea"
                value={JSON.stringify(task.draft.tests, null, 2)}
              />
            </>
          )}
          <p className="muted" role="status">
            {dirty
              ? "Есть несохранённые изменения"
              : `Черновик сохранён · ревизия ${revision}`}
          </p>
          <div className="actions">
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void save(false)}
            >
              Сохранить черновик
            </button>
            <button type="submit" className="primary" disabled={busy}>
              {task.step === "base"
                ? "Зафиксировать базу и открыть перенос"
                : "Зафиксировать перенос"}
            </button>
          </div>
        </fieldset>
      )}
    </form>
  );
}
