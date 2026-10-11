import type { components } from "./api-schema";

export type Schema<K extends keyof components["schemas"]> =
  components["schemas"][K];
export type User = Schema<"UserView">;
let accessToken: string | null = null;
let refreshPromise: Promise<void> | null = null;

function csrf(): string {
  const cookie = document.cookie
    .split("; ")
    .find((item) => item.startsWith("csrf_token="));
  return decodeURIComponent(cookie?.slice("csrf_token=".length) ?? "");
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function response(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<Response> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (path === "/auth/refresh" || path === "/auth/logout")
    headers.set("X-CSRF-Token", csrf());
  let result: Response;
  try {
    result = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(
      0,
      "network_error",
      "Нет связи с сервером. Проверьте подключение и повторите действие.",
    );
  }
  if (
    result.status === 401 &&
    retry &&
    accessToken &&
    !path.startsWith("/auth/")
  ) {
    await refresh();
    return response(path, options, false);
  }
  if (!result.ok) {
    const problem: { code?: string; detail?: string | { msg: string }[] } =
      await result.json().catch(() => ({}));
    const messages: Record<string, string> = {
      active_invitation_exists: "Вы уже пригласили этого кандидата по этой потребности. Другим кандидатам можно отправить приглашения.",
      bank_not_admitted: "Проверка навыков временно недоступна. Попробуйте позже.",
      credit_origin_invalid: "Не удалось подтвердить результат этого прохождения. Обратитесь в поддержку.",
      form_exhausted: "Новых вариантов заданий для этого уровня пока нет.",
    };
    const detail = messages[problem.code ?? ""] ?? (
      typeof problem.detail === "string"
        ? problem.detail
        : Array.isArray(problem.detail)
          ? problem.detail.map((item) => item.msg).join("; ")
          : "Запрос не выполнен. Повторите действие.");
    throw new ApiError(result.status, problem.code ?? "request_failed", detail);
  }
  return result;
}

export async function get<T>(path: string): Promise<T> {
  return (await response(path)).json() as Promise<T>;
}

export async function send<T = unknown>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const result = await response(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return result.status === 204
    ? (undefined as T)
    : (result.json() as Promise<T>);
}

async function refresh(): Promise<void> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const result: Schema<"AccessView"> = await send("/auth/refresh");
      accessToken = result.access_token;
    })()
      .catch((error) => {
        accessToken = null;
        throw error;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function restoreSession(): Promise<User | null> {
  if (!csrf()) return null;
  try {
    await refresh();
    return await get<User>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export async function login(email: string, password: string): Promise<User> {
  const result: Schema<"AccessView"> = await send("/auth/login", {
    email,
    password,
  });
  accessToken = result.access_token;
  return get<User>("/auth/me");
}

export async function logout(): Promise<void> {
  await send("/auth/logout");
  accessToken = null;
}

export function clearSession(): void {
  accessToken = null;
}

export async function download(path: string): Promise<void> {
  const blob = await (await response(path)).blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "aggratech-profile.pdf";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
