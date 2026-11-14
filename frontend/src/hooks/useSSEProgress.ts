/**
 * Custom React hook managing EventSource SSE lifecycle for /api/progress/{task_id}.
 * Handles named events ('progress', 'postprocessing', 'complete', 'error'),
 * connection recovery, graceful stream termination, and automatic cleanup.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { triggerBrowserDownload } from '../lib/api';
import type {
  CompleteEventData,
  DownloadFileItem,
  PostprocessingEventData,
  ProgressEventData,
  TaskStatus,
} from '../types/api';

export type SSEConnectionState = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

export interface UseSSEProgressOptions {
  /** Optional callback invoked on progress updates */
  onProgress?: (data: ProgressEventData) => void;
  /** Optional callback invoked during post-processing phase */
  onPostprocessing?: (data: PostprocessingEventData) => void;
  /** Optional callback invoked when download finishes successfully */
  onComplete?: (data: CompleteEventData) => void;
  /** Optional callback invoked on stream or task failure */
  onError?: (errorMessage: string) => void;
  /** Whether to automatically trigger browser file download on completion (default: false) */
  autoDownload?: boolean;
}

export interface UseSSEProgressResult {
  /** Connection state of the EventSource socket */
  connectionState: SSEConnectionState;
  /** Download task lifecycle status */
  status: TaskStatus | 'idle';
  /** Percentage completed (0.0 to 100.0) */
  progress: number;
  /** Download speed string (e.g. '4.2MiB/s') */
  speed: string | null;
  /** Estimated time remaining in seconds */
  eta: number | null;
  /** Status or post-processing description */
  message: string | null;
  /** Final relative download URL once completed */
  downloadUrl: string | null;
  /** Output filename */
  filename: string | null;
  /** Output file size in bytes */
  fileSize: number | null;
  /** Individual unbundled files list if multiple files downloaded */
  files: DownloadFileItem[] | null;
  /** Error message if failed */
  error: string | null;
  /** True if downloading or processing is actively in-flight */
  isDownloading: boolean;
  /** True if finished successfully */
  isComplete: boolean;
  /** Reset hook state back to idle */
  reset: () => void;
  /** Manually cancel stream connection */
  cancel: () => void;
}

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

