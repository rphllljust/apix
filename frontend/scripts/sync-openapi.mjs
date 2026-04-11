import { writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import openapiTS from 'openapi-typescript'

const baseUrl =
  process.env.OPENAPI_BASE_URL ||
  process.env.VITE_API_BASE_URL ||
  'http://localhost:8000'
const source = `${baseUrl.replace(/\/$/, '')}/openapi.json`
const outputPath = path.resolve(process.cwd(), 'src/types/openapi.generated.ts')

try {
  const output = await openapiTS(source)
  const fileBody =
    '// Arquivo gerado automaticamente via npm run openapi:sync.\n' +
    '// Nao editar manualmente.\n\n' +
    output

  await writeFile(outputPath, fileBody, 'utf8')
  console.log(`[OK] Tipagens OpenAPI atualizadas: ${outputPath}`)
} catch (error) {
  console.error(
    `[ERRO] Falha ao gerar tipagens a partir de ${source}. Verifique se a API esta no ar.`,
  )
  console.error(error)
  process.exitCode = 1
}

