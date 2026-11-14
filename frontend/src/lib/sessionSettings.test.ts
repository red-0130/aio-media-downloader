import { beforeEach, describe, expect, it } from 'bun:test';
import {
  clearAllSessionCookies,
  clearSessionProxy,
  deleteSessionCookie,
  evaluateCookieContent,
  getSessionCookie,
  getSessionCookies,
  getSessionProxy,
  parseNetscapeCookies,
  safeTimestampToIso,
  saveSessionCookie,
  saveSessionProxy,
  validateProxyUrl,
} from './sessionSettings';
import { inspectMedia, startDownload } from './api';

const SAMPLE_INSTAGRAM_NETSCAPE = `# Netscape HTTP Cookie File
.instagram.com	TRUE	/	TRUE	2000000000	sessionid	valid_instagram_session_123
.instagram.com	TRUE	/	TRUE	2000000000	ds_user_id	987654321
`;

const SAMPLE_TWITTER_NETSCAPE = `# Netscape HTTP Cookie File
.x.com	TRUE	/	TRUE	2000000000	auth_token	secret_auth_token_456
.x.com	TRUE	/	TRUE	2000000000	ct0	valid_csrf_token_789
`;

const SAMPLE_YOUTUBE_NETSCAPE = `# Netscape HTTP Cookie File
#HttpOnly_.youtube.com	TRUE	/	TRUE	2000000000	SID	valid_youtube_sid_999
`;

describe('sessionSettings: parseNetscapeCookies', () => {
  it('parses valid tab-separated Netscape format', () => {
    const cookies = parseNetscapeCookies(SAMPLE_INSTAGRAM_NETSCAPE);
    expect(cookies.length).toBe(2);
    expect(cookies[0].name).toBe('sessionid');
    expect(cookies[0].value).toBe('valid_instagram_session_123');
    expect(cookies[0].domain).toBe('.instagram.com');
    expect(cookies[0].expiry).toBe(2000000000);
    expect(cookies[0].httpOnly).toBe(false);
  });

  it('handles #HttpOnly_ lines correctly', () => {
    const cookies = parseNetscapeCookies(SAMPLE_YOUTUBE_NETSCAPE);
    expect(cookies.length).toBe(1);
    expect(cookies[0].name).toBe('SID');
    expect(cookies[0].httpOnly).toBe(true);
  });

  it('handles whitespace-separated lines fallback', () => {
    const text = '.instagram.com TRUE / TRUE 2000000000 sessionid custom_val';
    const cookies = parseNetscapeCookies(text);
    expect(cookies.length).toBe(1);
    expect(cookies[0].name).toBe('sessionid');
    expect(cookies[0].value).toBe('custom_val');
  });

  it('handles empty cookie values with trailing tab or 6 columns', () => {
    const withTab = '.youtube.com\tTRUE\t/\tTRUE\t2000000000\tLOGIN_INFO\t';
    const c1 = parseNetscapeCookies(withTab);
    expect(c1.length).toBe(1);
    expect(c1[0].name).toBe('LOGIN_INFO');
    expect(c1[0].value).toBe('');

    const sixCols = '.youtube.com\tTRUE\t/\tTRUE\t2000000000\tLOGIN_INFO';
    const c2 = parseNetscapeCookies(sixCols);
    expect(c2.length).toBe(1);
    expect(c2[0].name).toBe('LOGIN_INFO');
    expect(c2[0].value).toBe('');
  });

  it('returns empty array for comments or empty text', () => {
    expect(parseNetscapeCookies('')).toEqual([]);
    expect(parseNetscapeCookies('# Just a comment\n# Another comment')).toEqual([]);
  });
});

