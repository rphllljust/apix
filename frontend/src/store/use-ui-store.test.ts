import { beforeEach, describe, expect, it } from 'vitest'
import { useUiStore } from '@/store/use-ui-store'

describe('useUiStore', () => {
  beforeEach(() => {
    useUiStore.setState({
      selectedCourseId: null,
      syncMode: 'full',
      dataSource: 'rest',
    })
  })

  it('atualiza curso selecionado, modo de sync e fonte de dados', () => {
    useUiStore.getState().setSelectedCourseId(125)
    useUiStore.getState().setSyncMode('grades')
    useUiStore.getState().setDataSource('graphql')

    const state = useUiStore.getState()
    expect(state.selectedCourseId).toBe(125)
    expect(state.syncMode).toBe('grades')
    expect(state.dataSource).toBe('graphql')
  })
})
