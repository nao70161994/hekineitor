import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const rawSource = readFileSync(resolve(testDir, '../../static/game_flow.js'), 'utf8');
const source = rawSource.replaceAll('_fetching', 'window.__fetching');

function questionDom() {
  document.body.innerHTML = `
    <button class="btn-start" data-action="start-game">スタート</button>
    <button data-action="start-excluding"></button><button data-action="quick-retry"></button>
    <div id="resume-banner"></div><div id="question-text"></div>
    <div id="question-progress-message"></div><div id="question-hint"></div>
    <div id="question-axis-tag"></div><div id="question-stage-label"></div>
    <div class="progress-bar"><div id="progress-fill"></div></div>
    <button id="btn-back"></button><div id="contradiction-hint"></div>
    <div id="question-screen"></div><div id="result-screen"></div>`;
}

describe('HekiGameFlow', () => {
  beforeEach(() => {
    questionDom();
    window.__fetching = false;
    window.setFetching = vi.fn(value => { window.__fetching = value; });
    window.apiFetch = vi.fn();
    window.showToast = vi.fn();
    window.show = vi.fn();
    window.setGenieState = vi.fn();
    window._clearDraft = vi.fn();
    window._saveDraft = vi.fn();
    window._pushDraft = vi.fn();
    window._pauseDraft = vi.fn();
    window.HekiRenderers = {
      setText: (id, value) => { document.getElementById(id).textContent = value; },
      setProgressMessage: vi.fn(),
    };
    window.eval(source);
  });

  it('allows only one start request and keeps the prior draft when it fails', async () => {
    let rejectRequest;
    window.apiFetch.mockImplementation(() => new Promise((resolve, reject) => { rejectRequest = reject; }));

    const first = window.HekiGameFlow.startGame();
    const second = window.HekiGameFlow.startGame();
    expect(window.apiFetch).toHaveBeenCalledTimes(1);
    expect(window.__fetching).toBe(true);

    rejectRequest(new Error('network'));
    await Promise.all([first, second]);

    expect(window._clearDraft).not.toHaveBeenCalled();
    expect(window.__fetching).toBe(false);
    document.querySelectorAll('[data-action="start-game"], [data-action="start-excluding"], [data-action="quick-retry"]')
      .forEach(button => expect(button.disabled).toBe(false));
  });

  it('clears the prior draft only after a new game starts successfully', async () => {
    window.apiFetch.mockResolvedValue({question_id: 1, question: 'Q', count: 0, total: 20});

    await window.HekiGameFlow.startGame();

    expect(window._clearDraft).toHaveBeenCalledOnce();
    expect(window.__fetching).toBe(false);
    expect(window.show).toHaveBeenCalledWith('question-screen');
  });

  it('switches to an additional-question stage without moving progress backwards', () => {
    window.HekiGameFlow.showQuestion({question_id: 1, question: 'Q', count: 19, total: 20});
    expect(document.getElementById('progress-fill').style.width).toBe('95%');
    expect(document.getElementById('question-stage-label').textContent).toBe('質問 20/20');

    window.HekiGameFlow.showQuestion({question_id: 2, question: 'Q2', count: 20, total: 30});
    expect(document.getElementById('progress-fill').style.width).toBe('100%');
    expect(document.getElementById('question-stage-label').textContent).toBe('追加質問 1/10');
    expect(document.querySelector('.progress-bar').getAttribute('aria-valuetext')).toBe('追加質問 1/10');
  });
});
