import { describe, expect, it } from 'bun:test';
import { ApiError, extractErrorMessage, formatDetailItem, getSafeDownloadUrl, triggerBrowserDownload } from './api';

describe('api: formatDetailItem', () => {
  it('returns strings as-is', () => {
    expect(formatDetailItem('Simple error string')).toBe('Simple error string');
  });

  it('handles standard Pydantic error object with loc array and msg', () => {
    const pydanticItem = {
      loc: ['body', 'url'],
      msg: 'field required',
      type: 'value_error.missing',
    };
    expect(formatDetailItem(pydanticItem)).toBe('body.url: field required');
  });

  it('handles array detail items without loc safely', () => {
    expect(formatDetailItem({ msg: 'URL scheme not supported' })).toBe('URL scheme not supported');
    expect(formatDetailItem({ message: 'Token expired' })).toBe('Token expired');
    expect(formatDetailItem({ detail: 'Account is private' })).toBe('Account is private');
  });

  it('handles non-array loc or numeric loc', () => {
    expect(formatDetailItem({ loc: 'url', msg: 'invalid url' })).toBe('url: invalid url');
    expect(formatDetailItem({ loc: ['items', 0, 'id'], msg: 'not found' })).toBe('items.0.id: not found');
  });

  it('handles fallback JSON stringification', () => {
    expect(formatDetailItem({ code: 400 })).toBe('{"code":400}');
  });

  it('handles primitives, null, and undefined without throwing', () => {
    expect(formatDetailItem(null)).toBe('');
    expect(formatDetailItem(undefined)).toBe('');
    expect(formatDetailItem(123)).toBe('123');
    expect(formatDetailItem(true)).toBe('true');
  });
});

describe('api: extractErrorMessage', () => {
  it('extracts from ApiError with string detail', () => {
    const err = new ApiError(404, 'Not Found', 'Media item not found');
    expect(extractErrorMessage(err)).toBe('Media item not found');
  });

  it('extracts from ApiError with Pydantic array detail', () => {
    const err = new ApiError(422, 'Unprocessable Entity', [
      { loc: ['body', 'url'], msg: 'field required', type: 'value_error' },
      { loc: ['body', 'format_id'], msg: 'invalid choice', type: 'value_error' },
    ]);
    expect(extractErrorMessage(err)).toBe('body.url: field required, body.format_id: invalid choice');
  });

  it('extracts from ApiError with array detail lacking loc without throwing TypeError', () => {
    const err1 = new ApiError(422, 'Unprocessable Entity', [
      { msg: 'URL scheme not supported' } as any,
    ]);
    expect(extractErrorMessage(err1)).toBe('URL scheme not supported');

    const err2 = new ApiError(400, 'Bad Request', ['Error item A', 'Error item B'] as any);
    expect(extractErrorMessage(err2)).toBe('Error item A, Error item B');
  });

  it('extracts from standard Error instances', () => {
    const err = new Error('Network timeout during fetch');
    expect(extractErrorMessage(err)).toBe('Network timeout during fetch');
  });

  it('extracts from Error instances with attached detail', () => {
    const err = new Error('Fetch failed') as any;
    err.detail = 'Custom attached detail message';
    expect(extractErrorMessage(err)).toBe('Custom attached detail message');
  });

  it('extracts from plain objects with string detail', () => {
    expect(extractErrorMessage({ detail: 'Post not found or private' })).toBe('Post not found or private');
  });

  it('extracts from plain objects with array detail without loc', () => {
    expect(extractErrorMessage({ detail: [{ msg: 'URL scheme not supported' }] })).toBe(
      'URL scheme not supported'
    );
    expect(extractErrorMessage({ detail: ['First error', 'Second error'] })).toBe(
      'First error, Second error'
    );
  });

  it('extracts from plain objects with message or error fields', () => {
    expect(extractErrorMessage({ message: 'Server unavailable' })).toBe('Server unavailable');
    expect(extractErrorMessage({ error: 'Gateway timeout' })).toBe('Gateway timeout');
  });

  it('extracts from plain strings', () => {
    expect(extractErrorMessage('Direct error string')).toBe('Direct error string');
  });

  it('falls back gracefully on unknown or empty shapes', () => {
    expect(extractErrorMessage(null)).toBe('An unexpected error occurred. Please try again.');
    expect(extractErrorMessage(undefined)).toBe('An unexpected error occurred. Please try again.');
    expect(extractErrorMessage({})).toBe('An unexpected error occurred. Please try again.');
    expect(extractErrorMessage('')).toBe('An unexpected error occurred. Please try again.');
  });
});

