/**
 * Frontend API client with unified error extraction, typed fetch helpers,
 * and TanStack Query queries & mutations.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getSessionCookies, getSessionProxy } from './sessionSettings';
import type {
  CookieStatus,
  CookieUpdateRequest,
  DeleteCookiesResponse,
  DownloadRequest,
  DownloadResponse,
  InspectRequest,
  InspectResponse,
  ProxyConfig,
  ProxyUpdateRequest,
  SaveCookiesResponse,
  ValidationErrorItem,
} from '../types/api';

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

/**
 * Custom application API error wrapping HTTP status and structured detail.
 */
export class ApiError extends Error {
  public readonly status: number;
  public readonly detail: string | ValidationErrorItem[] | any;
  public readonly isAuthRequired: boolean;
  public readonly isRateLimit: boolean;
  public readonly isValidationError: boolean;

  constructor(status: number, message: string, detail?: string | ValidationErrorItem[] | any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail ?? message;
    this.isAuthRequired = status === 401;
    this.isRateLimit = status === 429;
    this.isValidationError = status === 422;
  }
}

/**
 * Safely format an individual validation or error detail item into a readable string.
 * Handles strings, Pydantic error objects ({ loc, msg }), generic error objects ({ message }),
 * or any primitive/unknown shape without throwing TypeError.
 */
export function formatDetailItem(d: any): string {
  if (d === null || d === undefined) {
    return '';
  }
  if (typeof d === 'string') {
    return d;
  }
  if (typeof d === 'object') {
    let locStr = '';
    if (Array.isArray(d?.loc)) {
      locStr = d.loc.filter((part: any) => part !== null && part !== undefined).join('.');
    } else if (d?.loc !== undefined && d?.loc !== null) {
      locStr = String(d.loc);
    }

    let msg = '';
    if (typeof d?.msg === 'string') {
      msg = d.msg;
    } else if (typeof d?.message === 'string') {
      msg = d.message;
    } else if (typeof d?.detail === 'string') {
      msg = d.detail;
    } else {
      try {
        msg = JSON.stringify(d);
      } catch {
        msg = String(d);
      }
    }

    return locStr ? `${locStr}: ${msg}` : msg;
  }
  return String(d);
}

/**
 * Extract clean, human-readable error message from any error shape.
 */
export function extractErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (Array.isArray(error.detail)) {
      const formatted = error.detail.map(formatDetailItem).filter(Boolean).join(', ');
      return formatted || error.message;
    }
    if (typeof error.detail === 'string' && error.detail.trim().length > 0) {
      return error.detail;
    }
    return error.message;
  }

  if (error instanceof Error) {
    const errObj = error as unknown as Record<string, unknown>;
    if (typeof errObj.detail === 'string' && errObj.detail.trim().length > 0) {
      return errObj.detail;
    }
    if (Array.isArray(errObj.detail)) {
      const formatted = errObj.detail.map(formatDetailItem).filter(Boolean).join(', ');
      if (formatted) return formatted;
    }
    return error.message;
  }

  // Handle plain objects (e.g. raw FastAPI error payload { detail: ... } or { message: ... })
  if (error && typeof error === 'object') {
    const obj = error as Record<string, unknown>;
    if (typeof obj.detail === 'string' && obj.detail.trim().length > 0) {
      return obj.detail;
    }
    if (Array.isArray(obj.detail)) {
      const formatted = obj.detail.map(formatDetailItem).filter(Boolean).join(', ');
      if (formatted) return formatted;
    }
    if (obj.detail && typeof obj.detail === 'object') {
      const formatted = formatDetailItem(obj.detail);
      if (formatted) return formatted;
    }
    if (typeof obj.message === 'string' && obj.message.trim().length > 0) {
      return obj.message;
    }
    if (typeof obj.error === 'string' && obj.error.trim().length > 0) {
      return obj.error;
    }
  }

  if (typeof error === 'string' && error.trim().length > 0) {
    return error;
  }

  return 'An unexpected error occurred. Please try again.';
}

/**
 * Universal JSON fetch helper with standard error parsing.
 */
