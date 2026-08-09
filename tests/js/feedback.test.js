import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const feedbackSource = readFileSync(resolve(testDir, '../../static/feedback.js'), 'utf8');
const teachSource = readFileSync(resolve(testDir, '../../static/teach.js'), 'utf8');

function feedbackDom() {
  document.body.innerHTML = `
    <div id="quick-feedback"><button></button></div>
    <button data-action="toggle-detail-feedback"></button>
    <div id="quick-feedback-status" class="hidden"></div>
    <div id="confirm-items"><div class="confirm-item" data-id="1"></div></div>
    <div id="teach-screen"></div><div id="result-screen"></div><div id="done-screen"></div>
    <p id="teach-label"></p><div id="fetish-list"></div>
    <button id="teach-more-candidates" class="hidden"></button>
    <button id="teach-submit-btn"></button><button id="add-skip-btn"></button>
    <div id="add-step1"></div><div id="add-step-more"></div>
    <div id="done-msg"></div>`;
}

describe('near-miss feedback', () => {
  beforeEach(() => {
    feedbackDom();
    window.gameState = {fetching: false};
    window.setFetching = vi.fn(value => { window.gameState.fetching = value; });
    window.show = vi.fn();
    window.showToast = vi.fn();
    window.escapeHtml = value => String(value);
    window._guessedId = 1;
    window._compoundIds = [];
    window.apiFetch = vi.fn();
    window.eval(feedbackSource);
    window.eval(teachSource);
  });

  it('shows only the top three candidates first and keeps the full fallback list', async () => {
    window.apiFetch.mockResolvedValue({
      status: 'wrong',
      fetishes: Array.from({length: 5}, (_, index) => ({id: index + 2, name: `候補${index + 1}`})),
    });

    await window.HekiFeedback.quickFeedback('maybe');

    expect(document.querySelectorAll('#fetish-list .fetish-item')).toHaveLength(5);
    expect(document.querySelectorAll('#fetish-list .candidate-extra.hidden')).toHaveLength(2);
    expect(document.getElementById('teach-more-candidates').classList.contains('hidden')).toBe(false);
    window.HekiTeach.showMoreCandidates();
    expect(document.querySelectorAll('#fetish-list .candidate-extra.hidden')).toHaveLength(0);
  });

  it('keeps a near-miss choice single-select and finalizes skipped feedback', async () => {
    window._addOnlyMode = 'maybe_deferred';
    window._teachSelected = new Map();
    document.getElementById('fetish-list').innerHTML = `
      <button id="ti-2" class="fetish-item"></button><button id="ti-3" class="fetish-item"></button>`;
    const first = document.getElementById('ti-2');
    const second = document.getElementById('ti-3');
    window.HekiTeach.toggleTeachItem(2, '候補1', first);
    window.HekiTeach.toggleTeachItem(3, '候補2', second);
    expect([...window._teachSelected.keys()]).toEqual([3]);
    expect(first.classList.contains('selected')).toBe(false);

    window.apiFetch.mockResolvedValue({status: 'done', feedback_outcome: 'maybe'});
    await window.HekiTeach.skipTeach();
    expect(window.apiFetch).toHaveBeenCalledWith('/api/finalize_added', {items: []});
    expect(document.getElementById('done-msg').textContent).toContain('惜しい');
  });

  it('does not leave the correction screen when finalization fails', async () => {
    window._addOnlyMode = 'maybe_deferred';
    window._teachSelected = new Map([[2, '候補1']]);
    window.apiFetch.mockResolvedValue(null);

    await window.HekiTeach.submitTeach();

    expect(window.show).not.toHaveBeenCalledWith('done-screen');
    expect(window._addOnlyMode).toBe('maybe_deferred');
  });

  it('ignores a second near-miss skip while the first request is pending', async () => {
    window._addOnlyMode = 'maybe_deferred';
    let finishRequest;
    window.apiFetch.mockReturnValue(new Promise(resolveRequest => { finishRequest = resolveRequest; }));

    const first = window.HekiTeach.skipTeach();
    const second = window.HekiTeach.skipTeach();
    expect(window.apiFetch).toHaveBeenCalledTimes(1);
    finishRequest({status: 'done', feedback_outcome: 'maybe'});
    await Promise.all([first, second]);

    expect(window.show).toHaveBeenCalledWith('done-screen');
  });

  it('finalizes a wrong rating when correction is skipped', async () => {
    window._addOnlyMode = false;
    window.apiFetch.mockResolvedValue({status: 'done', feedback_outcome: 'no'});

    await window.HekiTeach.skipTeach();

    expect(window.apiFetch).toHaveBeenCalledWith('/api/finalize_added', {items: []});
    expect(document.getElementById('done-msg').textContent).toContain('違う');
    expect(window.show).toHaveBeenCalledWith('done-screen');
  });
});
