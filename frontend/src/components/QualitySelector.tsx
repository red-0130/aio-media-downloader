import React from 'react';
import { Sliders, Music, Archive, Check, Sparkles } from 'lucide-react';
import type { AudioFormat, FormatOption, MediaType } from '../types/api';
import { cn, formatBytes } from '../lib/utils';

export interface QualitySelectorProps {
  formats: FormatOption[];
  mediaType: MediaType;
  selectedFormatId: string;
  onSelectFormatId: (id: string) => void;
  extractAudio: boolean;
  onToggleExtractAudio: (extract: boolean) => void;
  audioFormat: AudioFormat;
  onSelectAudioFormat: (format: AudioFormat) => void;
  packageAsZip: boolean;
  onTogglePackageAsZip: (asZip: boolean) => void;
  itemCount?: number;
}

const AUDIO_FORMATS: { format: AudioFormat; label: string; desc: string }[] = [
  { format: 'mp3', label: 'MP3', desc: 'Universal audio (320kbps)' },
  { format: 'm4a', label: 'M4A', desc: 'AAC audio container' },
  { format: 'wav', label: 'WAV', desc: 'Lossless uncompressed' },
];

export const QualitySelector: React.FC<QualitySelectorProps> = ({
  formats,
  mediaType,
  selectedFormatId,
  onSelectFormatId,
  extractAudio,
  onToggleExtractAudio,
  audioFormat,
  onSelectAudioFormat,
  packageAsZip,
  onTogglePackageAsZip,
  itemCount = 1,
}) => {
  // If backend returned no formats (e.g. pure image or gallery-dl carousel), provide a default "best" format
  const displayFormats =
    formats && formats.length > 0
      ? formats
      : [{ format_id: 'best', label: 'Best Quality (Original)', ext: 'auto' }];

  const isMultiItem = itemCount > 1 || mediaType === 'carousel' || mediaType === 'story';

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-6">
      {/* Title */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Sliders className="w-4 h-4 text-indigo-400" />
          <h3 className="text-base font-semibold text-slate-100">Quality & Format Options</h3>
        </div>
        <span className="text-xs text-slate-400">Step 2: Choose delivery</span>
      </div>

      {/* Audio Extraction Toggle Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between p-3.5 rounded-xl bg-slate-950/60 border border-slate-800">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                'w-9 h-9 rounded-lg flex items-center justify-center transition-colors',
                extractAudio
                  ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30'
                  : 'bg-slate-800 text-slate-400'
              )}
            >
              <Music className="w-4 h-4" />
            </div>
            <div>
              <div className="text-sm font-medium text-slate-200">Extract Audio Only</div>
              <div className="text-xs text-slate-400">
                Convert and save audio track using FFmpeg
              </div>
            </div>
          </div>

          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={extractAudio}
              onChange={(e) => onToggleExtractAudio(e.target.checked)}
              className="sr-only peer"
            />
            <div
              className={cn(
                "w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all",
                'peer-checked:bg-indigo-600'
              )}
            />
          </label>
        </div>

        {/* Audio Format Selector (When Audio Extract is ON) */}
        {extractAudio && (
          <div className="grid grid-cols-3 gap-2.5 pt-1 pl-2 animate-in fade-in slide-in-from-top-1 duration-200">
            {AUDIO_FORMATS.map(({ format, label, desc }) => {
              const isSelected = audioFormat === format;
              return (
                <button
                  key={format}
                  type="button"
                  onClick={() => onSelectAudioFormat(format)}
                  className={cn(
                    'p-3 rounded-xl border text-left transition-all',
                    isSelected
                      ? 'border-indigo-500 bg-indigo-500/10 text-indigo-200 ring-1 ring-indigo-500/30'
                      : 'border-slate-800 bg-slate-950/40 text-slate-400 hover:border-slate-700 hover:text-slate-300'
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-sm uppercase">{label}</span>
                    {isSelected && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                  </div>
                  <div className="text-[11px] text-slate-400 mt-1 line-clamp-1">{desc}</div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Video / Media Quality Grid (Only shown when NOT audio-only) */}
      {!extractAudio && (
        <div className="space-y-2.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-400 block">
            Video Quality / Resolution
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {displayFormats.map((fmt) => {
              const isSelected = selectedFormatId === fmt.format_id;
              return (
                <button
                  key={fmt.format_id}
                  type="button"
                  onClick={() => onSelectFormatId(fmt.format_id)}
                  className={cn(
                    'p-3 rounded-xl border text-left transition-all flex items-center justify-between gap-3',
                    isSelected
                      ? 'border-indigo-500 bg-indigo-500/15 text-slate-100 ring-1 ring-indigo-500/40 shadow-sm'
                      : 'border-slate-800 bg-slate-950/40 text-slate-300 hover:border-slate-700 hover:bg-slate-950/70'
                  )}
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate flex items-center gap-1.5">
                      {fmt.resolution && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-900/60 text-indigo-300 border border-indigo-700/50">
                          {fmt.resolution}
                        </span>
                      )}
                      <span className="truncate">{fmt.label}</span>
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
                      <span className="uppercase font-mono text-[11px] text-slate-400">
                        .{fmt.ext}
                      </span>
                      {fmt.filesize && (
                        <>
                          <span>•</span>
                          <span>~{formatBytes(fmt.filesize)}</span>
                        </>
                      )}
                    </div>
                  </div>

                  <div
                    className={cn(
                      'w-5 h-5 rounded-full border flex items-center justify-center flex-shrink-0 transition-colors',
                      isSelected
                        ? 'border-indigo-500 bg-indigo-600 text-white'
                        : 'border-slate-700 bg-slate-900'
                    )}
                  >
                    {isSelected && <Check className="w-3 h-3" />}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Package as ZIP Toggle (Prominently styled for multi-item / carousels) */}
      <div
        className={cn(
          'p-3.5 rounded-xl border transition-colors flex items-center justify-between',
          isMultiItem
            ? 'bg-indigo-950/20 border-indigo-500/30'
            : 'bg-slate-950/60 border-slate-800'
        )}
      >
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'w-9 h-9 rounded-lg flex items-center justify-center',
              packageAsZip
                ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30'
                : 'bg-slate-800 text-slate-400'
            )}
          >
            <Archive className="w-4 h-4" />
          </div>
          <div>
            <div className="text-sm font-medium text-slate-200 flex items-center gap-2">
              <span>Package as ZIP Archive</span>
              {isMultiItem && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-500/20 text-indigo-300 flex items-center gap-1 border border-indigo-500/40">
                  <Sparkles className="w-2.5 h-2.5" />
                  Recommended
                </span>
              )}
            </div>
            <div className="text-xs text-slate-400">
              Bundle items into a single downloadable .zip archive
            </div>
          </div>
        </div>

        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={packageAsZip}
            onChange={(e) => onTogglePackageAsZip(e.target.checked)}
            className="sr-only peer"
          />
          <div
            className={cn(
              "w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all",
              'peer-checked:bg-indigo-600'
            )}
          />
        </label>
      </div>
    </div>
  );
};
