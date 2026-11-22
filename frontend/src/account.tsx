import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { flushSync } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, LogOut, Moon, Sun, UserRound } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, cache } from "./api";
import bankMark from "./centr-invest.svg";
import { t, useLanguage } from "./locale";
import { useSystemDark, useTheme } from "./theme";

export type Viewer = {
  id: string;
  guest: boolean;
  email: string | null;
  email_verified: boolean;
  email_available: boolean;
  report_recipient: string | null;
  nickname: string;
  avatar: string | null;
  github_login: string | null;
  github_can_unlink: boolean;
  telegram_username: string;
};
export type SetViewer = (viewer: Viewer | null) => void;
const sessionSignal = "centerai-auth-change";
const emailReturnKey = "centerai-email-verification-return";
const emailVerificationHash = /^#verify-email=[A-Za-z0-9_-]{43}$/;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const systemDark = useSystemDark();
  const dark = theme === "dark" || (theme === "system" && systemDark);
  function switchTheme(button: HTMLButtonElement) {
    const next = dark ? "light" : "dark";
    if (
      !document.startViewTransition ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      setTheme(next);
      return;
    }

    const root = document.documentElement;
    if (root.classList.contains("theme-revealing")) return;
    const { left, top, width, height } = button.getBoundingClientRect();
    const x = left + width / 2;
    const y = top + height / 2;
    const radius = Math.hypot(
      Math.max(x, innerWidth - x),
      Math.max(y, innerHeight - y),
    );
    root.style.setProperty("--theme-reveal-origin", `${x}px ${y}px`);
    root.style.setProperty("--theme-reveal-radius", `${radius}px`);
    root.classList.add("theme-revealing");
    const transition = document.startViewTransition(() => {
      flushSync(() => setTheme(next));
    });
    const cleanup = () => {
      root.classList.remove("theme-revealing");
      root.style.removeProperty("--theme-reveal-origin");
      root.style.removeProperty("--theme-reveal-radius");
    };
    void transition.finished.then(cleanup, cleanup);
  }
  return (
    <button
      type="button"
      className="icon theme-toggle"
      aria-label={t("Тёмная тема")}
      aria-pressed={dark}
      title={t(dark ? "Включить светлую тему" : "Включить тёмную тему")}
      onClick={(event) => switchTheme(event.currentTarget)}
    >
      {dark ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
    </button>
  );
}

export function AccountGate({
  children,
}: {
  children: (viewer: Viewer, change: SetViewer) => ReactNode;
}) {
  const navigate = useNavigate();
  useLanguage((state) => state.language);
  const [viewer, setViewer] = useState<Viewer | null>();
  const [error, setError] = useState("");
  const current = useRef<Viewer | null | undefined>(undefined);
  const generation = useRef(0);
  useEffect(() => {
    if (!viewer || viewer.guest) return;
    let hash: string | null;
    try {
      hash = sessionStorage.getItem(emailReturnKey);
      sessionStorage.removeItem(emailReturnKey);
    } catch {
      return;
    }
    if (hash && emailVerificationHash.test(hash))
      navigate({ pathname: "/account", hash }, { replace: true });
  }, [viewer?.id, viewer?.guest, navigate]);
  const update = useCallback<SetViewer>((next) => {
    if (current.current?.id !== next?.id) cache.clear();
    current.current = next;
    setViewer(next);
    setError("");
  }, []);
  const change = useCallback<SetViewer>(
    (next) => {
      generation.current++;
      const changed = current.current?.id !== next?.id;
      update(next);
      if (changed) {
        try {
          localStorage.setItem(sessionSignal, String(Date.now()));
        } catch {}
      }
    },
    [update],
  );
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    try {
      const next = await api<Viewer | null>("/auth/session");
      if (request === generation.current) update(next);
    } catch {
      if (request === generation.current && current.current === undefined)
        setError("Не удалось проверить вход");
    }
  }, [update]);
  useEffect(() => {
    void refresh();
    const visibility = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const storage = (event: StorageEvent) => {
      if (event.key === sessionSignal) void refresh();
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("pageshow", refresh);
    window.addEventListener("storage", storage);
    window.addEventListener("centerai-session-check", refresh);
    return () => {
      generation.current++;
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pageshow", refresh);
      window.removeEventListener("storage", storage);
      window.removeEventListener("centerai-session-check", refresh);
    };
  }, [refresh]);
  useEffect(() => {
    if (!viewer) return;
    const interval = window.setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      if (!viewer.guest) {
        void refresh();
        return;
      }
      const request = generation.current;
      try {
        const next = await api<Viewer>("/auth/keepalive", "POST");
        if (generation.current === request) update(next);
      } catch {
        if (generation.current === request) void refresh();
      }
    }, 60_000);
    return () => window.clearInterval(interval);
  }, [viewer?.id, viewer?.guest, refresh, update]);
  if (viewer === undefined)
    return (
      <div className="loading" role="status">
        {t(error || "Загрузка…")}
        {error && (
          <button type="button" onClick={refresh}>
            {t("Повторить")}
          </button>
        )}
      </div>
    );
  return viewer ? (
    <div key={viewer.id}>{children(viewer, change)}</div>
  ) : (
    <Access enter={change} />
  );
}

