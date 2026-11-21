import { useState } from "react";
import { Link } from "react-router-dom";
import { api, date, Flow } from "./api";
import { useAction, useNotice } from "./ui";

export function ScheduleSettings({ flows }: { flows: Flow[] }) {
  const scheduled = flows.filter((f) =>
    f.graph.nodes.some((n) => n.type === "schedule_trigger"),
  );
  const [selected, setSelected] = useState("");
  const chosen = scheduled.find((f) => f.id === selected) ?? scheduled[0];
  if (!chosen)
    return (
      <>
        <p>Добавьте узел «Расписание» в редакторе сценария.</p>
        <Link to="/workflows">Открыть сценарии</Link>
      </>
    );
  return (
    <>
      <label>
        Сценарий с расписанием
        <select value={chosen.id} onChange={(e) => setSelected(e.target.value)}>
          {scheduled.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
      </label>
      <ScheduleForm key={chosen.id + chosen.revision} flow={chosen} />
    </>
  );
}
function ScheduleForm({ flow }: { flow: Flow }) {
  const node = flow.graph.nodes.find((n) => n.type === "schedule_trigger")!;
  const { act, busy } = useAction();
  const show = useNotice((s) => s.show);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        const config = {
          cron: form.get("cron"),
          timezone: form.get("zone"),
          enabled: form.has("on"),
        };
        const graph = {
          ...flow.graph,
          nodes: flow.graph.nodes.map((n) =>
            n.id === node.id ? { ...n, config } : n,
          ),
        };
        void act(async () => {
          await api("/workflows/" + flow.id + "/validate", "POST", graph);
          await api("/workflows/" + flow.id, "PUT", { ...flow, graph });
          show("Расписание сохранено");
        });
      }}
    >
      <label>
        Cron
        <input name="cron" required defaultValue={String(node.config.cron)} />
      </label>
      <label>
        Часовой пояс
        <input
          required
          name="zone"
          defaultValue={String(node.config.timezone)}
        />
      </label>
      <label className="check">
        <input
          name="on"
          type="checkbox"
          defaultChecked={Boolean(node.config.enabled)}
        />
        Включено
      </label>
      <small>Следующий запуск · {date(flow.next_due)}</small>
      <button disabled={busy}>Сохранить расписание</button>
    </form>
  );
}
