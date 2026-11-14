import React, { useEffect, useRef, useState } from 'react';
import {
  X,
  Shield,
  Cookie,
  Upload,
  FileText,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Server,
  Loader2,
  Info,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  BookOpen,
  Key,
} from 'lucide-react';
import {
  useCookieStatusesQuery,
  useProxyConfigQuery,
} from '../lib/api';
import {
  evaluateCookieContent,
  getSessionCookies,
  getSessionProxy,
  saveSessionCookie,
  deleteSessionCookie,
  saveSessionProxy,
  clearSessionProxy,
  subscribeToSessionSettings,
} from '../lib/sessionSettings';
import type { CookiePlatform } from '../types/api';
import { cn } from '../lib/utils';

export interface CookieSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultPlatform?: string;
}

interface PlatformGuide {
  name: string;
  domain: string;
  keyCookies: string[];
  whyNeeded: string;
  steps: string[];
}

const PLATFORM_GUIDES: Record<CookiePlatform, PlatformGuide> = {
  instagram: {
    name: 'Instagram',
    domain: 'instagram.com',
    keyCookies: ['sessionid', 'ds_user_id'],
    whyNeeded: 'Required for Stories, Highlights, Multi-photo Carousels, and private accounts.',
    steps: [
      'Open a new browser tab and navigate to https://www.instagram.com.',
      'Log into your account and verify that you can view stories, reels, and profiles normally.',
      'Click your cookie export extension icon (e.g. "Get cookies.txt LOCALLY") in your browser toolbar while on instagram.com.',
      'Click "Export" to download your cookies.txt or copy the Netscape cookies. Ensure the "sessionid" cookie is included.',
      'Click "Upload" or "Paste" under the Instagram section below to save cookies to your browser session (localStorage).',
    ],
  },
  twitter: {
    name: 'Twitter / X',
    domain: 'x.com / twitter.com',
    keyCookies: ['auth_token', 'ct0'],
    whyNeeded: 'Prevents rate limits (HTTP 429) and allows extraction of full-resolution original photos and 1080p video streams.',
    steps: [
      'Open a new browser tab and sign into https://x.com or https://twitter.com.',
      'Confirm that your timeline and media posts load without sign-in prompts.',
      'Click your cookie export extension icon while on the x.com or twitter.com tab.',
      'Export cookies as Netscape format. Key session cookies include "auth_token" and "ct0".',
      'Upload the .txt file or paste the Netscape text into the Twitter / X section below.',
    ],
  },
  youtube: {
    name: 'YouTube',
    domain: 'youtube.com',
    keyCookies: ['SID', '__Secure-1PSID', 'LOGIN_INFO'],
    whyNeeded: 'Bypasses YouTube bot verification checks, age-restricted video locks, and private video restrictions.',
    steps: [
      'Open a new tab and sign into your Google account at https://www.youtube.com.',
      'Ensure your account can watch age-restricted videos without additional verification.',
      'Click your cookie export extension icon while on the youtube.com tab.',
      'Export the cookies in Netscape format (contains "SID", "__Secure-1PSID", or "LOGIN_INFO").',
      'Upload the cookies.txt file or paste the text into the YouTube section below.',
    ],
  },
};

const RECOMMENDED_EXTENSIONS = [
  {
    name: 'Get cookies.txt LOCALLY',
    browser: 'Chrome / Firefox / Edge / Brave',
    desc: 'Recommended. Open-source, operates 100% locally with no telemetry, and exports standard Netscape HTTP format in one click.',
  },
  {
    name: 'Cookie-Editor',
    browser: 'Chrome / Firefox / Edge / Safari',
    desc: 'Versatile cookie manager. Open the extension, click the "Export" menu, and select "Netscape".',
  },
];

const PLATFORMS: { id: CookiePlatform; name: string; desc: string }[] = [
  {
    id: 'instagram',
    name: 'Instagram',
    desc: 'Crucial for stories, highlights, carousels, and private reels',
  },
  {
    id: 'twitter',
    name: 'Twitter / X',
    desc: 'Prevents rate limits and resolves high-res photos / 1080p video streams',
  },
  {
    id: 'youtube',
    name: 'YouTube',
    desc: 'Required for age-restricted videos and bot check verification',
  },
];

