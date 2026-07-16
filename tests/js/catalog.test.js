import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/catalog.js'), 'utf8');

function buildDom() {
  document.body.innerHTML = `
    <input id="catalog-search"><select id="catalog-category"><option value=""></option><option value="role">役割</option></select>
    <select id="catalog-discovery"><option value="all"></option><option value="discovered"></option><option value="undiscovered"></option></select>
    <button id="catalog-random"></button><span id="catalog-count"></span><span id="catalog-progress"></span>
    <div id="catalog-grid">
      <div class="item" data-fetish-id="0" data-category="relation" data-search="ntr 嫉妬" tabindex="0"></div>
      <div class="item" data-fetish-id="1" data-category="role" data-search="騎士 忠誠" tabindex="0"></div>
      <div class="item" data-fetish-id="2" data-category="role" data-search="先生 教師" tabindex="0"></div>
    </div><p id="catalog-empty" hidden></p>`;
}

describe('HekiCatalog', () => {
  beforeEach(() => {
    buildDom();
    const storage = new Map([['heki_history', JSON.stringify([{fetish_id: 0, compound_ids: [1]}])]]);
    vi.stubGlobal('localStorage', {getItem: key => storage.get(key) ?? null});
    Element.prototype.scrollIntoView = vi.fn();
    window.eval(source);
    window.HekiCatalog.init();
  });

  it('recognizes result ID zero and compound results as discovered', () => {
    const discovered = window.HekiCatalog.discoveredIds();
    expect([...discovered]).toEqual([0, 1]);
    expect(document.getElementById('catalog-progress').textContent).toBe('診断済み 2/3');
  });

  it('combines text, category and discovery filters', () => {
    const category = document.getElementById('catalog-category');
    category.value = 'role';
    category.dispatchEvent(new Event('change'));
    document.getElementById('catalog-discovery').value = 'undiscovered';
    document.getElementById('catalog-discovery').dispatchEvent(new Event('change'));

    const items = [...document.querySelectorAll('.item')];
    expect(items.map(item => item.hidden)).toEqual([true, true, false]);
    expect(document.getElementById('catalog-count').textContent).toBe('1/3種類を表示');

    document.getElementById('catalog-search').value = '該当なし';
    document.getElementById('catalog-search').dispatchEvent(new Event('input'));
    expect(document.getElementById('catalog-empty').hidden).toBe(false);
  });

  it('focuses one of the currently visible cards for random discovery', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    document.getElementById('catalog-random').click();
    expect(document.activeElement).toBe(document.querySelector('.item'));
    expect(document.activeElement.classList).toContain('is-random-pick');
  });
});
