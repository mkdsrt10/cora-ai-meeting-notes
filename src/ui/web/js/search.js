// Find-in-transcript search.
// Classic script sharing global scope with the other files in index.html (load order matters).

function setupTranscriptSearch() {
  const bar = $('#notepadSearchBar');
  const input = $('#notepadSearchInput');
  const countEl = $('#searchMatchCount');
  const prevBtn = $('#searchPrevBtn');
  const nextBtn = $('#searchNextBtn');
  const closeBtn = $('#searchCloseBtn');
  if (!bar || !input) return;

  let currentMatches = [];
  let currentIdx = -1;
  let originalContents = new Map();

  function getActivePanel() {
    const activeTab = document.querySelector('.notepad-tab.active')?.dataset.notepadTab;
    if (activeTab === 'transcript') return $('#notepadTranscript');
    if (activeTab === 'timeline') return $('#notepadTimeline');
    if (activeTab === 'notes') {
      const isEnhanced = $('#notepadEnhancedNotes')?.style.display !== 'none';
      return isEnhanced ? $('#notepadEnhancedNotes') : null;
    }
    return $('#notepadTranscript') || $('#notepadEnhancedNotes');
  }

  function clearHighlights() {
    originalContents.forEach((origHtml, container) => {
      container.innerHTML = origHtml;
    });
    originalContents.clear();
    currentMatches = [];
    currentIdx = -1;
    if (countEl) countEl.textContent = '0 of 0';
  }

  function openSearch() {
    bar.style.display = 'flex';
    input.focus();
    input.select();
    if (input.value.trim()) {
      performSearch(input.value.trim());
    }
  }

  function closeSearch() {
    bar.style.display = 'none';
    clearHighlights();
  }

  function performSearch(query) {
    clearHighlights();
    if (!query) return;

    const panel = getActivePanel();
    if (!panel) return;

    originalContents.set(panel, panel.innerHTML);

    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');

    function highlightNode(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        // Build the highlight from text nodes, never innerHTML: textContent
        // is already HTML-decoded, so re-parsing it would execute any markup
        // that arrived in a transcript, OCR text, or LLM output.
        const parts = node.textContent.split(regex);
        if (parts.length > 1) {
          const span = document.createElement('span');
          parts.forEach((part, i) => {
            if (!part) return;
            if (i % 2 === 1) {
              const mark = document.createElement('mark');
              mark.className = 'search-match';
              mark.textContent = part;
              span.appendChild(mark);
            } else {
              span.appendChild(document.createTextNode(part));
            }
          });
          node.parentNode.replaceChild(span, node);
        }
      } else if (node.nodeType === Node.ELEMENT_NODE && node.nodeName !== 'MARK' && node.nodeName !== 'SCRIPT' && node.nodeName !== 'STYLE') {
        Array.from(node.childNodes).forEach(highlightNode);
      }
    }

    highlightNode(panel);

    currentMatches = Array.from(panel.querySelectorAll('mark.search-match'));
    if (currentMatches.length > 0) {
      currentIdx = 0;
      updateMatchHighlight();
    } else {
      if (countEl) countEl.textContent = '0 of 0';
    }
  }

  function updateMatchHighlight() {
    currentMatches.forEach((m, idx) => {
      m.classList.toggle('active', idx === currentIdx);
    });
    if (currentIdx >= 0 && currentIdx < currentMatches.length) {
      const target = currentMatches[currentIdx];
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (countEl) countEl.textContent = `${currentIdx + 1} of ${currentMatches.length}`;
    }
  }

  function gotoNext() {
    if (currentMatches.length === 0) return;
    currentIdx = (currentIdx + 1) % currentMatches.length;
    updateMatchHighlight();
  }

  function gotoPrev() {
    if (currentMatches.length === 0) return;
    currentIdx = (currentIdx - 1 + currentMatches.length) % currentMatches.length;
    updateMatchHighlight();
  }

  // Cmd+F / Ctrl+F global listener
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'f' || e.key === 'F')) {
      e.preventDefault();
      if (currentView === 'recording-detail' || selectedDetail) {
        openSearch();
      } else {
        $('#sessionSearch')?.focus();
      }
    }
  });

  input.addEventListener('input', () => {
    performSearch(input.value.trim());
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (e.shiftKey) gotoPrev();
      else gotoNext();
    } else if (e.key === 'Escape') {
      closeSearch();
    }
  });

  prevBtn?.addEventListener('click', gotoPrev);
  nextBtn?.addEventListener('click', gotoNext);
  closeBtn?.addEventListener('click', closeSearch);

  $$('.notepad-tab').forEach(tab => tab.addEventListener('click', () => {
    if (bar.style.display !== 'none' && input.value.trim()) {
      setTimeout(() => performSearch(input.value.trim()), 50);
    }
  }));
}