export const CookieSettingsModal: React.FC<CookieSettingsModalProps> = ({
  isOpen,
  onClose,
  defaultPlatform,
}) => {
  const [activeTab, setActiveTab] = useState<'cookies' | 'proxy'>('cookies');
  const [pastingPlatform, setPastingPlatform] = useState<string | null>(defaultPlatform || null);
  const [pastedContent, setPastedContent] = useState('');
  const [proxyInput, setProxyInput] = useState('');
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(
    null
  );

  // Guide accordion states - open by default so step-by-step export instructions are immediately visible
  const [isGuideOpen, setIsGuideOpen] = useState(true);
  const [expandedPlatformGuide, setExpandedPlatformGuide] = useState<string | null>(null);

  // Client Session State (from localStorage)
  const [sessionCookies, setSessionCookies] = useState<Record<string, string>>(() => getSessionCookies());
  const [sessionProxy, setSessionProxy] = useState<string | null>(() => getSessionProxy());

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadTargetPlatform, setUploadTargetPlatform] = useState<string | null>(null);

  // Read-only server status queries (for fallback display)
  const { data: serverCookieMap, isLoading: isLoadingCookies } = useCookieStatusesQuery();
  const { data: serverProxyConfig, isLoading: isLoadingProxy } = useProxyConfigQuery();

  // Sync state with localStorage changes
  useEffect(() => {
    const unsub = subscribeToSessionSettings(() => {
      setSessionCookies(getSessionCookies());
      setSessionProxy(getSessionProxy());
    });
    return unsub;
  }, []);

  // Update pastingPlatform when modal is opened for a specific platform
  useEffect(() => {
    if (isOpen && defaultPlatform) {
      setPastingPlatform(defaultPlatform);
    }
  }, [isOpen, defaultPlatform]);

  // Sync session proxy into proxy input (kept empty if using server fallback)
  useEffect(() => {
    if (sessionProxy) {
      setProxyInput(sessionProxy);
    } else {
      setProxyInput('');
    }
  }, [sessionProxy]);

  // Handle ESC key to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const showNotification = (type: 'success' | 'error', text: string) => {
    setActionMessage({ type, text });
    setTimeout(() => {
      setActionMessage((curr) => (curr?.text === text ? null : curr));
    }, 4500);
  };

  const handleUploadClick = (platform: string) => {
    setUploadTargetPlatform(platform);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
      fileInputRef.current.click();
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !uploadTargetPlatform) return;

    try {
      if (file.size > 5 * 1024 * 1024) {
        throw new Error('Cookie file exceeds maximum allowed size of 5MB');
      }

      const text = await file.text();
      const status = saveSessionCookie(uploadTargetPlatform, text);
      setSessionCookies(getSessionCookies());
      showNotification(
        'success',
        `Session cookies for ${uploadTargetPlatform} saved in browser session (${status.cookie_count} cookies)!`
      );
    } catch (err) {
      showNotification('error', err instanceof Error ? err.message : String(err));
    } finally {
      setUploadTargetPlatform(null);
    }
  };

  const handleSavePasted = (platform: string) => {
    if (!pastedContent.trim()) {
      showNotification('error', 'Cookie content cannot be empty.');
      return;
    }

    try {
      const status = saveSessionCookie(platform, pastedContent.trim());
      setSessionCookies(getSessionCookies());
      showNotification(
        'success',
        `Session cookies for ${platform} saved in browser session (${status.cookie_count} cookies)!`
      );
      setPastingPlatform(null);
      setPastedContent('');
    } catch (err) {
      showNotification('error', err instanceof Error ? err.message : String(err));
    }
  };

  const handleDeleteCookies = (platform: string) => {
    try {
      deleteSessionCookie(platform);
      setSessionCookies(getSessionCookies());
      showNotification('success', `Session cookies for ${platform} cleared from browser session.`);
    } catch (err) {
      showNotification('error', err instanceof Error ? err.message : String(err));
    }
  };

  const handleSaveProxy = () => {
    try {
      if (!proxyInput.trim()) {
        clearSessionProxy();
        setSessionProxy(null);
        showNotification('success', 'Session proxy cleared. Using server configuration.');
        return;
      }

      saveSessionProxy(proxyInput.trim());
      setSessionProxy(proxyInput.trim());
      showNotification(
        'success',
        'Session proxy saved to browser localStorage. Applied to inspection & download requests.'
      );
    } catch (err) {
      showNotification('error', err instanceof Error ? err.message : String(err));
    }
  };

  const handleClearProxy = () => {
    try {
      clearSessionProxy();
      setSessionProxy(null);
      setProxyInput('');
      showNotification('success', 'Session proxy cleared. Requests will fall back to server configuration.');
    } catch (err) {
      showNotification('error', err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Hidden file input for cookie upload */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt"
          onChange={handleFileChange}
          className="hidden"
        />

        {/* Modal Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              <Shield className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-100">Settings & Authentication</h2>
              <p className="text-xs text-slate-400">
                Session-based Netscape cookies & proxy routing (stored locally in your browser)
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs Bar */}
        <div className="flex border-b border-slate-800 bg-slate-950/50 px-5 pt-2">
          <button
            type="button"
            onClick={() => setActiveTab('cookies')}
            className={cn(
              'flex items-center gap-2 py-2.5 px-4 text-xs font-semibold border-b-2 transition-all',
              activeTab === 'cookies'
                ? 'border-indigo-500 text-indigo-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            )}
          >
            <Cookie className="w-3.5 h-3.5" />
            <span>Platform Cookies</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('proxy')}
            className={cn(
              'flex items-center gap-2 py-2.5 px-4 text-xs font-semibold border-b-2 transition-all',
              activeTab === 'proxy'
                ? 'border-indigo-500 text-indigo-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            )}
          >
            <Server className="w-3.5 h-3.5" />
            <span>Proxy Configuration</span>
          </button>
        </div>

        {/* Global Notification Banner */}
        {actionMessage && (
          <div
            className={cn(
              'px-5 py-2.5 text-xs flex items-center gap-2 border-b transition-all',
              actionMessage.type === 'success'
                ? 'bg-emerald-950/30 text-emerald-300 border-emerald-500/30'
                : 'bg-rose-950/30 text-rose-300 border-rose-500/30'
            )}
          >
            {actionMessage.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            )}
            <span>{actionMessage.text}</span>
          </div>
        )}

        {/* Tab Content Body */}
        <div className="p-5 overflow-y-auto space-y-6">
          {activeTab === 'cookies' && (
            <div className="space-y-4">
              {/* Session Storage Notice */}
              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-slate-300 flex items-start gap-2.5">
                <Info className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <span className="font-semibold text-slate-200">
                    Client Session Isolation:
                  </span>
                  <p className="text-slate-400 leading-relaxed">
                    Cookies added here are saved safely in your browser’s <code className="text-indigo-300">localStorage</code>.
                    They are transmitted with your inspection and download requests without modifying or overwriting server configuration.
                    If omitted, the server falls back to server-side cookies.
                  </p>
                </div>
              </div>

              {/* In-Modal Step-by-Step Cookie Retrieval Instructions Accordion */}
              <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 overflow-hidden transition-all">
                <button
                  type="button"
                  onClick={() => setIsGuideOpen(!isGuideOpen)}
                  className="w-full p-3.5 flex items-center justify-between text-left hover:bg-indigo-950/30 transition-colors"
                >
                  <div className="flex items-center gap-2.5">
                    <BookOpen className="w-4 h-4 text-indigo-400" />
                    <div>
                      <span className="text-xs font-semibold text-indigo-200">
                        How to Obtain Netscape-Format Cookie Files
                      </span>
                      <p className="text-[11px] text-slate-400">
                        Step-by-step export instructions for Instagram, Twitter/X, and YouTube
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-indigo-300">
                    <span>{isGuideOpen ? 'Hide Guide' : 'Show Instructions'}</span>
                    {isGuideOpen ? (
                      <ChevronUp className="w-4 h-4 text-indigo-400" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-indigo-400" />
                    )}
                  </div>
                </button>

                {isGuideOpen && (
                  <div className="p-4 pt-1 border-t border-indigo-500/20 space-y-4 text-xs text-slate-300 animate-in fade-in duration-200">
                    {/* Recommended Extensions */}
                    <div className="space-y-2">
                      <span className="text-[11px] font-bold text-slate-200 uppercase tracking-wider block">
                        Recommended Browser Extensions:
                      </span>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {RECOMMENDED_EXTENSIONS.map((ext) => (
                          <div
                            key={ext.name}
                            className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 space-y-1"
                          >
                            <div className="font-semibold text-slate-200 flex items-center justify-between">
                              <span>{ext.name}</span>
                              <span className="text-[10px] text-indigo-400 font-normal">
                                {ext.browser}
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-400 leading-relaxed">
                              {ext.desc}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Platform-Specific Step-by-Step Instructions */}
                    <div className="space-y-3 pt-2">
                      <span className="text-[11px] font-bold text-slate-200 uppercase tracking-wider block">
                        Platform Instructions:
                      </span>

                      {PLATFORMS.map(({ id }) => {
                        const guide = PLATFORM_GUIDES[id];
                        return (
                          <div
                            key={id}
                            className="p-3 rounded-lg bg-slate-900/90 border border-slate-800 space-y-2"
                          >
                            <div className="flex items-center justify-between">
                              <span className="font-semibold text-xs text-slate-100 flex items-center gap-1.5">
                                <Key className="w-3.5 h-3.5 text-indigo-400" />
                                {guide.name} ({guide.domain})
                              </span>
                              <span className="text-[10px] font-mono text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded">
                                Key cookies: {guide.keyCookies.join(', ')}
                              </span>
                            </div>

                            <p className="text-[11px] text-slate-400">{guide.whyNeeded}</p>

                            <ol className="list-decimal list-inside space-y-1 text-[11px] text-slate-300 leading-relaxed pl-1">
                              {guide.steps.map((step, idx) => (
                                <li key={idx} className="pl-1">
                                  <span>{step}</span>
                                </li>
                              ))}
                            </ol>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {isLoadingCookies ? (
                <div className="flex items-center justify-center p-8 text-slate-400 gap-2">
                  <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
                  <span className="text-sm">Reading cookie status...</span>
                </div>
              ) : (
                <div className="space-y-3">
                  {PLATFORMS.map(({ id, name, desc }) => {
                    const sessionCookieContent =
                      sessionCookies[id] || (id === 'twitter' ? sessionCookies['x'] : undefined);
                    const hasSessionCookie = Boolean(sessionCookieContent);
                    const sessionStatus = hasSessionCookie
                      ? evaluateCookieContent(id, sessionCookieContent)
                      : null;
                    const serverStatus = serverCookieMap?.[id];
                    const isPasting = pastingPlatform === id;
                    const isGuideExpanded = expandedPlatformGuide === id;

                    return (
                      <div
                        key={id}
                        className="p-4 rounded-xl border border-slate-800 bg-slate-950/60 space-y-3 transition-colors"
                      >
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-sm text-slate-100">{name}</span>

                              {/* Status Badge */}
                              {hasSessionCookie && sessionStatus ? (
                                sessionStatus.valid ? (
                                  <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                                    <CheckCircle2 className="w-3 h-3" />
                                    Session Active ({sessionStatus.cookie_count} cookies)
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1">
                                    <AlertCircle className="w-3 h-3" />
                                    Session Expired
                                  </span>
                                )
                              ) : serverStatus?.exists ? (
                                serverStatus.valid ? (
                                  <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/30 flex items-center gap-1">
                                    <CheckCircle2 className="w-3 h-3" />
                                    Server Fallback ({serverStatus.cookie_count} cookies)
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-800 text-slate-400 border border-slate-700 flex items-center gap-1">
                                    <AlertCircle className="w-3 h-3" />
                                    Server Expired
                                  </span>
                                )
                              ) : (
                                <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">
                                  Missing
                                </span>
                              )}
                            </div>

                            <p className="text-xs text-slate-400 mt-0.5">{desc}</p>
                          </div>

                          {/* Action Buttons for this platform */}
                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            {/* Toggle Inline Help */}
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedPlatformGuide(isGuideExpanded ? null : id)
                              }
                              className={cn(
                                'px-2 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1 transition-colors',
                                isGuideExpanded
                                  ? 'border-indigo-500/50 bg-indigo-500/10 text-indigo-300'
                                  : 'border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                              )}
                              title="How to get cookies for this platform"
                            >
                              <HelpCircle className="w-3.5 h-3.5" />
                              <span className="hidden sm:inline">Guide</span>
                            </button>

                            <button
                              type="button"
                              onClick={() => handleUploadClick(id)}
                              className="px-2.5 py-1.5 rounded-lg border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs font-medium flex items-center gap-1.5 transition-colors"
                              title="Upload .txt cookie file into session"
                            >
                              <Upload className="w-3.5 h-3.5 text-indigo-400" />
                              <span>Upload</span>
                            </button>

                            <button
                              type="button"
                              onClick={() => {
                                setPastingPlatform(isPasting ? null : id);
                                setPastedContent('');
                              }}
                              className={cn(
                                'px-2.5 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1.5 transition-colors',
                                isPasting
                                  ? 'border-indigo-500 bg-indigo-500/20 text-indigo-300'
                                  : 'border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700'
                              )}
                              title="Paste Netscape cookie text into session"
                            >
                              <FileText className="w-3.5 h-3.5 text-indigo-400" />
                              <span>{isPasting ? 'Cancel' : 'Paste'}</span>
                            </button>

                            {hasSessionCookie && (
                              <button
                                type="button"
                                onClick={() => handleDeleteCookies(id)}
                                className="p-1.5 rounded-lg border border-slate-800 bg-slate-900 text-slate-400 hover:text-rose-400 hover:border-rose-500/30 transition-colors"
                                title="Clear session cookies"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </div>

                        {/* Inline Platform Retrieval Steps Drawer */}
                        {isGuideExpanded && (
                          <div className="p-3 rounded-lg bg-slate-900 border border-indigo-500/20 space-y-2 text-xs animate-in fade-in duration-150">
                            <div className="flex items-center justify-between text-indigo-300 font-semibold text-[11px]">
                              <span>How to retrieve {PLATFORM_GUIDES[id].name} cookies:</span>
                              <span className="font-mono text-[10px] text-slate-400">
                                Domain: {PLATFORM_GUIDES[id].domain}
                              </span>
                            </div>
                            <ol className="list-decimal list-inside space-y-1 text-[11px] text-slate-300 pl-1 leading-relaxed">
                              {PLATFORM_GUIDES[id].steps.map((st, i) => (
                                <li key={i}>{st}</li>
                              ))}
                            </ol>
                          </div>
                        )}

                        {/* Status detail line */}
                        <div className="text-[11px] text-slate-400 font-mono bg-slate-900/60 p-2 rounded-md border border-slate-800/80 flex items-center justify-between">
                          <span>
                            {hasSessionCookie && sessionStatus
                              ? sessionStatus.details
                              : serverStatus?.exists
                                ? `Fallback: ${serverStatus.details}`
                                : 'No session or server cookies configured'}
                          </span>
                          <span className="text-[10px] text-slate-500 uppercase tracking-wider ml-2 flex-shrink-0">
                            {hasSessionCookie ? 'Session (localStorage)' : 'Server Fallback'}
                          </span>
                        </div>

                        {/* Paste text area drawer */}
                        {isPasting && (
                          <div className="pt-2 border-t border-slate-800/80 space-y-2 animate-in fade-in duration-200">
                            <label className="text-xs font-medium text-slate-300 block">
                              Paste Netscape cookie contents for {name}:
                            </label>
                            <textarea
                              rows={4}
                              value={pastedContent}
                              onChange={(e) => setPastedContent(e.target.value)}
                              placeholder="# Netscape HTTP Cookie File&#10;.instagram.com&#9;TRUE&#9;/&#9;TRUE&#9;1750000000&#9;sessionid&#9;..."
                              className="w-full p-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-mono text-slate-200 placeholder-slate-500 outline-none focus:border-indigo-500"
                            />
                            <div className="flex justify-end gap-2">
                              <button
                                type="button"
                                onClick={() => setPastingPlatform(null)}
                                className="px-3 py-1.5 rounded-lg border border-slate-700 text-xs text-slate-300 hover:bg-slate-800"
                              >
                                Cancel
                              </button>
                              <button
                                type="button"
                                onClick={() => handleSavePasted(id)}
                                disabled={!pastedContent.trim()}
                                className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white flex items-center gap-1.5 disabled:opacity-50"
                              >
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                <span>Save to Session</span>
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {activeTab === 'proxy' && (
            <div className="space-y-5">
              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-slate-300 flex items-start gap-2.5">
                <Server className="w-4 h-4 text-sky-400 flex-shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <span className="font-semibold text-slate-200">
                    Session-Based Proxy Routing:
                  </span>
                  <p className="text-slate-400 leading-relaxed">
                    Set a proxy for your client session in <code className="text-sky-300">localStorage</code>.
                    This setting will accompany your inspection and download requests without modifying or overwriting server configuration.
                    If cleared, requests will fall back to server configuration.
                  </p>
                </div>
              </div>

              {isLoadingProxy ? (
                <div className="flex items-center justify-center p-8 text-slate-400 gap-2">
                  <Loader2 className="w-5 h-5 animate-spin text-sky-400" />
                  <span className="text-sm">Loading proxy settings...</span>
                </div>
              ) : (
                <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/60 space-y-4">
                  {/* Current Proxy Configuration Details */}
                  <div className="flex items-center justify-between text-xs pb-3 border-b border-slate-800">
                    <span className="text-slate-400">Current Configuration:</span>
                    <span className="px-2 py-0.5 rounded-full font-mono font-medium text-[11px] bg-slate-800 text-slate-300 border border-slate-700">
                      {sessionProxy
                        ? 'Source: Client Session (localStorage)'
                        : serverProxyConfig?.proxy
                          ? `Source: Server Default (${serverProxyConfig.proxy})`
                          : 'Source: Server Default (none)'}
                    </span>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-slate-200 block">
                      Proxy URL
                    </label>
                    <input
                      type="text"
                      value={proxyInput}
                      onChange={(e) => setProxyInput(e.target.value)}
                      placeholder={
                        serverProxyConfig?.proxy
                          ? `Server fallback: ${serverProxyConfig.proxy}`
                          : 'socks5://127.0.0.1:9050'
                      }
                      className="w-full py-2.5 px-3 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-slate-200 placeholder-slate-500 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/20"
                    />
                    <p className="text-[11px] text-slate-400">
                      Supported schemes: <code className="text-slate-300">socks5://</code>,{' '}
                      <code className="text-slate-300">socks5h://</code>,{' '}
                      <code className="text-slate-300">http://</code>,{' '}
                      <code className="text-slate-300">https://</code>
                    </p>
                  </div>

                  <div className="flex items-center justify-end gap-2 pt-2">
                    {sessionProxy && (
                      <button
                        type="button"
                        onClick={handleClearProxy}
                        className="px-3.5 py-2 rounded-xl border border-slate-700 text-xs font-medium text-slate-300 hover:bg-slate-800 transition-colors"
                      >
                        Clear Session Proxy
                      </button>
                    )}

                    <button
                      type="button"
                      onClick={handleSaveProxy}
                      className="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-xs font-medium text-white flex items-center gap-1.5 shadow-md shadow-sky-600/20 transition-all"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Apply to Session</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between text-xs text-slate-400">
          <span>Settings are saved in your browser session and sent per request</span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 font-medium transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
