import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/renderers.js'), 'utf8');

describe('HekiRenderers screen transitions', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="start-screen"><h2 id="start-title" tabindex="-1">S</h2></div><div id="question-screen" class="hidden"><h2 id="question-text" tabindex="-1">Q</h2></div>
      <div id="result-screen" class="hidden"><h2 id="result-name" tabindex="-1">R</h2></div>
      <div id="teach-screen"><h2 id="teach-label" tabindex="-1">T</h2></div>
      <div id="done-screen"><h2 id="done-msg" tabindex="-1">D</h2></div>`;
    vi.stubGlobal('requestAnimationFrame', callback => callback());
    Element.prototype.scrollIntoView = vi.fn();
    window.scrollTo = vi.fn();
    window.trackGameplayEvent = vi.fn();
    delete window.IntersectionObserver;
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

  it('labels the adjusted result value as a candidate score, not a probability', () => {
    document.body.innerHTML += '<div id="result-kicker"></div><div id="result-badges"></div><div id="result-score-note">確率ではありません</div>';
    window.HekiRenderers.renderResultDrama({probability: 3.9}, '結果', String);
    expect(document.getElementById('result-prob').textContent).toBe('候補スコア 3.9 / 100');
    expect(document.getElementById('result-prob').getAttribute('aria-describedby')).toBe('result-score-note');
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
      <div id="result-rival" class="hidden"></div><div id="result-desc"></div><div id="result-detail-desc"></div><div id="fetish-detail-link-slot"></div>
      <div id="confirm-items"></div><section id="profile-section" class="hidden"><div id="profile-list"></div></section>
      <div id="top-chart"></div>
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
        compound: [{fetish_id: 2, fetish_name: '要素A', fetish_desc: '要素Aの説明', probability: 50}],
        profile: [{fetish_name: '近い傾向', probability: 42}], related: [], works: [], cross_works: [], top_chart: [
          {fetish_name: '本命', probability: 72},
          {fetish_name: '対抗候補', probability: 63},
        ],
      },
      {escapeHtml: String, safeExternalUrl: String},
    );

    expect(document.getElementById('result-rival').textContent).toContain('対抗候補「対抗候補」');
    expect(document.getElementById('result-detail-desc').textContent)
      .toContain('本命と要素Aの傾向が同時に表れました。');
    expect(document.getElementById('contrastive-reasons-section').textContent)
      .toContain('対抗候補との差になった回答');
    expect(document.getElementById('reasons-section').textContent).toContain('本命そのものの決め手');
    const chart = document.getElementById('top-chart');
    expect(chart.querySelectorAll('progress')).toHaveLength(2);
    expect(chart.querySelector('progress').value).toBe(100);
    expect(chart.querySelector('progress').getAttribute('aria-label')).toContain('本命');
    expect(chart.querySelector('.chart-value').textContent).toBe('72 / 100');
    expect(document.querySelectorAll('.confirm-item-prob')[0].textContent).toBe('72 / 100');
    expect(document.querySelectorAll('.confirm-item-prob')[1].textContent).toBe('50 / 100');
    expect(document.querySelector('#profile-list .profile-item span').textContent).toBe('42 / 100');
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
    ['start-screen', 'start-title', true],
    ['question-screen', 'question-text', false],
    ['result-screen', 'result-name', false],
    ['teach-screen', 'teach-label', true],
    ['done-screen', 'done-msg', true],
  ])('focuses the main heading for %s and preserves the host when needed', (screenId, headingId, shouldScrollToHeading) => {
    window.HekiRenderers.showScreen(screenId);
    const heading = document.getElementById(headingId);
    if (shouldScrollToHeading) {
      expect(heading.scrollIntoView).toHaveBeenCalledWith({block: 'start', behavior: 'auto'});
    } else {
      expect(heading.scrollIntoView).not.toHaveBeenCalled();
    }

    expect(document.body.dataset.screen).toBe(screenId);
    expect(document.body.dataset.screen).toBe(screenId);
    expect(document.activeElement).toBe(heading);

  });
  it('scrolls a result transition back to the genie when the player has scrolled down', () => {
    Object.defineProperty(window, 'scrollY', {configurable: true, value: 120});
    window.HekiRenderers.showScreen('result-screen');

    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
    expect(document.activeElement).toBe(document.getElementById('result-name'));
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
  it('tracks only visible works with stable IDs and deduplicates repeated rendering', () => {
    document.body.innerHTML += `
      <section id="works-section" class="hidden">
        <div id="works-label"></div>
        <div id="cross-works-tags"></div>
        <div id="works-tags"></div>
      </section>`;
    const works = [1, 2, 3, 4, 5].map(id => ({
      title: `作品${id}`,
      url: `https://example.test/${id}`,
      work_id: `wrk_${id}`,
      edition_id: `wed_${id}`,
    }));
    const data = {compound: [], cross_works: [], works: [...works, works[0]]};
    const helpers = {escapeHtml: String, safeExternalUrl: String, resultName: '本命'};

    window.HekiRenderers.renderWorks(data, helpers);
    window.HekiRenderers.trackFeaturedWorks(data);
    expect(window.trackGameplayEvent).toHaveBeenCalledTimes(3);
    expect(window.trackGameplayEvent).toHaveBeenNthCalledWith(1, 'work_impression', expect.objectContaining({
      work_id: 'wrk_1', edition_id: 'wed_1',
    }));
    expect(window.trackGameplayEvent.mock.calls.flatMap(call => [call[1].work_id]))
      .not.toContain('wrk_4');

    window.HekiRenderers.renderWorks(data, helpers);
    window.HekiRenderers.trackFeaturedWorks(data);
    expect(window.trackGameplayEvent).toHaveBeenCalledTimes(3);
    window.HekiRenderers.toggleMoreWorks(document.querySelector('.works-more-toggle'));
    expect(window.trackGameplayEvent).toHaveBeenCalledTimes(5);
    expect(window.trackGameplayEvent.mock.calls.map(call => call[1].work_id))
      .toEqual(['wrk_1', 'wrk_2', 'wrk_3', 'wrk_4', 'wrk_5']);
  });

  it('records a work impression only after at least half the card enters the viewport', () => {
    document.body.innerHTML += `
      <section id="works-section" class="hidden">
        <div id="works-label"></div><div id="cross-works-tags"></div><div id="works-tags"></div>
      </section>`;
    let callback;
    const observe = vi.fn();
    const unobserve = vi.fn();
    window.IntersectionObserver = class {
      constructor(handler, options) {
        callback = handler;
        expect(options).toEqual({threshold: 0.5});
      }
      observe(card) { observe(card); }
      unobserve(card) { unobserve(card); }
      disconnect() {}
    };
    const data = {compound: [], cross_works: [], works: [{title: '作品', work_id: 'wrk_1', edition_id: 'wed_1'}]};
    window.HekiRenderers.renderWorks(
      data,
      {escapeHtml: String, safeExternalUrl: String, resultName: '本命'},
    );
    window.HekiRenderers.trackFeaturedWorks(data);
    const card = document.querySelector('.work-recommendation');
    expect(observe).toHaveBeenCalledWith(card);
    expect(window.trackGameplayEvent).not.toHaveBeenCalled();

    callback([{target: card, isIntersecting: true, intersectionRatio: 0.49}]);
    expect(window.trackGameplayEvent).not.toHaveBeenCalled();
    callback([{target: card, isIntersecting: true, intersectionRatio: 0.5}]);
    expect(window.trackGameplayEvent).toHaveBeenCalledTimes(1);
    expect(unobserve).toHaveBeenCalledWith(card);
  });

  it('does not let impression recording failures block recommendation rendering', () => {
    document.body.innerHTML += `
      <section id="works-section" class="hidden">
        <div id="works-label"></div><div id="cross-works-tags"></div><div id="works-tags"></div>
      </section>`;
    window.trackGameplayEvent.mockImplementation(() => { throw new Error('metrics unavailable'); });
    const data = {compound: [], cross_works: [], works: [{title: '作品', work_id: 'wrk_1', edition_id: 'wed_1'}]};
    expect(() => {
      window.HekiRenderers.renderWorks(data, {escapeHtml: String, safeExternalUrl: String, resultName: '本命'});
      window.HekiRenderers.trackFeaturedWorks(data);
    }).not.toThrow();
    expect(document.querySelector('.work-recommendation').textContent).toContain('作品');
  });
  it("keeps secondary result information collapsed until requested", () => {
    document.body.insertAdjacentHTML("beforeend", `<button data-action="toggle-result-details" aria-expanded="false">結果を詳しく見る</button><div id="result-details" class="hidden"></div><button data-action="toggle-result-actions" aria-expanded="false">もう一度遊ぶ</button><div id="result-more-actions" class="hidden"></div>`);
    window._guessData = {};
    const detailsButton = document.querySelector(`[data-action="toggle-result-details"]`);
    window.HekiRenderers.toggleResultDetails(detailsButton);
    expect(detailsButton.getAttribute("aria-expanded")).toBe("true");
    expect(document.getElementById("result-details").classList.contains("hidden")).toBe(false);
    const actionsButton = document.querySelector(`[data-action="toggle-result-actions"]`);
    window.HekiRenderers.toggleResultActions(actionsButton);
    expect(actionsButton.getAttribute("aria-expanded")).toBe("true");
    expect(document.getElementById("result-more-actions").classList.contains("hidden")).toBe(false);
  });
});
