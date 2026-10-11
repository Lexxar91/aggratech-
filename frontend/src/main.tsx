import { Component, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { get, logout, restoreSession, send } from "./api";
import type { User } from "./api";
import { AuthPage } from "./auth";
import { AssessmentPage } from "./assessment";
import {
  ApplicationPage,
  ApplicationsPage,
  InvitationOffer,
  InvitationsPage,
  VacanciesPage,
  VacancyEditor,
  VacancyPage,
} from "./communications";
import { NeedsPage, RecommendationsPage } from "./matching";
import { CandidateProfile, EmployerProfile, FspPage } from "./profiles";
import {
  Action,
  Badge,
  FeedbackContext,
  Heading,
  Link,
  Loading,
  Notice,
  Section,
  SessionContext,
  errorText,
} from "./ui";
import "./styles.css";
import fspLogo from "./assets/brand/fsp-logo.svg";

class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    /* Не выводим данные пользователя в консоль. */
  }
  render() {
    return this.state.failed ? (
      <Notice warning>
        Не удалось показать экран.{" "}
        <button onClick={() => location.reload()}>
          Перезагрузить страницу
        </button>
      </Notice>
    ) : (
      this.props.children
    );
  }
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [starting, setStarting] = useState(true);
  const [startupError, setStartupError] = useState("");
  const [hash, setHash] = useState(location.hash.slice(1) || "home");
  const [feedback, setFeedback] = useState({ text: "", error: false });
  useEffect(() => {
    const change = () => {
      setHash(location.hash.slice(1) || "home");
      setFeedback((current) =>
        current.error ? { text: "", error: false } : current,
      );
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    let active = true;
    restoreSession()
      .then((value) => {
        if (active) setUser(value);
      })
      .catch((error) => {
        if (active) setStartupError(errorText(error));
      })
      .finally(() => {
        if (active) setStarting(false);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    document.querySelector<HTMLElement>("#content")?.focus();
  }, [hash]);
  const [route, id, candidateId] = hash.split("/");
  const candidate = user?.role === "candidate";
  const guestRoutes = [
    "home",
    "login",
    "register",
    "verify",
    "reset",
    "reset-request",
    "vacancies",
    "vacancy",
  ];
  useEffect(() => {
    if (!starting && !startupError && !user && !guestRoutes.includes(route))
      location.hash = "#login";
  }, [starting, startupError, user, route]); // eslint-disable-line react-hooks/exhaustive-deps
  const navigation = candidate
    ? [
        ["profile", "Профиль и приватность"],
        ["assessment", "Проверка навыков и история"],
        ["vacancies", "Вакансии"],
        ["applications", "Мои отклики"],
        ["invitations", "Предложения от компаний"],
        ["fsp", "Достижения ФСП"],
      ]
    : [
        ["profile", "Компания"],
        ["needs", "Потребности и подбор"],
        ["invitations", "Отправленные приглашения"],
        ["vacancies", "Мои вакансии"],
      ];
  function screen(): ReactNode {
    if (
      ["login", "register", "verify", "reset", "reset-request"].includes(route)
    )
      return <AuthPage route={route} token={decodeURIComponent(id ?? "")} />;
    if (route === "home")
      return (
        <>
          <Heading
            title="Работа начинается с понятных условий."
            subtitle="Aggratech объединяет профиль, проверку навыков и общение по согласию."
          />
          <div className="card-grid">
            <Section title="Кандидату">
              <p>
                Сохраните профиль, подтвердите навыки, откликнитесь на
                вакансию и выберите, кому показать контакты.
              </p>
              <Link primary to={user ? "profile" : "register"}>
                Открыть кабинет
              </Link>
            </Section>
            <Section title="Работодателю">
              <p>
                Опишите потребность, сравнивайте доступных кандидатов и
                отправляйте предложения с обязательной зарплатой.
              </p>
              <Link to={user ? "profile" : "register"}>Начать работу</Link>
            </Section>
          </div>
          <Notice>
            Вы управляете своими контактами. Компания увидит их только после
            вашего согласия, которое можно отозвать.
          </Notice>
        </>
      );
    if (route === "vacancies") return <VacanciesPage />;
    if (route === "vacancy" && id) return <VacancyPage id={id} />;
    if (!user) return <Loading />;
    if (["profile", "candidate", "employer"].includes(route))
      return candidate ? <CandidateProfile /> : <EmployerProfile />;
    if (route === "invitations") return <InvitationsPage id={id} />;
    if (route === "application" && id) return <ApplicationPage id={id} />;
    if (route === "applications" && (candidate || id))
      return <ApplicationsPage vacancyId={id} />;
    if (candidate && route === "assessment") return <AssessmentPage id={id} />;
    if (candidate && route === "fsp") return <FspPage />;
    if (!candidate && route === "needs") return <NeedsPage id={id} />;
    if (!candidate && route === "recommendations" && id)
      return <RecommendationsPage id={id} />;
    if (!candidate && route === "offer" && id && candidateId)
      return <InvitationOffer needId={id} candidateId={candidateId} />;
    if (!candidate && route === "vacancy-edit")
      return <VacancyEditor id={id} />;
    return (
      <>
        <Heading title="Раздел недоступен" />
        <Notice>Проверьте ссылку и роль аккаунта.</Notice>
        <Link to="profile">В кабинет</Link>
      </>
    );
  }
  return (
    <SessionContext.Provider value={{ user, setUser }}>
      <FeedbackContext.Provider
        value={(text, error = false) => setFeedback({ text, error })}
      >
        <a
          className="skip-link"
          href="#content"
          onClick={(event) => {
            event.preventDefault();
            document.getElementById("content")?.focus();
          }}
        >
          Перейти к содержимому
        </a>
        <header className="topbar">
          <a className="brand" href="#home">
            <img className="brand-logo" src={fspLogo} alt="Федерация спортивного программирования" />
            <span className="brand-name">aggratech<span className="brand-sub">НАВЫКИ И КАРЬЕРА</span></span>
          </a>
          <div className="topbar-actions">
            <Badge>Навыки и карьера</Badge>
            {user ? (
              <Action
                onClick={async () => {
                  await logout();
                  setUser(null);
                  location.hash = "#login";
                }}
              >
                Выйти
              </Action>
            ) : (
              <Link to="login">Войти в кабинет</Link>
            )}
          </div>
        </header>
        <div className={user ? "app-layout" : "guest-layout"}>
          {user && (
            <aside className="sidebar">
              <div className="account">
                <div className="avatar" aria-hidden="true">
                  {candidate ? "К" : "Р"}
                </div>
                <div>
                  <strong>{candidate ? "Кандидат" : "Работодатель"}</strong>
                  <small>{user.email}</small>
                </div>
              </div>
              <nav aria-label="Разделы кабинета">
                {navigation.map(([to, label], index) => (
                  <a
                    key={to}
                    href={`#${to}`}
                    aria-current={route === to ? "page" : undefined}
                  >
                    <span aria-hidden="true">0{index + 1}</span>
                    {label}
                  </a>
                ))}
              </nav>
              <div className="sidebar-note">
                <span className="dot" />
                Контакты под вашим контролем
                <p>Доступ открывается по согласию и может быть отозван.</p>
              </div>
            </aside>
          )}
          <main id="content" tabIndex={-1}>
            <p
              id="feedback"
              role={feedback.error ? "alert" : "status"}
              aria-live="polite"
              className={
                feedback.text
                  ? `feedback ${feedback.error ? "error" : "success"}`
                  : "feedback hidden"
              }
            >
              {feedback.text}
            </p>
            {user && !user.email_verified && (
              <Notice warning>
                Подтвердите email по ссылке из письма.{" "}
                <Action
                  onClick={async () => {
                    await send("/auth/resend-verification", {
                      email: user.email,
                    });
                    setFeedback({
                      text: "Письмо подтверждения отправлено.",
                      error: false,
                    });
                  }}
                >
                  Отправить письмо повторно
                </Action>
                <Action
                  onClick={async () => setUser(await get<User>("/auth/me"))}
                >
                  Проверить подтверждение
                </Action>
              </Notice>
            )}
            {starting ? (
              <Loading />
            ) : startupError ? (
              <Notice warning>
                {startupError}
                <Action onClick={() => location.reload()}>Повторить</Action>
              </Notice>
            ) : (
              <ErrorBoundary key={`${hash}-${user?.id ?? "guest"}`}>
                {screen()}
              </ErrorBoundary>
            )}
            <footer>
              Aggratech · Проверенные навыки. Прозрачные условия. Контакты под вашим контролем.
            </footer>
          </main>
        </div>
      </FeedbackContext.Provider>
    </SessionContext.Provider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
