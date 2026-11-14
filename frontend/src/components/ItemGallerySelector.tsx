import React, { useState } from 'react';
import { CheckSquare, Square, Film, Image as ImageIcon, Clock, AlertCircle } from 'lucide-react';
import type { MediaItem } from '../types/api';
import { cn, formatDuration } from '../lib/utils';

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
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <span>Select Gallery & Story Items</span>
            <span className="text-xs font-normal text-slate-400">
              ({selectedIndices.length} of {items.length} selected)
            </span>
          </h3>
          <p className="text-xs text-slate-400">
            Pick specific photos or video slides to download
          </p>
        </div>

        {/* Action Button: Select All / Deselect All */}
        <button
          type="button"
          onClick={handleSelectAllToggle}
          className={cn(
            'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors',
            isAllSelected
              ? 'border-indigo-500/50 bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/20'
              : 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
          )}
        >
          {isAllSelected ? (
            <>
              <CheckSquare className="w-3.5 h-3.5 text-indigo-400" />
              <span>Deselect All</span>
            </>
          ) : (
            <>
              <Square className="w-3.5 h-3.5 text-slate-400" />
              <span>Select All ({items.length})</span>
            </>
          )}
        </button>
      </div>

      {/* Warning when 0 items selected */}
      {isNoneSelected && (
        <div className="flex items-center gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>No items selected. Select at least one item to proceed with download.</span>
        </div>
      )}

      {/* Items Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
        {items.map((item) => {
          const isSelected = selectedIndices.includes(item.index);
          const hasImageError = !!failedThumbnails[item.index];
          const thumbUrl = item.thumbnail || item.url;

          return (
            <div
              key={item.index}
              onClick={() => handleToggleIndex(item.index)}
              className={cn(
                'group relative rounded-xl overflow-hidden border cursor-pointer transition-all duration-200 select-none aspect-square bg-slate-950 flex flex-col justify-between',
                isSelected
                  ? 'border-indigo-500 ring-2 ring-indigo-500/40 shadow-lg shadow-indigo-500/10'
                  : 'border-slate-800 hover:border-slate-700 opacity-70 hover:opacity-100'
              )}
            >
              {/* Media Thumbnail */}
              {thumbUrl && !hasImageError ? (
                <img
                  src={thumbUrl}
                  alt={`Item ${item.index + 1}`}
                  onError={() => handleImageError(item.index)}
                  className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center text-slate-400 gap-1.5 p-2 text-center">
                  {item.type === 'video' ? (
                    <Film className="w-6 h-6 text-slate-400" />
                  ) : (
                    <ImageIcon className="w-6 h-6 text-slate-400" />
                  )}
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider">
                    {item.type}
                  </span>
                </div>
              )}

              {/* Top Bar on Item: Checkbox & Index Badge */}
              <div className="absolute top-2 inset-x-2 flex items-center justify-between pointer-events-none">
                <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-slate-950/80 text-slate-200 backdrop-blur-md border border-slate-700/60 shadow-sm">
                  #{item.index + 1}
                </span>

                <div
                  className={cn(
                    'w-5 h-5 rounded-md border flex items-center justify-center shadow-md transition-colors',
                    isSelected
                      ? 'bg-indigo-600 border-indigo-400 text-white'
                      : 'bg-slate-900/90 border-slate-600 text-transparent'
                  )}
                >
                  <CheckSquare className="w-3.5 h-3.5" />
                </div>
              </div>

              {/* Bottom Bar: Type icon & Duration or Resolution */}
              <div className="absolute bottom-2 inset-x-2 flex items-center justify-between pointer-events-none">
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-950/80 text-slate-300 backdrop-blur-md border border-slate-800 flex items-center gap-1 shadow-sm">
                  {item.type === 'video' ? (
                    <>
                      <Film className="w-2.5 h-2.5 text-indigo-400" />
                      <span>Video</span>
                    </>
                  ) : (
                    <>
                      <ImageIcon className="w-2.5 h-2.5 text-pink-400" />
                      <span>Photo</span>
                    </>
                  )}
                </span>

                {item.duration !== null && item.duration !== undefined && item.duration > 0 && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-950/80 text-slate-200 backdrop-blur-md border border-slate-800 flex items-center gap-1 shadow-sm">
                    <Clock className="w-2.5 h-2.5 text-slate-400" />
                    <span>{formatDuration(item.duration)}</span>
                  </span>
                )}
                {item.resolution && !item.duration && (
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-slate-950/80 text-slate-400 backdrop-blur-md border border-slate-800 shadow-sm">
                    {item.resolution}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