async function fetchJson<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err) {
    throw new ApiError(
      0,
      'Failed to connect to backend server. Please verify network or proxy.',
      String(err)
    );
  }

  if (!response.ok) {
    let errorDetail: any = response.statusText;
    try {
      const errJson = await response.json();
      if (errJson && errJson.detail !== undefined) {
        errorDetail = errJson.detail;
      } else if (errJson && (errJson.message || errJson.error)) {
        errorDetail = errJson.message || errJson.error;
      }
    } catch {
      // Body not JSON
    }

    let displayMessage = `Request failed (${response.status})`;
    if (typeof errorDetail === 'string' && errorDetail.trim().length > 0) {
      displayMessage = errorDetail;
    } else if (Array.isArray(errorDetail)) {
      const formatted = errorDetail.map(formatDetailItem).filter(Boolean).join(', ');
      if (formatted) {
        displayMessage = formatted;
      }
    } else if (errorDetail && typeof errorDetail === 'object') {
      const formatted = formatDetailItem(errorDetail);
      if (formatted) {
        displayMessage = formatted;
      }
    }

    throw new ApiError(response.status, displayMessage, errorDetail);
  }

  return response.json() as Promise<T>;
}

/**
 * Multipart FormData fetch helper for cookie file uploads.
 */
async function fetchMultipart<T>(endpoint: string, formData: FormData): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      body: formData,
    });
  } catch (err) {
    throw new ApiError(0, 'Failed to connect to backend server during file upload.', String(err));
  }

  if (!response.ok) {
    let errorDetail: any = response.statusText;
    try {
      const errJson = await response.json();
      if (errJson && errJson.detail !== undefined) {
        errorDetail = errJson.detail;
      } else if (errJson && (errJson.message || errJson.error)) {
        errorDetail = errJson.message || errJson.error;
      }
    } catch {
      // Non-JSON response
    }

    let displayMessage = `Upload failed (${response.status})`;
    if (typeof errorDetail === 'string' && errorDetail.trim().length > 0) {
      displayMessage = errorDetail;
    } else if (Array.isArray(errorDetail)) {
      const formatted = errorDetail.map(formatDetailItem).filter(Boolean).join(', ');
      if (formatted) {
        displayMessage = formatted;
      }
    } else if (errorDetail && typeof errorDetail === 'object') {
      const formatted = formatDetailItem(errorDetail);
      if (formatted) {
        displayMessage = formatted;
      }
    }

    throw new ApiError(response.status, displayMessage, errorDetail);
  }

  return response.json() as Promise<T>;
}

// ============================================================================
// Raw API Client Functions
// ============================================================================

/**
 * Inspect target URL to probe available formats, items, and metadata.
 * Automatically injects client session cookies and proxy from localStorage when present.
 */
