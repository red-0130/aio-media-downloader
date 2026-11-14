import React, { useState } from 'react';
import {
  Download,
  Settings,
  AlertTriangle,
  Sparkles,
  KeyRound,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { UrlInput } from './components/UrlInput';
import { MediaPreview } from './components/MediaPreview';
import { QualitySelector } from './components/QualitySelector';
import { ItemGallerySelector } from './components/ItemGallerySelector';
import { DownloadProgress } from './components/DownloadProgress';
import { CookieSettingsModal } from './components/CookieSettingsModal';
import {
  useInspectMediaMutation,
  useStartDownloadMutation,
  ApiError,
  extractErrorMessage,
} from './lib/api';
import { useSSEProgress } from './hooks/useSSEProgress';
import type { AudioFormat, InspectResponse } from './types/api';
import { cn } from './lib/utils';

export const App: React.FC = () => {
  // Input & Inspection State
  const [url, setUrl] = useState('');
  const [inspectData, setInspectData] = useState<InspectResponse | null>(null);
  const [inspectError, setInspectError] = useState<{
    message: string;
    isAuthRequired?: boolean;
    isRateLimit?: boolean;
    platform?: string;
  } | null>(null);

  // Configuration State
  const [selectedFormatId, setSelectedFormatId] = useState<string>('best');
  const [extractAudio, setExtractAudio] = useState(false);
  const [audioFormat, setAudioFormat] = useState<AudioFormat>('mp3');
  const [packageAsZip, setPackageAsZip] = useState(true);
  const [selectedIndices, setSelectedIndices] = useState<number[]>([]);

  // Task & SSE Progress State
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  // Modal State
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [settingsDefaultPlatform, setSettingsDefaultPlatform] = useState<string | undefined>(undefined);

  // React Query Mutations
  const inspectMutation = useInspectMediaMutation();
  const downloadMutation = useStartDownloadMutation();

  // SSE Progress Hook
  const sse = useSSEProgress(activeTaskId, {
    autoDownload: false,
  });

  // Handle URL Inspection
  const handleInspect = async () => {
    if (!url.trim()) return;

    setInspectError(null);
    setInspectData(null);
    setActiveTaskId(null);
    sse.reset();

    try {
      const result = await inspectMutation.mutateAsync({ url: url.trim() });
      setInspectData(result);

      // Default format
      if (result.formats && result.formats.length > 0) {
        setSelectedFormatId(result.formats[0].format_id);
      } else {
        setSelectedFormatId('best');
      }

      // Default select all items for carousel/stories
      if (result.items && result.items.length > 0) {
        setSelectedIndices(result.items.map((i) => i.index));
      } else {
        setSelectedIndices([]);
      }

      // Default ZIP packaging to true for carousels/stories
      if (result.media_type === 'carousel' || result.media_type === 'story' || (result.items && result.items.length > 1)) {
        setPackageAsZip(true);
      } else {
        setPackageAsZip(false);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setInspectError({
          message: err.message,
          isAuthRequired: err.isAuthRequired,
          isRateLimit: err.isRateLimit,
        });
      } else {
        setInspectError({
          message: extractErrorMessage(err),
        });
      }
    }
  };

  // Handle Starting Download
  const handleStartDownload = async () => {
    if (!inspectData) return;

    // Multi-item validation: at least 1 item must be selected
    const isMultiItem =
      inspectData.media_type === 'carousel' ||
      inspectData.media_type === 'story' ||
      (inspectData.items && inspectData.items.length > 1);

    if (isMultiItem && selectedIndices.length === 0) {
      setInspectError({
        message: 'Please select at least one item from the gallery to download.',
      });
      return;
    }

    try {
      const response = await downloadMutation.mutateAsync({
        url: inspectData.url,
        format_id: extractAudio ? null : selectedFormatId,
        selected_indices: isMultiItem ? selectedIndices : null,
        extract_audio: extractAudio,
        audio_format: audioFormat,
        package_as_zip: packageAsZip,
        metadata: inspectData as unknown as Record<string, unknown>,
      });

      setActiveTaskId(response.task_id);
    } catch (err) {
      setInspectError({
        message: extractErrorMessage(err),
      });
    }
  };

  const handleResetAll = () => {
    setUrl('');
    setInspectData(null);
    setInspectError(null);
    setActiveTaskId(null);
    sse.reset();
  };

  const detectPlatformFromUrl = (inputUrl: string): string => {
    try {
      const lower = inputUrl.toLowerCase();
      if (lower.includes('youtube.com') || lower.includes('youtu.be')) return 'youtube';
      if (lower.includes('twitter.com') || lower.includes('x.com')) return 'twitter';
      if (lower.includes('instagram.com') || lower.includes('instagr.am')) return 'instagram';
    } catch {
      // Ignore
    }
    return 'instagram';
  };

  const openSettingsForPlatform = (platform?: string) => {
    setSettingsDefaultPlatform(platform);
    setIsSettingsOpen(true);
  };

  const hasItems = inspectData?.items && inspectData.items.length > 0;
  const isMultiItem =
    inspectData?.media_type === 'carousel' ||
    inspectData?.media_type === 'story' ||
    (inspectData?.items && inspectData.items.length > 1);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col antialiased">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-40 w-full backdrop-blur-md bg-slate-950/80 border-b border-slate-800/80">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          {/* Logo & Title */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-400 flex items-center justify-center text-white shadow-lg shadow-indigo-600/30">
              <Download className="w-5 h-5" />
            </div>
            <div>
              <div className="font-bold text-base md:text-lg tracking-tight text-white flex items-center gap-2">
                <span>All-in-One Downloader</span>
                <span className="hidden sm:inline-flex text-[10px] font-semibold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
                  Universal
                </span>
              </div>
              <p className="hidden md:block text-[11px] text-slate-400">
                Self-hosted media extraction powered by yt-dlp, gallery-dl & ffmpeg
              </p>
            </div>
          </div>

          {/* Right Action Icons */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => openSettingsForPlatform()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-slate-800 bg-slate-900/90 hover:bg-slate-800 text-slate-300 text-xs font-medium transition-colors shadow-sm"
              title="Settings (Cookies & Proxy)"
            >
              <Settings className="w-4 h-4 text-slate-400" />
              <span className="hidden sm:inline">Settings</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-8 md:py-12 space-y-8">
        {/* Hero Header */}
        <section className="text-center space-y-2.5 max-w-2xl mx-auto">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 mb-1">
            <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
            <span>Fast, high-fidelity media downloads</span>
          </div>
          <h1 className="text-2xl md:text-4xl font-extrabold tracking-tight text-white">
            Download Any Video, Audio or Gallery
          </h1>
          <p className="text-sm md:text-base text-slate-400">
            Paste any link from YouTube, Instagram, Twitter/X, or TikTok to inspect formats, pick
            qualities, and download with real-time progress.
          </p>
        </section>

        {/* Step 1: Input URL */}
        <section className="space-y-4">
          <UrlInput
            url={url}
            onChange={setUrl}
            onInspect={handleInspect}
            isLoading={inspectMutation.isPending}
            disabled={inspectMutation.isPending || downloadMutation.isPending || sse.isDownloading}
          />

          {/* Error Alert Banner */}
          {inspectError && (
            <div className="p-4 rounded-2xl bg-rose-950/30 border border-rose-500/40 text-rose-200 text-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-in fade-in duration-200">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-rose-100">
                    {inspectError.isAuthRequired
                      ? 'Authentication Required'
                      : inspectError.isRateLimit
                      ? 'Platform Rate Limit Exceeded'
                      : 'Extraction Error'}
                  </div>
                  <div className="text-xs text-rose-300 mt-0.5 font-mono">
                    {inspectError.message}
                  </div>
                </div>
              </div>

              {/* Action Button for 401 Auth Required or 429 */}
              {inspectError.isAuthRequired && (
                <button
                  type="button"
                  onClick={() => openSettingsForPlatform(detectPlatformFromUrl(url))}
                  className="px-3.5 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold flex items-center gap-1.5 flex-shrink-0 shadow-md shadow-rose-600/30 transition-all"
                >
                  <KeyRound className="w-3.5 h-3.5" />
                  <span>Configure Cookies</span>
                </button>
              )}
            </div>
          )}
        </section>

        {/* Step 2: Inspection Result & Configuration */}
        {inspectData && !activeTaskId && (
          <section className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            {/* Top Row: Media Preview Card & Quality Selector */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              <div className="lg:col-span-6 xl:col-span-7">
                <MediaPreview data={inspectData} />
              </div>

              <div className="lg:col-span-6 xl:col-span-5">
                <QualitySelector
                  formats={inspectData.formats || []}
                  mediaType={inspectData.media_type}
                  selectedFormatId={selectedFormatId}
                  onSelectFormatId={setSelectedFormatId}
                  extractAudio={extractAudio}
                  onToggleExtractAudio={setExtractAudio}
                  audioFormat={audioFormat}
                  onSelectAudioFormat={setAudioFormat}
                  packageAsZip={packageAsZip}
                  onTogglePackageAsZip={setPackageAsZip}
                  itemCount={inspectData.items?.length || 1}
                />
              </div>
            </div>

            {/* Gallery Selector for Carousels & Stories */}
            {hasItems && isMultiItem && (
              <ItemGallerySelector
                items={inspectData.items || []}
                selectedIndices={selectedIndices}
                onChangeSelectedIndices={setSelectedIndices}
              />
            )}

            {/* Step 2 Execution Bar */}
            <div className="p-4 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="text-xs text-slate-400">
                {isMultiItem ? (
                  <span>
                    Ready to download{' '}
                    <strong className="text-slate-200">{selectedIndices.length} items</strong>
                    {packageAsZip && ' packaged as .ZIP'}
                  </span>
                ) : (
                  <span>
                    Ready to download in{' '}
                    <strong className="text-slate-200">
                      {extractAudio ? `Audio (${audioFormat.toUpperCase()})` : selectedFormatId}
                    </strong>
                  </span>
                )}
              </div>

              <div className="flex items-center gap-3 w-full sm:w-auto">
                <button
                  type="button"
                  onClick={handleResetAll}
                  className="px-4 py-3 rounded-xl border border-slate-700 bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 flex items-center justify-center gap-1.5 transition-colors"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Start Over</span>
                </button>

                <button
                  type="button"
                  onClick={handleStartDownload}
                  disabled={downloadMutation.isPending || (isMultiItem && selectedIndices.length === 0)}
                  className={cn(
                    'flex-1 sm:flex-none px-6 py-3 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all duration-200',
                    'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-xl shadow-indigo-600/30',
                    'hover:from-indigo-500 hover:to-indigo-600 hover:shadow-indigo-600/50 active:scale-95',
                    'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:shadow-none'
                  )}
                >
                  {downloadMutation.isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Queuing Task...</span>
                    </>
                  ) : (
                    <>
                      <Download className="w-4 h-4" />
                      <span>Start Download</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </section>
        )}

        {/* Step 3: SSE Download Progress & File Retrieval */}
        {activeTaskId && (
          <section className="animate-in fade-in slide-in-from-bottom-3 duration-300">
            <DownloadProgress
              status={sse.status}
              progress={sse.progress}
              speed={sse.speed}
              eta={sse.eta}
              message={sse.message}
              downloadUrl={sse.downloadUrl}
              filename={sse.filename}
              fileSize={sse.fileSize}
              error={sse.error}
              isDownloading={sse.isDownloading}
              isComplete={sse.isComplete}
              onReset={handleResetAll}
              onCancel={sse.cancel}
            />
          </section>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 py-6 mt-12 bg-slate-950/60 text-xs text-slate-400">
        <div className="max-w-6xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3 text-center sm:text-left">
          <div>
            <span>All-in-One Media Downloader • Self-Hosted & Open Source</span>
          </div>
          <div className="flex items-center gap-4 text-slate-400">
            <span>yt-dlp</span>
            <span>•</span>
            <span>gallery-dl</span>
            <span>•</span>
            <span>FFmpeg</span>
          </div>
        </div>
      </footer>

      {/* Cookie & Proxy Settings Modal */}
      <CookieSettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        defaultPlatform={settingsDefaultPlatform}
      />
    </div>
  );
};
