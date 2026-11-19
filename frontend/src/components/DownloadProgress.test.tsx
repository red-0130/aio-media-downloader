import { describe, expect, it } from 'bun:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { DownloadProgress } from './DownloadProgress';
import type { DownloadFileItem } from '../types/api';

describe('DownloadProgress Component (Anchor Link Replacement)', () => {
  it('renders single-file delivery card with an <a> element with expected href and download attributes', () => {
    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Download ready',
        downloadUrl: '/api/files/task-101/video_sample.mp4',
        filename: 'video_sample.mp4',
        fileSize: 1048576,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    // Should render an <a> tag with href and download attribute
    expect(html).toContain('Save File');
    expect(html).toContain('href="/api/files/task-101/video_sample.mp4"');
    expect(html).toContain('download="video_sample.mp4"');

    // Verify it is an anchor element and not a button
    expect(html).toMatch(/<a[^>]*href="\/api\/files\/task-101\/video_sample\.mp4"[^>]*>[\s\S]*?Save File[\s\S]*?<\/a>/);
    expect(html).not.toMatch(/<button[^>]*>[\s\S]*?Save File[\s\S]*?<\/button>/);
  });

  it('encodes special characters like # in single-file downloadUrl to %23', () => {
    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Download ready',
        downloadUrl: '/api/files/task-102/#Umingle_#shorts.mp4',
        filename: '#Umingle_#shorts.mp4',
        fileSize: 2097152,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    // '#' in downloadUrl should be encoded as '%23' in href
    expect(html).toContain('href="/api/files/task-102/%23Umingle_%23shorts.mp4"');
    // filename in download attribute retains raw filename
    expect(html).toContain('download="#Umingle_#shorts.mp4"');
    expect(html).toMatch(/<a[^>]*href="\/api\/files\/task-102\/%23Umingle_%23shorts\.mp4"[^>]*>/);
  });

  it('renders absolute http/https download URLs correctly in anchor href', () => {
    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Download ready',
        downloadUrl: 'https://cdn.example.com/downloads/media_archive.zip',
        filename: 'media_archive.zip',
        fileSize: 5242880,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    expect(html).toContain('href="https://cdn.example.com/downloads/media_archive.zip"');
    expect(html).toContain('download="media_archive.zip"');
    expect(html).toMatch(/<a[^>]*href="https:\/\/cdn\.example\.com\/downloads\/media_archive\.zip"[^>]*>/);
  });

  it('renders unbundled multi-file item list with <a> elements for individual item saves', () => {
    const files: DownloadFileItem[] = [
      {
        download_url: '/api/files/task-200/photo_01.jpg',
        filename: 'photo_01.jpg',
        file_size: 102400,
      },
      {
        download_url: '/api/files/task-200/#slide_02.png',
        filename: '#slide_02.png',
        file_size: 204800,
      },
    ];

    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Multi-item ready',
        downloadUrl: null,
        filename: null,
        fileSize: 307200,
        files: files,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    // First item anchor link
    expect(html).toContain('href="/api/files/task-200/photo_01.jpg"');
    expect(html).toContain('download="photo_01.jpg"');
    expect(html).toMatch(/<a[^>]*href="\/api\/files\/task-200\/photo_01\.jpg"[^>]*>[\s\S]*?Save[\s\S]*?<\/a>/);

    // Second item anchor link with '#' encoded to '%23'
    expect(html).toContain('href="/api/files/task-200/%23slide_02.png"');
    expect(html).toContain('download="#slide_02.png"');
    expect(html).toMatch(/<a[^>]*href="\/api\/files\/task-200\/%23slide_02\.png"[^>]*>[\s\S]*?Save[\s\S]*?<\/a>/);

    // Neither individual save element should be a button
    expect(html).not.toMatch(/<button[^>]*>[\s\S]*?Save<\/button>/);
  });

  it('keeps the batch action button "Save All Files" as a <button> element', () => {
    const files: DownloadFileItem[] = [
      {
        download_url: '/api/files/task-300/slide_01.jpg',
        filename: 'slide_01.jpg',
        file_size: 50000,
      },
      {
        download_url: '/api/files/task-300/slide_02.jpg',
        filename: 'slide_02.jpg',
        file_size: 60000,
      },
    ];

    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Multi-item ready',
        downloadUrl: null,
        filename: null,
        fileSize: 110000,
        files: files,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    // "Save All Files" must be a <button> element, NOT an <a> anchor
    expect(html).toContain('Save All Files');
    expect(html).toMatch(/<button[^>]*type="button"[^>]*>[\s\S]*?Save All Files[\s\S]*?<\/button>/);
    expect(html).not.toMatch(/<a[^>]*>[\s\S]*?Save All Files[\s\S]*?<\/a>/);
  });

  it('does not render download links when download is in progress or not complete', () => {
    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'downloading',
        progress: 45.5,
        speed: '3.5 MiB/s',
        eta: 15,
        message: 'Downloading media...',
        downloadUrl: null,
        filename: null,
        fileSize: null,
        error: null,
        isDownloading: true,
        isComplete: false,
      })
    );

    expect(html).not.toContain('Save File');
    expect(html).not.toContain('Save All Files');
    expect(html).toContain('Downloading Media...');
  });
});
