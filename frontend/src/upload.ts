import type { Project } from "./api";

export function uploadProject(
  values: FormData,
  progress: (percent: number) => void,
): Promise<Project> {
  return uploadForm<Project>("/api/v1/projects", values, progress);
}

export function uploadForm<T>(
  path: string,
  values: FormData,
  progress: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) progress(Math.round((e.loaded * 100) / e.total));
    };
    xhr.onerror = () =>
      reject(new Error("Соединение прервано при загрузке проекта"));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as T);
      else reject(new Error(xhr.response?.detail || "Ошибка загрузки проекта"));
    };
    xhr.send(values);
  });
}
