window.gameState = window.gameState || {
  fetching: false,
  guessData: null,
  excludedIds: [],
};

window.HekiState = (() => {
  const state = window.gameState;

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

  return {setFetching, setExcludedIds, getExcludedIds, resetExcludedIds, setGuessData};
})();