function passwordStrength(password: string, email: string) {
  const length = [...password].length;
  const value = password.toLowerCase();
  const letters = value.replace(/[^a-zа-яё]/g, "");
  const local = email.trim().toLowerCase().split("@")[0];
  const sequences = [
    "abcdefghijklmnopqrstuvwxyz",
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    "qwertyuiopasdfghjklzxcvbnm",
    "01234567890123456789",
  ];
  if (
    length < 12 ||
    new Set(value).size < 5 ||
    /^(.+)\1+$/su.test(value) ||
    /^(password|passwd|qwerty|qwertyuiop|admin|letmein|iloveyou|пароль|йцукен|йцукенгшщз|привет)$/.test(
      letters,
    ) ||
    ([...local].length >= 5 && value.includes(local)) ||
    sequences.some(
      (sequence) =>
        sequence.includes(value) ||
        [...sequence].reverse().join("").includes(value),
    )
  )
    return 1;
  if (length >= 18) return 4;
  return length >= 14 ? 3 : 2;
}

function Access({ enter }: { enter: SetViewer }) {
  const { language, setLanguage } = useLanguage();
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const githubResult = params.get("github");
  const github = useQuery({
    queryKey: ["/auth/github/status"],
    queryFn: () => api<{ available: boolean }>("/auth/github/status"),
  });
  const [mode, setMode] = useState<"register" | "login">(
    location.hash.startsWith("#verify-email=") ||
      (githubResult && params.get("mode") !== "register")
      ? "login"
      : "register",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const registering = mode === "register";
  const strength = password ? passwordStrength(password, email) : 0;
  const levels = [
    "Введите пароль",
    "Слабый",
    "Средний",
    "Надёжный",
    "Очень надёжный",
  ];

  const submit = async (action: "register" | "login" | "guest") => {
    if (pending) return;
    if (action === "register" && strength < 2) {
      setError(t("Выберите более надёжный пароль"));
      return;
    }
    setPending(true);
    setError("");
    try {
      const account = await api<Viewer>(
        "/auth/" + action,
        "POST",
        action === "guest" ? undefined : { email: email.trim(), password },
      );
      if (
        action !== "login" ||
        (location.pathname === "/account" &&
          !location.hash.startsWith("#verify-email="))
      )
        navigate("/", { replace: true });
      enter(account);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : t("Не удалось проверить вход"),
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="access">
      <div className="access-controls">
        <ThemeToggle />
      </div>
      <section className="access-intro" aria-labelledby="access-brand">
        <div className="brand" id="access-brand">
          <img className="brandMark" src={bankMark} alt="" />
          CenTRap
        </div>
      </section>
      <section className="access-form" aria-labelledby="access-title">
        <div className="access-switch">
          <button
            type="button"
            aria-pressed={registering}
            disabled={pending}
            onClick={() => {
              setMode("register");
              setPassword("");
              setShow(false);
              setError("");
            }}
          >
            {t("Регистрация")}
          </button>
          <button
            type="button"
            aria-pressed={!registering}
            disabled={pending}
            onClick={() => {
              setMode("login");
              setPassword("");
              setShow(false);
              setError("");
            }}
          >
            {t("Вход в аккаунт")}
          </button>
        </div>
        <h2 id="access-title">
          {t(registering ? "Создайте аккаунт" : "Войдите в аккаунт")}
        </h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit(mode);
          }}
        >
          <label>
            {t("Электронная почта")}
            <input
              required
              type="email"
              name="email"
              autoComplete="username"
              maxLength={254}
              placeholder="name@example.com"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError("");
              }}
              disabled={pending}
            />
          </label>
          <label htmlFor="account-password">{t("Пароль")}</label>
          <div className="access-password">
            <input
              id="account-password"
              required
              type={show ? "text" : "password"}
              maxLength={128}
              autoComplete={registering ? "new-password" : "current-password"}
              aria-describedby={registering ? "password-guidance" : undefined}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError("");
              }}
              disabled={pending}
            />
            <button
              type="button"
              aria-label={t(show ? "Скрыть пароль" : "Показать пароль")}
              onClick={() => setShow(!show)}
            >
              {show ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {registering && (
            <div className="password-guidance" id="password-guidance">
              <div
                className="strength-meter"
                data-strength={strength}
                aria-hidden="true"
              >
                {[1, 2, 3, 4].map((level) => (
                  <span key={level} data-filled={strength >= level} />
                ))}
              </div>
              <strong aria-live="polite">{t(levels[strength])}</strong>
              <small>
                {t(
                  "Минимум 12 символов. Подойдёт длинная фраза из нескольких несвязанных слов.",
                )}
              </small>
            </div>
          )}
          {error && (
            <p role="alert" className="account-error">
              {error}
            </p>
          )}
          <button type="submit" className="primary" disabled={pending}>
            {t(registering ? "Создать аккаунт" : "Войти")}
          </button>
        </form>
        <div className="access-guest">
          {githubResult === "unlinked" && (
            <p role="alert">
              {t(
                "Сначала войдите с почтой и привяжите GitHub в личном кабинете",
              )}
            </p>
          )}
          {githubResult === "existing-email" && (
            <p role="alert">
              {t(
                "Для этой почты уже есть аккаунт CenTRap. Войдите с почтой и привяжите GitHub в личном кабинете.",
              )}
            </p>
          )}
          {githubResult === "email-unavailable" && (
            <p role="alert">
              {t("Для регистрации подтвердите основной email в GitHub.")}
            </p>
          )}
          {(githubResult === "failed" || githubResult === "conflict") && (
            <p role="alert">{t("Не удалось продолжить через GitHub")}</p>
          )}
          <button
            type="button"
            className="access-github"
            disabled={pending || github.isPending}
            onClick={async () => {
              if (!github.data?.available) {
                setError(
                  t(
                    "Для входа через GitHub администратору нужно настроить OAuth на сервере CenTRap.",
                  ),
                );
                return;
              }
              setPending(true);
              setError("");
              try {
                const result = await api<{ url: string }>(
                  "/auth/github/" + (registering ? "register" : "login"),
                  "POST",
                );
                if (emailVerificationHash.test(location.hash)) {
                  try {
                    sessionStorage.setItem(emailReturnKey, location.hash);
                  } catch {}
                }
                window.location.assign(result.url);
              } catch (failure) {
                setError(
                  failure instanceof Error
                    ? failure.message
                    : t("Не удалось продолжить через GitHub"),
                );
                setPending(false);
              }
            }}
          >
            {t(
              registering
                ? "Зарегистрироваться через GitHub"
                : "Войти через GitHub",
            )}
          </button>
          {!github.isPending && !github.data?.available && (
            <p>{t("Подключение GitHub пока не настроено")}</p>
          )}
          <button
            type="button"
            disabled={pending}
            onClick={() => void submit("guest")}
          >
            {t("Продолжить как гость")}
          </button>
          <p>
            {t(
              "История гостя удаляется при выходе или окончании гостевой сессии.",
            )}
          </p>
        </div>
      </section>
      <footer className="access-language">
        <select
          aria-label={t("Язык")}
          value={language}
          onChange={(event) =>
            setLanguage(event.target.value === "en" ? "en" : "ru")
          }
        >
          <option value="ru">Русский</option>
          <option value="en">English</option>
        </select>
      </footer>
    </main>
  );
}

