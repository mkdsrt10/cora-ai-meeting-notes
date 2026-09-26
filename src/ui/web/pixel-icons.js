/* Pixel-art icon system — 8x8 grid icons rendered as crisp inline SVG.
   Renders every [data-icon] span found in the DOM. Exposes window.renderIcons(root)
   so callers can re-run it after injecting new markup (not currently needed by
   app.js, since all data-icon spans live in the static index.html markup, but kept
   available for future dynamic templates). */
(function () {
  const PX_ICONS = {
    mic:      { rows: ["00111000","01111100","01111100","01111100","00111000","00111000","01111100","00000000"], color: "var(--amber)" },
    dot:      { rows: ["00000000","00111000","01111100","01111100","01111100","01111100","00111000","00000000"], color: "var(--coral)" },
    calendar: { rows: ["01000010","01111110","01111110","01111110","01010010","01000010","01010010","01111110"], color: "var(--violet)" },
    chart:    { rows: ["00000000","00000110","00000110","00011110","00011110","01111110","01111110","11111111"], color: "var(--teal)" },
    person:   { rows: ["00011000","00111100","00111100","00011000","00000000","01111110","11111111","11111111"], color: "var(--ink)" },
    check:    { rows: ["00000000","00000000","00000011","00000110","01001100","00111000","00110000","00000000"], color: "var(--teal)" },
    warning:  { rows: ["00011000","00111100","00111100","01111110","01111110","11111111","11111111","00000000"], color: "var(--coral)" },
    folder:   { rows: ["00000000","01110000","11111111","11111111","11111111","11111111","11111111","00000000"], color: "var(--amber)" }
  };
  function iconRects(name) {
    const def = PX_ICONS[name];
    if (!def) return "";
    let rects = "";
    def.rows.forEach((row, r) => {
      for (let c = 0; c < 8; c++) {
        if (row[c] === "1") rects += `<rect x="${c}" y="${r}" width="1" height="1" fill="${def.color}"/>`;
      }
    });
    if (name === "warning") {
      [1, 2, 3, 5].forEach(r => { rects += `<rect x="3" y="${r}" width="1" height="1" fill="var(--ink)"/>`; });
    }
    return rects;
  }
  function buildIconSVG(name, sizePx) {
    return `<svg class="pxicon" viewBox="0 0 8 8" width="${sizePx}" height="${sizePx}">${iconRects(name)}</svg>`;
  }
  function renderIcons(root) {
    (root || document).querySelectorAll("[data-icon]").forEach(el => {
      const name = el.getAttribute("data-icon");
      const size = el.getAttribute("data-size") || 24;
      el.innerHTML = buildIconSVG(name, size);
    });
  }
  window.renderIcons = renderIcons;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => renderIcons());
  } else {
    renderIcons();
  }
})();
