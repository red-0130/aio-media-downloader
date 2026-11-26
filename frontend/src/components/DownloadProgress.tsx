import React, { useEffect, useRef, useState } from 'react';
import {
  Card,
  VStack,
  HStack,
  StackItem,
  Heading,
  Text,
  Badge,
  Button,
  ProgressBar,
  Banner,
  Tooltip,
  useMediaQuery,
} from '@astryxdesign/core';
import {
  Download,
  Check,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  XCircle,
  Activity,
  Timer,
  FileCheck,
  Files,
} from 'lucide-react';
import type { DownloadFileItem, TaskStatus } from '../types/api';
import { formatBytes } from '../lib/utils';
import { getSafeDownloadUrl, triggerBrowserDownload } from '../lib/api';

export interface DownloadProgressProps {
  status: TaskStatus | 'idle';
  progress: number;
  speed: string | null;
  eta: number | null;
  message: string | null;
  downloadUrl: string | null;
  filename: string | null;
  fileSize: number | null;
  files?: DownloadFileItem[] | null;
  error: string | null;
  isDownloading: boolean;
  isComplete: boolean;
  isMobile?: boolean;
  onReset?: () => void;
  onCancel?: () => void;
}

const splitFilename = (name: string): { stem: string; ext: string | null } => {
  const lastDot = name.lastIndexOf('.');
  if (lastDot > 0 && lastDot < name.length - 1) {
    const ext = name.slice(lastDot);
    if (ext.length <= 10 && !/\s/.test(ext)) {
      return { stem: name.slice(0, lastDot), ext };
    }
  }
  return { stem: name, ext: null };
};

const FilenameLabel: React.FC<{ name: string; weight: 'semibold' | 'medium' }> = ({
  name,
  weight,
}) => {
  const { stem, ext } = splitFilename(name);
  return (
    <Tooltip content={name} hasHoverIndication={false}>
      <HStack gap={0} align="end" width="100%">
        {/* shortcut: align="end" may leave a gap on 2-line un-clamped stems; avoids JS ResizeObserver measurement */}
        <StackItem style={{ flexShrink: 1 }}>
          <Text weight={weight} maxLines={2} wordBreak="break-word" hasTruncateTooltip={false}>
            {stem}
          </Text>
        </StackItem>
        {ext && (
          <StackItem size="static">
            <Text weight={weight} textWrap="nowrap">
              {ext}
            </Text>
          </StackItem>
        )}
      </HStack>
    </Tooltip>
  );
};

interface FileDownloadRowProps {
  icon: React.ReactNode;
  filename: string;
  fileSize?: number | null;
  downloadUrl: string;
  actionLabel: string;
  variant: 'primary' | 'secondary';
  size: 'sm' | 'md';
  isSaved: boolean;
  onSave: () => void;
  fullWidthAction?: boolean;
  padding: 2 | 3;
  gap: 2 | 3;
  weight: 'semibold' | 'medium';
}

const FileDownloadRow: React.FC<FileDownloadRowProps> = ({
  icon,
  filename,
  fileSize,
  downloadUrl,
  actionLabel,
  variant,
  size,
  isSaved,
  onSave,
  fullWidthAction = false,
  padding,
  gap,
  weight,
}) => {
  const iconClass = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4';
  const infoRow = (
    <HStack gap={gap} align="center" width="100%">
      <StackItem size="static">{icon}</StackItem>
      <StackItem size="fill">
        <VStack gap={0} width="100%">
          <FilenameLabel name={filename} weight={weight} />
          {fileSize != null && fileSize > 0 && (
            <Text type="supporting" color="secondary">
              {formatBytes(fileSize)}
            </Text>
          )}
        </VStack>
      </StackItem>
    </HStack>
  );

  const actionButton = (
    <Button
      variant={variant}
      size={size}
      width={fullWidthAction ? '100%' : undefined}
      href={getSafeDownloadUrl(downloadUrl)}
      icon={isSaved ? <Check className={iconClass} /> : <Download className={iconClass} />}
      label={isSaved ? 'Saved' : actionLabel}
      aria-label={`${isSaved ? 'Saved' : actionLabel}: ${filename}`}
      onClick={onSave}
      {...({ download: filename } as Record<string, string>)}
    />
  );

  return (
    <Card padding={padding} variant="muted" width="100%">
      {fullWidthAction ? (
        <VStack gap={3} width="100%">
          {infoRow}
          {actionButton}
        </VStack>
      ) : (
        <HStack gap={gap} align="center" justify="between" width="100%">
          <StackItem size="fill">{infoRow}</StackItem>
          <StackItem size="static">{actionButton}</StackItem>
        </HStack>
      )}
    </Card>
  );
};

