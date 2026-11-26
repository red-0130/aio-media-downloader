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
    expect(html).not.toMatch(/<button[^>]*>[\s\S]*?>Save<[\s\S]*?<\/button>/);
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

  it('wraps and clamps long single-file names while keeping the extension separate and visible', () => {
    const longStem = 'a_very_long_unbroken_filename_without_spaces_1234567890_abcdefghijklmnopqrstuvwxyz';
    const fullName = `${longStem}.mp4`;

    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Download ready',
        downloadUrl: `/api/files/task-400/${fullName}`,
        filename: fullName,
        fileSize: 4096,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    expect(html).toContain('astryx-stack-item');
    expect(html).toContain('flex-shrink:1');
    expect(html).toContain('-webkit-line-clamp:2');
    expect(html).toContain(`>${longStem}<`);
    expect(html).toContain('>.mp4<');
    expect(html).toContain(`download="${fullName}"`);
  });

  it('keeps extensions visible on long filenames in multi-file items and handles filename edge cases', () => {
    const longStem = 'instagram_story_carousel_item_without_spaces_0987654321_zyxwvutsrqponmlkjihgfedcba';
    const files: DownloadFileItem[] = [
      {
        download_url: `/api/files/task-401/${longStem}.jpg`,
        filename: `${longStem}.jpg`,
        file_size: 8192,
      },
      {
        download_url: '/api/files/task-401/long_filename_without_any_extension',
        filename: 'long_filename_without_any_extension',
        file_size: 2048,
      },
      {
        download_url: '/api/files/task-401/.hidden_dotfile',
        filename: '.hidden_dotfile',
        file_size: 512,
      },
      {
        download_url: '/api/files/task-401/trailing_dot.',
        filename: 'trailing_dot.',
        file_size: 512,
      },
      {
        download_url: '/api/files/task-401/archive.tar.gz',
        filename: 'archive.tar.gz',
        file_size: 1024,
      },
      {
        download_url: '/api/files/task-401/title.with_more_than_ten_chars_after_dot',
        filename: 'title.with_more_than_ten_chars_after_dot',
        file_size: 1024,
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
        fileSize: 10240,
        files,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    expect(html).toContain(`>${longStem}<`);
    expect(html).toContain('>.jpg<');
    expect(html).toContain('>long_filename_without_any_extension<');
    expect(html).toContain('>.hidden_dotfile<');
    expect(html).toContain('>trailing_dot.<');
    expect(html).toContain('>archive.tar<');
    expect(html).toContain('>.gz<');
    expect(html).toContain('>title.with_more_than_ten_chars_after_dot<');
    expect(html).toContain(`download="${longStem}.jpg"`);
  });

  it('falls back to "Downloaded Media" when single-file filename is null', () => {
    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Download ready',
        downloadUrl: '/api/files/task-402/file.bin',
        filename: null,
        fileSize: 1024,
        error: null,
        isDownloading: false,
        isComplete: true,
      })
    );

    expect(html).toContain('>Downloaded Media<');
    expect(html).toContain('download="Downloaded Media"');
  });

  it('renders single-file "Save File" as a button-styled anchor with icon, full-width on mobile and inline on desktop', () => {
    const baseProps = {
      status: 'completed' as const,
      progress: 100,
      speed: null,
      eta: null,
      message: 'Download ready',
      downloadUrl: '/api/files/task-500/clip.mp4',
      filename: 'clip.mp4',
      fileSize: 2048,
      error: null,
      isDownloading: false,
      isComplete: true,
    };

    const desktopHtml = renderToString(
      React.createElement(DownloadProgress, { ...baseProps, isMobile: false })
    );
    expect(desktopHtml).toMatch(/<a[^>]*data-variant="primary"[^>]*aria-label="Save File: clip\.mp4"[^>]*download="clip\.mp4"[^>]*href="\/api\/files\/task-500\/clip\.mp4"[^>]*>[\s\S]*?<svg[\s\S]*?Save File[\s\S]*?<\/a>/);
    expect(desktopHtml).not.toMatch(/<a[^>]*--x-width:100%[^>]*>[\s\S]*?Save File/);

    const mobileHtml = renderToString(
      React.createElement(DownloadProgress, { ...baseProps, isMobile: true })
    );
    expect(mobileHtml).toMatch(/<a[^>]*style="--x-width:100%"[^>]*>[\s\S]*?Save File[\s\S]*?<\/a>/);
    expect(mobileHtml).toMatch(/<a[^>]*data-variant="primary"[^>]*aria-label="Save File: clip\.mp4"[^>]*download="clip\.mp4"[^>]*href="\/api\/files\/task-500\/clip\.mp4"[^>]*>[\s\S]*?<svg[\s\S]*?Save File[\s\S]*?<\/a>/);
  });

  it('renders multi-file "Save" anchors with Download icons and distinct secondary styling from primary "Save All Files"', () => {
    const files: DownloadFileItem[] = [
      {
        download_url: '/api/files/task-501/one.jpg',
        filename: 'one.jpg',
        file_size: 1000,
      },
      {
        download_url: '/api/files/task-501/two.jpg',
        filename: 'two.jpg',
        file_size: 2000,
      },
    ];

    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'completed',
        progress: 100,
        speed: null,
        eta: null,
        message: 'Ready',
        downloadUrl: null,
        filename: null,
        fileSize: 3000,
        files,
        error: null,
        isDownloading: false,
        isComplete: true,
        isMobile: false,
      })
    );

    expect(html).toMatch(/<a[^>]*data-variant="secondary"[^>]*aria-label="Save: one\.jpg"[^>]*download="one\.jpg"[^>]*href="\/api\/files\/task-501\/one\.jpg"[^>]*>[\s\S]*?<svg[\s\S]*?Save[\s\S]*?<\/a>/);
    expect(html).toMatch(/<button[^>]*type="button"[^>]*data-variant="primary"[^>]*>[\s\S]*?<svg[\s\S]*?Save All Files[\s\S]*?<\/button>/);
  });

  it('renders a cancelled state with Start Over recovery button when status is idle', () => {
    const html = renderToString(
      React.createElement(DownloadProgress, {
        status: 'idle',
        progress: 25,
        speed: null,
        eta: null,
        message: 'Download cancelled',
        downloadUrl: null,
        filename: null,
        fileSize: null,
        error: null,
        isDownloading: false,
        isComplete: false,
        onReset: () => {},
      })
    );

    expect(html).toContain('Download Cancelled');
    expect(html).toContain('Download cancelled');
    expect(html).toContain('Start Over');
    expect(html).not.toContain('Downloading Media...');
    expect(html).not.toContain('Save File');
    expect(html).not.toContain('>Cancel<');
  });
});