describe('sessionSettings: evaluateCookieContent', () => {
  it('evaluates valid future session cookies as active', () => {
    const status = evaluateCookieContent('instagram', SAMPLE_INSTAGRAM_NETSCAPE);
    expect(status.platform).toBe('instagram');
    expect(status.exists).toBe(true);
    expect(status.valid).toBe(true);
    expect(status.cookie_count).toBe(2);
    expect(status.expires_at).toBeTruthy();
  });

  it('evaluates expired cookies correctly', () => {
    const expiredContent = `# Netscape HTTP Cookie File
.instagram.com	TRUE	/	TRUE	1000000000	sessionid	old_expired_session
`;
    const status = evaluateCookieContent('instagram', expiredContent);
    expect(status.exists).toBe(true);
    expect(status.valid).toBe(false);
    expect(status.details).toContain('expired');
  });

  it('evaluates empty content as non-existent', () => {
    const status = evaluateCookieContent('twitter', '');
    expect(status.exists).toBe(false);
    expect(status.valid).toBe(false);
  });

  it('safely handles astronomical/overflow expiration timestamps without throwing RangeError', () => {
    const overflowContent = `# Netscape HTTP Cookie File
.instagram.com	TRUE	/	TRUE	999999999999999999	sessionid	infinite_session_val
`;
    expect(() => evaluateCookieContent('instagram', overflowContent)).not.toThrow();
    const status = evaluateCookieContent('instagram', overflowContent);
    expect(status.valid).toBe(true);
    expect(status.cookie_count).toBe(1);
  });

  it('safeTimestampToIso handles invalid, zero, negative, and overflow timestamps', () => {
    expect(safeTimestampToIso(null)).toBeNull();
    expect(safeTimestampToIso(undefined)).toBeNull();
    expect(safeTimestampToIso(0)).toBeNull();
    expect(safeTimestampToIso(-100)).toBeNull();
    expect(safeTimestampToIso(NaN)).toBeNull();
    expect(safeTimestampToIso(99999999999999999999)).toBeNull();
    expect(safeTimestampToIso(1750000000)).toBe('2025-06-15T15:06:40.000Z');
  });
});

describe('sessionSettings: validateProxyUrl', () => {
  it('accepts socks5, socks5h, http, and https proxies with port', () => {
    expect(validateProxyUrl('socks5://127.0.0.1:9050')).toBe('socks5://127.0.0.1:9050');
    expect(validateProxyUrl('socks5h://user:pass@proxy.example.com:1080')).toBe(
      'socks5h://user:pass@proxy.example.com:1080'
    );
    expect(validateProxyUrl('http://10.0.0.1:8080')).toBe('http://10.0.0.1:8080');
    expect(validateProxyUrl('https://secure-proxy.internal:8443')).toBe(
      'https://secure-proxy.internal:8443'
    );
  });

  it('rejects unsupported proxy schemes', () => {
    expect(() => validateProxyUrl('ftp://127.0.0.1:21')).toThrow('Unsupported proxy scheme');
    expect(() => validateProxyUrl('ws://127.0.0.1:8080')).toThrow('Unsupported proxy scheme');
  });

  it('rejects invalid ports', () => {
    expect(() => validateProxyUrl('socks5://127.0.0.1:99999')).toThrow('Proxy port must be between');
  });
});

