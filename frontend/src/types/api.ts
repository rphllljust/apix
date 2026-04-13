export interface HealthResponse {
  moodle: {
    status: 'online' | 'offline' | 'auth_error'
    username: string
    fullname: string
    userid: number
    site: string
    version: string
  }
  sheets: {
    status: 'online' | 'offline'
    last_check: string
  }
}

export interface CourseItem {
  id: number
  shortname?: string
  fullname?: string
  visible?: number
}

export interface SyncLogItem {
  sync_id: string
  timestamp: string
  direction: 'moodle_to_sheets' | 'sheets_to_moodle'
  entity: 'users' | 'grades' | 'enrollments' | 'progress'
  course_id: number
  records_processed: number
  records_created: number
  records_updated: number
  records_failed: number
  errors: string[]
  duration_seconds: number
  status: 'success' | 'partial' | 'failed'
}

export interface SyncSummaryResponse {
  direction: string
  started_at: string
  finished_at: string
  duration_seconds: number
  processed_counts: Record<string, number>
  warnings: string[]
  extra: Record<string, unknown>
}

export interface MoodleTokenConfigResponse {
  ok: boolean
  message: string
  moodle: {
    username: string
    fullname: string
    userid: number
    site: string
    version: string
  }
  runtime_status: 'online' | 'degraded'
}

export interface GoogleSheetsOAuthStartResponse {
  auth_url: string
  expires_in_seconds: number
  redirect_uri: string
}

export interface GoogleSheetsConfigResponse {
  integration_mode: 'oauth' | 'apps_script'
  oauth: {
    configured: boolean
    client_id_masked: string
    redirect_uri: string
    refresh_token_configured: boolean
  }
  apps_script: {
    configured: boolean
    webhook_url: string
    webhook_token_configured: boolean
    timeout_seconds: number
  }
  spreadsheet: {
    id: string
    url: string
  }
}

export interface GoogleSheetsConfigPayload {
  client_id: string
  client_secret: string
  redirect_uri: string
  spreadsheet: string
}

export interface GoogleSheetsConfigSaveResponse {
  ok: boolean
  message: string
  integration_mode: 'oauth' | 'apps_script'
  oauth: {
    configured: boolean
    redirect_uri: string
    refresh_token_configured: boolean
  }
  apps_script?: {
    configured: boolean
    webhook_url: string
    webhook_token_configured: boolean
    timeout_seconds: number
  }
  spreadsheet: {
    id: string
    url: string
  }
  sheets_runtime_status: 'online' | 'offline'
}

export interface GoogleSheetsAppsScriptConfigPayload {
  spreadsheet: string
  webhook_url: string
  webhook_token?: string
}

export interface DriveToMoodleSyncResponse {
  direction: string
  started_at: string
  finished_at: string
  duration_seconds: number
  processed_counts: {
    uploaded: number
    failed: number
  }
  warnings: string[]
  extra: {
    uploaded: string[]
    failed: string[]
    triggered_by: string
  }
}
