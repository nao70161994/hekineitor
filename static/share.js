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
    const p = parseFloat(probability) || 0;
    if (p >= 90) return 'AIに完全看破された人';
    if (p >= 75) return '濃厚反応タイプ';
    if (p >= 50) return '否定しきれない人';
    return '未確認レアタイプ';
  }

  function resultRarity(probability) {
    const p = parseFloat(probability) || 0;
    if (p >= 90) return 'SSR';
    if (p >= 75) return 'SR';
    if (p >= 50) return 'R';
    return 'SECRET';
  }

  function buildShareText(name, probability, guessData = {}) {
    const compound = guessData.compound && guessData.compound.length > 0;
    const p = parseFloat(probability) || 0;
    const title = resultTitle(probability);
    const rarity = resultRarity(probability);
    if (compound) return `へきネイターで複合性癖「${name}」を検出。称号「${title}」/ レア度${rarity}`;
    if (p >= 90) return `へきネイターに性癖を完全看破された。称号「${title}」/ レア度${rarity}: ${name} ${probability}%`;
    if (p >= 75) return `へきネイターの診断結果は「${name}」。称号「${title}」/ AI一致率${probability}%。これ当たってる？`;
    if (p >= 50) return `へきネイターに「${name}」の気配を検出された。称号「${title}」/ AI一致率${probability}%`;
    return `へきネイターに「${name}」って言われた。称号「${title}」。これは当たってる？`;
  }

  function shareResult(name = diagnosedName) {
    const origin = window.location.origin;
    const guessData = window._guessData || {};
    const probability = guessData.probability || '';
    const desc = (guessData.fetish_desc || '').slice(0, 80);
    const shareUrl = `${origin}/r?f=${encodeURIComponent(name)}&p=${probability}&d=${encodeURIComponent(desc)}`;
    const opening = buildShareText(name, probability, guessData);
    const text = `${opening}\n#へきネイター`;
    trackShareEvent('share_button_click', {resultName: name, channel: 'button', success: true});
    if (navigator.share) {
      navigator.share({title: `私の性癖は「${name}」`, text, url: shareUrl})
        .then(() => trackShareEvent('web_share_success', {resultName: name, channel: 'web_share', success: true}))
        .catch(() => trackShareEvent('web_share_failure', {resultName: name, channel: 'web_share', success: false}));
      return;
    }
    if (navigator.clipboard) {
      navigator.clipboard.writeText(`${text}\n${shareUrl}`)
        .then(() => {
          showToast('クリップボードにコピーしました', '#27ae60');
          trackShareEvent('copy_success', {resultName: name, channel: 'clipboard', success: true});
        })
        .catch(() => trackShareEvent('copy_failure', {resultName: name, channel: 'clipboard', success: false}));
    }
    trackShareEvent('x_share_click', {resultName: name, channel: 'x', success: true});
    window.open(
      'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(shareUrl),
      '_blank',
      'noopener'
    );
  }

  return {buildShareText, resultTitle, resultRarity, setDiagnosedName, shareResult, trackShareEvent};
})();

window.setDiagnosedName = value => window.HekiShare.setDiagnosedName(value);
window._buildShareText = (name, prob, guessData) => window.HekiShare.buildShareText(name, prob, guessData);
window.shareResult = () => window.HekiShare.shareResult();
window._trackShareEvent = (eventName, options) => window.HekiShare.trackShareEvent(eventName, options);

window._resultTitle = prob => window.HekiShare.resultTitle(prob);
window._resultRarity = prob => window.HekiShare.resultRarity(prob);
