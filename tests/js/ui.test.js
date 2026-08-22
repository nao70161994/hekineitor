import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/ui.js'), 'utf8');

function modalDom() {
  document.body.innerHTML = `
    <header class="site-header"></header>
    <main class="app-main" id="app-main" tabindex="-1">
      <button id="open">診断を中断する</button>
    </main>
    <footer class="site-footer"></footer>
    <div class="modal-overlay hidden" id="modal-restart">
      <div class="modal-box" role="dialog" tabindex="-1">
        <button id="cancel">キャンセル</button>
        <button id="confirm">確定</button>
      </div>
    </div>`;
}

describe('HekiUi modal accessibility', () => {
  beforeEach(() => {
    modalDom();
    window.HekiRenderers = undefined;
    window.requestAnimationFrame = callback => callback();
    window.updateExcludeButtons = vi.fn();
    window._checkDraft = vi.fn();
    window.eval(source);
  });

  it('makes the background inert and focuses the dialog', () => {
    const trigger = document.getElementById('open');
    trigger.focus();

    window.HekiUi.openModal('modal-restart');

    expect(document.querySelector('.modal-overlay').classList.contains('hidden')).toBe(false);
    expect(document.querySelector('[role="dialog"]')).toBe(document.activeElement);
    for (const element of document.querySelectorAll('.site-header, .app-main, .site-footer')) {
      expect(element.inert).toBe(true);
      expect(element.getAttribute('aria-hidden')).toBe('true');
    }
  });

  it('traps Tab and restores focus to the opening control after Escape', () => {
    const trigger = document.getElementById('open');
    const first = document.getElementById('cancel');
    const last = document.getElementById('confirm');
    trigger.focus();
    window.HekiUi.openModal('modal-restart');

    last.focus();
    const tab = new KeyboardEvent('keydown', {key: 'Tab', cancelable: true});
    window.HekiUi.handleModalKeydown(tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(first);

    first.focus();
    const shiftTab = new KeyboardEvent('keydown', {key: 'Tab', shiftKey: true, cancelable: true});
    window.HekiUi.handleModalKeydown(shiftTab);
    expect(document.activeElement).toBe(last);

    const escape = new KeyboardEvent('keydown', {key: 'Escape', cancelable: true});
    window.HekiUi.handleModalKeydown(escape);
    expect(document.querySelector('.modal-overlay').classList.contains('hidden')).toBe(true);
    expect(document.activeElement).toBe(trigger);
    expect(document.querySelector('.app-main').inert).toBe(false);
    expect(document.querySelector('.app-main').hasAttribute('aria-hidden')).toBe(false);
  });
});