export async function inspectMedia(request: InspectRequest): Promise<InspectResponse> {
  const sessionCookies = getSessionCookies();
  const sessionProxy = getSessionProxy();

  const payload: InspectRequest = {
    ...request,
    cookies:
      request.cookies !== undefined
        ? request.cookies
        : Object.keys(sessionCookies).length > 0
          ? sessionCookies
          : undefined,
    proxy:
      request.proxy !== undefined
        ? request.proxy
        : sessionProxy || undefined,
  };

  return fetchJson<InspectResponse>('/api/inspect', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Trigger background media download task and acquire unique task_id.
 * Automatically injects client session cookies and proxy from localStorage when present.
 */
export async function startDownload(request: DownloadRequest): Promise<DownloadResponse> {
  const sessionCookies = getSessionCookies();
  const sessionProxy = getSessionProxy();

  const payload: DownloadRequest = {
    ...request,
    cookies:
      request.cookies !== undefined
        ? request.cookies
        : Object.keys(sessionCookies).length > 0
          ? sessionCookies
          : undefined,
    proxy:
      request.proxy !== undefined
        ? request.proxy
        : sessionProxy || undefined,
  };

  return fetchJson<DownloadResponse>('/api/download', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Fetch cookie status for all supported platforms.
 */
export async function getCookieStatuses(): Promise<Record<string, CookieStatus>> {
  return fetchJson<Record<string, CookieStatus>>('/api/settings/cookies', {
    method: 'GET',
  });
}

/**
 * Save pasted Netscape cookies for a platform.
 */
export async function savePastedCookies(req: CookieUpdateRequest): Promise<SaveCookiesResponse> {
  return fetchJson<SaveCookiesResponse>('/api/settings/cookies', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/**
 * Upload a Netscape cookie file for a platform.
 */
export async function uploadCookieFile(platform: string, file: File): Promise<SaveCookiesResponse> {
  if (file.size > 5 * 1024 * 1024) {
    throw new ApiError(413, 'Cookie file exceeds maximum allowed size of 5MB');
  }
  const formData = new FormData();
  formData.append('platform', platform);
  formData.append('file', file);
  return fetchMultipart<SaveCookiesResponse>('/api/settings/cookies/upload', formData);
}

/**
 * Delete stored cookies for a platform.
 */
export async function deleteCookies(platform: string): Promise<DeleteCookiesResponse> {
  return fetchJson<DeleteCookiesResponse>(`/api/settings/cookies/${encodeURIComponent(platform)}`, {
    method: 'DELETE',
  });
}

/**
 * Retrieve current effective SOCKS5 / HTTP proxy settings.
 */
export async function getProxyConfig(): Promise<ProxyConfig> {
  return fetchJson<ProxyConfig>('/api/settings/proxy', {
    method: 'GET',
  });
}

/**
 * Update runtime SOCKS5 / HTTP proxy configuration.
 */
export async function setProxyConfig(req: ProxyUpdateRequest): Promise<ProxyConfig> {
  return fetchJson<ProxyConfig>('/api/settings/proxy', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/**
 * Safely format and resolve download URL, encoding '#' as '%23'
 * and prepending BASE_URL if relative.
 */
export function getSafeDownloadUrl(downloadUrl: string): string {
  // Ensure '#' is URL-encoded as '%23' in the download URL to prevent the browser
  // from interpreting '#' as a client-side URL fragment identifier, which causes
  // truncation and server routing errors.
  let safeUrl = downloadUrl;
  if (safeUrl.includes('#')) {
    safeUrl = safeUrl.replace(/#/g, '%23');
  }
  return safeUrl.startsWith('http') ? safeUrl : `${BASE_URL}${safeUrl}`;
}

/**
 * Trigger browser file download from completed download_url.
 */
export function triggerBrowserDownload(downloadUrl: string, filename?: string): void {
  const fullUrl = getSafeDownloadUrl(downloadUrl);
  const anchor = document.createElement('a');
  anchor.href = fullUrl;
  if (filename) {
    anchor.download = filename;
  }
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

// ============================================================================
// TanStack Query Hooks & Mutations
// ============================================================================

export const QUERY_KEYS = {
  cookies: ['settings', 'cookies'] as const,
  proxy: ['settings', 'proxy'] as const,
};

/**
 * Mutation hook for inspecting media URLs.
 */
export function useInspectMediaMutation() {
  return useMutation({
    mutationFn: (request: InspectRequest) => inspectMedia(request),
  });
}

/**
 * Mutation hook for initiating downloads.
 */
export function useStartDownloadMutation() {
  return useMutation({
    mutationFn: (request: DownloadRequest) => startDownload(request),
  });
}

/**
 * Query hook for cookie status.
 */
export function useCookieStatusesQuery() {
  return useQuery({
    queryKey: QUERY_KEYS.cookies,
    queryFn: getCookieStatuses,
    staleTime: 10_000,
  });
}

/**
 * Mutation hook for saving pasted cookies.
 */
export function useSaveCookiesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (req: CookieUpdateRequest) => savePastedCookies(req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.cookies });
    },
  });
}

/**
 * Mutation hook for uploading cookie files.
 */
export function useUploadCookieFileMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, file }: { platform: string; file: File }) =>
      uploadCookieFile(platform, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.cookies });
    },
  });
}

/**
 * Mutation hook for deleting platform cookies.
 */
export function useDeleteCookiesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (platform: string) => deleteCookies(platform),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.cookies });
    },
  });
}

/**
 * Query hook for proxy configuration.
 */
export function useProxyConfigQuery() {
  return useQuery({
    queryKey: QUERY_KEYS.proxy,
    queryFn: getProxyConfig,
    staleTime: 30_000,
  });
}

/**
 * Mutation hook for updating runtime proxy.
 */
export function useSetProxyConfigMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (req: ProxyUpdateRequest) => setProxyConfig(req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.proxy });
    },
  });
}
