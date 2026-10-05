import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

export const api = axios.create({ baseURL: '/api', timeout: 120_000 });

const ACCESS_KEY = 'wa.access', REFRESH_KEY = 'wa.refresh';
const store = {
  get access() { return sessionStorage.getItem(ACCESS_KEY); },
  get refresh() { return localStorage.getItem(REFRESH_KEY); },
  set(access: string, refresh: string) { sessionStorage.setItem(ACCESS_KEY, access); localStorage.setItem(REFRESH_KEY, refresh); },
  clear() { sessionStorage.removeItem(ACCESS_KEY); localStorage.removeItem(REFRESH_KEY); },
};
export const tokens = store;

let onLogout: () => void = () => {};
export const setLogoutHandler = (fn: () => void) => { onLogout = fn; };

api.interceptors.request.use((cfg) => {
  if (store.access) cfg.headers.Authorization = `Bearer ${store.access}`;
  return cfg;
});

/** One refresh at a time; concurrent 401s wait for the same promise (refresh tokens are single-use). */
let refreshing: Promise<string> | null = null;
async function refreshAccess(): Promise<string> {
  const refreshToken = store.refresh;
  if (!refreshToken) throw new Error('no refresh token');
  const r = await axios.post('/api/auth/refresh', { refreshToken });
  store.set(r.data.accessToken, r.data.refreshToken);
  return r.data.accessToken;
}

api.interceptors.response.use((r) => r, async (error: AxiosError) => {
  const cfg = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
  const isAuthCall = cfg?.url?.startsWith('/auth/');
  if (error.response?.status === 401 && cfg && !cfg._retried && !isAuthCall && store.refresh) {
    cfg._retried = true;
    try {
      refreshing ??= refreshAccess().finally(() => { refreshing = null; });
      const access = await refreshing;
      cfg.headers.Authorization = `Bearer ${access}`;
      return api(cfg);
    } catch {
      store.clear();
      onLogout();
    }
  } else if (error.response?.status === 401 && !isAuthCall) {
    store.clear();
    onLogout();
  }
  return Promise.reject(error);
});

export interface ApiErrorInfo { code: string; message: string; details?: unknown; status?: number }
export function apiError(e: unknown): ApiErrorInfo {
  const ax = e as AxiosError<{ error?: { code: string; message: string; details?: unknown } }>;
  const body = ax.response?.data?.error;
  if (body) return { ...body, status: ax.response?.status };
  if (ax.code === 'ERR_NETWORK' || !ax.response) return { code: 'NETWORK', message: 'Cannot reach the server. Check your connection.' };
  return { code: 'UNKNOWN', message: 'Something went wrong', status: ax.response?.status };
}
