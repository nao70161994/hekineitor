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
  it('renders low-information results as provisional', () => {
    document.body.innerHTML += '<div id="result-kicker"></div><div id="result-badges"></div><div id="result-rival" class="hidden"></div>';
    window.HekiRenderers.renderResultDrama(
      {provisional: true, provisional_message: 'まだ読み切れません', probability: 30},
      '結果',
      String,
    );
    expect(document.getElementById('result-kicker').textContent).toBe('まだ読み切れません');
    expect(document.getElementById('result-rival').textContent).toContain('追加質問に答えると');
    expect(document.getElementById('result-rival').classList.contains('hidden')).toBe(false);
  });

  it('separates contrastive evidence from ordinary reasons with an accessible label', () => {
    document.body.innerHTML += `
      <section id="reasons-section" class="hidden">
        <div class="reasons-label">決め手になった回答</div>
        <div id="reasons-list"></div>
      </section>`;
    window.HekiRenderers.renderContrastiveReasons(
      [{text: '対抗候補より本命を支持した回答', ans: 1}],
      {fetish_name: '対抗候補'},
      String,
    );

    const section = document.getElementById('contrastive-reasons-section');
    expect(section.getAttribute('aria-labelledby')).toBe('contrastive-reasons-label');
    expect(document.getElementById('contrastive-reasons-label').textContent)
      .toBe('対抗候補「対抗候補」との差になった回答');
    expect(section.textContent).toContain('対抗候補より本命を支持した回答');
    expect(document.querySelector('#reasons-section').textContent).toContain('決め手になった回答');
  });

  it('renders runner-up evidence and the compound explanation in separate regions', () => {
    document.body.innerHTML += `
      <div id="result-kicker"></div><div id="result-badges"></div>
      <div id="result-rival" class="hidden"></div><div id="result-desc"></div>
      <section id="reasons-section" class="hidden">
        <div class="reasons-label">決め手になった回答</div>
        <div id="reasons-list"></div>
      </section>`;
    window.HekiRenderers.renderGuess(
      {
        fetish_id: 1,
        fetish_name: '本命',
        fetish_desc: '本命の説明',
        probability: 72,
        runner_up: {fetish_name: '対抗候補', gap_points: 8.5},
        contrastive_reasons: [{text: '対抗候補との差になった回答', ans: 1}],
        reasons: [{text: '本命そのものの決め手', ans: 0.5}],
        compound_explanation: '本命と要素Aの傾向が同時に表れました。',
        compound: [{fetish_id: 2, fetish_name: '要素A', fetish_desc: '要素Aの説明'}],
        profile: [], related: [], works: [], cross_works: [], top_chart: [],
      },
      {escapeHtml: String, safeExternalUrl: String},
    );

    expect(document.getElementById('result-rival').textContent).toContain('対抗候補「対抗候補」');
    expect(document.getElementById('result-desc').textContent)
      .toContain('本命と要素Aの傾向が同時に表れました。');
    expect(document.getElementById('contrastive-reasons-section').textContent)
      .toContain('対抗候補との差になった回答');
    expect(document.getElementById('reasons-section').textContent).toContain('本命そのものの決め手');
  });

  it('renders stable work identity attributes', () => {
    const html = window.HekiRenderers.renderWorkTag(
      {title: 'Work', url: 'https://example.test/work', work_id: 'wrk_1', edition_id: 'wed_1'},
      '',
      {escapeHtml: String, safeExternalUrl: String, resultName: 'Result'},
    );
    expect(html).toContain('data-work-id="wrk_1"');
    expect(html).toContain('data-edition-id="wed_1"');
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
  it('renders the deciding answers for every compound component', () => {
    document.body.innerHTML += `
      <section id="compound-reasons-section" class="hidden">
        <div id="compound-reasons-list"></div>
      </section>`;
    window.HekiRenderers.renderCompoundReasons(
      {
        fetish_name: '本命',
        reasons: [{text: '本命の決め手', ans: 1}],
        compound: [
          {fetish_name: '要素A', reasons: [{text: '要素Aの決め手', ans: -0.5}]},
          {fetish_name: '要素B', reasons: []},
        ],
      },
      String,
    );
    const section = document.getElementById('compound-reasons-section');
    expect(section.classList.contains('hidden')).toBe(false);
    expect(section.textContent).toContain('本命の決め手');
    expect(section.textContent).toContain('要素Aの決め手');
    expect(section.textContent).toContain('どちらかといえばいいえ');
    expect(section.textContent).toContain('個別の決め手はまだ十分に絞れていません');
  });

  it('uses server-provided recommendation reasons and preserves link-specific reasons', () => {
    document.body.innerHTML += `
      <section id="works-section" class="hidden">
        <div id="works-label"></div>
        <div id="cross-works-tags"></div>
        <div id="works-tags"></div>
      </section>`;
    window.HekiRenderers.renderWorks(
      {
        compound: [{fetish_name: '要素A'}],
        cross_works: [{title: '作品A'}],
        works: [{title: '作品B', recommendation_reason: '作品固有の理由'}],
        work_recommendations: [
          {reason: '組み合わせに基づく理由'},
          {reason: 'サーバーの通常理由'},
        ],
      },
      {escapeHtml: String, safeExternalUrl: value => value, resultName: '本命 × 要素A'},
    );
    const featured = document.getElementById('cross-works-tags');
    expect(featured.textContent).toContain('組み合わせに基づく理由');
    expect(featured.textContent).toContain('作品固有の理由');
    expect(featured.textContent).not.toContain('サーバーの通常理由');
  });
});
