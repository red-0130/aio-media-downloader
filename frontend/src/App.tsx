import React, { useState } from 'react';
import {
  Layout,
  LayoutHeader,
  LayoutContent,
  LayoutFooter,
  VStack,
  HStack,
  StackItem,
  Grid,
  Card,
  Heading,
  Text,
  Token,
  Button,
  Banner,
  Center,
  useMediaQuery,
} from '@astryxdesign/core';
import {
  Download,
  KeyRound,
  RotateCcw,
  Sparkles,
  Zap,
} from 'lucide-react';
import { NavigationHeader } from './components/NavigationHeader';
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

export const App: React.FC = () => {
  const isMobile = useMediaQuery('(max-width: 768px)');

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
      if (
        result.media_type === 'carousel' ||
        result.media_type === 'story' ||
        (result.items && result.items.length > 1)
      ) {
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

    const isMulti =
      inspectData.media_type === 'carousel' ||
      inspectData.media_type === 'story' ||
      (inspectData.items && inspectData.items.length > 1);

    if (isMulti && selectedIndices.length === 0) {
      setInspectError({
        message: 'Please select at least one item from the gallery to download.',
      });
      return;
    }

    try {
      const response = await downloadMutation.mutateAsync({
        url: inspectData.url,
        format_id: extractAudio ? null : selectedFormatId,
        selected_indices: isMulti ? selectedIndices : null,
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
    <Layout
      height="fill"
      contentWidth={1120}
      header={
        <LayoutHeader hasDivider>
          <NavigationHeader onOpenSettings={() => openSettingsForPlatform()} />
        </LayoutHeader>
      }
      footer={
        <LayoutFooter hasDivider>
          {isMobile && inspectData && !activeTaskId ? (
            <Card padding={2} variant="transparent" width="100%">
              <HStack gap={2} align="center" justify="between" width="100%">
                <StackItem size="fill">
                  <VStack gap={0}>
                    <Text weight="semibold" maxLines={1}>
                      {isMultiItem
                        ? `${selectedIndices.length} item(s) selected`
                        : extractAudio
                        ? `Audio (${audioFormat.toUpperCase()})`
                        : selectedFormatId}
                    </Text>
                    <Text type="supporting" color="secondary" maxLines={1}>
                      {isMultiItem && packageAsZip ? 'Bundle as .ZIP' : 'Ready to download'}
                    </Text>
                  </VStack>
                </StackItem>

                <HStack gap={1.5} align="center">
                  <Button
                    variant="secondary"
                    size="md"
                    isIconOnly
                    icon={<RotateCcw className="w-4 h-4" />}
                    label="Start Over"
                    onClick={handleResetAll}
                  />

                  <Button
                    variant="primary"
                    size="md"
                    icon={<Download className="w-4 h-4" />}
                    label={downloadMutation.isPending ? 'Queuing...' : 'Start Download'}
                    isLoading={downloadMutation.isPending}
                    isDisabled={downloadMutation.isPending || (isMultiItem && selectedIndices.length === 0)}
                    onClick={handleStartDownload}
                  />
                </HStack>
              </HStack>
            </Card>
          ) : isMobile ? (
            <VStack gap={2} align="center" justify="center" width="100%">
              <HStack gap={2} align="center" justify="center" wrap="wrap">
                <Zap className="w-3.5 h-3.5 text-indigo-400" />
                <Text type="supporting" color="secondary" justify="center">
                  All-in-One Media Downloader • Self-Hosted Studio
                </Text>
              </HStack>
              <HStack gap={2} align="center" justify="center" wrap="wrap">
                <Token size="sm" color="default" label="yt-dlp" />
                <Token size="sm" color="default" label="gallery-dl" />
                <Token size="sm" color="default" label="FFmpeg" />
              </HStack>
            </VStack>
          ) : (
            <HStack gap={4} align="center" justify="between" width="100%" wrap="wrap">
              <HStack gap={2} align="center">
                <Zap className="w-3.5 h-3.5 text-indigo-400" />
                <Text type="supporting" color="secondary">
                  All-in-One Media Downloader • Self-Hosted Universal Studio
                </Text>
              </HStack>
              <HStack gap={2} align="center">
                <Token size="sm" color="default" label="yt-dlp" />
                <Token size="sm" color="default" label="gallery-dl" />
                <Token size="sm" color="default" label="FFmpeg" />
              </HStack>
            </HStack>
          )}
        </LayoutFooter>
      }
    >
      <LayoutContent padding={4}>
        <VStack gap={5} width="100%">
          {/* Hero Section */}
          <Center width="100%" padding={2}>
            <VStack gap={2} align="center">
              <HStack gap={1} align="center">
                <Token
                  color="purple"
                  icon={<Sparkles className="w-3 h-3" />}
                  label="CYBER MEDIA STUDIO"
                />
              </HStack>
              <Heading level={1}>
                Download Any Video, Audio or Story
              </Heading>
              <Text type="supporting" color="secondary">
                Paste any link from YouTube, Instagram, Twitter/X, or TikTok to inspect formats, pick qualities, and download with real-time SSE progress.
              </Text>
            </VStack>
          </Center>

          {/* Stage 1: URL Command Input */}
          <UrlInput
            url={url}
            onChange={setUrl}
            onInspect={handleInspect}
            isLoading={inspectMutation.isPending}
            disabled={inspectMutation.isPending || downloadMutation.isPending || sse.isDownloading}
          />

          {/* Error Alert Banner */}
          {inspectError && (
            <Banner
              status="error"
              title={
                inspectError.isAuthRequired
                  ? 'Authentication Required'
                  : inspectError.isRateLimit
                  ? 'Platform Rate Limit Exceeded'
                  : 'Media Extraction Error'
              }
              description={inspectError.message}
              endContent={
                inspectError.isAuthRequired ? (
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<KeyRound className="w-3.5 h-3.5" />}
                    label="Configure Cookies"
                    onClick={() => openSettingsForPlatform(detectPlatformFromUrl(url))}
                  />
                ) : undefined
              }
            />
          )}

          {/* Stage 2: Studio Split Stage (Media Preview & Delivery Options) */}
          {inspectData && !activeTaskId && (
            <VStack gap={4} width="100%">
              {/* Studio Split Grid: Preview (Left) & Delivery Options (Right) */}
              <Grid columns={{ minWidth: 340, max: 2 }} gap={4} width="100%">
                <MediaPreview data={inspectData} />
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
              </Grid>

              {/* Gallery Curator for Carousels & Multi-item Stories */}
              {hasItems && isMultiItem && (
                <ItemGallerySelector
                  items={inspectData.items || []}
                  selectedIndices={selectedIndices}
                  onChangeSelectedIndices={setSelectedIndices}
                />
              )}

              {/* Action Command Bar (Desktop Stage) */}
              {!isMobile && (
                <Card padding={3} elevation="high" width="100%">
                  <HStack gap={3} align="center" justify="between" width="100%" wrap="wrap">
                    <VStack gap={0}>
                      <Text weight="semibold">
                        {isMultiItem
                          ? `Ready to download ${selectedIndices.length} item(s)${packageAsZip ? ' packaged as .ZIP' : ''}`
                          : `Ready to download in ${extractAudio ? `Audio (${audioFormat.toUpperCase()})` : selectedFormatId}`}
                      </Text>
                      <Text type="supporting" color="secondary">
                        Click Start Download to initialize worker task
                      </Text>
                    </VStack>

                    <HStack gap={2} align="center">
                      <Button
                        variant="secondary"
                        size="md"
                        icon={<RotateCcw className="w-4 h-4" />}
                        label="Start Over"
                        onClick={handleResetAll}
                      />

                      <Button
                        variant="primary"
                        size="md"
                        icon={<Download className="w-4 h-4" />}
                        label={downloadMutation.isPending ? 'Queuing Task...' : 'Start Download'}
                        isLoading={downloadMutation.isPending}
                        isDisabled={downloadMutation.isPending || (isMultiItem && selectedIndices.length === 0)}
                        onClick={handleStartDownload}
                      />
                    </HStack>
                  </HStack>
                </Card>
              )}
            </VStack>
          )}

          {/* Stage 3: Real-Time SSE Telemetry & File Retrieval */}
          {activeTaskId && (
            <DownloadProgress
              status={sse.status}
              progress={sse.progress}
              speed={sse.speed}
              eta={sse.eta}
              message={sse.message}
              downloadUrl={sse.downloadUrl}
              filename={sse.filename}
              fileSize={sse.fileSize}
              files={sse.files}
              error={sse.error}
              isDownloading={sse.isDownloading}
              isComplete={sse.isComplete}
              onReset={handleResetAll}
              onCancel={sse.cancel}
            />
          )}
        </VStack>
      </LayoutContent>

      {/* Settings Modal (Netscape Cookies & Proxy Configuration) */}
      <CookieSettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        defaultPlatform={settingsDefaultPlatform}
      />
    </Layout>
  );
};
