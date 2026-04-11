describe('Dashboard AVA', () => {
  it('carrega tela principal', () => {
    cy.visit('/')
    cy.contains('Painel de Integracao Moodle').should('be.visible')
    cy.contains('Executar Sincronizacao').should('be.visible')
  })
})

