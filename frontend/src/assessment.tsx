import { useEffect, useRef, useState } from "react";
import { send } from "./api";
import type { Schema } from "./api";
import { Markdown, TaskStatement } from "./markdown";
import { taskExample } from "./task-examples";
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
export function Result({ result, state }: { result: Schema<"ResultView">; state?: string }) {
  const level = result.grade === "middle" ? "Middle" : "Junior";
  const title = result.verified ? `Ваш уровень — ${level}` : state === "technical_error" ? "Проверка временно прервана из-за сбоя" : result.outcome === "not_confirmed" ? `Уровень ${level} пока не подтверждён` : result.outcome === "review_required" ? "Решения требуют дополнительной проверки" : result.outcome === "confirmed" ? result.mode === "demo" ? "Тренировочное прохождение завершено" : "Не удалось подтвердить результат. Обратитесь в поддержку." : state === "expired" || result.assessed_at ? "Недостаточно завершённых решений для подтверждения уровня" : "Проверка ещё не завершена";
  return (
    <Section title="Результат">
      <div className="result-header">
        <Badge>{statusNames[result.outcome] ?? result.outcome}</Badge>
        <Badge>{result.grade.toUpperCase()}</Badge>
      </div>
      <p className="result-title">{title}</p>
      {result.mode === "demo" && <Notice warning>Это тренировочное прохождение. Для публикации уровня пройдите проверку навыков.</Notice>}
      {result.outcome === "not_confirmed" && <Notice warning>Для подтверждения важны все проверяемые навыки. Общий балл не заменяет выполнение обязательных требований.</Notice>}
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
                  met: "Требования выполнены",
                  not_met: "Нужно доработать",
                  not_checked: "Недостаточно данных",
                  below: "Нужно доработать",
                  insufficient: "Недостаточно данных",
                } as Record<string, string>
              )[skill.status] ?? skill.status}{" "}

            </small>
          </div>
        ))}
      </div>
      <p className="muted">Проверенные навыки: Python, SQL и HTTP/API. Дата: {date(result.assessed_at)}</p>
      {!!result.requirements?.length && (
        <details open={result.outcome === "not_confirmed"}>
          <summary>Что выполнено и что нужно доработать</summary>
          {result.requirements.map((item, index) => (
            <p key={`${item.task_id}-${index}`}>
              <strong>Задание {item.task_number ?? 1}. {item.task_title || "Проверка навыка"}</strong> · {item.task_id === "Y6-J" && item.skill === "security_validation" ? "Ограничение фактического размера и очистка временных данных" : item.action}: {item.passed === true ? "выполнено" : item.passed === false ? "не выполнено" : "нет завершённого доказательства"}
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
        subtitle="Выберите уровень, который хотите подтвердить. Затем выполните задания."
      />
      <div className="actions">
        <Link to="profile">К профилю</Link>
      </div>
      {!availability.data.credit_available && <Notice warning>Проверка навыков временно недоступна. Попробуйте позже.</Notice>}
      <Section title="Как проходит проверка">
        <div className="steps">
          <div>
            <strong>01 / Подготовка</strong>
            <p>Выберите Junior или Middle и подтвердите правила.</p>
          </div>
          <div>
            <strong>02 / Основные задания · 30 минут</strong>
            <p>{availability.data.a_tasks} заданий. У каждого задания две части: исходное и изменённое условие.</p>
          </div>
          <div>
            <strong>03 / Дополнительные задания · 15 минут</strong>
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
          Повтор того же уровня — через 7 дней, смена опубликованного — через 30
          дней; не более двух завершённых прохождений за 30 дней. Для новой попытки
          нужны задания, которые вы ещё не видели.
        </p>
      </Section>
      <Section title="Подготовка к проверке">
        <Form
          label="Начать проверку навыков"
          onSubmit={async (data) => {
            if (!availability.data?.credit_available) throw new Error("Проверка навыков временно недоступна.");
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
              mode: "credit",
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
            <Field name="grade" label="Уровень" value="junior">
              <option value="junior">Junior</option>
              <option value="middle">Middle</option>
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
              {cycle.grade === "middle" ? "Middle" : "Junior"} · {statusNames[cycle.state] ?? "Проверка"} ·{" "}
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
              {appeal.state === "open" ? "Рассматривается" : "Рассмотрена"}: {appeal.resolution ?? "Решение ожидается"}
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
      aria-label={start ? "До начала дополнительной части" : "До срока сдачи"}
    >
      <span>{start ? "Начните дополнительную часть в течение" : "Осталось времени"}</span>
      <strong>{display}</strong>
      <small>
        До: {date(deadline)}.{" "}
        {seconds === 0 && "Время истекло. Статус обновится автоматически."}
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
    if (!cycle || ["completed", "expired", "invalidated"].includes(cycle.state))
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
        subtitle={`${cycle.grade === "middle" ? "Middle" : "Junior"} · ${statusNames[cycle.state] ?? "Проверка решений"}`}
      />
      <div className="actions">
        <Link to="assessment">Все прохождения</Link>
        <Link to="profile">К профилю</Link>
        <Action onClick={reload}>Обновить состояние</Action>
      </div>
      <ol className="assessment-progress" aria-label="Ход проверки">{["Подготовка", "Задания", "Проверка решений", "Результат"].map((step, index) => <li key={step} aria-current={(cycle.state === "completed" ? 3 : cycle.state === "grading" ? 2 : 1) === index ? "step" : undefined}>{step}</li>)}</ol>
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
        <Section title="Завершение части проверки">
          <p>
            Отправьте обе части каждого задания. После завершения решения изменить нельзя. Неотправленные черновики не оцениваются.

          </p>
          <Action
            onClick={async () => {
              await send(`/assessment/cycles/${id}/submit/${cycle.state}`, {});
              reload();
            }}
          >
            {cycle.state === "A" ? "Завершить основные задания" : "Завершить проверку"}
          </Action>
        </Section>
      )}
      {cycle.state === "B_ready" && (
        <Section title="Основные задания отправлены">
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
            Начать дополнительные задания (15 минут)
          </Action>
        </Section>
      )}
      {cycle.state.includes("grading") && (
        <Notice>
          Ответы проверяются. Страница обновляет состояние автоматически.
        </Notice>
      )}
      <Result result={cycle.result} state={cycle.state} />
      {cycle.state === "completed" && cycle.result.outcome === "confirmed" && (
        <Action
          onClick={async () => {
            await send(`/assessment/cycles/${id}/publish`, {});
            feedback("Выбор результата сохранён.");
          }}
        >
          Опубликовать результат
        </Action>
      )}
      {cycle.state === "completed" && cycle.result.outcome === "not_confirmed" && <Section title="Следующий шаг"><p>Доработайте указанные навыки. Повторная проверка того же уровня доступна не раньше {date(new Date(new Date(cycle.completed_at ?? cycle.created_at).getTime() + 7 * 86400000).toISOString())}. Действуют ограничения: две завершённые проверки за 30 дней и наличие новых заданий.</p><Link to="assessment">К выбору уровня и истории</Link></Section>}
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
    <details className="task-disclosure" open={(task.number ?? 1) === 1}>
      <summary className="task-summary">
        <span className="task-index">{String(task.number ?? 1).padStart(2, "0")}</span>
        <span className="task-summary-title">Задание {task.number ?? 1}. {task.title || "Проверка навыка"}</span>
        <Badge>{task.language === "sql" ? "SQL" : "Python"} · {task.finalized ? "Решение отправлено" : task.step === "base" ? "Первая часть" : "Вторая часть"}</Badge>
      </summary>
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
      <div className="task-workspace">
      <div className="task-condition">
      <TaskStatement condition={task.condition} language={task.language} example={taskExample(task.task_id ?? "")} />
      <p>{task.diagnosis_prompt}</p>
      {task.input !== null && <details open>
        <summary>Данные задания</summary>
        <pre>{JSON.stringify(task.input, null, 2)}</pre>
      </details>}
      </div>
      {task.finalized ? (
        <Notice>Ответ зафиксирован.</Notice>
      ) : (
        <fieldset disabled={busy}>
          {task.task_id ? <Field name="source" label={task.language === "sql" ? "Редактор SQL-решения" : "Редактор Python-решения"} type="textarea" value={task.draft.source} /> : task.python_required && (
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
              <Markdown text={task.structured_condition} />
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
              : "Черновик сохранён"}
          </p>
          <p>После отправки изменить это решение нельзя. Будет отправлен текущий текст из редактора.</p>
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
                ? "Отправить решение и перейти ко второй части"
                : "Отправить решение второй части"}
            </button>
          </div>
        </fieldset>
      )}
      </div>
    </form>
    </details>
  );
}
