import React, { useState } from 'react';
import {
  Card,
  VStack,
  HStack,
  AspectRatio,
  Heading,
  Text,
  Badge,
  Token,
  Button,
  Center,
} from '@astryxdesign/core';
import {
  Film,
  Image as ImageIcon,
  Music,
  Layers,
  Sparkles,
  User,
  ExternalLink,
  Clock,
} from 'lucide-react';
import type { InspectResponse, MediaType } from '../types/api';
import { formatDuration } from '../lib/utils';

export interface MediaPreviewProps {
  data: InspectResponse;
}

function getMediaTypeIcon(type: MediaType) {
  switch (type) {
    case 'video':
      return <Film className="w-3.5 h-3.5" />;
    case 'image':
      return <ImageIcon className="w-3.5 h-3.5" />;
    case 'audio':
      return <Music className="w-3.5 h-3.5" />;
    case 'carousel':
      return <Layers className="w-3.5 h-3.5" />;
    case 'story':
      return <Sparkles className="w-3.5 h-3.5" />;
    default:
      return <Film className="w-3.5 h-3.5" />;
  }
}

function getPlatformTokenColor(platform: string): 'red' | 'pink' | 'cyan' | 'teal' | 'default' {
  switch (platform.toLowerCase()) {
    case 'youtube':
      return 'red';
    case 'instagram':
      return 'pink';
    case 'twitter':
    case 'x':
      return 'cyan';
    case 'tiktok':
      return 'teal';
    default:
      return 'default';
  }
}

export const MediaPreview: React.FC<MediaPreviewProps> = ({ data }) => {
  const [imageError, setImageError] = useState(false);
  const platformTokenColor = getPlatformTokenColor(data.platform);

  const primaryItem = data.items && data.items.length > 0 ? data.items[0] : null;
  const duration = primaryItem?.duration ?? null;

  return (
    <Card padding={3} elevation="med" width="100%">
      <VStack gap={3} width="100%">
        {/* AspectRatio Media Display Stage */}
        <Card padding={0} variant="muted" width="100%">
          <AspectRatio ratio={16 / 9} fit="cover">
            {data.thumbnail && !imageError ? (
              <img
                src={data.thumbnail}
                alt={data.title || 'Media thumbnail'}
                onError={() => setImageError(true)}
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                loading="lazy"
              />
            ) : (
              <Center width="100%" height="100%">
                <VStack gap={2} align="center">
                  {getMediaTypeIcon(data.media_type)}
                  <Text type="supporting" color="secondary">
                    No preview thumbnail available
                  </Text>
                </VStack>
              </Center>
            )}
          </AspectRatio>
        </Card>

        {/* Floating / Inline Chips Header */}
        <HStack gap={2} align="center" justify="between" width="100%" wrap="wrap">
          <HStack gap={2} align="center" wrap="wrap">
            <Token color={platformTokenColor} label={data.platform.toUpperCase()} />
            <Token
              color="purple"
              icon={getMediaTypeIcon(data.media_type)}
              label={data.media_type.toUpperCase()}
            />
            {data.items && data.items.length > 1 && (
              <Badge
                variant="cyan"
                icon={<Layers className="w-3 h-3" />}
                label={`${data.items.length} items`}
              />
            )}
            {duration !== null && duration > 0 && (
              <Token
                color="default"
                icon={<Clock className="w-3 h-3" />}
                label={formatDuration(duration)}
              />
            )}
          </HStack>

          {data.url && (
            <Button
              variant="ghost"
              size="sm"
              icon={<ExternalLink className="w-3.5 h-3.5" />}
              label="Source Link"
              onClick={() => window.open(data.url, '_blank', 'noopener,noreferrer')}
            />
          )}
        </HStack>

        {/* Media Metadata Heading & Details */}
        <VStack gap={1} width="100%">
          <Heading level={2}>
            {data.title || 'Untitled Media'}
          </Heading>

          {data.uploader && (
            <HStack gap={1} align="center">
              <User className="w-3.5 h-3.5 text-indigo-400" />
              <Text type="supporting" color="secondary">
                {data.uploader}
              </Text>
            </HStack>
          )}
        </VStack>
      </VStack>
    </Card>
  );
};
