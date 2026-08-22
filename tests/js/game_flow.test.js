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
    <div id="question-progress-message"></div>
    <div id="question-axis-tag"></div><div id="question-stage-label"></div>
    <div class="progress-bar"><div id="progress-fill"></div></div>
    <button id="btn-back"></button><div id="contradiction-hint"></div>
    <div id="question-screen"><div class="btn-group"><button class="btn" data-action="send-answer" data-answer="1" aria-pressed="false">はい</button></div>
    <div id="answer-status"></div>
    <button id="answer-reconcile" class="btn btn-idk answer-reconcile hidden"></button>
    </div>
    <div id="result-screen"></div>`;
}

describe('HekiGameFlow', () => {
  beforeEach(() => {
    questionDom();
    window.__fetching = false;
    window.setFetching = vi.fn(value => { window.__fetching = value; });
    window.setAnswerButtons = vi.fn(disabled => {
      document.querySelectorAll('#question-screen [data-action="send-answer"]').forEach(button => {
        button.disabled = disabled;
      });
    });
    window.apiFetch = vi.fn();
    window.showToast = vi.fn();
    window.trackGameplayEvent = vi.fn();
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
  it('shows answer waiting state and restores controls after request failure', async () => {
    window.HekiGameFlow.showQuestion({question_id: 1, question: 'Q', count: 0, total: 20});
    window.apiFetch.mockRejectedValue(new Error('network'));

    await window.HekiGameFlow.sendAnswer(1);

    const yes = document.querySelector('[data-answer="1"]');
    expect(yes.classList.contains('answer-selected')).toBe(true);
    expect(yes.getAttribute('aria-pressed')).toBe('true');
    expect(yes.disabled).toBe(true);
    expect(window.apiFetch).toHaveBeenCalledTimes(2);
    expect(window.trackGameplayEvent).toHaveBeenCalledWith('answer_retried', {
      source: 'question',
      outcome: 'failure',
      question_id: 1,
      answered_count: 0,
    });
    const firstPayload = window.apiFetch.mock.calls[0][1];
    const secondPayload = window.apiFetch.mock.calls[1][1];
    expect(firstPayload.answer_request_id).toBeTruthy();
    expect(secondPayload.answer_request_id).toBe(firstPayload.answer_request_id);
    const reconcile = document.getElementById('answer-reconcile');
    expect(reconcile.classList.contains('hidden')).toBe(false);
    expect(reconcile.disabled).toBe(false);

    window.apiFetch.mockResolvedValueOnce({action: 'question', question_id: 2, question: 'Q2', count: 1, total: 20});
    await window.HekiGameFlow.retryPendingAnswer();

    expect(window.apiFetch.mock.calls[2][1].answer_request_id).toBe(firstPayload.answer_request_id);
    expect(document.getElementById('question-text').textContent).toBe('Q2');
    expect(yes.disabled).toBe(false);
  });

  it.each([
    ['a definitive HTTP failure', Object.assign(new Error('bad request'), {status: 400})],
    ['a wrapped session expiry', new Error('session_expired')],
  ])('unlocks the old question after %s', async (_label, error) => {
    window.HekiGameFlow.showQuestion({question_id: 1, question: 'Q', count: 0, total: 20});
    window.apiFetch.mockRejectedValue(error);

    await window.HekiGameFlow.sendAnswer(1);

    const yes = document.querySelector('[data-answer="1"]');
    expect(window.apiFetch).toHaveBeenCalledTimes(1);
    expect(yes.classList.contains('answer-selected')).toBe(false);
    expect(yes.disabled).toBe(false);
    expect(document.getElementById('answer-reconcile').classList.contains('hidden')).toBe(true);
    expect(document.getElementById('answer-status').textContent).toContain('選び直してください');
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

  it('uses the self-contained question and shows adaptive progress without a separate answer hint', () => {
    window.HekiGameFlow.showQuestion({
      question_id: 7,
      question: '安心できる場面より、緊張する場面の方が感覚が鋭くなる？',
      hint: '答えが見えてきました…もう少しです',
      answer_frame: '普段の感覚・行動として',
      count: 5,
      total: 20,
    });

    expect(document.getElementById('question-answer-frame')).toBeNull();
    expect(document.getElementById('question-hint')).toBeNull();
    expect(window.HekiRenderers.setProgressMessage)
      .toHaveBeenCalledWith('答えが見えてきました…もう少しです');
  });

  it('describes adaptive phases without promising a fixed remaining question count', () => {
    window.HekiGameFlow.showQuestion({question_id: 1, question: 'Q', count: 19, total: 20});
    expect(document.getElementById('progress-fill').style.width).toBe('67%');
    expect(document.getElementById('question-stage-label').textContent).toBe('質問 20・候補を比べています');

    window.HekiGameFlow.showQuestion({question_id: 2, question: 'Q2', count: 20, total: 30});
    expect(document.getElementById('progress-fill').style.width).toBe('74%');
    expect(document.getElementById('question-stage-label').textContent).toBe('質問 21・確信を確かめています');
    expect(document.getElementById('question-stage-label').textContent).not.toContain('/');
  });

  it('finalizes the anonymous summary on page exit after a result is shown', () => {
    const sendBeacon = vi.fn(() => true);
    Object.defineProperty(navigator, 'sendBeacon', {value: sendBeacon, configurable: true});
    window.HekiRenderers.renderGuess = vi.fn(() => '結果');
    window.HekiRenderers.trackFeaturedWorks = vi.fn();
    window.setLastFetishName = vi.fn();
    window.setDiagnosedName = vi.fn();
    window.saveHistory = vi.fn();
    window.escapeHtml = value => String(value);
    window.safeExternalUrl = value => String(value);
    window.HekiGameFlow.showQuestion({question_id: 4, question: 'Q', count: 3, total: 20});
    window.HekiGameFlow.showGuess({fetish_id: 2, fetish_name: '結果', probability: 70, compound: []});

    window.HekiGameFlow.reportDropoff();

    expect(sendBeacon).toHaveBeenCalledOnce();
    expect(sendBeacon.mock.calls[0][0]).toBe('/api/dropoff');
  });
});
