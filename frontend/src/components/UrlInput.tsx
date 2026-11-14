import React, { useState } from 'react';
import { Search, Clipboard, X, Loader2, Youtube, Instagram, Twitter, Music2 } from 'lucide-react';
import { cn } from '../lib/utils';

export interface UrlInputProps {
  url: string;
  onChange: (url: string) => void;
  onInspect: () => void;
  isLoading: boolean;
  disabled?: boolean;
}

interface PlatformPill {
  name: string;
  domain: string;
  icon: React.ReactNode;
  activeColor: string;
}

const PLATFORMS: PlatformPill[] = [
  {
    name: 'YouTube',
    domain: 'https://www.youtube.com/watch?v=',
    icon: <Youtube className="w-3.5 h-3.5 text-red-400" />,
    activeColor: 'hover:border-red-500/50 hover:bg-red-500/10 text-red-300',
  },
  {
    name: 'Instagram',
    domain: 'https://www.instagram.com/p/',
    icon: <Instagram className="w-3.5 h-3.5 text-pink-400" />,
    activeColor: 'hover:border-pink-500/50 hover:bg-pink-500/10 text-pink-300',
  },
  {
    name: 'Twitter / X',
    domain: 'https://x.com/user/status/',
    icon: <Twitter className="w-3.5 h-3.5 text-sky-400" />,
    activeColor: 'hover:border-sky-500/50 hover:bg-sky-500/10 text-sky-300',
  },
  {
    name: 'TikTok',
    domain: 'https://www.tiktok.com/@user/video/',
    icon: <Music2 className="w-3.5 h-3.5 text-teal-400" />,
    activeColor: 'hover:border-teal-500/50 hover:bg-teal-500/10 text-teal-300',
  },
];

export const UrlInput: React.FC<UrlInputProps> = ({
  url,
  onChange,
  onInspect,
  isLoading,
  disabled = false,
}) => {
  const [pasteSuccess, setPasteSuccess] = useState(false);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !isLoading && url.trim()) {
      e.preventDefault();
      onInspect();
    }
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        onChange(text.trim());
        setPasteSuccess(true);
        setTimeout(() => setPasteSuccess(false), 1500);
      }
    } catch {
      // Clipboard read failed (e.g. permission denied or insecure context)
      // Gracefully focus input
      const inputEl = document.getElementById('media-url-input');
      inputEl?.focus();
    }
  };

  const handleClear = () => {
    onChange('');
    const inputEl = document.getElementById('media-url-input');
    inputEl?.focus();
  };

  const handlePillClick = (domain: string) => {
    if (!url) {
      onChange(domain);
      const inputEl = document.getElementById('media-url-input') as HTMLInputElement | null;
      inputEl?.focus();
    }
  };

  return (
    <div className="w-full space-y-3">
      {/* Search Input Bar */}
      <div
        className={cn(
          'relative flex items-center rounded-2xl bg-slate-900/90 border border-slate-700/80 shadow-2xl transition-all duration-200',
          'focus-within:border-indigo-500/80 focus-within:ring-2 focus-within:ring-indigo-500/20'
        )}
      >
        <div className="pl-4 text-slate-400 flex items-center pointer-events-none">
          <Search className="w-5 h-5 text-slate-400" />
        </div>

        <input
          id="media-url-input"
          type="url"
          value={url}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || isLoading}
          placeholder="Paste URL (YouTube, Instagram reels/stories, Twitter/X, TikTok...)"
          className={cn(
            'w-full py-4 pl-3 pr-28 bg-transparent text-slate-100 placeholder-slate-400 text-sm md:text-base outline-none',
            'disabled:opacity-50 disabled:cursor-not-allowed'
          )}
          aria-label="Media URL input"
          autoComplete="off"
          spellCheck={false}
        />

        {/* Clear & Paste buttons */}
        <div className="absolute right-24 md:right-28 flex items-center gap-1">
          {url && !disabled && !isLoading && (
            <button
              type="button"
              onClick={handleClear}
              aria-label="Clear URL"
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}

          <button
            type="button"
            onClick={handlePaste}
            disabled={disabled || isLoading}
            aria-label="Paste from clipboard"
            className={cn(
              'hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-slate-700 text-slate-300 hover:bg-slate-800 hover:text-slate-100 transition-colors',
              pasteSuccess && 'text-emerald-400 border-emerald-500/50 bg-emerald-500/10'
            )}
            title="Paste from clipboard"
          >
            <Clipboard className="w-3.5 h-3.5" />
            <span>{pasteSuccess ? 'Pasted!' : 'Paste'}</span>
          </button>
        </div>

        {/* Inspect / Search Button */}
        <button
          type="button"
          onClick={onInspect}
          disabled={disabled || isLoading || !url.trim()}
          aria-label="Inspect media"
          className={cn(
            'absolute right-2 px-4 py-2.5 rounded-xl font-medium text-sm flex items-center gap-2 transition-all duration-200',
            'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-lg shadow-indigo-600/30',
            'hover:from-indigo-500 hover:to-indigo-600 hover:shadow-indigo-600/50 active:scale-95',
            'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:shadow-none'
          )}
        >
          {isLoading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="hidden sm:inline">Analyzing...</span>
            </>
          ) : (
            <span>Inspect</span>
          )}
        </button>
      </div>

      {/* Quick Platform Pills */}
      <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
        <span className="text-slate-400 font-medium mr-1">Supported platforms:</span>
        {PLATFORMS.map((platform) => (
          <button
            key={platform.name}
            type="button"
            onClick={() => handlePillClick(platform.domain)}
            className={cn(
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-slate-800 bg-slate-900/60 text-slate-400 transition-colors',
              platform.activeColor
            )}
          >
            {platform.icon}
            <span>{platform.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
