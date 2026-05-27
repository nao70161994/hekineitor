window.HekiShare = (() => {
  let diagnosedName = '';

  function setDiagnosedName(value) {
    diagnosedName = value || '';
  }

  function trackShareEvent(eventName, options = {}) {
    const payload = {
      event_name: eventName,
      result_name: options.resultName || diagnosedName || '',
      channel: options.channel || '',
      success: Object.prototype.hasOwnProperty.call(options, 'success') ? options.success : null,
    };
    try {
      fetch('/api/share_event', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(() => {});
    } catch (error) {
      // Share tracking must never block the share flow.
    }
  }

  function resultTitle(probability) {
    return 'あなたの『癖』は……';
  }

  function resultRarity(probability) {
    return 'AI観測ログ';
  }

  function buildShareText(name, probability, guessData = {}) {
    const lines = [
      'あなたの『癖』は……',
      '',
      `『${name || '???'}』`,
    ];
    if (probability !== '') lines.push('', `AI精度${probability}%`);
    lines.push('', '次はあなたの番です……');
    return lines.join('\n');
  }

  function legacyShareUrl(name, probability, desc) {
    const shareUrl = new URL('/r', window.location.origin);
    shareUrl.searchParams.set('f', name);
    if (probability !== '') shareUrl.searchParams.set('p', probability);
    if (desc) shareUrl.searchParams.set('d', desc);
    return shareUrl.toString();
  }

  async function createShortShareUrl(name, probability, desc) {
    try {
      const res = await fetch('/api/share_link', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, probability, desc}),
      });
      if (!res.ok) return '';
      const data = await res.json();
      if (!data.share_url) return '';
      return new URL(data.share_url, window.location.origin).toString();
    } catch (error) {
      return '';
    }
  }

  async function sharePayload(name = diagnosedName) {
    const guessData = window._guessData || {};
    const probability = guessData.probability || '';
    const desc = (guessData.fetish_desc || '').slice(0, 80);
    const opening = buildShareText(name, probability, guessData);
    const shortUrl = await createShortShareUrl(name, probability, desc);
    return {
      guessData,
      probability,
      url: shortUrl || legacyShareUrl(name, probability, desc),
      text: `${opening}\n#へきネイター`,
    };
  }

  async function openXShare(name = diagnosedName, trackButton = true) {
    const payload = await sharePayload(name);
    if (trackButton) trackShareEvent('share_button_click', {resultName: name, channel: 'x', success: true});
    trackShareEvent('x_share_click', {resultName: name, channel: 'x', success: true});
    window.open(
      'https://twitter.com/intent/tweet?text=' + encodeURIComponent(payload.text) + '&url=' + encodeURIComponent(payload.url),
      '_blank',
      'noopener'
    );
  }

  async function shareResult(name = diagnosedName) {
    const payload = await sharePayload(name);
    trackShareEvent('share_button_click', {resultName: name, channel: 'button', success: true});
    if (navigator.share) {
      navigator.share({title: `あなたの『癖』は…… ${name}`, text: payload.text, url: payload.url})
        .then(() => trackShareEvent('web_share_success', {resultName: name, channel: 'web_share', success: true}))
        .catch(() => trackShareEvent('web_share_failure', {resultName: name, channel: 'web_share', success: false}));
      return;
    }
    if (navigator.clipboard) {
      navigator.clipboard.writeText(`${payload.text}\n${payload.url}`)
        .then(() => {
          showToast('クリップボードにコピーしました', '#27ae60');
          trackShareEvent('copy_success', {resultName: name, channel: 'clipboard', success: true});
        })
        .catch(() => trackShareEvent('copy_failure', {resultName: name, channel: 'clipboard', success: false}));
    }
    openXShare(name, false);
  }

  return {buildShareText, resultTitle, resultRarity, setDiagnosedName, shareResult, openXShare, trackShareEvent, legacyShareUrl};
})();

window.setDiagnosedName = value => window.HekiShare.setDiagnosedName(value);
window._buildShareText = (name, prob, guessData) => window.HekiShare.buildShareText(name, prob, guessData);
window.shareResult = () => window.HekiShare.shareResult();
window.shareResultX = () => window.HekiShare.openXShare();
window._trackShareEvent = (eventName, options) => window.HekiShare.trackShareEvent(eventName, options);

window._resultTitle = prob => window.HekiShare.resultTitle(prob);
window._resultRarity = prob => window.HekiShare.resultRarity(prob);
