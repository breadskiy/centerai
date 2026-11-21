import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Eye,
  EyeOff,
  FolderGit2,
  History,
  LogOut,
  UserRound,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, cache } from "./api";
import bankMark from "./centr-invest.svg";
import { t, useLanguage } from "./locale";

export type Viewer = {
  id: string;
  guest: boolean;
  email: string | null;
  nickname: string;
  avatar: string | null;
  telegram_username: string;
  telegram_connected: boolean;
};
export type SetViewer = (viewer: Viewer | null) => void;
const sessionSignal = "centerai-auth-change";

export function AccountGate({
  children,
}: {
  children: (viewer: Viewer, change: SetViewer) => ReactNode;
}) {
  useLanguage((state) => state.language);
  const [viewer, setViewer] = useState<Viewer | null>();
  const [error, setError] = useState("");
  const current = useRef<Viewer | null | undefined>(undefined);
  const generation = useRef(0);
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

function passwordStrength(password: string) {
  if ([...password].length < 8 || !password.trim()) return 1;
  if (!/\p{L}/u.test(password) || !/[0-9]/.test(password)) return 2;
  return /[\p{P}\p{S}]/u.test(password) ? 4 : 3;
}

function Access({ enter }: { enter: SetViewer }) {
  const [mode, setMode] = useState<"register" | "login">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const registering = mode === "register";
  const strength = password ? passwordStrength(password) : 0;
  const levels = [
    "Введите пароль",
    "Слабый",
    "Средний",
    "Надёжный",
    "Очень надёжный",
  ];

  const submit = async (action: "register" | "login" | "guest") => {
    if (pending) return;
    if (action === "register" && strength < 3) {
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
      if (action !== "login" || location.pathname === "/account")
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
      <section className="access-intro" aria-labelledby="access-brand">
        <div className="brand" id="access-brand">
          <img className="brandMark" src={bankMark} alt="" />
          CenterAI
        </div>
        <div className="access-copy">
          <h1>{t("Проверка Kotlin-репозиториев")}</h1>
          <p>
            {t(
              "Загружайте исходники, запускайте проверки и возвращайтесь к результатам в своём кабинете.",
            )}
          </p>
          <div className="access-flow" aria-hidden="true">
            <span>
              <FolderGit2 size={20} />
            </span>
            <i />
            <span>
              <History size={20} />
            </span>
          </div>
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
                  "Минимум 8 символов, включая буквы и цифры. Спецсимволы повышают надёжность.",
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
  const [nickname, setNickname] = useState(viewer.nickname);
  const [username, setUsername] = useState(viewer.telegram_username);
  const [token, setToken] = useState("");
  const [chat, setChat] = useState("");
  const [pending, setPending] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);
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
  const disconnect = async () => {
    await api("/integrations/telegram", "DELETE");
    change({ ...viewer, telegram_connected: false });
    setNotice({ text: t("Telegram отключён"), error: false });
  };
  const saveTelegram = async (event: FormEvent) => {
    event.preventDefault();
    await run(async () => {
      await api("/integrations/telegram", "PUT", {
        token: token.trim(),
        chat: chat.trim(),
      });
      change({ ...viewer, telegram_connected: true });
      setToken("");
      setChat("");
      setNotice({ text: t("Настройки Telegram сохранены"), error: false });
    });
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
      <div className="account-layout">
        <aside className="panel account-summary">
          <span className="account-avatar">
            {viewer.avatar ? <img src={viewer.avatar} alt="" /> : <UserRound size={24} />}
          </span>
          {!viewer.guest && <div className="account-actions">
            <label className="avatar-picker">
              {t("Выбрать фото")}
              <input type="file" accept="image/jpeg,image/png,image/webp" disabled={pending}
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (!file) return;
                  void run(async () => {
                    if (file.size > 2 * 1024 * 1024)
                      throw new Error(t("Фото должно занимать не больше 2 МБ"));
                    const form = new FormData();
                    form.set("file", file);
                    change(await api<Viewer>("/auth/avatar", "PUT", form));
                  });
                }} />
            </label>
            {viewer.avatar && <button type="button" disabled={pending} onClick={() => void run(async () => {
              change(await api<Viewer>("/auth/avatar", "DELETE"));
            })}>{t("Удалить фото")}</button>}
          </div>}
          <div>
            <h2>
              {viewer.nickname || t(viewer.guest ? "Гость" : "Пользователь")}
            </h2>
            {viewer.email && <p>{viewer.email}</p>}
          </div>
          <button
            type="button"
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
                <h2>{t("Уведомления в Telegram")}</h2>
                <p>
                  {t(
                    viewer.telegram_connected
                      ? "Бот подключён. Он отправляет отчёты из сценариев с узлом Telegram."
                      : "Подключите бота для сценариев, которые отправляют отчёты в Telegram.",
                  )}
                </p>
                <form onSubmit={saveTelegram}>
                  <label>
                    {t("Токен бота")}
                    <input
                      type="password"
                      autoComplete="off"
                      required={!viewer.telegram_connected}
                      maxLength={128}
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                      placeholder={
                        viewer.telegram_connected
                          ? t("Сохранённый токен")
                          : undefined
                      }
                    />
                  </label>
                  <label>
                    {t("ID чата")}
                    <input
                      required
                      maxLength={34}
                      value={chat}
                      onChange={(e) => setChat(e.target.value)}
                    />
                  </label>
                  <div className="account-actions">
                    <button type="submit" disabled={pending}>
                      {t("Сохранить подключение")}
                    </button>
                    {viewer.telegram_connected && (
                      <>
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() =>
                            void run(async () => {
                              await api("/integrations/telegram/test", "POST");
                              setNotice({
                                text: t("Проверочное сообщение отправлено"),
                                error: false,
                              });
                            })
                          }
                        >
                          {t("Отправить тест")}
                        </button>
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() => void run(disconnect)}
                        >
                          {t("Отключить")}
                        </button>
                      </>
                    )}
                  </div>
                </form>
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
