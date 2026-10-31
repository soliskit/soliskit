import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const documents = {
  'requirements.md': '# Requirements',
  'evidence-record.md': '# Evidence Record',
};

for (const [file, heading] of Object.entries(documents)) {
  test(`document shell: ${file}`, async () => {
    const content = await readFile(new URL(`../docs/${file}`, import.meta.url), 'utf8');
    assert.ok(content.startsWith(`${heading}\n`), 'expected document heading');
    assert.ok(content.trim().length > heading.length, 'expected document structure');
  });
}
