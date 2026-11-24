import React, { useEffect, useRef, useState } from 'react';
import {
  Dialog,
  BottomSheet,
  Card,
  VStack,
  HStack,
  Heading,
  Text,
  Badge,
  Token,
  Button,
  Banner,
  SegmentedControl,
  SegmentedControlItem,
  TextInput,
  TextArea,
  useMediaQuery,
} from '@astryxdesign/core';
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

export interface CookieSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultPlatform?: string;
  defaultTab?: 'cookies' | 'proxy';
  presentation?: 'dialog' | 'bottom-sheet';
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
  defaultTab = 'cookies',
  presentation,
}) => {
  const isMobile = useMediaQuery('(max-width: 768px)');
  const resolvedPresentation = presentation ?? (isMobile ? 'bottom-sheet' : 'dialog');
  const [activeTab, setActiveTab] = useState<'cookies' | 'proxy'>(defaultTab);

  useEffect(() => {
    if (isOpen && defaultTab) {
      setActiveTab(defaultTab);
    }
  }, [isOpen, defaultTab]);

  const [pastingPlatform, setPastingPlatform] = useState<string | null>(defaultPlatform || null);
  const [pastedContent, setPastedContent] = useState('');
  const [proxyInput, setProxyInput] = useState('');
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(
    null
  );

  // Guide accordion states
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

  // Sync session proxy into proxy input
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

  const modalContent = (
    <Card padding={4} variant="transparent" width="100%">
      <VStack gap={4} width="100%">
        {/* Modal Header */}
          <HStack gap={2} align="center" justify="between" width="100%">
            <HStack gap={3} align="center">
              <Shield className="w-5 h-5 text-indigo-400" />
              <VStack gap={0}>
                <Heading level={2}>
                  Settings & Authentication
                </Heading>
                <Text type="supporting" color="secondary">
                  Session-based Netscape cookies & proxy routing (stored locally in your browser)
                </Text>
              </VStack>
            </HStack>

            <Button
              variant="ghost"
              size="sm"
              isIconOnly
              icon={<X className="w-4 h-4" />}
              label="Close settings"
              onClick={onClose}
            />
          </HStack>

          {/* Navigation Tabs (Platform Cookies vs Proxy) */}
          <SegmentedControl
            label="Settings Categories"
            value={activeTab}
            onChange={(val) => setActiveTab(val as 'cookies' | 'proxy')}
            layout="fill"
          >
            <SegmentedControlItem
              value="cookies"
              label="Platform Cookies"
              icon={<Cookie className="w-4 h-4 text-indigo-400" />}
            />
            <SegmentedControlItem
              value="proxy"
              label="Proxy Configuration"
              icon={<Server className="w-4 h-4 text-sky-400" />}
            />
          </SegmentedControl>

          {/* Notification Banner */}
          {actionMessage && (
            <Banner
              status={actionMessage.type === 'success' ? 'success' : 'error'}
              title={actionMessage.text}
            />
          )}

          {/* Tab 1: Platform Cookies */}
          {activeTab === 'cookies' && (
            <VStack gap={4} width="100%">
              {/* Session Storage Notice */}
              <Card padding={3} variant="muted" width="100%">
                <HStack gap={2} align="start" width="100%">
                  <Info className="w-4 h-4 text-indigo-400" />
                  <VStack gap={1} width="100%">
                    <Text weight="semibold">
                      Client Session Isolation:
                    </Text>
                    <Text type="supporting" color="secondary">
                      Cookies added here are saved safely in your browser’s localStorage. They are transmitted with your inspection and download requests without modifying or overwriting server configuration. If omitted, the server falls back to server-side cookies.
                    </Text>
                  </VStack>
                </HStack>
              </Card>

              {/* In-Modal Step-by-Step Cookie Retrieval Guidance */}
              <Card padding={3} variant="muted" width="100%">
                <VStack gap={3} width="100%">
                  <HStack gap={2} align="center" justify="between" width="100%">
                    <HStack gap={2} align="center">
                      <BookOpen className="w-4 h-4 text-indigo-400" />
                      <VStack gap={0}>
                        <Text weight="semibold">
                          How to Obtain Netscape-Format Cookie Files
                        </Text>
                        <Text type="supporting" color="secondary">
                          Step-by-step export instructions for Instagram, Twitter/X, and YouTube
                        </Text>
                      </VStack>
                    </HStack>

                    <Button
                      variant="ghost"
                      size="sm"
                      icon={isGuideOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                      label={isGuideOpen ? 'Hide Guide' : 'Show Instructions'}
                      onClick={() => setIsGuideOpen(!isGuideOpen)}
                    />
                  </HStack>

                  {isGuideOpen && (
                    <VStack gap={3} width="100%">
                      {/* Recommended Extensions */}
                      <VStack gap={2} width="100%">
                        <Text weight="semibold">
                          Recommended Browser Extensions
                        </Text>
                        <HStack gap={2} wrap="wrap" width="100%">
                          {RECOMMENDED_EXTENSIONS.map((ext) => (
                            <Card key={ext.name} padding={2} variant="default" width="100%">
                              <VStack gap={1} width="100%">
                                <HStack gap={2} align="center" justify="between">
                                  <Text weight="semibold">
                                    {ext.name}
                                  </Text>
                                  <Token size="sm" color="cyan" label={ext.browser} />
                                </HStack>
                                <Text type="supporting" color="secondary">
                                  {ext.desc}
                                </Text>
                              </VStack>
                            </Card>
                          ))}
                        </HStack>
                      </VStack>

                      {/* Platform-Specific Step-by-Step Instructions */}
                      <VStack gap={2} width="100%">
                        <Text weight="semibold">
                          Platform Instructions:
                        </Text>
                        {PLATFORMS.map(({ id }) => {
                          const guide = PLATFORM_GUIDES[id];
                          return (
                            <Card key={id} padding={3} variant="default" width="100%">
                              <VStack gap={2} width="100%">
                                <HStack gap={2} align="center" justify="between">
                                  <HStack gap={1} align="center">
                                    <Key className="w-3.5 h-3.5 text-indigo-400" />
                                    <Text weight="semibold">
                                      {guide.name} ({guide.domain})
                                    </Text>
                                  </HStack>
                                  <Badge
                                    variant="purple"
                                    label={`Key cookies: ${guide.keyCookies.join(', ')}`}
                                  />
                                </HStack>

                                <Text type="supporting" color="secondary">
                                  {guide.whyNeeded}
                                </Text>

                                <VStack gap={1} width="100%">
                                  {guide.steps.map((step, idx) => (
                                    <HStack key={idx} gap={2} align="start">
                                      <Badge variant="neutral" label={`${idx + 1}`} />
                                      <Text type="supporting" color="secondary">
                                        {step}
                                      </Text>
                                    </HStack>
                                  ))}
                                </VStack>
                              </VStack>
                            </Card>
                          );
                        })}
                      </VStack>
                    </VStack>
                  )}
                </VStack>
              </Card>

              {/* Platform Cookie Manager Cards */}
              {isLoadingCookies ? (
                <HStack gap={2} align="center" justify="center" width="100%">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                  <Text type="supporting" color="secondary">
                    Reading cookie status...
                  </Text>
                </HStack>
              ) : (
                <VStack gap={3} width="100%">
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
                      <Card key={id} padding={3} variant="default" width="100%">
                        <VStack gap={3} width="100%">
                          <HStack gap={2} align="center" justify="between" width="100%" wrap="wrap">
                            <VStack gap={0}>
                              <HStack gap={2} align="center">
                                <Heading level={4}>
                                  {name}
                                </Heading>

                                {/* Session / Server Status Badge */}
                                {hasSessionCookie && sessionStatus ? (
                                  sessionStatus.valid ? (
                                    <Badge
                                      variant="success"
                                      icon={<CheckCircle2 className="w-3 h-3" />}
                                      label={`Session Active (${sessionStatus.cookie_count} cookies)`}
                                    />
                                  ) : (
                                    <Badge
                                      variant="warning"
                                      icon={<AlertCircle className="w-3 h-3" />}
                                      label="Session Expired"
                                    />
                                  )
                                ) : serverStatus?.exists ? (
                                  serverStatus.valid ? (
                                    <Badge
                                      variant="info"
                                      icon={<CheckCircle2 className="w-3 h-3" />}
                                      label={`Server Fallback (${serverStatus.cookie_count} cookies)`}
                                    />
                                  ) : (
                                    <Badge
                                      variant="neutral"
                                      icon={<AlertCircle className="w-3 h-3" />}
                                      label="Server Expired"
                                    />
                                  )
                                ) : (
                                  <Badge variant="neutral" label="Missing" />
                                )}
                              </HStack>
                              <Text type="supporting" color="secondary">
                                {desc}
                              </Text>
                            </VStack>

                            {/* Action Buttons */}
                            <HStack gap={1} align="center">
                              <Button
                                variant={isGuideExpanded ? 'secondary' : 'ghost'}
                                size="sm"
                                icon={<HelpCircle className="w-3.5 h-3.5" />}
                                label="Guide"
                                onClick={() =>
                                  setExpandedPlatformGuide(isGuideExpanded ? null : id)
                                }
                              />
                              <Button
                                variant="secondary"
                                size="sm"
                                icon={<Upload className="w-3.5 h-3.5 text-indigo-400" />}
                                label="Upload"
                                onClick={() => handleUploadClick(id)}
                              />
                              <Button
                                variant={isPasting ? 'primary' : 'secondary'}
                                size="sm"
                                icon={<FileText className="w-3.5 h-3.5 text-indigo-400" />}
                                label={isPasting ? 'Cancel' : 'Paste'}
                                onClick={() => {
                                  setPastingPlatform(isPasting ? null : id);
                                  setPastedContent('');
                                }}
                              />
                              {hasSessionCookie && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  isIconOnly
                                  icon={<Trash2 className="w-3.5 h-3.5 text-rose-400" />}
                                  label={`Clear ${name} session cookies`}
                                  onClick={() => handleDeleteCookies(id)}
                                />
                              )}
                            </HStack>
                          </HStack>

                          {/* Expanded Step Guide */}
                          {isGuideExpanded && (
                            <Card padding={2} variant="muted" width="100%">
                              <VStack gap={2} width="100%">
                                <HStack gap={2} align="center" justify="between">
                                  <Text weight="semibold">
                                    How to retrieve {PLATFORM_GUIDES[id].name} cookies:
                                  </Text>
                                  <Text type="supporting" color="secondary">
                                    Domain: {PLATFORM_GUIDES[id].domain}
                                  </Text>
                                </HStack>
                                <VStack gap={1} width="100%">
                                  {PLATFORM_GUIDES[id].steps.map((st, i) => (
                                    <Text key={i} type="supporting" color="secondary">
                                      {i + 1}. {st}
                                    </Text>
                                  ))}
                                </VStack>
                              </VStack>
                            </Card>
                          )}

                          {/* Status Detail Note */}
                          <HStack gap={2} align="center" justify="between" width="100%">
                            <Text type="supporting" color="secondary">
                              {hasSessionCookie && sessionStatus
                                ? sessionStatus.details
                                : serverStatus?.exists
                                ? `Fallback: ${serverStatus.details}`
                                : 'No session or server cookies configured'}
                            </Text>
                            <Badge
                              variant="neutral"
                              label={hasSessionCookie ? 'Session (localStorage)' : 'Server Fallback'}
                            />
                          </HStack>

                          {/* Paste Drawer */}
                          {isPasting && (
                            <VStack gap={2} width="100%">
                              <TextArea
                                label={`Paste Netscape cookie contents for ${name}`}
                                value={pastedContent}
                                onChange={(val) => setPastedContent(val)}
                                placeholder="# Netscape HTTP Cookie File&#10;.instagram.com&#9;TRUE&#9;/&#9;TRUE&#9;1750000000&#9;sessionid&#9;..."
                                rows={4}
                                width="100%"
                              />
                              <HStack gap={2} align="center" justify="end" width="100%">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  label="Cancel"
                                  onClick={() => setPastingPlatform(null)}
                                />
                                <Button
                                  variant="primary"
                                  size="sm"
                                  icon={<CheckCircle2 className="w-3.5 h-3.5" />}
                                  label="Save to Session"
                                  isDisabled={!pastedContent.trim()}
                                  onClick={() => handleSavePasted(id)}
                                />
                              </HStack>
                            </VStack>
                          )}
                        </VStack>
                      </Card>
                    );
                  })}
                </VStack>
              )}
            </VStack>
          )}

          {/* Tab 2: Proxy Configuration */}
          {activeTab === 'proxy' && (
            <VStack gap={4} width="100%">
              {/* Proxy Explanation Notice */}
              <Card padding={3} variant="muted" width="100%">
                <HStack gap={2} align="start" width="100%">
                  <Server className="w-4 h-4 text-sky-400" />
                  <VStack gap={1} width="100%">
                    <Text weight="semibold">
                      Session-Based Proxy Routing:
                    </Text>
                    <Text type="supporting" color="secondary">
                      Set a proxy for your client session in localStorage. This setting will accompany your inspection and download requests without modifying or overwriting server configuration. If cleared, requests will fall back to server configuration.
                    </Text>
                  </VStack>
                </HStack>
              </Card>

              {isLoadingProxy ? (
                <HStack gap={2} align="center" justify="center" width="100%">
                  <Loader2 className="w-4 h-4 animate-spin text-sky-400" />
                  <Text type="supporting" color="secondary">
                    Loading proxy settings...
                  </Text>
                </HStack>
              ) : (
                <Card padding={4} variant="default" width="100%">
                  <VStack gap={3} width="100%">
                    {/* Status Badge */}
                    <HStack gap={2} align="center" justify="between" width="100%">
                      <Text type="supporting" color="secondary">
                        Current Configuration:
                      </Text>
                      <Badge
                        variant="info"
                        label={
                          sessionProxy
                            ? 'Source: Client Session (localStorage)'
                            : serverProxyConfig?.source === 'env' || serverProxyConfig?.proxy
                            ? 'Source: Server Default (configured)'
                            : 'Source: Server Default (none)'
                        }
                      />
                    </HStack>

                    <TextInput
                      label="Proxy URL"
                      placeholder="e.g. socks5://host:port or http://host:port"
                      value={proxyInput}
                      onChange={(val) => setProxyInput(val)}
                      width="100%"
                    />

                    <Text type="supporting" color="secondary">
                      Supported schemes: socks5://, socks5h://, http://, https://
                    </Text>

                    <HStack gap={2} align="center" justify="end" width="100%">
                      {sessionProxy && (
                        <Button
                          variant="ghost"
                          size="sm"
                          label="Clear Session Proxy"
                          onClick={handleClearProxy}
                        />
                      )}
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<CheckCircle2 className="w-3.5 h-3.5" />}
                        label="Apply to Session"
                        onClick={handleSaveProxy}
                      />
                    </HStack>
                  </VStack>
                </Card>
              )}
            </VStack>
          )}

          {/* Modal Footer */}
          <HStack gap={2} align="center" justify="between" width="100%">
            <Text type="supporting" color="secondary">
              Settings are saved in your browser session and sent per request
            </Text>
            <Button
              variant="secondary"
              size="sm"
              label="Close"
              onClick={onClose}
            />
          </HStack>
        </VStack>
      </Card>
  );

  if (resolvedPresentation === 'bottom-sheet') {
    return (
      <BottomSheet
        isOpen={isOpen}
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        label="Settings & Authentication"
        height="tall"
      >
        {/* Hidden file input for cookie upload */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        {modalContent}
      </BottomSheet>
    );
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      width={680}
      maxHeight="88dvh"
      purpose="info"
    >
      {/* Hidden file input for cookie upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt"
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />
      {modalContent}
    </Dialog>
  );
};
