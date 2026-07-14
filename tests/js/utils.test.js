import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeAll, describe, expect, it} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/utils.js'), 'utf8');

beforeAll(() => {
  window.eval(source);
});

describe('HekiUtils', () => {
  it('escapes every HTML-sensitive character', () => {
    expect(window.HekiUtils.escapeHtml(`<a href="'">&`)).toBe(
      '&lt;a href=&quot;&#39;&quot;&gt;&amp;',
    );
  });

  it('accepts only HTTP and HTTPS external URLs', () => {
    expect(window.HekiUtils.safeExternalUrl('https://example.com/item')).toBe(
      'https://example.com/item',
    );
    expect(window.HekiUtils.safeExternalUrl('javascript:alert(1)')).toBeNull();
    expect(window.HekiUtils.safeExternalUrl('data:text/plain,test')).toBeNull();
  });
});