export const DownloadProgress: React.FC<DownloadProgressProps> = ({
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
  isMobile: isMobileProp,
  onReset,
  onCancel,
}) => {
  const mediaQueryIsMobile = useMediaQuery('(max-width: 768px)');
  const isMobile = isMobileProp ?? mediaQueryIsMobile;
  const [savedKeys, setSavedKeys] = useState<Record<string, boolean>>({});
  const batchTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const percent = Math.min(100, Math.max(0, Math.round(progress * 10) / 10));

  const clearBatchTimers = () => {
    batchTimersRef.current.forEach(clearTimeout);
    batchTimersRef.current = [];
  };

  useEffect(() => {
    setSavedKeys({});
    clearBatchTimers();
    return clearBatchTimers;
  }, [downloadUrl, files]);

  const markSaved = (key: string) => {
    setSavedKeys((prev) => (prev[key] ? prev : { ...prev, [key]: true }));
  };

  const handleDownloadAllClick = () => {
    if (!files || files.length === 0) return;
    clearBatchTimers();
    batchTimersRef.current = files.map((f, idx) =>
      setTimeout(() => {
        triggerBrowserDownload(f.download_url, f.filename);
        markSaved(`${idx}:${f.download_url}`);
      }, idx * 200)
    );
  };

  const isPostProcessing = status === 'postprocessing';
  const hasMultipleFiles = Boolean(files && files.length > 1);
  const allFilesSaved = Boolean(
    hasMultipleFiles && files && files.every((f, idx) => savedKeys[`${idx}:${f.download_url}`])
  );

  return (
    <Card padding={4} elevation="high" width="100%">
      <VStack gap={4} width="100%">
        {/* Header Telemetry Status Bar */}
        <HStack gap={2} align="center" justify="between" width="100%" wrap="wrap">
          <HStack gap={2} align="center">
            {isComplete ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            ) : status === 'error' ? (
              <AlertTriangle className="w-5 h-5 text-rose-400" />
            ) : (
              <Activity className="w-5 h-5 text-indigo-400 animate-pulse" />
            )}

            <Heading level={3}>
              {isComplete
                ? 'Download Ready'
                : status === 'error'
                ? 'Task Failed'
                : isPostProcessing
                ? 'Post-Processing Media...'
                : 'Downloading Media...'}
            </Heading>
          </HStack>

          <HStack gap={2} align="center">
            {isDownloading && onCancel && (
              <Button
                variant="ghost"
                size="sm"
                icon={<XCircle className="w-3.5 h-3.5 text-rose-400" />}
                label="Cancel"
                onClick={onCancel}
              />
            )}
            {(isComplete || status === 'error') && onReset && (
              <Button
                variant="secondary"
                size="sm"
                icon={<RotateCcw className="w-3.5 h-3.5" />}
                label="Start Over"
                onClick={onReset}
              />
            )}
          </HStack>
        </HStack>

        {/* Live Telemetry Progress Bar */}
        {!isComplete && status !== 'error' && (
          <VStack gap={2} width="100%">
            <ProgressBar
              label="Download Progress"
              value={percent}
              max={100}
              isIndeterminate={isPostProcessing}
              hasValueLabel={!isPostProcessing}
              variant={isPostProcessing ? 'warning' : 'accent'}
            />

            {/* Metrics Chips */}
            <HStack gap={3} align="center" justify="between" width="100%" wrap="wrap">
              <HStack gap={2} align="center">
                {speed && (
                  <Badge
                    variant="blue"
                    icon={<Activity className="w-3 h-3" />}
                    label={speed}
                  />
                )}
                {eta !== null && eta > 0 && (
                  <Badge
                    variant="neutral"
                    icon={<Timer className="w-3 h-3" />}
                    label={`${eta}s remaining`}
                  />
                )}
              </HStack>

              {message && (
                <Text type="supporting" color="secondary">
                  {message}
                </Text>
              )}
            </HStack>
          </VStack>
        )}

        {/* Error Alert Banner */}
        {status === 'error' && error && (
          <Banner
            status="error"
            title="Download Operation Failed"
            description={error}
          />
        )}

        {/* Completion Stage: Direct File Retrieval */}
        {isComplete && (
          <VStack gap={4} width="100%">
            {/* Single File Delivery Card */}
            {downloadUrl && (
              <FileDownloadRow
                icon={<FileCheck className="w-6 h-6 text-emerald-400" />}
                filename={filename || 'Downloaded Media'}
                fileSize={fileSize}
                downloadUrl={downloadUrl}
                actionLabel="Save File"
                variant="primary"
                size="md"
                isSaved={Boolean(savedKeys[downloadUrl])}
                onSave={() => markSaved(downloadUrl)}
                fullWidthAction={isMobile}
                padding={3}
                gap={3}
                weight="semibold"
              />
            )}

            {/* Unbundled Multi-File Items List */}
            {hasMultipleFiles && files && (
              <VStack gap={3} width="100%">
                <HStack gap={2} align="center" justify="between" width="100%" wrap="wrap">
                  <HStack gap={2} align="center">
                    <Files className="w-4 h-4 text-indigo-400" />
                    <Heading level={4}>
                      Individual Media Files ({files.length})
                    </Heading>
                  </HStack>

                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    icon={allFilesSaved ? <Check className="w-3.5 h-3.5" /> : <Download className="w-3.5 h-3.5" />}
                    label={allFilesSaved ? 'Saved All' : 'Save All Files'}
                    onClick={handleDownloadAllClick}
                  />
                </HStack>

                <VStack gap={2} width="100%">
                  {files.map((file, idx) => {
                    const fileKey = `${idx}:${file.download_url}`;
                    return (
                      <FileDownloadRow
                        key={idx}
                        icon={<Badge variant="neutral" label={`#${idx + 1}`} />}
                        filename={file.filename || 'Downloaded Media'}
                        fileSize={file.file_size}
                        downloadUrl={file.download_url}
                        actionLabel="Save"
                        variant="secondary"
                        size="sm"
                        isSaved={Boolean(savedKeys[fileKey])}
                        onSave={() => markSaved(fileKey)}
                        padding={2}
                        gap={2}
                        weight="medium"
                      />
                    );
                  })}
                </VStack>
              </VStack>
            )}
          </VStack>
        )}
      </VStack>
    </Card>
  );
};
