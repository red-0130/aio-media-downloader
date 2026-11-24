import React, { useState } from 'react';
import {
  Card,
  VStack,
  HStack,
  StackItem,
  TextInput,
  Button,
  Text,
  useMediaQuery,
} from '@astryxdesign/core';
import {
  Search,
  Clipboard,
  Check,
  Sparkles,
  Youtube,
  Instagram,
  Twitter,
  Music2,
} from 'lucide-react';

export interface UrlInputProps {
  url: string;
  onChange: (url: string) => void;
  onInspect: () => void;
  isLoading: boolean;
  disabled?: boolean;
  isMobile?: boolean;
}

export interface PlatformPill {
  name: string;
  domain: string;
  icon: React.ReactNode;
}

export const PLATFORMS: PlatformPill[] = [
  {
    name: 'YouTube',
    domain: 'https://www.youtube.com/watch?v=',
    icon: <Youtube className="w-3.5 h-3.5 text-rose-400" />,
  },
  {
    name: 'Instagram',
    domain: 'https://www.instagram.com/p/',
    icon: <Instagram className="w-3.5 h-3.5 text-pink-400" />,
  },
  {
    name: 'Twitter / X',
    domain: 'https://x.com/user/status/',
    icon: <Twitter className="w-3.5 h-3.5 text-sky-400" />,
  },
  {
    name: 'TikTok',
    domain: 'https://www.tiktok.com/@user/video/',
    icon: <Music2 className="w-3.5 h-3.5 text-teal-400" />,
  },
];

export function canTriggerInspect(url: string, isLoading: boolean): boolean {
  return !isLoading && Boolean(url && url.trim().length > 0);
}

export function handleInspectSubmit(
  url: string,
  isLoading: boolean,
  onInspect: () => void
): boolean {
  if (canTriggerInspect(url, isLoading)) {
    onInspect();
    return true;
  }
  return false;
}

export function handleInputKeyDown(
  e: { key: string; preventDefault: () => void },
  url: string,
  isLoading: boolean,
  onInspect: () => void
): boolean {
  if (e.key === 'Enter' && canTriggerInspect(url, isLoading)) {
    e.preventDefault();
    onInspect();
    return true;
  }
  return false;
}

export function handlePillClick(
  domain: string,
  url: string,
  onChange: (url: string) => void
): boolean {
  if (!url || !url.trim()) {
    onChange(domain);
    const inputEl = typeof document !== 'undefined' ? document.getElementById('media-url-input') : null;
    inputEl?.focus();
    return true;
  }
  return false;
}

export const UrlInput: React.FC<UrlInputProps> = ({
  url,
  onChange,
  onInspect,
  isLoading,
  disabled = false,
  isMobile: isMobileProp,
}) => {
  const mediaQueryIsMobile = useMediaQuery('(max-width: 768px)');
  const isMobile = isMobileProp ?? mediaQueryIsMobile;
  const [pasteSuccess, setPasteSuccess] = useState(false);

  const onSubmit = () => {
    handleInspectSubmit(url, isLoading, onInspect);
  };

  const handlePaste = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.readText) {
        const text = await navigator.clipboard.readText();
        if (text) {
          onChange(text.trim());
          setPasteSuccess(true);
          setTimeout(() => setPasteSuccess(false), 1500);
          return;
        }
      }
    } catch {
      // Clipboard read failed or permission denied; gracefully fall through to focus input
    }
    const inputEl = typeof document !== 'undefined' ? document.getElementById('media-url-input') : null;
    inputEl?.focus();
  };

  const onPillClick = (domain: string) => {
    handlePillClick(domain, url, onChange);
  };

  return (
    <Card padding={3} elevation="med" width="100%">
      <VStack gap={3} width="100%">
        {/* Main Input Control Bar */}
        {isMobile ? (
          <VStack gap={2} width="100%">
            <TextInput
              id="media-url-input"
              label="Media URL"
              isLabelHidden
              placeholder="Paste video, reel, story, or post URL..."
              value={url}
              onChange={(val) => onChange(val)}
              onEnter={onSubmit}
              hasClear
              isDisabled={disabled || isLoading}
              startIcon={<Search className="w-4 h-4 text-indigo-400" />}
              width="100%"
            />

            <HStack gap={2} align="center" width="100%">
              <StackItem size="static">
                <Button
                  variant="secondary"
                  size="md"
                  icon={
                    pasteSuccess ? (
                      <Check className="w-4 h-4 text-emerald-400" />
                    ) : (
                      <Clipboard className="w-4 h-4 text-indigo-400" />
                    )
                  }
                  label={pasteSuccess ? 'Pasted' : 'Paste'}
                  onClick={handlePaste}
                  isDisabled={disabled || isLoading}
                />
              </StackItem>

              <StackItem size="fill">
                <Button
                  variant="primary"
                  size="md"
                  icon={<Sparkles className="w-4 h-4" />}
                  label={isLoading ? 'Inspecting...' : 'Inspect Link'}
                  isLoading={isLoading}
                  isDisabled={disabled || isLoading || !url.trim()}
                  onClick={onSubmit}
                  width="100%"
                />
              </StackItem>
            </HStack>
          </VStack>
        ) : (
          <HStack gap={2} align="center" width="100%">
            <StackItem size="fill">
              <TextInput
                id="media-url-input"
                label="Media URL"
                isLabelHidden
                placeholder="Paste video, reel, story, or post URL (YouTube, Instagram, Twitter/X, TikTok)..."
                value={url}
                onChange={(val) => onChange(val)}
                onEnter={onSubmit}
                hasClear
                isDisabled={disabled || isLoading}
                startIcon={<Search className="w-4 h-4 text-indigo-400" />}
                width="100%"
              />
            </StackItem>

            <StackItem size="static">
              <Button
                variant="secondary"
                size="md"
                icon={
                  pasteSuccess ? (
                    <Check className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Clipboard className="w-4 h-4 text-indigo-400" />
                  )
                }
                label={pasteSuccess ? 'Pasted' : 'Paste'}
                onClick={handlePaste}
                isDisabled={disabled || isLoading}
              />
            </StackItem>

            <StackItem size="static">
              <Button
                variant="primary"
                size="md"
                icon={<Sparkles className="w-4 h-4" />}
                label={isLoading ? 'Inspecting...' : 'Inspect Link'}
                isLoading={isLoading}
                isDisabled={disabled || isLoading || !url.trim()}
                onClick={onSubmit}
              />
            </StackItem>
          </HStack>
        )}

        {/* Quick Platform Presets */}
        <HStack
          gap={2}
          align="center"
          justify={isMobile ? 'center' : 'start'}
          width="100%"
          wrap="wrap"
        >
          {!isMobile && (
            <Text type="supporting" color="secondary">
              Supported platforms:
            </Text>
          )}
          {PLATFORMS.map((p) => (
            <Button
              key={p.name}
              variant="ghost"
              size="sm"
              icon={p.icon}
              label={p.name}
              isIconOnly={isMobile}
              tooltip={p.name}
              onClick={() => onPillClick(p.domain)}
              isDisabled={disabled || isLoading}
            />
          ))}
        </HStack>
      </VStack>
    </Card>
  );
};
