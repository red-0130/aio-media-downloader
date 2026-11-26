import { describe, expect, it } from 'bun:test';
import { formatBytes, formatDuration } from './utils';

describe('utils: formatBytes', () => {
  it('returns "0 B" for falsy, zero, NaN, or non-finite inputs', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(null)).toBe('0 B');
    expect(formatBytes(undefined)).toBe('0 B');
    expect(formatBytes(NaN)).toBe('0 B');
    expect(formatBytes(Infinity)).toBe('0 B');
    expect(formatBytes(-Infinity)).toBe('0 B');
  });

  it('safely handles negative numbers without producing "NaN undefined"', () => {
    expect(formatBytes(-1)).toBe('0 B');
    expect(formatBytes(-1024)).toBe('0 B');
    expect(formatBytes(-99999)).toBe('0 B');
  });

  it('formats positive bytes correctly across units', () => {
    expect(formatBytes(1)).toBe('1 B');
    expect(formatBytes(500)).toBe('500 B');
    expect(formatBytes(1024)).toBe('1 KB');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1048576)).toBe('1 MB');
    expect(formatBytes(1073741824)).toBe('1 GB');
    expect(formatBytes(1099511627776)).toBe('1 TB');
  });

  it('caps at TB for huge byte sizes', () => {
    // 10 PB
    const tenPB = 10 * 1024 * 1024 * 1024 * 1024 * 1024;
    expect(formatBytes(tenPB)).toBe('10240 TB');
  });

  it('respects decimals parameter', () => {
    expect(formatBytes(1536, 0)).toBe('2 KB');
    expect(formatBytes(1536, 2)).toBe('1.5 KB');
    expect(formatBytes(1234567, 2)).toBe('1.18 MB');
  });
});

describe('utils: formatDuration', () => {
  it('returns "0:00" for non-positive, NaN, null, undefined, or non-finite inputs', () => {
    expect(formatDuration(0)).toBe('0:00');
    expect(formatDuration(-1)).toBe('0:00');
    expect(formatDuration(-30)).toBe('0:00');
    expect(formatDuration(null)).toBe('0:00');
    expect(formatDuration(undefined)).toBe('0:00');
    expect(formatDuration(NaN)).toBe('0:00');
    expect(formatDuration(Infinity)).toBe('0:00');
    expect(formatDuration(-Infinity)).toBe('0:00');
  });

  it('handles sub-second duration', () => {
    expect(formatDuration(0.7)).toBe('0:00');
    expect(formatDuration(0.99)).toBe('0:00');
  });

  it('formats standard MM:SS durations correctly', () => {
    expect(formatDuration(1)).toBe('0:01');
    expect(formatDuration(9)).toBe('0:09');
    expect(formatDuration(10)).toBe('0:10');
    expect(formatDuration(59)).toBe('0:59');
    expect(formatDuration(60)).toBe('1:00');
    expect(formatDuration(75)).toBe('1:15');
    expect(formatDuration(599)).toBe('9:59');
    expect(formatDuration(600)).toBe('10:00');
    expect(formatDuration(3599)).toBe('59:59');
  });

  it('formats HH:MM:SS durations when duration >= 1 hour', () => {
    expect(formatDuration(3600)).toBe('1:00:00');
    expect(formatDuration(3665)).toBe('1:01:05');
    expect(formatDuration(7325)).toBe('2:02:05');
    expect(formatDuration(86400)).toBe('24:00:00');
  });
});
