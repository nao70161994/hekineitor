window.HekiUtils = (() => {
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function safeExternalUrl(value) {
    if (!value) return null;
    try {
      const url = new URL(String(value), window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }

  return {escapeHtml, safeExternalUrl};
})();
