window.gameState = window.gameState || {
  fetching: false,
  guessData: null,
  excludedIds: [],
  lastFetishName: '',
  confirmedIds: [],
};

window.HekiState = (() => {
  const state = window.gameState;
  if (state.lastFetishName == null) state.lastFetishName = '';

  function setFetching(value) {
    state.fetching = Boolean(value);
    return state.fetching;
  }

  function setExcludedIds(ids) {
    state.excludedIds = Array.isArray(ids) ? ids : [];
    window._excludedIds = state.excludedIds;
    return state.excludedIds;
  }

  function getExcludedIds() {
    if (!Array.isArray(window._excludedIds)) window._excludedIds = state.excludedIds || [];
    return window._excludedIds;
  }

  function resetExcludedIds() {
    return setExcludedIds([]);
  }

  function setGuessData(data) {
    state.guessData = data || null;
    window._guessData = state.guessData;
    return state.guessData;
  }

  function setConfirmedIds(ids) {
    state.confirmedIds = Array.isArray(ids) ? ids.filter(id => id != null) : [];
    window._confirmedIds = state.confirmedIds;
    return state.confirmedIds;
  }

  function setLastFetishName(value) {
    state.lastFetishName = value || '';
    window.lastFetishName = state.lastFetishName;
    return state.lastFetishName;
  }

  return {setFetching, setExcludedIds, getExcludedIds, resetExcludedIds, setGuessData, setConfirmedIds, setLastFetishName};
})();

window.setLastFetishName = value => window.HekiState.setLastFetishName(value);
window.setConfirmedIds = ids => window.HekiState.setConfirmedIds(ids);
