/**
 * Format raw bytes into human-friendly string (e.g. 14.5 MiB).
 */
export function formatBytes(bytes?: number | null, decimals = 1): string {
  if (
    bytes === null ||
    bytes === undefined ||
    isNaN(bytes) ||
    !isFinite(bytes) ||
    bytes <= 0
  ) {
    return '0 B';
  }

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];

  const i = Math.floor(Math.log(bytes) / Math.log(k));
  if (i < 0) return `${bytes} B`;
  const idx = Math.min(i, sizes.length - 1);
  return `${parseFloat((bytes / Math.pow(k, idx)).toFixed(dm))} ${sizes[idx]}`;
}

/**
 * Format duration in seconds to MM:SS or HH:MM:SS.
 */
export function formatDuration(seconds?: number | null): string {
  if (
    seconds === null ||
    seconds === undefined ||
    isNaN(seconds) ||
    !isFinite(seconds) ||
    seconds <= 0
  ) {
    return '0:00';
  }

  const totalSeconds = Math.floor(seconds);
  const hrs = Math.floor(totalSeconds / 3600);
  const mins = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;

  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}
