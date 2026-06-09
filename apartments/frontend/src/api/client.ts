import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "/api",
  timeout: 15_000,
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    console.error("[api]", err.config?.url, err.response?.status, err.message);
    return Promise.reject(err);
  }
);
