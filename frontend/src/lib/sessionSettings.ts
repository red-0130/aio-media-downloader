/**
 * Client Session-based Cookie and Proxy storage using localStorage.
 *
 * Keeps client authentication and proxy settings isolated in the browser
 * without mutating or overwriting server configuration.
 */

export const SESSION_COOKIES_STORAGE_KEY = 'media_downloader_session_cookies';
export const SESSION_PROXY_STORAGE_KEY = 'media_downloader_session_proxy';

// Fallback legacy keys
const FALLBACK_COOKIES_KEY = 'session_cookies';
const FALLBACK_PROXY_KEY = 'session_proxy';

export interface ParsedCookie {
  domain: string;
  includeSubdomains: boolean;
  path: string;
  secure: boolean;
  expiry: number;
  name: string;
  value: string;
  httpOnly: boolean;
}

export interface SessionCookieStatus {
  platform: string;
  exists: boolean;
  valid: boolean;
  expires_at: string | null;
  cookie_count: number;
  details: string | null;
  source: 'session';
}

export const KEY_COOKIES_BY_PLATFORM: Record<string, string[]> = {
  instagram: ['sessionid', 'ds_user_id'],
  twitter: ['auth_token', 'ct0'],
  x: ['auth_token', 'ct0'],
  youtube: ['SID', '__Secure-1PSID', 'LOGIN_INFO'],
  tiktok: ['sessionid', 'sessionid_ss', 'sid_tt', 'sid_guard'],
};

/**
 * Safely convert unix timestamp to ISO string handling milliseconds and overflow (> year 9999).
 */
export function safeTimestampToIso(ts: number | null | undefined): string | null {
  if (ts === null || ts === undefined || ts <= 0 || isNaN(ts)) {
    return null;
  }
  try {
    let val = ts;
    if (val > 100_000_000_000) {
      val = Math.floor(val / 1000);
    }
    const dt = new Date(val * 1000);
    if (isNaN(dt.getTime())) {
      return null;
    }
    return dt.toISOString();
  } catch {
    return null;
  }
}

/**
 * Parse Netscape HTTP Cookie File formatted text into array of cookie objects.
 */
export function parseNetscapeCookies(content: string): ParsedCookie[] {
  const cookies: ParsedCookie[] = [];
  if (!content) return cookies;

  const lines = content.split(/\r?\n/);
  for (const rawLine of lines) {
    let line = rawLine.replace(/[\r\n]+$/, '');
    if (!line.trim()) continue;

    let httpOnly = false;
    if (line.startsWith('#HttpOnly_')) {
      httpOnly = true;
      line = line.substring('#HttpOnly_'.length);
    } else if (line.startsWith('#')) {
      continue;
    }

    let parts = line.split('\t');
    if (parts.length === 6) {
      parts.push('');
    } else if (parts.length < 6) {
      const wsParts = line.trim().split(/\s+/);
      if (wsParts.length === 6) {
        parts = [...wsParts, ''];
      } else if (wsParts.length >= 7) {
        parts = [...wsParts.slice(0, 6), wsParts.slice(6).join(' ')];
      } else {
        continue;
      }
    }

    const domain = parts[0];
    const includeSubdomains = parts[1].toUpperCase() === 'TRUE';
    const path = parts[2];
    const secure = parts[3].toUpperCase() === 'TRUE';
    const expiry = parseInt(parts[4], 10);
    const name = parts[5];
    const value = parts[6] || '';

    if (!isNaN(expiry)) {
      cookies.push({
        domain,
        includeSubdomains,
        path,
        secure,
        expiry,
        name,
        value,
        httpOnly,
      });
    }
  }

  return cookies;
}

/**
 * Verify and evaluate the validity of Netscape cookie text for a platform.
 */
