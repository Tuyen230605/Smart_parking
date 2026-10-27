import { createHttpApi } from "./http";
import { mockApi } from "./mock";
import type { Api } from "./types";

const base = import.meta.env.VITE_API_BASE_URL as string | undefined;

export const usingMock = !base;
export const api: Api = base ? createHttpApi(base.replace(/\/$/, "")) : mockApi;
export * from "./types";
