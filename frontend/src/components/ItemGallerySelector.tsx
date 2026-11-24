import React, { useState } from 'react';
import {
  Card,
  VStack,
  HStack,
  Grid,
  Heading,
  Text,
  Badge,
  Token,
  Button,
  Banner,
  Center,
  AspectRatio,
} from '@astryxdesign/core';
import {
  CheckSquare,
  Square,
  Film,
  Image as ImageIcon,
  Clock,
  Layers,
} from 'lucide-react';
import type { MediaItem } from '../types/api';
import { formatDuration } from '../lib/utils';

export interface ItemGallerySelectorProps {
  items: MediaItem[];
  selectedIndices: number[];
  onChangeSelectedIndices: (indices: number[]) => void;
}

export const ItemGallerySelector: React.FC<ItemGallerySelectorProps> = ({
  items,
  selectedIndices,
  onChangeSelectedIndices,
}) => {
  const [failedThumbnails, setFailedThumbnails] = useState<Record<number, boolean>>({});

  const allIndices = items.map((it) => it.index);
  const isAllSelected = items.length > 0 && selectedIndices.length === items.length;
  const isNoneSelected = selectedIndices.length === 0;

  const handleSelectAllToggle = () => {
    if (isAllSelected) {
      onChangeSelectedIndices([]);
    } else {
      onChangeSelectedIndices(allIndices);
    }
  };

  const handleToggleIndex = (index: number) => {
    if (selectedIndices.includes(index)) {
      onChangeSelectedIndices(selectedIndices.filter((i) => i !== index));
    } else {
      onChangeSelectedIndices([...selectedIndices, index].sort((a, b) => a - b));
    }
  };

  const handleImageError = (index: number) => {
    setFailedThumbnails((prev) => ({ ...prev, [index]: true }));
  };

  return (
    <Card padding={4} elevation="med" width="100%">
      <VStack gap={4} width="100%">
        {/* Header Action Bar */}
        <HStack gap={2} align="center" justify="between" width="100%" wrap="wrap">
          <VStack gap={0}>
            <HStack gap={2} align="center">
              <Layers className="w-4 h-4 text-indigo-400" />
              <Heading level={3}>
                Curate Story & Gallery Items
              </Heading>
              <Badge
                variant="purple"
                label={`${selectedIndices.length} / ${items.length}`}
              />
            </HStack>
            <Text type="supporting" color="secondary">
              Pick individual photos or video clips to download
            </Text>
          </VStack>

          <Button
            variant={isAllSelected ? 'secondary' : 'primary'}
            size="sm"
            icon={
              isAllSelected ? (
                <CheckSquare className="w-3.5 h-3.5 text-indigo-400" />
              ) : (
                <Square className="w-3.5 h-3.5" />
              )
            }
            label={isAllSelected ? 'Deselect All' : `Select All (${items.length})`}
            onClick={handleSelectAllToggle}
          />
        </HStack>

        {/* Warning Banner when nothing selected */}
        {isNoneSelected && (
          <Banner
            status="warning"
            title="No items selected"
            description="Select at least one photo or video slide to proceed with extraction."
          />
        )}

        {/* Responsive Gallery Grid */}
        <Grid columns={{ minWidth: 150, max: 4 }} gap={3} width="100%">
          {items.map((item) => {
            const isSelected = selectedIndices.includes(item.index);
            const hasImageError = !!failedThumbnails[item.index];
            const thumbUrl = item.thumbnail || item.url;

            return (
              <Card
                key={item.index}
                padding={2}
                variant={isSelected ? 'default' : 'muted'}
                elevation={isSelected ? 'low' : 'none'}
                width="100%"
              >
                <VStack gap={2} width="100%">
                  {/* Item Thumbnail */}
                  <AspectRatio ratio={1} fit="cover">
                    {thumbUrl && !hasImageError ? (
                      <img
                        src={thumbUrl}
                        alt={`Slide ${item.index + 1}`}
                        onError={() => handleImageError(item.index)}
                        style={{
                          width: '100%',
                          height: '100%',
                          objectFit: 'cover',
                          borderRadius: '8px',
                          filter: isSelected ? 'none' : 'grayscale(40%) opacity(70%)',
                        }}
                        loading="lazy"
                      />
                    ) : (
                      <Center width="100%" height="100%">
                        <VStack gap={1} align="center">
                          {item.type === 'video' ? (
                            <Film className="w-5 h-5 text-indigo-400" />
                          ) : (
                            <ImageIcon className="w-5 h-5 text-slate-400" />
                          )}
                          <Text type="supporting" color="secondary">
                            Slide {item.index + 1}
                          </Text>
                        </VStack>
                      </Center>
                    )}
                  </AspectRatio>

                  {/* Metadata Chips & Selection Button */}
                  <HStack gap={1} align="center" justify="between" width="100%">
                    <HStack gap={1} align="center">
                      <Badge variant="neutral" label={`#${item.index + 1}`} />
                      <Token
                        size="sm"
                        color={item.type === 'video' ? 'blue' : 'teal'}
                        label={item.type.toUpperCase()}
                      />
                      {item.duration !== null && item.duration !== undefined && item.duration > 0 && (
                        <Token
                          size="sm"
                          color="default"
                          icon={<Clock className="w-2.5 h-2.5" />}
                          label={formatDuration(item.duration)}
                        />
                      )}
                    </HStack>

                    <Button
                      variant={isSelected ? 'primary' : 'ghost'}
                      size="sm"
                      isIconOnly
                      icon={
                        isSelected ? (
                          <CheckSquare className="w-3.5 h-3.5" />
                        ) : (
                          <Square className="w-3.5 h-3.5 text-slate-500" />
                        )
                      }
                      label={isSelected ? `Deselect #${item.index + 1}` : `Select #${item.index + 1}`}
                      onClick={() => handleToggleIndex(item.index)}
                    />
                  </HStack>
                </VStack>
              </Card>
            );
          })}
        </Grid>
      </VStack>
    </Card>
  );
};
