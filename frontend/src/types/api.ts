/**
 * API Type Definitions for All-in-One Media Downloader Frontend
 *
 * Mapped directly from Backend Pydantic V2 Models:
 * - backend/app/models/inspect.py
 * - backend/app/models/download.py
 * - backend/app/models/progress.py
 * - backend/app/models/cookies.py
 * - backend/app/models/proxy.py
 * - backend/app/routers/settings.py
 * - backend/app/services/progress_manager.py
 */

// ============================================================================
// 1. Primitive Unions & Platform Types
// ============================================================================

/** Supported media types recognized by backend inspect router */
export type MediaType = 'video' | 'image' | 'audio' | 'carousel' | 'story';

/** Known primary platforms with open string extension */
export type PlatformType =
  | 'youtube'
  | 'instagram'
  | 'twitter'
  | 'tiktok'
  | 'generic'
  | (string & {});

export type MediaPlatform = PlatformType;

/** Item type within carousels or stories */
export type MediaItemType = 'video' | 'image' | 'audio';

/** Supported audio extraction container formats */
export type AudioFormat = 'mp3' | 'm4a' | 'wav';

/** Download task lifecycle statuses */
export type TaskStatus =
  | 'queued'
  | 'downloading'
  | 'postprocessing'
  | 'completed'
  | 'error';

/** Platforms supported by cookie manager */
export type CookiePlatform = 'instagram' | 'twitter' | 'youtube' | 'tiktok';
export type SupportedCookiePlatform = CookiePlatform;

/** Origin of the active proxy setting */
export type ProxySource = 'runtime' | 'env' | 'none';

// ============================================================================
// 2. Inspection Models (POST /api/inspect)
// ============================================================================

/** Payload to inspect a media URL */
export interface InspectRequest {
  /** The URL of the media to inspect */
  url: string;
  /** Optional client session cookies per platform or raw Netscape string */
  cookies?: Record<string, string> | string | null;
  /** Optional client session proxy URL */
  proxy?: string | null;
}

/** Individual item in a carousel or story */
export interface MediaItem {
  /** 0-based index of the item */
  index: number;
  /** Type of media item */
  type: MediaItemType;
  /** Direct URL of the media resource if available */
  url?: string | null;
  /** Direct thumbnail URL */
  thumbnail?: string | null;
  /** Resolution string (e.g. "1080x1920") */
  resolution?: string | null;
  /** Duration in seconds if video */
  duration?: number | null;
  /** Creation or upload date string */
  date?: string | null;
  /** Original filename stem */
  original_name?: string | null;
  /** Original CDN filename stem */
  original_name_first?: string | null;
}

/** Available download quality or format */
export interface FormatOption {
  /** Unique format identifier for download (e.g. "best", "1080p", "audio-mp3") */
  format_id: string;
  /** Human-readable label for UI display */
  label: string;
  /** File extension (e.g. "mp4", "mp3", "jpg") */
  ext: string;
  /** Estimated filesize in bytes if available */
  filesize?: number | null;
  /** Video resolution label (e.g. "1080p", "720p") */
  resolution?: string | null;
}

/** Alias for FormatOption matching UI nomenclature */
export type MediaFormat = FormatOption;

/** Normalized response returned from inspection */
export interface InspectResponse {
  /** Normalized identifier for the extracted media */
  id: string;
  /** Original requested URL */
  url: string;
  /** Platform identifier */
  platform: PlatformType;
  /** Media title or post description */
  title: string;
  /** Author / channel / uploader handle */
  uploader?: string | null;
  /** Main preview thumbnail URL */
  thumbnail?: string | null;
  /** Overall classification of media */
  media_type: MediaType;
  /** Items for carousels or stories */
  items?: MediaItem[];
  /** Available qualities/formats for single media */
  formats?: FormatOption[];
  /** Media creation or upload date string */
  date?: string | null;
  /** Original CDN filename stem or resource identifier */
  original_name_first?: string | null;
}

// ============================================================================
// 3. Download Models (POST /api/download)
// ============================================================================

/** Payload to request media download */
export interface DownloadRequest {
  /** Target media URL */
  url: string;
  /** Requested format identifier (default: "best") */
  format_id?: string | null;
  /** Subset of item indices to download (for carousels/stories) */
  selected_indices?: number[] | null;
  /** Whether to extract audio only (default: false) */
  extract_audio?: boolean;
  /** Audio container format (default: "mp3") */
  audio_format?: AudioFormat;
  /** Whether to bundle multiple items into a ZIP archive (default: true) */
  package_as_zip?: boolean;
  /** Optional pre-inspected metadata to bypass re-inspection */
  metadata?: Record<string, unknown> | null;
  /** Optional client session cookies per platform or raw Netscape string */
  cookies?: Record<string, string> | string | null;
  /** Optional client session proxy URL */
  proxy?: string | null;
}

/** Initial response acknowledging download task creation */
export interface DownloadResponse {
  /** Unique task identifier */
  task_id: string;
  /** Initial task status (default: "queued") */
  status: string;
}

/** Individual downloaded file information when unbundled */
export interface DownloadFileItem {
  /** Filename of individual file */
  filename: string;
  /** Relative API URL to retrieve the file */
  download_url: string;
  /** File size in bytes if available */
  file_size?: number | null;
}