describe('api: ApiError flags and properties', () => {
  it('correctly sets flags based on HTTP status codes', () => {
    const err401 = new ApiError(401, 'Auth required');
    expect(err401.isAuthRequired).toBe(true);
    expect(err401.isRateLimit).toBe(false);
    expect(err401.isValidationError).toBe(false);

    const err429 = new ApiError(429, 'Rate limited');
    expect(err429.isAuthRequired).toBe(false);
    expect(err429.isRateLimit).toBe(true);
    expect(err429.isValidationError).toBe(false);

    const err422 = new ApiError(422, 'Validation error');
    expect(err422.isAuthRequired).toBe(false);
    expect(err422.isRateLimit).toBe(false);
    expect(err422.isValidationError).toBe(true);

    const err500 = new ApiError(500, 'Server error');
    expect(err500.isAuthRequired).toBe(false);
    expect(err500.isRateLimit).toBe(false);
    expect(err500.isValidationError).toBe(false);
  });
});

describe('api: getSafeDownloadUrl', () => {
  it('encodes # characters as %23', () => {
    expect(getSafeDownloadUrl('/api/files/task-1/#video.mp4')).toBe('/api/files/task-1/%23video.mp4');
    expect(getSafeDownloadUrl('/api/files/task-1/#tag1_#tag2.zip')).toBe('/api/files/task-1/%23tag1_%23tag2.zip');
  });

  it('keeps URLs without # unchanged', () => {
    expect(getSafeDownloadUrl('/api/files/task-1/normal_video.mp4')).toBe('/api/files/task-1/normal_video.mp4');
  });

  it('preserves full http/https URLs and encodes # in them', () => {
    expect(getSafeDownloadUrl('https://example.com/files/download.mp4')).toBe('https://example.com/files/download.mp4');
    expect(getSafeDownloadUrl('https://example.com/files/#hash.mp4')).toBe('https://example.com/files/%23hash.mp4');
    expect(getSafeDownloadUrl('http://cdn.local:8000/media.mp3')).toBe('http://cdn.local:8000/media.mp3');
  });

  it('keeps already encoded %23 URLs intact', () => {
    expect(getSafeDownloadUrl('/api/files/task-1/%23already_encoded.mp4')).toBe('/api/files/task-1/%23already_encoded.mp4');
  });
});

describe('api: triggerBrowserDownload', () => {
  it('encodes # as %23 in downloadUrl and sets anchor.download retaining #', () => {
    let createdAnchor: any = null;
    let appendedChild: any = null;
    let removedChild: any = null;
    let clickCalled = false;

    const fakeAnchor = {
      href: '',
      download: '',
      style: { display: '' },
      click: () => {
        clickCalled = true;
      },
    };

    (globalThis as any).document = {
      createElement: (tag: string) => {
        if (tag === 'a') {
          createdAnchor = { ...fakeAnchor };
          return createdAnchor;
        }
        return {};
      },
      body: {
        appendChild: (el: any) => {
          appendedChild = el;
        },
        removeChild: (el: any) => {
          removedChild = el;
        },
      },
    };

    try {
      triggerBrowserDownload('/api/files/task-123/#Umingle_video.mp4', '#Umingle_video.mp4');
      expect(createdAnchor).not.toBeNull();
      expect(createdAnchor.href).toBe('/api/files/task-123/%23Umingle_video.mp4');
      expect(createdAnchor.download).toBe('#Umingle_video.mp4');
      expect(clickCalled).toBe(true);
      expect(appendedChild).toBe(createdAnchor);
      expect(removedChild).toBe(createdAnchor);
    } finally {
      delete (globalThis as any).document;
    }
  });

  it('keeps already encoded URLs intact and sets anchor.download', () => {
    let createdAnchor: any = null;

    const fakeAnchor = {
      href: '',
      download: '',
      style: { display: '' },
      click: () => {},
    };

    (globalThis as any).document = {
      createElement: (tag: string) => {
        if (tag === 'a') {
          createdAnchor = { ...fakeAnchor };
          return createdAnchor;
        }
        return {};
      },
      body: {
        appendChild: () => {},
        removeChild: () => {},
      },
    };

    try {
      triggerBrowserDownload('/api/files/task-123/%23Umingle_video.mp4', '#Umingle_video.mp4');
      expect(createdAnchor).not.toBeNull();
      expect(createdAnchor.href).toBe('/api/files/task-123/%23Umingle_video.mp4');
      expect(createdAnchor.download).toBe('#Umingle_video.mp4');
    } finally {
      delete (globalThis as any).document;
    }
  });
});

