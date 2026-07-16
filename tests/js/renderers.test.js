import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/renderers.js'), 'utf8');

describe('HekiRenderers screen transitions', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="start-screen"></div><div id="question-screen" class="hidden"><h2 id="question-text" tabindex="-1">Q</h2></div>
      <div id="result-screen" class="hidden"><h2 id="result-name" tabindex="-1">R</h2></div>
      <div id="teach-screen"></div><div id="done-screen"></div>`;
    vi.stubGlobal('requestAnimationFrame', callback => callback());
    Element.prototype.scrollIntoView = vi.fn();
    window.eval(source);
  });

  it.each([
    ['question-screen', 'question-text'],
    ['result-screen', 'result-name'],
  ])('scrolls and focuses the main heading for %s', (screenId, headingId) => {
    window.HekiRenderers.showScreen(screenId);
    const heading = document.getElementById(headingId);
    expect(heading.scrollIntoView).toHaveBeenCalledWith({block: 'start', behavior: 'auto'});
    expect(document.activeElement).toBe(heading);
  });
});