/** Final result of a completed download task (internal router/service contract) */
export interface DownloadResult {
  /** Unique task identifier */
  task_id: string;
  /** Human-friendly filename of the output media or bundle */
  filename: string;
  /** Absolute path on disk to the output file */
  file_path: string;
  /** Size of the output file in bytes */
  file_size: number;
  /** Relative API URL to retrieve the file */
  download_url: string;
  /** True if output is a packaged ZIP archive */
  is_zip: boolean;
  /** Individual files if unbundled */
  files?: DownloadFileItem[] | null;
}

// ============================================================================
// 4. Progress & Server-Sent Events (SSE) Models (GET /api/progress/{task_id})
// ============================================================================

/** Comprehensive progress status of an asynchronous download job */
export interface TaskProgress {
  /** Unique task identifier */
  task_id: string;
  /** Current lifecycle state of the download task */
  status: TaskStatus;
  /** Download progress percentage (0.0 to 100.0) */
  progress: number;
  /** Download speed string (e.g. "4.2MiB/s") */
  speed?: string | null;
  /** Estimated time remaining in seconds */
  eta?: number | null;
  /** Detailed status or post-processing message */
  message?: string | null;
  /** Relative URL to retrieve the finished media */
  download_url?: string | null;
  /** Filename for client saving */
  filename?: string | null;
  /** Total size in bytes if available */
  file_size?: number | null;
  /** Error message if task failed */
  error?: string | null;
  /** Individual completed files when unbundled */
  files?: DownloadFileItem[] | null;
}

/** SSE Event Names emitted by GET /api/progress/{task_id} */
export type SSEEventName = 'progress' | 'postprocessing' | 'complete' | 'error';

/** Payload emitted with event: 'progress' */
export interface ProgressEventData {
  status: 'queued' | 'downloading';
  progress: number;
  speed?: string | null;
  eta?: number | null;
  message?: string | null;
}

export type ProgressEventPayload = ProgressEventData;

/** Payload emitted with event: 'postprocessing' */
export interface PostprocessingEventData {
  status: 'postprocessing';
  message?: string | null;
}

export type PostprocessingEventPayload = PostprocessingEventData;

/** Payload emitted with event: 'complete' */
export interface CompleteEventData {
  status: 'completed';
  download_url: string;
  filename: string;
  file_size: number;
  files?: DownloadFileItem[] | null;
}

export type CompleteEventPayload = CompleteEventData;

/** Payload emitted with event: 'error' */
export interface ErrorEventData {
  status: 'error';
  message: string;
}

export type ErrorEventPayload = ErrorEventData;

/** Discriminated union of all SSE event payloads */
export type SSEPayload =
  | ProgressEventPayload
  | PostprocessingEventPayload
  | CompleteEventPayload
  | ErrorEventPayload;

export type ProgressSSEEvent =
  | { event: 'progress'; data: ProgressEventData }
  | { event: 'postprocessing'; data: PostprocessingEventData }
  | { event: 'complete'; data: CompleteEventData }
  | { event: 'error'; data: ErrorEventData };

// ============================================================================
// 5. Settings Models (Cookies & Proxy APIs)
// ============================================================================

/** Status details for a platform's cookie file */
export interface CookieStatus {
  /** Platform name (instagram, twitter, youtube, tiktok) */
  platform: CookiePlatform | string;
  /** Whether a cookie file exists on disk */
  exists: boolean;
  /** Whether cookies are well-formatted and not expired */
  valid: boolean;
  /** ISO timestamp of key session cookie expiration if detected */
  expires_at?: string | null;
  /** Total number of valid cookies found in file */
  cookie_count: number;
  /** Human-readable status summary or error notes */
  details?: string | null;
}

/** Map of cookie statuses by platform returned from GET /api/settings/cookies */
export interface CookieStatusMap {
  instagram: CookieStatus;
  twitter: CookieStatus;
  youtube: CookieStatus;
  tiktok: CookieStatus;
  [platform: string]: CookieStatus;
}

/** Alias for cookie status response */
export type CookieStatusResponse = Record<string, CookieStatus>;

/** Payload to upload or paste cookie content (POST /api/settings/cookies) */
export interface CookieUpdateRequest {
  /** Target platform (instagram, twitter, youtube, tiktok) */
  platform: CookiePlatform | string;
  /** Netscape HTTP Cookie File formatted text */
  content: string;
}

/** Alias for CookieUpdateRequest matching UI action naming */
export type CookieSaveRequest = CookieUpdateRequest;

/** Response returned after saving pasted cookies */
export interface SaveCookiesResponse {
  status: 'saved' | 'uploaded';
  platform: string;
  cookie_status: CookieStatus;
}

export type CookieSaveResponse = SaveCookiesResponse;
export type CookieUploadResponse = SaveCookiesResponse;

/** Response returned after deleting cookie file */
export interface DeleteCookiesResponse {
  status: 'deleted' | 'not_found';
  platform: string;
}

export type CookieDeleteResponse = DeleteCookiesResponse;

/** Current proxy settings configuration (GET /api/settings/proxy) */
export interface ProxyConfig {
  /** SOCKS5 or HTTP proxy URL */
  proxy: string | null;
  /** Source of current proxy configuration */
  source: ProxySource;
}

/** Alias for ProxyConfig matching settings response naming */
export type ProxySettingsResponse = ProxyConfig;

/** Payload to update the runtime proxy setting (POST /api/settings/proxy) */
export interface ProxyUpdateRequest {
  /** New proxy URL, or null/empty string to clear */
  proxy: string | null;
}

// ============================================================================
// 6. Generic API Error & Helper Types
// ============================================================================

export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** Standard FastAPI error payload */
export interface APIErrorResponse {
  detail: string | ValidationErrorItem[];
}

export type ApiErrorResponse = APIErrorResponse;
