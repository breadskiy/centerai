import { t as translateText, useLanguage } from "./locale";
import React, { Suspense } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  Folder,
  History,
  LayoutDashboard,
  Settings2,
  UserRound,
  Workflow,
} from "lucide-react";
import "@fontsource/ibm-plex-sans/cyrillic-400.css";
import "@fontsource/ibm-plex-sans/cyrillic-600.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import bankMark from "./centr-invest.svg";
import { cache } from "./api";
import { Boundary, Toast } from "./ui";
import { AccountGate, AccountPage } from "./account";
import type { SetViewer, Viewer } from "./account";
import {
  Dashboard,
  Projects,
  ProjectDetail,
  Workflows,
  SettingsPage,
} from "./workspace";
const HistoryPage = React.lazy(() =>
  import("./results").then((m) => ({ default: m.HistoryPage })),
);
const Monitor = React.lazy(() =>
  import("./results").then((m) => ({ default: m.Monitor })),
);
const FindingsPage = React.lazy(() =>
  import("./results").then((m) => ({ default: m.FindingsPage })),
);
const EditorPage = React.lazy(() =>
  import("./editor").then((m) => ({ default: m.EditorPage })),
);
import "./utilities.css";
import "./style.css";

const nav = [
  ["/", "Главная", LayoutDashboard],
  ["/projects", "Сессии", Folder],
  ["/workflows", "Сценарии", Workflow],
  ["/runs", "Запуски", History],
  ["/settings", "Настройки", Settings2],
] as const;
function Shell({ viewer, change }: { viewer: Viewer; change: SetViewer }) {
  const location = useLocation();
  const language = useLanguage((state) => state.language);
  return (
    <div className="shell">
      <aside className="side">
        <Link className="brand" to="/">
          <img
            className="brandMark"
            src={bankMark}
            alt={translateText("Центр-инвест")}
          />
          CenterAI
        </Link>
        <nav aria-label={translateText("Основная навигация")}>
          {nav.map(([url, text, Icon]) => (
            <NavLink key={url} end={url === "/"} to={url}>
              <Icon size={18} />
              <span>{translateText(text)}</span>
            </NavLink>
          ))}
        </nav>
        <NavLink
          to="/account"
          className="account-link"
          aria-label={translateText("Личный кабинет")}
          title={translateText("Личный кабинет")}
        >
          {viewer.avatar ? <img src={viewer.avatar} alt="" /> : <UserRound size={19} />}
          <span>
            <strong>{translateText("Личный кабинет")}</strong>
            <small>
              {viewer.nickname || viewer.email || translateText("Гость")}
            </small>
          </span>
        </NavLink>
      </aside>
      <div className="content">
        <main>
          <Boundary key={language + location.pathname}>
            <Suspense
              fallback={
                <div className="loading" role="status">
                  {translateText("Загрузка…")}
                </div>
              }
            >
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/projects" element={<Projects />} />
                <Route path="/projects/:id" element={<ProjectDetail />} />
                <Route path="/workflows" element={<Workflows />} />
                <Route path="/workflows/:id" element={<EditorPage />} />
                <Route path="/runs" element={<HistoryPage />} />
                <Route path="/runs/:id" element={<Monitor />} />
                <Route path="/findings" element={<FindingsPage />} />
                <Route path="/findings/:sessionId" element={<FindingsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route
                  path="/account"
                  element={<AccountPage viewer={viewer} change={change} />}
                />
                <Route
                  path="*"
                  element={<Link to="/">{translateText("На главную")}</Link>}
                />
              </Routes>
            </Suspense>
          </Boundary>
        </main>
      </div>
      <Toast />
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={cache}>
      <BrowserRouter>
        <AccountGate>
          {(viewer, change) => <Shell viewer={viewer} change={change} />}
        </AccountGate>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