export function evaluateCookieContent(
  platform: string,
  content: string | null | undefined
): SessionCookieStatus {
  const platformClean = platform.toLowerCase();
  if (!content || !content.trim()) {
    return {
      platform: platformClean,
      exists: false,
      valid: false,
      expires_at: null,
      cookie_count: 0,
      details: 'No session cookies configured',
      source: 'session',
    };
  }

  const cookies = parseNetscapeCookies(content);
  if (cookies.length === 0) {
    return {
      platform: platformClean,
      exists: true,
      valid: false,
      expires_at: null,
      cookie_count: 0,
      details: 'Cookie content is empty or invalid Netscape format',
      source: 'session',
    };
  }

  const keyNames = KEY_COOKIES_BY_PLATFORM[platformClean] || [];
  const nowTs = Math.floor(Date.now() / 1000);

  let keyCookieFound = false;
  let earliestKeyExpiry: number | null = null;
  let isKeyExpired = false;

  for (const c of cookies) {
    if (keyNames.includes(c.name)) {
      keyCookieFound = true;
      let exp = c.expiry;
      if (exp > 100_000_000_000) exp = Math.floor(exp / 1000);
      if (exp > 0) {
        if (earliestKeyExpiry === null || exp < earliestKeyExpiry) {
          earliestKeyExpiry = exp;
        }
        if (exp < nowTs) {
          isKeyExpired = true;
        }
      }
    }
  }

  if (keyCookieFound && isKeyExpired) {
    const expiresAt = earliestKeyExpiry ? safeTimestampToIso(earliestKeyExpiry) : null;
    return {
      platform: platformClean,
      exists: true,
      valid: false,
      expires_at: expiresAt,
      cookie_count: cookies.length,
      details: `Session cookie for ${platform} has expired`,
      source: 'session',
    };
  }

  if (keyCookieFound && earliestKeyExpiry) {
    const expiresAt = safeTimestampToIso(earliestKeyExpiry);
    return {
      platform: platformClean,
      exists: true,
      valid: true,
      expires_at: expiresAt,
      cookie_count: cookies.length,
      details: `Valid session cookies found (${cookies.length} total)`,
      source: 'session',
    };
  }

  return {
    platform: platformClean,
    exists: true,
    valid: true,
    expires_at: null,
    cookie_count: cookies.length,
    details: `Session cookies loaded (${cookies.length} total)`,
    source: 'session',
  };
}

/**
 * Validate proxy URL scheme, hostname, and port.
 */
export function validateProxyUrl(proxy: string): string {
  if (!proxy || !proxy.trim()) {
    throw new Error('Proxy URL cannot be empty');
  }

  const cleaned = proxy.trim();
  let parsed: URL;
  try {
    parsed = new URL(cleaned);
  } catch (e) {
    const portMatch = cleaned.match(/:(\d+)(?:\/|$)/);
    if (portMatch) {
      const portNum = parseInt(portMatch[1], 10);
      if (portNum < 1 || portNum > 65535) {
        throw new Error(`Proxy port must be between 1 and 65535 (got ${portNum})`);
      }
    }
    throw new Error(`Invalid proxy URL: ${e instanceof Error ? e.message : String(e)}`);
  }

  const scheme = parsed.protocol.replace(':', '').toLowerCase();
  if (!['socks5', 'socks5h', 'http', 'https'].includes(scheme)) {
    throw new Error(
      `Unsupported proxy scheme '${scheme}'. Supported schemes: socks5, socks5h, http, https`
    );
  }

  if (!parsed.hostname) {
    throw new Error('Proxy URL must include a valid hostname');
  }

  if (parsed.port) {
    const portNum = parseInt(parsed.port, 10);
    if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
      throw new Error(`Proxy port must be between 1 and 65535 (got ${parsed.port})`);
    }
  }

  return cleaned;
}

let inMemoryStorage: Record<string, string> = {};

function getStorage(): {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
} {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      const testKey = '__test_ls__';
      window.localStorage.setItem(testKey, testKey);
      window.localStorage.removeItem(testKey);
      return window.localStorage;
    }
    if (typeof globalThis !== 'undefined' && (globalThis as any).localStorage) {
      return (globalThis as any).localStorage;
    }
  } catch {
    // Fallback on restricted storage
  }

  return {
    getItem: (key: string) => (key in inMemoryStorage ? inMemoryStorage[key] : null),
    setItem: (key: string, value: string) => {
      inMemoryStorage[key] = value;
    },
    removeItem: (key: string) => {
      delete inMemoryStorage[key];
    },
  };
}

function notifySettingsChanged(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('session-settings-changed'));
  }
}

/**
 * Retrieve all client session cookies from localStorage as a platform -> content map.
 */
