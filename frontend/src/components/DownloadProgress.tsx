import React from 'react';
import {
  Download,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  XCircle,
  HardDrive,
  Activity,
  Timer,
  FileCheck,
} from 'lucide-react';
import type { TaskStatus } from '../types/api';
import { cn, formatBytes } from '../lib/utils';
import { triggerBrowserDownload } from '../lib/api';

export interface DownloadProgressProps {
  status: TaskStatus | 'idle';
  progress: number;
  speed: string | null;
  eta: number | null;
  message: string | null;
  downloadUrl: string | null;
  filename: string | null;
  fileSize: number | null;
  error: string | null;
  isDownloading: boolean;
  isComplete: boolean;
  onReset?: () => void;
  onCancel?: () => void;
}

export const DownloadProgress: React.FC<DownloadProgressProps> = ({
  status,
  progress,
  speed,
  eta,
  message,
  downloadUrl,
  filename,
  fileSize,
  error,
  isDownloading,
  isComplete,
  onReset,
  onCancel,
}) => {
  const percent = Math.min(100, Math.max(0, Math.round(progress * 10) / 10));

  const handleDownloadClick = () => {
    if (downloadUrl) {
      triggerBrowserDownload(downloadUrl, filename || undefined);
    }
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-2xl space-y-5 animate-in fade-in duration-300">
      {/* Header Row */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          {isComplete ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          ) : status === 'error' ? (
            <AlertTriangle className="w-5 h-5 text-rose-400" />
          ) : (
            <Activity className="w-5 h-5 text-indigo-400 animate-pulse" />
          )}

          <h3 className="text-base font-semibold text-slate-100">
            {isComplete
              ? 'Download Ready'
              : status === 'error'
              ? 'Task Failed'
              : status === 'postprocessing'
              ? 'Post-Processing Media...'
              : 'Downloading Media...'}
          </h3>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {isDownloading && onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="text-xs px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700 flex items-center gap-1 transition-colors"
            >
              <XCircle className="w-3.5 h-3.5 text-slate-400" />
              <span>Cancel</span>
            </button>
          )}

          {(isComplete || status === 'error') && onReset && (
            <button
              type="button"
              onClick={onReset}
              className="text-xs px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700 flex items-center gap-1 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>New Download</span>
            </button>
          )}
        </div>
      </div>

      {/* In-Flight Progress State */}
      {isDownloading && (
        <div className="space-y-3">
          {/* Progress Bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-300 font-medium capitalize">
                {status === 'postprocessing' ? 'FFmpeg Conversion / Packaging' : 'Download Progress'}
              </span>
              <span className="font-mono text-indigo-300 font-semibold">{percent}%</span>
            </div>

            <div className="h-3 w-full bg-slate-950 rounded-full overflow-hidden border border-slate-800 p-0.5">
              <div
                className={cn(
                  'h-full rounded-full transition-all duration-300 ease-out shadow-sm',
                  status === 'postprocessing'
                    ? 'bg-gradient-to-r from-amber-500 to-indigo-500 animate-pulse'
                    : 'bg-gradient-to-r from-indigo-600 via-indigo-500 to-sky-400'
                )}
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>

          {/* Metrics Row (Speed, ETA, Status Message) */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-1 text-xs text-slate-400">
            {speed && (
              <div className="flex items-center gap-1.5 bg-slate-950/40 p-2 rounded-lg border border-slate-800/60">
                <HardDrive className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                <span className="truncate">
                  Speed: <strong className="text-slate-200 font-mono">{speed}</strong>
                </span>
              </div>
            )}

            {eta !== null && eta > 0 && (
              <div className="flex items-center gap-1.5 bg-slate-950/40 p-2 rounded-lg border border-slate-800/60">
                <Timer className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" />
                <span className="truncate">
                  ETA: <strong className="text-slate-200 font-mono">{eta}s</strong>
                </span>
              </div>
            )}

            <div className="col-span-2 sm:col-span-1 flex items-center gap-1.5 bg-slate-950/40 p-2 rounded-lg border border-slate-800/60">
              <Activity className="w-3.5 h-3.5 text-teal-400 flex-shrink-0" />
              <span className="truncate" title={message || 'Working...'}>
                {message || 'Processing...'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Completed State */}
      {isComplete && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/30">
            <div className="flex items-start gap-3 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 flex-shrink-0">
                <FileCheck className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-slate-100 truncate" title={filename || ''}>
                  {filename || 'Downloaded File'}
                </div>
                <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
                  {fileSize && (
                    <span className="font-mono text-emerald-300 font-medium">
                      {formatBytes(fileSize)}
                    </span>
                  )}
                  <span>•</span>
                  <span>Ready to save to disk</span>
                </div>
              </div>
            </div>

            {/* Direct Download Button */}
            <button
              type="button"
              onClick={handleDownloadClick}
              className={cn(
                'px-5 py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all duration-200 flex-shrink-0',
                'bg-gradient-to-r from-emerald-600 to-emerald-500 text-white shadow-lg shadow-emerald-600/30',
                'hover:from-emerald-500 hover:to-emerald-600 hover:shadow-emerald-600/50 active:scale-95'
              )}
            >
              <Download className="w-4 h-4" />
              <span>Save File</span>
            </button>
          </div>
        </div>
      )}

      {/* Error State */}
      {status === 'error' && (
        <div className="p-4 rounded-xl bg-rose-950/20 border border-rose-500/30 space-y-3">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h4 className="text-sm font-semibold text-rose-200">Download Failed</h4>
              <p className="text-xs text-rose-300 leading-relaxed font-mono">
                {error || message || 'An unexpected error occurred during download execution.'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
