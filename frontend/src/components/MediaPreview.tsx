import React, { useState } from 'react';
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
import { cn, formatDuration, getPlatformBadgeColor } from '../lib/utils';

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

export const MediaPreview: React.FC<MediaPreviewProps> = ({ data }) => {
  const [imageError, setImageError] = useState(false);
  const platformColor = getPlatformBadgeColor(data.platform);

  // Compute duration from items if not directly provided
  const primaryItem = data.items && data.items.length > 0 ? data.items[0] : null;
  const duration = primaryItem?.duration ?? null;

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl overflow-hidden shadow-xl flex flex-col md:flex-row gap-5 p-4 md:p-5">
      {/* Thumbnail Container */}
      <div className="relative w-full md:w-64 lg:w-72 aspect-video md:aspect-[4/3] bg-slate-950 rounded-xl overflow-hidden flex-shrink-0 border border-slate-800/80">
        {data.thumbnail && !imageError ? (
          <img
            src={data.thumbnail}
            alt={data.title}
            onError={() => setImageError(true)}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center text-slate-400 gap-2 p-4 text-center">
            {getMediaTypeIcon(data.media_type)}
            <span className="text-xs">No thumbnail available</span>
          </div>
        )}

        {/* Floating Badges on Thumbnail */}
        <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5">
          <span
            className={cn(
              'px-2 py-0.5 rounded-md text-xs font-semibold uppercase tracking-wider backdrop-blur-md border shadow-md flex items-center gap-1',
              platformColor.bg,
              platformColor.text,
              platformColor.border
            )}
          >
            {data.platform}
          </span>
        </div>

        {/* Duration badge or Items count badge at bottom right */}
        <div className="absolute bottom-2.5 right-2.5 flex items-center gap-1.5">
          {data.items && data.items.length > 1 && (
            <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-slate-950/80 text-indigo-300 border border-indigo-500/30 backdrop-blur-md flex items-center gap-1 shadow-md">
              <Layers className="w-3 h-3" />
              <span>{data.items.length} items</span>
            </span>
          )}

          {duration !== null && duration > 0 && (
            <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-slate-950/80 text-slate-200 border border-slate-700/60 backdrop-blur-md flex items-center gap-1 shadow-md">
              <Clock className="w-3 h-3 text-slate-400" />
              <span>{formatDuration(duration)}</span>
            </span>
          )}
        </div>
      </div>

      {/* Metadata Column */}
      <div className="flex-1 flex flex-col justify-between space-y-3 min-w-0">
        <div className="space-y-2">
          {/* Header row: Media type badge + External Link */}
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-300 border border-slate-700/50">
              {getMediaTypeIcon(data.media_type)}
              <span className="capitalize">{data.media_type}</span>
            </span>

            <a
              href={data.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-slate-400 hover:text-indigo-400 flex items-center gap-1 transition-colors"
              title="Open source URL in new tab"
            >
              <span>Source URL</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {/* Title */}
          <h2
            className="text-lg md:text-xl font-semibold text-slate-100 line-clamp-2 hover:line-clamp-none transition-all leading-snug"
            title={data.title}
          >
            {data.title || 'Untitled Media'}
          </h2>

          {/* Uploader / Channel */}
          {data.uploader && (
            <div className="flex items-center gap-1.5 text-sm text-slate-400 font-medium">
              <User className="w-3.5 h-3.5 text-slate-400" />
              <span>{data.uploader}</span>
            </div>
          )}
        </div>

        {/* Formats and items preview pill summary */}
        <div className="pt-2 border-t border-slate-800/80 flex flex-wrap items-center gap-2 text-xs text-slate-400">
          {data.formats && data.formats.length > 0 && (
            <span className="bg-slate-800/60 px-2.5 py-1 rounded-md border border-slate-700/50 text-slate-300">
              {data.formats.length} format{data.formats.length > 1 ? 's' : ''} available
            </span>
          )}
          {data.items && data.items.length > 0 && (
            <span className="bg-slate-800/60 px-2.5 py-1 rounded-md border border-slate-700/50 text-slate-300">
              {data.items.length} media item{data.items.length > 1 ? 's' : ''} detected
            </span>
          )}
          <span className="bg-slate-800/40 px-2.5 py-1 rounded-md border border-slate-800 text-slate-400">
            ID: {data.id}
          </span>
        </div>
      </div>
    </div>
  );
};
