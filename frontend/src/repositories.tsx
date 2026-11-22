import { useMutation, useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, cache, date } from "./api";
import { t } from "./locale";
import { Heading } from "./ui";

type Repository = {
  id: string;
  name: string;
  branch: string;
  archived: boolean;
  owner: boolean;
};
type Watch = {
  enabled: boolean;
  sha: string | null;
  head_sha: string | null;
  head_committed_at: number | null;
  profile: string;
  scan_profile: string;
  scenario_revision: number;
  scan_scenario_revision: number;
  branch: string;
  error: string | null;
  run_id: string | null;
  status: string | null;
  count: number | null;
};

const endpoint = "/github-repositories";
const watchesEndpoint = endpoint + "/watches";

export function RepositoriesPage() {
  const [search, setSearch] = useSearchParams();
  const requestedPage = Number(search.get("page"));
  const page =
    Number.isInteger(requestedPage) &&
    requestedPage >= 1 &&
    requestedPage <= 1000
      ? requestedPage
      : 1;
  function setPage(next: number) {
    setSearch(next === 1 ? {} : { page: String(next) });
  }
  const list = useQuery({
    queryKey: [endpoint, page],
    queryFn: () =>
      api<{
        items: Repository[];
        has_more: boolean;
        needs_github_login: boolean;
      }>(endpoint + "?page=" + page),
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const watches = useQuery({
    queryKey: [watchesEndpoint],
    queryFn: () => api<Record<string, Watch>>(watchesEndpoint),
    refetchInterval: 5000,
  });
  const saveWatch = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api(endpoint + "/" + id + "/watch", "PUT", { enabled, page }),
    onSuccess: () => cache.invalidateQueries({ queryKey: [watchesEndpoint] }),
  });
  const renewAccess = useMutation({
    mutationFn: () =>
      api<{ url: string }>(
        "/auth/github/link?return_to_repositories=true",
        "POST",
      ),
    onSuccess: ({ url }) => window.location.assign(url),
  });
  const error =
    list.error ?? watches.error ?? saveWatch.error ?? renewAccess.error;

  return (
    <>
      <Heading
        title={t("Мои репозитории")}
        sub={t(
          "CenterAI проверяет новые коммиты основной ветки публичных репозиториев, пока сервер запущен.",
        )}
        action={
          <button
            type="button"
            disabled={list.isFetching}
            onClick={() => {
              void cache.invalidateQueries({ queryKey: [endpoint] });
              void cache.invalidateQueries({ queryKey: [watchesEndpoint] });
            }}
          >
            <RefreshCw size={16} aria-hidden="true" />
            {t(list.isFetching ? "Обновляем…" : "Обновить")}
          </button>
        }
      />
      {error && <p role="alert">{error.message}</p>}
      {list.data?.needs_github_login && (
        <div className="account-actions">
          <p>
            {t(
              "Подтвердите доступ GitHub, чтобы увидеть репозитории, где вы соавтор.",
            )}
          </p>
          <button
            type="button"
            disabled={renewAccess.isPending}
            onClick={() => renewAccess.mutate()}
          >
            {t("Подтвердить доступ GitHub")}
          </button>
        </div>
      )}
      {list.isPending && <p role="status">{t("Загрузка…")}</p>}
      {list.data?.items.length === 0 && (
        <p>{t("Публичных репозиториев на этой странице нет.")}</p>
      )}
      {!!list.data?.items.length && (
        <section className="panel repository-list">
          <table aria-label={t("Мои репозитории")}>
            <thead>
              <tr>
                <th scope="col">{t("Репозиторий")}</th>
                <th scope="col">{t("Ветка")}</th>
                <th scope="col">{t("Автопроверка")}</th>
                <th scope="col">{t("Сценарий")}</th>
                <th scope="col">{t("Последний коммит")}</th>
                <th scope="col">{t("Находки")}</th>
                <th scope="col">{t("Последний результат")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((repo) => {
                const watch = watches.data?.[repo.id];
                const head = watch?.head_sha ?? watch?.sha;
                const profile = watch?.profile ?? "full";
                const currentRun =
                  watch?.sha === head &&
                  (watch?.scan_profile ?? "full") === profile &&
                  (watch?.scan_scenario_revision ?? 0) ===
                    (watch?.scenario_revision ?? 0)
                    ? watch
                    : undefined;
                return (
                  <tr key={repo.id}>
                    <td>
                      {repo.name}
                      <small className="repository-role">
                        {t(repo.owner ? "Владелец" : "Соавтор")}
                      </small>
                    </td>
                    <td>
                      <code>{watch?.enabled ? watch.branch : repo.branch}</code>
                    </td>
                    <td>
                      <input
                        className="repository-toggle"
                        type="checkbox"
                        role="switch"
                        aria-label={t("Автопроверка") + " " + repo.name}
                        checked={watch?.enabled ?? false}
                        disabled={
                          !watches.data ||
                          saveWatch.isPending ||
                          (repo.archived && !watch?.enabled)
                        }
                        onChange={(event) =>
                          saveWatch.mutate({
                            id: repo.id,
                            enabled: event.target.checked,
                          })
                        }
                      />
                    </td>
                    <td>
                      {repo.archived ? (
                        "—"
                      ) : (
                        <Link
                          className="button"
                          to={`/repositories/${repo.id}/scenario?page=${page}`}
                        >
                          {t("Настроить сценарий")}
                        </Link>
                      )}
                    </td>
                    <td>
                      {watch?.head_committed_at ? (
                        <time
                          dateTime={new Date(
                            watch.head_committed_at * 1000,
                          ).toISOString()}
                        >
                          {date(watch.head_committed_at)}
                        </time>
                      ) : (
                        "—"
                      )}
                      {head && (
                        <small className="repository-role">
                          <code title={head}>{head.slice(0, 7)}</code>
                        </small>
                      )}
                    </td>
                    <td>
                      {currentRun?.status === "success"
                        ? (currentRun.count ?? "—")
                        : "—"}
                    </td>
                    <td>
                      <WatchStatus
                        enabled={watch?.enabled && !currentRun?.sha}
                        error={watch?.error}
                        status={currentRun?.status}
                      />
                      {currentRun?.run_id && (
                        <>
                          {" "}
                          ·{" "}
                          <Link to={"/runs/" + currentRun.run_id}>
                            {t("Открыть отчёт")}
                          </Link>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
      {(page > 1 || list.data?.has_more) && (
        <p>
          <button disabled={page === 1} onClick={() => setPage(page - 1)}>
            {t("Назад")}
          </button>{" "}
          {page}{" "}
          <button
            disabled={page >= 1000 || !list.data?.has_more}
            onClick={() => setPage(page + 1)}
          >
            {t("Далее")}
          </button>
        </p>
      )}
    </>
  );
}

function WatchStatus({
  enabled,
  error,
  status,
}: {
  enabled?: boolean;
  error?: string | null;
  status?: string | null;
}) {
  if (error) return <span>{t(error)}</span>;
  if (status === "queued" || status === "running") {
    return <span>{t("Идёт проверка")}</span>;
  }
  if (status === "success") return <span>{t("Проверено")}</span>;
  if (status) return <span>{t("Проверка не завершилась")}</span>;
  return <span>{t(enabled ? "Ожидаем проверку" : "Проверок пока нет")}</span>;
}
