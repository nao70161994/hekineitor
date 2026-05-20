window.HekiShare = (() => {
  let diagnosedName = '';

  function setDiagnosedName(value) {
    diagnosedName = value || '';
  }

  function buildShareText(name, probability, guessData) {
    const compound = guessData.compound && guessData.compound.length > 0;
    const p = parseFloat(probability) || 0;
    if (compound) return `へきネイターで診断したら複合性癖「${name}」だった。情報量が多い`;
    if (p >= 90) return `へきネイターに性癖を完全に見破られた: ${name} ${probability}%`;
    if (p >= 75) return `へきネイターで診断したら「${name}」だった。これ当たってる？ ${probability}%`;
    if (p >= 50) return `へきネイターの診断結果は「${name}」。否定しきれない ${probability}%`;
    return `へきネイターに「${name}」って言われた。これは当たってる？`;
  }

  function shareResult(name = diagnosedName) {
    const origin = window.location.origin;
    const guessData = window._guessData || {};
    const probability = guessData.probability || '';
    const desc = (guessData.fetish_desc || '').slice(0, 80);
    const shareUrl = `${origin}/r?f=${encodeURIComponent(name)}&p=${probability}&d=${encodeURIComponent(desc)}`;
    const opening = buildShareText(name, probability, guessData);
    const text = `${opening}\n#へきネイター`;
    if (navigator.share) {
      navigator.share({title: `私の性癖は「${name}」`, text, url: shareUrl}).catch(() => {});
      return;
    }
    if (navigator.clipboard) {
      navigator.clipboard.writeText(`${text}\n${shareUrl}`).then(() => showToast('クリップボードにコピーしました', '#27ae60'));
    }
    window.open(
      'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(shareUrl),
      '_blank',
      'noopener'
    );
  }

  return {buildShareText, setDiagnosedName, shareResult};
})();
