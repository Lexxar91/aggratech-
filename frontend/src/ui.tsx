import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useState,
} from "react";
import type { FormEvent, ReactNode, Ref } from "react";
import { get } from "./api";
import type { User } from "./api";

export const SessionContext = createContext<{
  user: User | null;
  setUser: (user: User | null) => void;
}>({ user: null, setUser: () => {} });
export const FeedbackContext = createContext<
  (text: string, error?: boolean) => void
>(() => {});
export const useFeedback = () => useContext(FeedbackContext);

export function useLoad<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    get<T>(path)
      .then((value) => {
        if (active) setData(value);
      })
      .catch((cause: Error) => {
        if (active) setError(cause.message);
      });
    return () => {
      active = false;
    };
  }, [path, version]);
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  return { data, error, reload };
}

export function Loading() {
  return (
    <div className="state" role="status">
      <span className="spinner" />
      Загружаем данные…
    </div>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Notice({
  children,
  warning = false,
}: {
  children: ReactNode;
  warning?: boolean;
}) {
  return (
    <div className={warning ? "notice warning" : "notice"}>{children}</div>
  );
}
export function LoadError({
  error,
  retry,
}: {
  error: string;
  retry: () => void;
}) {
  return (
    <div className="notice warning" role="alert">
      <p>{error}</p>
      <Action onClick={retry}>Повторить загрузку</Action>
    </div>
  );
}
export function Heading({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">AGGRATECH / ЛИЧНЫЙ КАБИНЕТ</p>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}
export function Section({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
export function Badge({ children }: { children: ReactNode }) {
  return <span className="badge">{children}</span>;
}
export function Link({
  to,
  children,
  primary = false,
}: {
  to: string;
  children: ReactNode;
  primary?: boolean;
}) {
  return (
    <a
      className={primary ? "button primary" : "button secondary"}
      href={`#${to}`}
    >
      {children}
    </a>
  );
}

export function Field({
  name,
  label,
  value = "",
  type = "text",
  required = false,
  min,
  max,
  placeholder,
  children,
}: {
  name: string;
  label: string;
  value?: string | number | null;
  type?: string;
  required?: boolean;
  min?: number;
  max?: number;
  placeholder?: string;
  children?: ReactNode;
}) {
  const unique = useId();
  const id = ["email", "password"].includes(name) ? name : `${name}-${unique}`;
  const props = {
    name,
    id,
    defaultValue: value ?? "",
    required,
    placeholder,
    "aria-label": label,
  };
  return (
    <label
      className={type === "textarea" ? "field wide" : "field"}
      htmlFor={id}
    >
      <span>
        {label}
        {required && <span aria-hidden="true"> *</span>}
      </span>
      {children ? (
        <select {...props}>{children}</select>
      ) : type === "textarea" ? (
        <textarea {...props} rows={5} />
      ) : (
        <input
          {...props}
          type={type}
          min={min}
          max={max}
          step={type === "number" ? "any" : undefined}
          minLength={type === "password" ? 12 : undefined}
          maxLength={type === "password" ? 128 : undefined}
          autoComplete={type === "password" ? "current-password" : undefined}
        />
      )}
    </label>
  );
}

export function Check({
  name,
  label,
  checked = false,
  required = false,
  value,
}: {
  name: string;
  label: string;
  checked?: boolean;
  required?: boolean;
  value?: string;
}) {
  return (
    <label className="check">
      <input
        type="checkbox"
        name={name}
        defaultChecked={checked}
        required={required}
        value={value}
      />
      {label}
    </label>
  );
}
export function Form({
  children,
  onSubmit,
  label,
  className = "",
  formRef,
}: {
  children: ReactNode;
  onSubmit: (data: FormData) => Promise<void>;
  label: string;
  className?: string;
  formRef?: Ref<HTMLFormElement>;
}) {
  const [busy, setBusy] = useState(false);
  const feedback = useFeedback();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await onSubmit(data);
    } catch (cause) {
      feedback(errorText(cause), true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      ref={formRef}
      onSubmit={submit}
      className={className}
      aria-busy={busy}
    >
      <fieldset disabled={busy}>
        {children}
        <div className="form-actions">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : label}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
export function Action({
  children,
  onClick,
  disabled = false,
  danger = false,
}: {
  children: ReactNode;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
  danger?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const feedback = useFeedback();
  return (
    <button
      type="button"
      className={danger ? "danger" : "secondary"}
      disabled={disabled || busy}
      onClick={async () => {
        setBusy(true);
        try {
          await onClick();
        } catch (cause) {
          feedback(errorText(cause), true);
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? "Подождите…" : children}
    </button>
  );
}

export const errorText = (cause: unknown) =>
  cause instanceof Error ? cause.message : "Не удалось выполнить действие.";
export const value = (data: FormData, name: string) =>
  String(data.get(name) ?? "").trim();
export const optional = (data: FormData, name: string) =>
  value(data, name) || null;
export const number = (data: FormData, name: string) =>
  Number(value(data, name));
export const checked = (data: FormData, name: string) => data.has(name);
export const list = (data: FormData, name: string) =>
  value(data, name)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
export const date = (raw: string | null | undefined) =>
  raw ? new Date(raw).toLocaleString("ru-RU") : "Не указано";
export const money = (
  from: string | number | null,
  to: string | number | null,
) =>
  from === null && to === null
    ? "Зарплата не указана"
    : `${from === null ? "…" : Number(from).toLocaleString("ru-RU")} — ${to === null ? "…" : Number(to).toLocaleString("ru-RU")} ₽ до налогов`;
export const formatNames = {
  remote: "Удалённо",
  hybrid: "Гибрид",
  office: "Офис",
};
export const skillNames: Record<string, string> = {
  language_algorithms: "Python и алгоритмы",
  sql_data: "SQL и данные",
  http_api: "HTTP и API",
  debug_reliability: "Отладка и надёжность",
  security_validation: "Безопасность и валидация",
};
export const statusNames: Record<string, string> = {
  published: "Опубликована",
  closed: "Закрыта",
  submitted: "Отправлен",
  viewed: "Просмотрен",
  accepted: "Принят",
  rejected: "Отклонён",
  withdrawn: "Отозван",
  sent: "Отправлено",
  expired: "Срок истёк",
  completed: "Завершено",
  A: "Основные задания",
  B: "Дополнительные задания",
  B_ready: "Можно начать дополнительные задания",
  technical_error: "Проверка временно прервана",
  invalidated: "Прохождение отменено",
  grading: "Оценивается",
  confirmed: "Требования выполнены",
  not_confirmed: "Требования пока не выполнены",
  insufficient: "Недостаточно данных",
  review_required: "Нужна проверка достоверности",
};