export function AccountPage({
  viewer,
  change,
}: {
  viewer: Viewer;
  change: SetViewer;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const github = useQuery({
    queryKey: ["/auth/github/status"],
    queryFn: () => api<{ available: boolean }>("/auth/github/status"),
    enabled: !viewer.guest,
  });
  const githubResult = new URLSearchParams(location.search).get("github");
  const emailToken = new URLSearchParams(location.hash.slice(1)).get(
    "verify-email",
  );
  const [nickname, setNickname] = useState(viewer.nickname);
  const [username, setUsername] = useState(viewer.telegram_username);
  const [pending, setPending] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [reportsOnly, setReportsOnly] = useState(true);
  const [emailPassword, setEmailPassword] = useState("");
  const [notice, setNotice] = useState<{ text: string; error: boolean }>();
  const run = async (fn: () => Promise<void>) => {
    if (pending) return;
    setNotice(undefined);
    setPending(true);
    try {
      await fn();
    } catch (failure) {
      setNotice({
        text:
          failure instanceof Error
            ? failure.message
            : t("Сервер вернул ошибку"),
        error: true,
      });
    } finally {
      setPending(false);
    }
  };
  const logOut = (confirm: boolean) => {
    if (
      confirm &&
      !window.confirm(t("Завершить гостевую сессию и удалить её данные?"))
    )
      return;
    void run(async () => {
      await api("/auth/logout", "POST");
      navigate("/", { replace: true });
      change(null);
    });
  };
  return (
    <>
      <div className="heading">
        <h1>{t("Личный кабинет")}</h1>
      </div>
      <div className="account-layout" data-guest={viewer.guest}>
        <aside className="panel account-summary">
          <span className="account-avatar">
            {viewer.avatar ? (
              <img src={viewer.avatar} alt="" />
            ) : (
              <UserRound aria-hidden="true" />
            )}
          </span>
          <div className="account-identity">
            <h2>
              {viewer.nickname || t(viewer.guest ? "Гость" : "Пользователь")}
            </h2>
            {viewer.email && <p>{viewer.email}</p>}
          </div>
          {!viewer.guest && (
            <div className="account-actions">
              <label className="avatar-picker">
                {t("Выбрать фото")}
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={pending}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (!file) return;
                    void run(async () => {
                      if (file.size > 2 * 1024 * 1024)
                        throw new Error(
                          t("Фото должно занимать не больше 2 МБ"),
                        );
                      const form = new FormData();
                      form.set("file", file);
                      change(await api<Viewer>("/auth/avatar", "PUT", form));
                    });
                  }}
                />
              </label>
              {viewer.avatar && (
                <button
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    void run(async () => {
                      change(await api<Viewer>("/auth/avatar", "DELETE"));
                    })
                  }
                >
                  {t("Удалить фото")}
                </button>
              )}
            </div>
          )}
          <button
            type="button"
            className="account-sign-out"
            disabled={pending}
            onClick={() => logOut(viewer.guest)}
          >
            <LogOut size={17} />
            {t(
              viewer.guest ? "Завершить гостевую сессию" : "Выйти из аккаунта",
            )}
          </button>
        </aside>
        <div className="account-details">
          {viewer.guest ? (
            <section className="panel account-card">
              <h2>{t("Гостевой режим")}</h2>
              <p>
                {t(
                  "Можно запускать проверки вручную. История и исходники удаляются при выходе или через 30 минут вне активной вкладки. Чтобы сохранять проверки, завершите гостевую сессию и зарегистрируйтесь.",
                )}
              </p>
            </section>
          ) : (
            <>
              <section className="panel account-card">
                <h2>{t("Профиль")}</h2>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void run(async () => {
                      const saved = await api<Viewer>(
                        "/auth/profile",
                        "PATCH",
                        { nickname, telegram_username: username },
                      );
                      setNickname(saved.nickname);
                      setUsername(saved.telegram_username);
                      change(saved);
                      setProfileSaved(true);
                    });
                  }}
                >
                  <label>
                    {t("Никнейм")}
                    <input
                      autoComplete="nickname"
                      maxLength={60}
                      value={nickname}
                      onChange={(e) => {
                        setNickname(e.target.value);
                        setProfileSaved(false);
                      }}
                    />
                  </label>
                  <label>
                    {t("Имя пользователя Telegram")}
                    <input
                      placeholder="@username"
                      maxLength={33}
                      value={username}
                      onChange={(e) => {
                        setUsername(e.target.value);
                        setProfileSaved(false);
                      }}
                    />
                  </label>
                  <div className="account-actions">
                    <button className="primary" disabled={pending}>
                      {t("Сохранить профиль")}
                    </button>
                    {profileSaved && (
                      <span role="status">{t("Профиль сохранён")}</span>
                    )}
                  </div>
                </form>
              </section>
              <section className="panel account-card">
                <h2>{t("Отправка по почте")}</h2>
                <p>
                  {t(
                    viewer.email_verified
                      ? "Почта подтверждена."
                      : "Подтвердите почту, чтобы использовать узел Email.",
                  )}
                </p>
                {emailToken ? (
                  <button
                    type="button"
                    disabled={pending}
                    onClick={() =>
                      void run(async () => {
                        const account = await api<Viewer>(
                          "/auth/email/verify",
                          "POST",
                          { token: emailToken },
                        );
                        change(account);
                        await cache.invalidateQueries({
                          queryKey: ["/registry"],
                        });
                        navigate(
                          { pathname: "/account", search: location.search },
                          { replace: true },
                        );
                        setNotice({
                          text: t(
                            account.report_recipient !== viewer.report_recipient
                              ? "Адрес для отчётов подтверждён."
                              : "Почта подтверждена.",
                          ),
                          error: false,
                        });
                      })
                    }
                  >
                    {t("Подтвердить адрес")}
                  </button>
                ) : viewer.email_available ? (
                  <>
                    {!viewer.email_verified && (
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() =>
                          void run(async () => {
                            await api("/auth/email/verification", "POST", {});
                            setNotice({
                              text: t(
                                "Письмо отправлено. Откройте ссылку из письма.",
                              ),
                              error: false,
                            });
                          })
                        }
                      >
                        {t("Отправить письмо для подтверждения")}
                      </button>
                    )}
                    <details>
                      <summary>{t("Добавить или изменить адрес")}</summary>
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          void run(async () => {
                            await api("/auth/email/verification", "POST", {
                              email: newEmail,
                              password: emailPassword,
                              reports_only: reportsOnly,
                            });
                            setEmailPassword("");
                            setNotice({
                              text: t(
                                "Подтвердите новый адрес по ссылке из письма.",
                              ),
                              error: false,
                            });
                          });
                        }}
                      >
                        <label className="check">
                          <input
                            type="checkbox"
                            checked={reportsOnly}
                            onChange={(event) =>
                              setReportsOnly(event.target.checked)
                            }
                          />
                          {t("Использовать только для отчётов")}
                        </label>
                        <label>
                          {t("Новый адрес почты")}
                          <input
                            type="email"
                            required
                            maxLength={254}
                            autoComplete="email"
                            value={newEmail}
                            onChange={(event) =>
                              setNewEmail(event.target.value)
                            }
                          />
                        </label>
                        {viewer.github_can_unlink && (
                          <label>
                            {t("Текущий пароль")}
                            <input
                              type="password"
                              required
                              maxLength={128}
                              autoComplete="current-password"
                              value={emailPassword}
                              onChange={(event) =>
                                setEmailPassword(event.target.value)
                              }
                            />
                          </label>
                        )}
                        <button type="submit" disabled={pending}>
                          {t("Отправить письмо для подтверждения")}
                        </button>
                      </form>
                    </details>
                  </>
                ) : (
                  <p>{t("Почтовый сервер не настроен.")}</p>
                )}
                {viewer.report_recipient && (
                  <div className="account-actions">
                    <span>
                      {t("Дополнительный адрес для отчётов")}
                      {": "}
                      {viewer.report_recipient}
                    </span>
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() =>
                        void run(async () => {
                          change(
                            await api<Viewer>(
                              "/auth/email/report-recipient",
                              "DELETE",
                            ),
                          );
                          await cache.invalidateQueries({
                            queryKey: ["/registry"],
                          });
                        })
                      }
                    >
                      {t("Удалить адрес для отчётов")}
                    </button>
                  </div>
                )}
              </section>
              <section className="panel account-card">
                <h2>GitHub</h2>
                {githubResult === "linked" && (
                  <p role="status">{t("Аккаунт GitHub привязан")}</p>
                )}
                {githubResult === "failed" && (
                  <p role="alert">{t("Не удалось подключиться к GitHub")}</p>
                )}
                {githubResult === "conflict" && (
                  <p role="alert">
                    {t(
                      "Этот аккаунт GitHub уже привязан или сначала нужно отвязать текущий",
                    )}
                  </p>
                )}
                {viewer.github_login ? (
                  <>
                    <p>@{viewer.github_login}</p>
                    <button
                      type="button"
                      disabled={pending || !viewer.github_can_unlink}
                      onClick={() =>
                        void run(async () => {
                          await api("/auth/github/link", "DELETE");
                          navigate("/account", { replace: true });
                          change({ ...viewer, github_login: null });
                        })
                      }
                    >
                      {t("Отвязать GitHub")}
                    </button>
                    {!viewer.github_can_unlink && (
                      <p>
                        {t("GitHub используется как единственный способ входа")}
                      </p>
                    )}
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      disabled={pending || github.isPending}
                      onClick={() =>
                        void run(async () => {
                          if (!github.data?.available) {
                            throw new Error(
                              t(
                                "Для входа через GitHub администратору нужно настроить OAuth на сервере CenTRap.",
                              ),
                            );
                          }
                          const result = await api<{ url: string }>(
                            "/auth/github/link",
                            "POST",
                          );
                          window.location.assign(result.url);
                        })
                      }
                    >
                      {t("Привязать GitHub")}
                    </button>
                    {!github.isPending && !github.data?.available && (
                      <p>{t("Подключение GitHub пока не настроено")}</p>
                    )}
                  </>
                )}
              </section>
            </>
          )}
          {notice && (
            <p
              role={notice.error ? "alert" : "status"}
              className={notice.error ? "account-error" : "account-notice"}
            >
              {notice.text}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
