import { describe, expect, it } from 'bun:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CookieSettingsModal } from './CookieSettingsModal';

describe('CookieSettingsModal Component (R2 Acceptance Criteria)', () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  queryClient.setQueryData(['settings', 'cookies'], {
    instagram: { platform: 'instagram', exists: false, valid: false, cookie_count: 0, details: null },
    twitter: { platform: 'twitter', exists: false, valid: false, cookie_count: 0, details: null },
    youtube: { platform: 'youtube', exists: false, valid: false, cookie_count: 0, details: null },
  });
  queryClient.setQueryData(['settings', 'proxy'], { proxy: null, source: 'default' });

  const renderModal = (props: {
    isOpen: boolean;
    defaultPlatform?: string;
    defaultTab?: 'cookies' | 'proxy';
    presentation?: 'dialog' | 'bottom-sheet';
  }) => {
    return renderToString(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(CookieSettingsModal, {
          isOpen: props.isOpen,
          onClose: () => {},
          defaultPlatform: props.defaultPlatform,
          defaultTab: props.defaultTab,
          presentation: props.presentation,
        })
      )
    );
  };

  it('renders nothing when isOpen is false', () => {
    const html = renderModal({ isOpen: false });
    expect(html).toBe('');
  });

  it('renders in-modal cookie retrieval guidance for all supported platforms when open', () => {
    const html = renderModal({ isOpen: true });

    // Modal title & session storage notice
    expect(html).toContain('Settings &amp; Authentication');
    expect(html).toContain('localStorage');
    expect(html).toContain('Client Session Isolation');

    // In-modal step-by-step retrieval guide section
    expect(html).toContain('How to Obtain Netscape-Format Cookie Files');
    expect(html).toContain('Step-by-step export instructions for Instagram, Twitter/X, and YouTube');

    // Recommended extensions listed with guidance
    expect(html).toContain('Recommended Browser Extensions');
    expect(html).toContain('Get cookies.txt LOCALLY');
    expect(html).toContain('Cookie-Editor');

    // Instagram guidance
    expect(html).toContain('Instagram');
    expect(html).toContain('instagram.com');
    expect(html).toContain('sessionid');
    expect(html).toContain('Stories, Highlights, Multi-photo Carousels');

    // Twitter / X guidance
    expect(html).toContain('Twitter / X');
    expect(html).toContain('auth_token');
    expect(html).toContain('ct0');
    expect(html).toContain('Prevents rate limits (HTTP 429)');

    // YouTube guidance
    expect(html).toContain('YouTube');
    expect(html).toContain('youtube.com');
    expect(html).toContain('LOGIN_INFO');
    expect(html).toContain('Bypasses YouTube bot verification');
  });

  it('displays platform tabs for Cookies and Proxy', () => {
    const html = renderModal({ isOpen: true });
    expect(html).toContain('Platform Cookies');
    expect(html).toContain('Proxy Configuration');
  });

  it('renders upload, paste, and guide buttons for each platform', () => {
    const html = renderModal({ isOpen: true });
    // Upload and Paste action labels
    expect(html).toContain('Upload');
    expect(html).toContain('Paste');
    expect(html).toContain('Guide');
  });

  it('recognizes cookies stored under x alias and renders active session status for Twitter / X', () => {
    const { saveSessionCookie, clearAllSessionCookies } = require('../lib/sessionSettings');
    clearAllSessionCookies();
    const twitterCookie =
      '# Netscape HTTP Cookie File\n.x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\tval_123\n.x.com\tTRUE\t/\tTRUE\t2000000000\tct0\tcsrf_456\n';
    saveSessionCookie('x', twitterCookie);

    const html = renderModal({ isOpen: true });
    expect(html).toContain('Session Active');
    expect(html).toContain('cookies)');
    clearAllSessionCookies();
  });

  it('renders proxy tab with sanitized badge and generic placeholder when server proxy is configured', () => {
    queryClient.setQueryData(['settings', 'proxy'], { proxy: null, source: 'env' });
    const html = renderModal({ isOpen: true, defaultTab: 'proxy' });

    expect(html).toContain('Proxy Configuration');
    expect(html).toContain('Source: Server Default (configured)');
    expect(html).toContain('placeholder="e.g. socks5://host:port or http://host:port"');
    expect(html).not.toContain('socks5://127.0.0.1:9050');
    expect(html).not.toContain('Server fallback:');
  });

  it('never leaks server default SOCKS5 URL or credentials in UI even if proxy property is populated', () => {
    queryClient.setQueryData(['settings', 'proxy'], {
      proxy: 'socks5://secret_user:secret_pass@super-secret-proxy.corp:1080',
      source: 'env',
    });
    const html = renderModal({ isOpen: true, defaultTab: 'proxy' });

    expect(html).toContain('Source: Server Default (configured)');
    expect(html).toContain('placeholder="e.g. socks5://host:port or http://host:port"');
    expect(html).not.toContain('secret_user');
    expect(html).not.toContain('secret_pass');
    expect(html).not.toContain('super-secret-proxy.corp');
    expect(html).not.toContain('socks5://secret_user');
    expect(html).not.toContain('socks5://127.0.0.1:9050');
    expect(html).not.toContain('Server fallback:');
  });

  it('renders Source: Server Default (none) when no server or session proxy is set', () => {
    queryClient.setQueryData(['settings', 'proxy'], { proxy: null, source: 'none' });
    const html = renderModal({ isOpen: true, defaultTab: 'proxy' });

    expect(html).toContain('Source: Server Default (none)');
    expect(html).toContain('placeholder="e.g. socks5://host:port or http://host:port"');
    expect(html).not.toContain('socks5://127.0.0.1:9050');
  });

  it('renders adaptive presentation with BottomSheet when presentation="bottom-sheet"', () => {
    const html = renderModal({ isOpen: true, presentation: 'bottom-sheet' });

    // Verify it renders the Astryx bottom sheet structure
    expect(html).toContain('astryx-bottom-sheet');
    expect(html).toContain('Settings &amp; Authentication');
    expect(html).toContain('Platform Cookies');
    expect(html).toContain('Proxy Configuration');
    expect(html).toContain('How to Obtain Netscape-Format Cookie Files');
    expect(html).toContain('Instagram');
    expect(html).toContain('Twitter / X');
    expect(html).toContain('YouTube');
  });

  it('renders adaptive presentation with Dialog when presentation="dialog"', () => {
    const html = renderModal({ isOpen: true, presentation: 'dialog' });

    expect(html).toContain('Settings &amp; Authentication');
    expect(html).toContain('Platform Cookies');
    expect(html).toContain('Proxy Configuration');
  });
});
