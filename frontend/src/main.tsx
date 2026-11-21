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
  ScanLine,
  Settings2,
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
  ["/projects", "Проекты", Folder],
  ["/workflows", "Сценарии", Workflow],
  ["/runs", "Запуски", History],
  ["/findings", "Находки", ScanLine],
  ["/settings", "Настройки", Settings2],
] as const;
function Shell() {
  const location = useLocation();
  return (
    <div className="shell">
      <aside className="side">
        <Link className="brand" to="/">
          <img className="brandMark" src={bankMark} alt="Центр-инвест" />
          CenterAI
        </Link>
        <nav aria-label="Основная навигация">
          {nav.map(([url, text, Icon]) => (
            <NavLink key={url} end={url === "/"} to={url}>
              <Icon size={18} />
              <span>{text}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="content">
        <main>
          <Boundary key={location.pathname}>
            <Suspense
              fallback={
                <div className="loading" role="status">
                  Загрузка…
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
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<Link to="/">На главную</Link>} />
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
        <Shell />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