describe('sessionSettings: localStorage persistence', () => {
  beforeEach(() => {
    clearAllSessionCookies();
    clearSessionProxy();
  });

  it('saves, retrieves, and deletes platform cookies in localStorage', () => {
    expect(getSessionCookie('instagram')).toBeNull();

    saveSessionCookie('instagram', SAMPLE_INSTAGRAM_NETSCAPE);
    expect(getSessionCookie('instagram')).toContain('valid_instagram_session_123');
    expect(getSessionCookie('Instagram')).toContain('valid_instagram_session_123');
    expect(getSessionCookie('INSTAGRAM')).toContain('valid_instagram_session_123');

    // Test twitter / x alias
    saveSessionCookie('twitter', SAMPLE_TWITTER_NETSCAPE);
    expect(getSessionCookie('twitter')).toContain('secret_auth_token_456');
    expect(getSessionCookie('x')).toContain('secret_auth_token_456');
    expect(getSessionCookie('X')).toContain('secret_auth_token_456');

    const all = getSessionCookies();
    expect(all.instagram).toContain('valid_instagram_session_123');

    deleteSessionCookie('instagram');
    expect(getSessionCookie('instagram')).toBeNull();

    // Verify deleting 'twitter' clears both 'twitter' and 'x' alias
    saveSessionCookie('x', SAMPLE_TWITTER_NETSCAPE);
    expect(getSessionCookie('x')).not.toBeNull();
    deleteSessionCookie('twitter');
    expect(getSessionCookie('x')).toBeNull();
    expect(getSessionCookie('twitter')).toBeNull();

    // Verify saving 'twitter' cleans up previous 'x' key preventing duplicate storage
    saveSessionCookie('x', SAMPLE_TWITTER_NETSCAPE);
    expect(getSessionCookies()['x']).toBeDefined();
    saveSessionCookie('twitter', SAMPLE_TWITTER_NETSCAPE);
    expect(getSessionCookies()['x']).toBeUndefined();
    expect(getSessionCookies()['twitter']).toBeDefined();

    // Verify deleteSessionCookie handles uppercase and mixed case keys
    saveSessionCookie('YouTube', SAMPLE_YOUTUBE_NETSCAPE);
    expect(getSessionCookie('youtube')).not.toBeNull();
    deleteSessionCookie('YOUTUBE');
    expect(getSessionCookie('youtube')).toBeNull();
  });

  it('rejects cookie content exceeding 5MB', () => {
    const hugeContent = 'a'.repeat(5 * 1024 * 1024 + 10);
    expect(() => saveSessionCookie('instagram', hugeContent)).toThrow(
      'Cookie content exceeds maximum allowed size of 5MB'
    );
  });

  it('saves, retrieves, and clears proxy in localStorage', () => {
    expect(getSessionProxy()).toBeNull();

    saveSessionProxy('socks5://127.0.0.1:9050');
    expect(getSessionProxy()).toBe('socks5://127.0.0.1:9050');

    clearSessionProxy();
    expect(getSessionProxy()).toBeNull();
  });
});

describe('sessionSettings: inspectMedia and startDownload session integration', () => {
  beforeEach(() => {
    clearAllSessionCookies();
    clearSessionProxy();
  });

  it('inspectMedia automatically supplies session cookies and proxy when configured', async () => {
    saveSessionCookie('youtube', SAMPLE_YOUTUBE_NETSCAPE);
    saveSessionProxy('socks5://127.0.0.1:9050');

    let capturedUrl = '';
    let capturedBody: any = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      capturedUrl = url;
      capturedBody = JSON.parse((init?.body as string) || '{}');
      return new Response(
        JSON.stringify({
          id: 'test-id',
          url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
          platform: 'youtube',
          title: 'Test',
          media_type: 'video',
          items: [],
          formats: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }) as any;

    try {
      await inspectMedia({ url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ' });

      expect(capturedUrl).toContain('/api/inspect');
      expect(capturedBody.url).toBe('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
      expect(capturedBody.proxy).toBe('socks5://127.0.0.1:9050');
      expect(capturedBody.cookies).toBeDefined();
      expect(capturedBody.cookies.youtube).toContain('valid_youtube_sid_999');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('inspectMedia omits cookies and proxy when no session settings configured', async () => {
    let capturedBody: any = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (_url: string, init?: RequestInit) => {
      capturedBody = JSON.parse((init?.body as string) || '{}');
      return new Response(
        JSON.stringify({
          id: 'test-id',
          url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
          platform: 'youtube',
          title: 'Test',
          media_type: 'video',
          items: [],
          formats: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }) as any;

    try {
      await inspectMedia({ url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ' });

      expect(capturedBody.url).toBe('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
      expect(capturedBody.cookies).toBeUndefined();
      expect(capturedBody.proxy).toBeUndefined();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('startDownload automatically supplies session cookies and proxy when configured', async () => {
    saveSessionCookie('twitter', SAMPLE_TWITTER_NETSCAPE);
    saveSessionProxy('http://proxy.internal:8080');

    let capturedUrl = '';
    let capturedBody: any = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      capturedUrl = url;
      capturedBody = JSON.parse((init?.body as string) || '{}');
      return new Response(
        JSON.stringify({
          task_id: 'task-test-dl',
          status: 'queued',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }) as any;

    try {
      await startDownload({ url: 'https://x.com/user/status/123456' });

      expect(capturedUrl).toContain('/api/download');
      expect(capturedBody.proxy).toBe('http://proxy.internal:8080');
      expect(capturedBody.cookies.twitter).toContain('secret_auth_token_456');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
