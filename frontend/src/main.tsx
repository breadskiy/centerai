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
  GitBranch,
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
import { AccountGate, AccountPage, ThemeToggle } from "./account";
import type { SetViewer, Viewer } from "./account";
import { RepositoriesPage } from "./repositories";
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
const EditorPage = React.lazy(() =>
  import("./editor").then((m) => ({ default: m.EditorPage })),
);
const RepositoryEditorPage = React.lazy(() =>
  import("./editor").then((m) => ({ default: m.RepositoryEditorPage })),
);
import "./utilities.css";
import "./style.css";

const nav = [
  ["/", "Главная", LayoutDashboard],
  ["/projects", "Сессии", Folder],
  ["/workflows", "Сценарии", Workflow],
  ["/runs", "Запуски", History],
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
          CenTRap
        </Link>
        <nav aria-label={translateText("Основная навигация")}>
          {nav.map(([url, text, Icon]) => (
            <NavLink key={url} end={url === "/"} to={url}>
              <Icon size={18} />
              <span>{translateText(text)}</span>
            </NavLink>
          ))}
          {viewer.github_login && (
            <NavLink to="/repositories">
              <GitBranch size={18} />
              <span>{translateText("Мои репозитории")}</span>
            </NavLink>
          )}
          <NavLink to="/settings">
            <Settings2 size={18} />
            <span>{translateText("Настройки")}</span>
          </NavLink>
        </nav>
        <div className="account-shortcuts">
          <ThemeToggle />
          <NavLink
            to="/account"
            className="account-link"
            aria-label={translateText("Личный кабинет")}
            title={translateText("Личный кабинет")}
          >
            {viewer.avatar ? (
              <img src={viewer.avatar} alt="" />
            ) : (
              <UserRound size={19} aria-hidden="true" />
            )}
          </NavLink>
        </div>
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
                <Route path="/settings" element={<SettingsPage />} />
                {viewer.github_login && (
                  <>
                    <Route
                      path="/repositories"
                      element={<RepositoriesPage />}
                    />
                    <Route
                      path="/repositories/:id/scenario"
                      element={<RepositoryEditorPage />}
                    />
                  </>
                )}
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
