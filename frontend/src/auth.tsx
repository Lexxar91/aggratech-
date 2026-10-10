import { useContext } from "react";
import { clearSession, get, login, send } from "./api";
import type { Schema } from "./api";
import {
  Field,
  Form,
  Heading,
  Link,
  Notice,
  SessionContext,
  useFeedback,
  value,
} from "./ui";

export function AuthPage({ route, token }: { route: string; token?: string }) {
  const { user, setUser } = useContext(SessionContext);
  const feedback = useFeedback();
  const register = route === "register";
  if (route === "verify")
    return (
      <div className="auth-card">
        <Heading
          title="Подтверждение email"
          subtitle="Подтверждение разрешает действия с профилем и прохождение assessment."
        />
        <Form
          label="Подтвердить email"
          onSubmit={async () => {
            await send("/auth/verify-email", { token });
            if (user) setUser(await get("/auth/me"));
            feedback("Email подтверждён.");
            location.hash = user ? "#profile" : "#login";
          }}
        >
          <Notice>Нажмите кнопку, чтобы подтвердить адрес из письма.</Notice>
        </Form>
      </div>
    );
  if (route === "reset-request")
    return (
      <div className="auth-card">
        <Heading title="Восстановление пароля" />
        <Form
          label="Отправить ссылку"
          onSubmit={async (data) => {
            const result: Schema<"MessageView"> = await send(
              "/auth/password-reset/request",
              { email: value(data, "reset_email") },
            );
            feedback(result.detail);
          }}
        >
          <Field name="reset_email" label="Email" type="email" required />
        </Form>
        <Link to="login">Вернуться ко входу</Link>
      </div>
    );
  if (route === "reset")
    return (
      <div className="auth-card">
        <Heading title="Новый пароль" />
        <Form
          label="Изменить пароль"
          onSubmit={async (data) => {
            await send("/auth/password-reset/confirm", {
              token,
              password: String(data.get("new_password") ?? ""),
            });
            clearSession();
            setUser(null);
            feedback("Пароль изменён. Войдите снова.");
            location.hash = "#login";
          }}
        >
          <Field
            name="new_password"
            label="Новый пароль (от 12 символов)"
            type="password"
            required
          />
        </Form>
      </div>
    );
  return (
    <div className="auth-layout">
      <div className="auth-intro">
        <p className="eyebrow">НАВЫКИ. УСЛОВИЯ. СОГЛАСИЕ.</p>
        <h2>
          Следующий шаг
          <br />в вашей карьере.
        </h2>
        <p>
          Профиль, понятная проверка навыков и общение с работодателем на ваших
          условиях.
        </p>
        <Notice warning>
          Хакатонное приложение. Демонстрационные результаты не
          подтверждают квалификацию.
        </Notice>
      </div>
      <div className="auth-card">
        <Heading
          title={register ? "Регистрация" : "Вход"}
          subtitle="Рады видеть вас в Aggratech"
        />
        <Form
          label={register ? "Зарегистрироваться" : "Войти"}
          onSubmit={async (data) => {
            const email = value(data, "email"),
              password = String(data.get("password") ?? "");
            if (register) {
              await send("/auth/register", {
                email,
                password,
                role: value(data, "role"),
              });
              feedback("Аккаунт создан. Письмо подтверждения отправлено.");
            }
            setUser(await login(email, password));
            location.hash = "#profile";
          }}
        >
          <Field name="email" label="Email" type="email" required />
          <Field
            name="password"
            label="Пароль (от 12 символов)"
            type="password"
            required
          />
          {register && (
            <Field name="role" label="Роль" value="candidate">
              <option value="candidate">Кандидат</option>
              <option value="employer">Работодатель</option>
            </Field>
          )}
        </Form>
        <div className="actions">
          <Link to={register ? "login" : "register"}>
            {register ? "Уже есть аккаунт" : "Создать аккаунт"}
          </Link>
          <Link to="reset-request">Восстановить пароль</Link>
        </div>
      </div>
    </div>
  );
}
