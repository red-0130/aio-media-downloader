import React from 'react';
import {
  Card,
  VStack,
  HStack,
  Heading,
  Text,
  SegmentedControl,
  SegmentedControlItem,
  Selector,
  Switch,
  Token,
} from '@astryxdesign/core';
import {
  Sliders,
  Film,
  Music,
  Archive,
} from 'lucide-react';
import type { AudioFormat, FormatOption, MediaType } from '../types/api';
import { formatBytes } from '../lib/utils';

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
  { format: 'mp3', label: 'MP3 (320kbps)', desc: 'Universal audio' },
  { format: 'm4a', label: 'M4A (AAC)', desc: 'Apple/AAC container' },
  { format: 'wav', label: 'WAV (Lossless)', desc: 'Uncompressed audio' },
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
  const displayFormats =
    formats && formats.length > 0
      ? formats
      : [{ format_id: 'best', label: 'Best Quality (Original)', ext: 'auto' }];

  const isMultiItem = itemCount > 1 || mediaType === 'carousel' || mediaType === 'story';

  // Build format options for Astryx Selector
  const formatOptions = displayFormats.map((f) => {
    const extLabel = f.ext ? f.ext.toUpperCase() : 'AUTO';
    const sizeLabel = f.filesize ? ` • ${formatBytes(f.filesize)}` : '';
    const resLabel = f.resolution ? ` (${f.resolution})` : '';
    return {
      value: f.format_id,
      label: `${f.label || f.format_id}${resLabel} [${extLabel}${sizeLabel}]`,
    };
  });

  return (
    <Card padding={4} elevation="med" width="100%">
      <VStack gap={4} width="100%">
        {/* Section Header */}
        <HStack gap={2} align="center" justify="between" width="100%">
          <HStack gap={2} align="center">
            <Sliders className="w-4 h-4 text-indigo-400" />
            <Heading level={3}>
              Delivery & Format Options
            </Heading>
          </HStack>
          <Token size="sm" color="purple" label="Step 2" />
        </HStack>

        {/* Media Stream Mode (Video vs Audio-Only) */}
        <VStack gap={2} width="100%">
          <Text type="supporting" color="secondary">
            Output Stream Type:
          </Text>
          <SegmentedControl
            label="Output Stream Type"
            value={extractAudio ? 'audio' : 'video'}
            onChange={(val) => onToggleExtractAudio(val === 'audio')}
            layout="fill"
          >
            <SegmentedControlItem
              value="video"
              label="Video & Audio"
              icon={<Film className="w-4 h-4 text-indigo-400" />}
            />
            <SegmentedControlItem
              value="audio"
              label="Audio Only (FFmpeg)"
              icon={<Music className="w-4 h-4 text-pink-400" />}
            />
          </SegmentedControl>
        </VStack>

        {/* Format Selector: Video Format dropdown OR Audio Codec segmented */}
        {!extractAudio ? (
          <VStack gap={2} width="100%">
            <Selector
              label="Video Quality & Codec"
              value={selectedFormatId}
              onChange={(val) => onSelectFormatId(val)}
              options={formatOptions}
              width="100%"
            />
          </VStack>
        ) : (
          <VStack gap={2} width="100%">
            <Text type="supporting" color="secondary">
              Audio Codec & Bitrate:
            </Text>
            <SegmentedControl
              label="Audio Codec Format"
              value={audioFormat}
              onChange={(val) => onSelectAudioFormat(val as AudioFormat)}
              layout="fill"
            >
              {AUDIO_FORMATS.map((af) => (
                <SegmentedControlItem
                  key={af.format}
                  value={af.format}
                  label={af.label}
                />
              ))}
            </SegmentedControl>
          </VStack>
        )}

        {/* Multi-Item ZIP Packaging Switch */}
        <Card padding={3} variant="muted" width="100%">
          <HStack gap={3} align="center" justify="between" width="100%">
            <HStack gap={2} align="center">
              <Archive className="w-4 h-4 text-indigo-400" />
              <VStack gap={0}>
                <Text weight="medium">
                  Package as .ZIP Archive
                </Text>
                <Text type="supporting" color="secondary">
                  {isMultiItem
                    ? 'Bundle all selected items into a single zip file'
                    : 'Download media in a compressed ZIP archive'}
                </Text>
              </VStack>
            </HStack>
            <Switch
              label="Package as ZIP"
              isLabelHidden
              value={packageAsZip}
              onChange={(checked) => onTogglePackageAsZip(checked)}
            />
          </HStack>
        </Card>
      </VStack>
    </Card>
  );
};