export function getSessionCookies(): Record<string, string> {
  try {
    const storage = getStorage();
    const raw =
      storage.getItem(SESSION_COOKIES_STORAGE_KEY) ||
      storage.getItem(FALLBACK_COOKIES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Retrieve client session cookies for a specific platform.
 */
export function getSessionCookie(platform: string): string | null {
  const all = getSessionCookies();
  const target = platform.toLowerCase();
  if (all[target]) return all[target];
  for (const [k, v] of Object.entries(all)) {
    if (k.toLowerCase() === target) return v;
  }
  if (target === 'twitter' || target === 'x') {
    for (const [k, v] of Object.entries(all)) {
      const kLower = k.toLowerCase();
      if (kLower === 'twitter' || kLower === 'x') return v;
    }
  }
  return null;
}

/**
 * Save client session cookies for a platform into localStorage.
 */
export function saveSessionCookie(platform: string, content: string): SessionCookieStatus {
  if (!content || !content.trim()) {
    throw new Error('Cookie content cannot be empty');
  }

  if (content.length > 5 * 1024 * 1024) {
    throw new Error('Cookie content exceeds maximum allowed size of 5MB');
  }

  let cleanContent = content.trim();
  if (
    !cleanContent.startsWith('# Netscape HTTP Cookie File') &&
    !cleanContent.startsWith('# HTTP Cookie File')
  ) {
    cleanContent = '# Netscape HTTP Cookie File\n' + cleanContent;
  }

  const status = evaluateCookieContent(platform, cleanContent);
  if (!status.valid && status.cookie_count === 0) {
    throw new Error('Invalid format: no valid Netscape cookie entries found');
  }

  const platKey = platform.toLowerCase();
  const all = getSessionCookies();

  // Clear any existing keys matching platKey or alias case-insensitively to prevent duplicates
  for (const k of Object.keys(all)) {
    const kLower = k.toLowerCase();
    if (
      kLower === platKey ||
      ((platKey === 'twitter' || platKey === 'x') && (kLower === 'twitter' || kLower === 'x'))
    ) {
      delete all[k];
    }
  }

  all[platKey] = cleanContent;

  const storage = getStorage();
  storage.setItem(SESSION_COOKIES_STORAGE_KEY, JSON.stringify(all));
  storage.setItem(FALLBACK_COOKIES_KEY, JSON.stringify(all));

  notifySettingsChanged();
  return status;
}

/**
 * Delete client session cookies for a platform from localStorage.
 */
export function deleteSessionCookie(platform: string): void {
  const platKey = platform.toLowerCase();
  const all = getSessionCookies();
  let changed = false;

  for (const k of Object.keys(all)) {
    const kLower = k.toLowerCase();
    if (
      kLower === platKey ||
      ((platKey === 'twitter' || platKey === 'x') && (kLower === 'twitter' || kLower === 'x'))
    ) {
      delete all[k];
      changed = true;
    }
  }

  if (changed) {
    const storage = getStorage();
    storage.setItem(SESSION_COOKIES_STORAGE_KEY, JSON.stringify(all));
    storage.setItem(FALLBACK_COOKIES_KEY, JSON.stringify(all));
    notifySettingsChanged();
  }
}

/**
 * Clear all client session cookies from localStorage.
 */
export function clearAllSessionCookies(): void {
  const storage = getStorage();
  storage.removeItem(SESSION_COOKIES_STORAGE_KEY);
  storage.removeItem(FALLBACK_COOKIES_KEY);
  inMemoryStorage = {};
  notifySettingsChanged();
}

/**
 * Retrieve client session proxy setting from localStorage.
 */
export function getSessionProxy(): string | null {
  try {
    const storage = getStorage();
    const proxy =
      storage.getItem(SESSION_PROXY_STORAGE_KEY) ||
      storage.getItem(FALLBACK_PROXY_KEY);
    if (proxy && proxy.trim()) return proxy.trim();
    return null;
  } catch {
    return null;
  }
}

/**
 * Save client session proxy setting to localStorage.
 */
export function saveSessionProxy(proxy: string | null): void {
  if (!proxy || !proxy.trim()) {
    clearSessionProxy();
    return;
  }

  const validated = validateProxyUrl(proxy);
  const storage = getStorage();
  storage.setItem(SESSION_PROXY_STORAGE_KEY, validated);
  storage.setItem(FALLBACK_PROXY_KEY, validated);
  notifySettingsChanged();
}

/**
 * Clear client session proxy setting from localStorage.
 */
export function clearSessionProxy(): void {
  const storage = getStorage();
  storage.removeItem(SESSION_PROXY_STORAGE_KEY);
  storage.removeItem(FALLBACK_PROXY_KEY);
  notifySettingsChanged();
}

/**
 * Subscribe to session settings updates (across tabs and within current tab).
 */
export function subscribeToSessionSettings(callback: () => void): () => void {
  if (typeof window === 'undefined') {
    return () => {};
  }

  const handleCustomEvent = () => callback();
  const handleStorageEvent = (e: StorageEvent) => {
    if (
      e.key === SESSION_COOKIES_STORAGE_KEY ||
      e.key === SESSION_PROXY_STORAGE_KEY ||
      e.key === FALLBACK_COOKIES_KEY ||
      e.key === FALLBACK_PROXY_KEY
    ) {
      callback();
    }
  };

  window.addEventListener('session-settings-changed', handleCustomEvent);
  window.addEventListener('storage', handleStorageEvent);

  return () => {
    window.removeEventListener('session-settings-changed', handleCustomEvent);
    window.removeEventListener('storage', handleStorageEvent);
  };
}
