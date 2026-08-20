import { readFile, readdir, stat } from "node:fs/promises";
import { join } from "node:path";

const requiredPaths = [
  "apps/api/src/app.ts",
  "packages/domain/src/model.ts",
  "packages/domain/src/scenario-registry.ts",
  "docs/architecture/m0-domain-model.md",
  "docs/adr/0001-modular-monolith.md",
];

async function collectFiles(directory) {
  const entries = await readdir(directory);
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry);
    const details = await stat(path);
    if (details.isDirectory()) files.push(...(await collectFiles(path)));
    else files.push(path);
  }
  return files;
}

for (const path of requiredPaths) {
  await stat(path);
}

const domainFiles = (await collectFiles("packages/domain/src")).filter((path) => path.endsWith(".ts"));
const forbiddenImports = /from\s+["'](?:@nestjs|next|express|fastify|prisma|typeorm|drizzle|pg)/;
const scenarioConditional = /if\s*\([^\n)]*scenario(?:Key)?\s*===/i;

for (const path of domainFiles) {
  const source = await readFile(path, "utf8");
  if (forbiddenImports.test(source)) {
    throw new Error(`Domain layer imports infrastructure: ${path}`);
  }
  if (scenarioConditional.test(source)) {
    throw new Error(`Scenario-specific conditional found in core: ${path}`);
  }
}

console.log(`Architecture check passed (${domainFiles.length} domain files).`);