export function useSSEProgress(
  taskId: string | null,
  options: UseSSEProgressOptions = {}
): UseSSEProgressResult {
  const { onProgress, onPostprocessing, onComplete, onError, autoDownload = false } = options;

  const [connectionState, setConnectionState] = useState<SSEConnectionState>('idle');
  const [status, setStatus] = useState<TaskStatus | 'idle'>('idle');
  const [progress, setProgress] = useState<number>(0);
  const [speed, setSpeed] = useState<string | null>(null);
  const [eta, setEta] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [fileSize, setFileSize] = useState<number | null>(null);
  const [files, setFiles] = useState<DownloadFileItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const isTerminalRef = useRef<boolean>(false);
  const retryCountRef = useRef<number>(0);

  // Store callbacks in ref to avoid re-subscribing on callback reference changes
  const callbacksRef = useRef({ onProgress, onPostprocessing, onComplete, onError, autoDownload });
  useEffect(() => {
    callbacksRef.current = { onProgress, onPostprocessing, onComplete, onError, autoDownload };
  });

  const reset = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    isTerminalRef.current = false;
    retryCountRef.current = 0;
    setConnectionState('idle');
    setStatus('idle');
    setProgress(0);
    setSpeed(null);
    setEta(null);
    setMessage(null);
    setDownloadUrl(null);
    setFilename(null);
    setFileSize(null);
    setFiles(null);
    setError(null);
  }, []);

  const cancel = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    isTerminalRef.current = true;
    setConnectionState('disconnected');
    if (status !== 'completed' && status !== 'error') {
      setStatus('idle');
      setMessage('Download cancelled');
    }
  }, [status]);

  useEffect(() => {
    if (!taskId) {
      reset();
      return;
    }

    isTerminalRef.current = false;
    retryCountRef.current = 0;
    setConnectionState('connecting');
    setStatus('queued');
    setProgress(0);
    setError(null);
    setMessage('Connecting to task stream...');

    const streamUrl = `${BASE_URL}/api/progress/${encodeURIComponent(taskId)}`;
    const es = new EventSource(streamUrl);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnectionState('connected');
      retryCountRef.current = 0;
    };

    // 1. Handle "progress" event
    es.addEventListener('progress', (event: MessageEvent) => {
      if (isTerminalRef.current) return;
      try {
        const data: ProgressEventData = JSON.parse(event.data);
        setStatus(data.status);
        if (data.progress !== undefined && data.progress !== null) {
          setProgress((prev) => Math.max(prev, data.progress));
        }
        setSpeed(data.speed ?? null);
        setEta(data.eta ?? null);
        if (data.message) setMessage(data.message);
        callbacksRef.current.onProgress?.(data);
      } catch (e) {
        console.error('Failed to parse progress event:', e);
      }
    });

    // 2. Handle "postprocessing" event
    es.addEventListener('postprocessing', (event: MessageEvent) => {
      if (isTerminalRef.current) return;
      try {
        const data: PostprocessingEventData = JSON.parse(event.data);
        setStatus('postprocessing');
        setMessage(data.message || 'Processing media...');
        callbacksRef.current.onPostprocessing?.(data);
      } catch (e) {
        console.error('Failed to parse postprocessing event:', e);
      }
    });

    // 3. Handle "complete" event
    es.addEventListener('complete', (event: MessageEvent) => {
      try {
        const data: CompleteEventData = JSON.parse(event.data);
        isTerminalRef.current = true;
        setStatus('completed');
        setProgress(100);
        setDownloadUrl(data.download_url);
        setFilename(data.filename);
        setFileSize(data.file_size);
        setFiles(data.files ?? null);
        setMessage('Download complete');
        setConnectionState('disconnected');

        // Close stream immediately to prevent browser reconnection attempts
        es.close();
        eventSourceRef.current = null;

        callbacksRef.current.onComplete?.(data);

        if (callbacksRef.current.autoDownload && data.download_url) {
          triggerBrowserDownload(data.download_url, data.filename);
        }
      } catch (e) {
        console.error('Failed to parse complete event:', e);
      }
    });

    // 4. Handle "error" event emitted by backend
    es.addEventListener('error', (event: MessageEvent) => {
      // If event has data, it is a custom backend error event
      if (event.data) {
        try {
          const data = JSON.parse(event.data);
          const errMessage = data.message || 'Download task failed';
          isTerminalRef.current = true;
          setStatus('error');
          setError(errMessage);
          setMessage(errMessage);
          setConnectionState('error');

          es.close();
          eventSourceRef.current = null;

          callbacksRef.current.onError?.(errMessage);
          return;
        } catch {
          // If unparseable data, fall through to native onerror handling
        }
      }
    });

    // 5. Handle native transport / network disconnection onerror
    es.onerror = () => {
      // If task already reached terminal state (complete or error), ignore closed stream
      if (isTerminalRef.current) {
        return;
      }

      if (es.readyState === EventSource.CLOSED) {
        isTerminalRef.current = true;
        setConnectionState('error');
        setStatus('error');
        const errMsg = 'Connection to download progress stream closed by server';
        setError(errMsg);
        setMessage(errMsg);
        es.close();
        eventSourceRef.current = null;
        callbacksRef.current.onError?.(errMsg);
      } else {
        // EventSource is automatically retrying (readyState === CONNECTING)
        retryCountRef.current += 1;
        setConnectionState('connecting');
        if (retryCountRef.current > 10) {
          isTerminalRef.current = true;
          setConnectionState('error');
          setStatus('error');
          const errMsg = 'Exceeded maximum connection retries to progress stream';
          setError(errMsg);
          setMessage(errMsg);
          es.close();
          eventSourceRef.current = null;
          callbacksRef.current.onError?.(errMsg);
        }
      }
    };

    return () => {
      if (es) {
        es.close();
      }
      eventSourceRef.current = null;
    };
  }, [taskId, reset]);

  const isDownloading =
    status === 'queued' || status === 'downloading' || status === 'postprocessing';
  const isComplete = status === 'completed';

  return {
    connectionState,
    status,
    progress,
    speed,
    eta,
    message,
    downloadUrl,
    filename,
    fileSize,
    files,
    error,
    isDownloading,
    isComplete,
    reset,
    cancel,
  };
}
