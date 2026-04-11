import { create } from 'zustand'

type SyncMode = 'full' | 'grades' | 'enrollments'
type DataSourceMode = 'rest' | 'graphql'

interface UiStoreState {
  selectedCourseId: number | null
  syncMode: SyncMode
  dataSource: DataSourceMode
  setSelectedCourseId: (value: number | null) => void
  setSyncMode: (value: SyncMode) => void
  setDataSource: (value: DataSourceMode) => void
}

export const useUiStore = create<UiStoreState>((set) => ({
  selectedCourseId: null,
  syncMode: 'full',
  dataSource: 'rest',
  setSelectedCourseId: (value) => set({ selectedCourseId: value }),
  setSyncMode: (value) => set({ syncMode: value }),
  setDataSource: (value) => set({ dataSource: value }),
}))
