import { Component, ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
  Activity,
  Check,
  ChevronRight,
  Clock3,
  FolderArchive,
  Layers3,
  ScanLine,
  Workflow,
  X,
} from "lucide-react";
import { create } from "zustand";
import { Run, date, duration, cache } from "./api";

type Notice = { text: string; bad: boolean };
export const useNotice = create<{
  notice: Notice | null;
  show: (text: string, bad?: boolean) => void;
  clear: () => void;
}>((set) => ({
  notice: null,
  show: (text, bad = false) => set({ notice: { text, bad } }),
  clear: () => set({ notice: null }),
}));
export function Toast() {
  const { notice, clear } = useNotice();
  useEffect(() => {
    if (notice) {
      const t = setTimeout(clear, 6500);
      return () => clearTimeout(t);
    }
  }, [notice, clear]);
  return (
    notice &&
    createPortal(
      <div role="status" className={"toast " + (notice.bad ? "bad" : "")}>
        <span>{notice.text}</span>
        <button aria-label="Закрыть сообщение" onClick={clear}>
          <X size={16} />
        </button>
      </div>,
      document.querySelector("dialog[open]") ?? document.body,
    )
  );
}
export function useAction() {
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const show = useNotice((s) => s.show);
  return {
    busy,
    act: async (fn: () => Promise<void>) => {
      if (lock.current) return;
      lock.current = true;
      setBusy(true);
      try {
        await fn();
        await cache.invalidateQueries();
      } catch (e) {
        show(e instanceof Error ? e.message : "Ошибка операции", true);
      } finally {
        lock.current = false;
        setBusy(false);
      }
    },
  };
}
export function Heading({
  title,
  sub,
  action,
}: {
  title: string;
  sub?: string;
  action?: ReactNode;
}) {
  return (
    <header className="heading">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {action}
    </header>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="emptyicon">
        <Layers3 size={22} />
      </div>
      <strong>{title}</strong>
      {children && <div>{children}</div>}
    </div>
  );
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={close}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
    >
      <div className="dialogHead">
        <h2>{title}</h2>
        <button className="icon" aria-label="Закрыть" onClick={close}>
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
const names: Record<string, string> = {
  queued: "В очереди",
  running: "Выполняется",
  success: "Завершён",
  failed: "Ошибка",
  pending: "Ожидание",
  skipped: "Пропущен",
  cancelled: "Отменён",
};
export function Status({ value }: { value: string | null }) {
  return (
    <span className={"status " + (value || "pending")}>
      {value === "success" ? (
        <Check size={13} />
      ) : value === "running" ? (
        <Activity size={13} />
      ) : (
        <i />
      )}
      {value ? names[value] || value : "Без запусков"}
    </span>
  );
}
export function Severity({ value }: { value: string }) {
  return <span className={"severity " + value}>{value}</span>;
}
export function RunsTable({
  rows,
  compact = false,
}: {
  rows: Run[];
  compact?: boolean;
}) {
  return rows.length ? (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            <th>Сценарий / проект</th>
            <th>Статус</th>
            <th>Время запуска</th>
            {!compact && <th>Длительность</th>}
            <th>{compact ? "Критичность" : "Находки"}</th>
            {!compact && <th />}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>
                <Link to={"/runs/" + r.id}>
                  <b>{r.workflow_name}</b>
                </Link>
                <small>{r.project_name}</small>
              </td>
              <td>
                <Status value={r.status} />
              </td>
              <td>{date(r.created)}</td>
              {!compact && <td className="mono">{duration(r)}</td>}
              <td className="mono">
                {compact ? (
                  <div className="run-risk">
                    {["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].flatMap(
                      (level) =>
                        r.levels?.[level]
                          ? [
                              <span key={level}>
                                <Severity value={level} /> {r.levels[level]}
                              </span>,
                            ]
                          : [],
                    )}
                    {!r.count && "—"}
                  </div>
                ) : (
                  r.count
                )}
              </td>
              {!compact && (
                <td>
                  <Link aria-label="Открыть запуск" to={"/runs/" + r.id}>
                    <ChevronRight size={16} />
                  </Link>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty title="История запусков пуста">
      Здесь появятся этапы и результаты первой проверки.
    </Empty>
  );
}
export const icons: Record<string, typeof Workflow> = {
  manual_trigger: Activity,
  schedule_trigger: Clock3,
  repository_source: FolderArchive,
  secrets_scanner: ScanLine,
  sca_scanner: Layers3,
  sast_scanner: Workflow,
};
export class Boundary extends Component<
  { children: ReactNode },
  { error: string }
> {
  state = { error: "" };
  static getDerivedStateFromError(e: Error) {
    return { error: e.message };
  }
  render() {
    return this.state.error ? (
      <section className="panel empty" role="alert">
        <h2>Не удалось открыть раздел</h2>
        <p>{this.state.error}</p>
        <button onClick={() => location.reload()}>Повторить загрузку</button>
      </section>
    ) : (
      this.props.children
    );
  }
}
