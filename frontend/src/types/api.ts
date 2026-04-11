export interface HealthResponse {
  moodle: {
    site_name?: string
    username?: string
    moodle_release?: string
  }
  sheets_ok: boolean
  last_moodle_to_sheets: string | null
  last_sheets_to_moodle: string | null
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

