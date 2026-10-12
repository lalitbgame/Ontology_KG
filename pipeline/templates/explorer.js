(function () {
  "use strict";

  // Node type codes come from build_viz_data.py
  var TYPE_COLOR = { U: "var(--clause)", A: "var(--abbr)", D: "var(--def)", E: "var(--eq)", V: "var(--var)",
                     T: "var(--tab)", F: "var(--fig)", N: "var(--foot)", X: "var(--ext)", P: "var(--ext)",
                     R: "var(--doc)", G: "var(--ink-faint)" };
  var TYPE_NAME = { A: "Abbreviation", D: "Definition", E: "Equation", V: "Variable", T: "Table", F: "Figure",
                    N: "Footnote", X: "External document", P: "Cited provision", R: "Document", G: "Group" };
  var CONTAINS = { HAS_DIVISION: 1, HAS_CHILD: 1, HAS_ABBREVIATION: 1, HAS_DEFINITION: 1, HAS_TABLE: 1,
                   HAS_FIGURE: 1, HAS_EQUATION: 1, HAS_FOOTNOTE: 1, HAS_PROVISION: 1, HAS_VERSION: 1 };

  var nodes = DATA.nodes;
  var parentOf = {}, rowEls = {}, childUlEls = {}, treeLabel = {};
  var outRel = {}, inRel = {};
  DATA.edges.forEach(function (e) {
    (outRel[e[0]] = outRel[e[0]] || []).push({ id: e[1], ty: e[2], tx: e[3] });
    (inRel[e[1]] = inRel[e[1]] || []).push({ id: e[0], ty: e[2], tx: e[3] });
  });

  function typeName(n) { return n.t === "U" ? (n.ty || "Unit") : (TYPE_NAME[n.t] || n.ty); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function shortLabel(id, max) {
    var n = nodes[id];
    var s = n ? (n.lb || id) : (treeLabel[id] || id);
    return max && s.length > max ? s.slice(0, max - 1) + "…" : s;
  }

  // ---------- Search index ----------
  var searchIndex = Object.keys(nodes).map(function (id) {
    var n = nodes[id];
    return { id: id, text: ((n.lb || "") + " " + (n.title || "") + " " + (n.body || "") + " " + (n.extra || "")).toLowerCase() };
  });

  // ---------- Tree ----------
  var treeRoot = document.getElementById("treeRoot");
  function buildRow(meta) {
    var row = document.createElement("div");
    row.className = "row";
    row.dataset.id = meta.id;
    var tw = document.createElement("span");
    tw.className = "twisty" + (meta.children.length ? "" : " leaf");
    tw.textContent = meta.children.length ? "▸" : "";
    row.appendChild(tw);
    var n = nodes[meta.id];
    if (n && n.t !== "G") {
      var dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = TYPE_COLOR[n.t] || "var(--clause)";
      row.appendChild(dot);
    }
    var label = document.createElement("span");
    label.className = "row-label";
    var lb = meta.label;
    var m = lb.match(/^(\S+\.)\s(.*)$/);
    label.innerHTML = (n && n.t === "U" && m) ? '<span class="num">' + esc(m[1]) + "</span>" + esc(m[2]) : esc(lb);
    if (!n || n.t === "G") label.style.fontWeight = "600";
    row.appendChild(label);
    return row;
  }
  function buildTree(meta, container, depth) {
    var li = document.createElement("li");
    var row = buildRow(meta);
    treeLabel[meta.id] = meta.label;
    row.style.paddingLeft = (10 + depth * 16) + "px";
    li.appendChild(row);
    rowEls[meta.id] = row;
    if (meta.children.length) {
      var ul = document.createElement("ul");
      ul.className = "collapsed";
      meta.children.forEach(function (c) { parentOf[c.id] = meta.id; buildTree(c, ul, depth + 1); });
      li.appendChild(ul);
      childUlEls[meta.id] = ul;
    } else {
      childUlEls[meta.id] = null;
    }
    container.appendChild(li);
  }
  DATA.tree.children.forEach(function (top) { buildTree(top, treeRoot, 0); });
  DATA.tree.children.forEach(function (top) { setExpanded(top.id, true); });

  function setExpanded(id, on) {
    var ul = childUlEls[id], row = rowEls[id];
    if (!ul || !row) return;
    ul.classList.toggle("collapsed", !on);
    row.classList.toggle("expanded", on);
  }
  function isExpanded(id) { return rowEls[id] && rowEls[id].classList.contains("expanded"); }
  treeRoot.addEventListener("click", function (e) {
    var row = e.target.closest(".row");
    if (!row) return;
    var id = row.dataset.id;
    if (childUlEls[id]) setExpanded(id, !isExpanded(id));
    if (nodes[id]) select(id, false);
  });
  function revealPath(id) {
    var chain = [], cur = parentOf[id];
    while (cur) { chain.unshift(cur); cur = parentOf[cur]; }
    chain.forEach(function (a) { setExpanded(a, true); });
  }
  function pathTo(id) {
    var chain = [id], cur = parentOf[id];
    while (cur) { chain.unshift(cur); cur = parentOf[cur]; }
    return chain;
  }
  function childrenOf(id) {
    var ul = childUlEls[id];
    if (!ul) return [];
    return Array.prototype.map.call(ul.querySelectorAll(":scope > li > .row"), function (r) { return r.dataset.id; });
  }

  // ---------- Detail ----------
  var selectedId = null;
  var mainInner = document.getElementById("mainInner");
  function select(id, reveal) {
    if (!nodes[id]) return;
    if (selectedId && rowEls[selectedId]) rowEls[selectedId].classList.remove("selected");
    selectedId = id;
    if (reveal !== false) revealPath(id);
    if (rowEls[id]) { rowEls[id].classList.add("selected"); rowEls[id].scrollIntoView({ block: "nearest" }); }
    renderDetail(id);
    if (window.innerWidth <= 760) document.getElementById("rail").classList.remove("open");
    try { history.replaceState(null, "", "#" + encodeURIComponent(id)); } catch (e) {}
  }
  function metaCell(k, v) {
    return '<div class="meta-cell"><div class="k">' + esc(k) + '</div><div class="v">' + esc(v == null || v === "" ? "—" : v) + "</div></div>";
  }
  function relRow(id, sub) {
    var n = nodes[id];
    if (!n) return "";
    return '<div class="rel-row" data-id="' + esc(id) + '"><span class="dot" style="background:' + (TYPE_COLOR[n.t] || "var(--clause)") + '"></span>' +
      '<div class="rl-main"><div class="rl-label">' + esc(shortLabel(id, 110)) + '</div><div class="rl-sub">' + esc(sub || typeName(n)) + "</div></div>" +
      '<span class="rl-arrow">→</span></div>';
  }
  function relSection(title, list, incoming) {
    var groups = {};
    list.forEach(function (r) { (groups[r.ty] = groups[r.ty] || []).push(r); });
    var html = "";
    Object.keys(groups).sort().forEach(function (ty) {
      if (CONTAINS[ty]) return;
      var g = groups[ty];
      html += '<div class="section-heading">' + esc(title) + " · " + esc(ty) + " (" + g.length + ")</div>";
      html += '<div class="rel-list">' + g.slice(0, 200).map(function (r) {
        return relRow(r.id, r.tx ? "“" + r.tx + "”" : typeName(nodes[r.id] || {}));
      }).join("") + "</div>";
      if (g.length > 200) html += '<div class="note">+' + (g.length - 200) + " more</div>";
    });
    return html;
  }
  function renderKatex(root) {
    if (!window.katex) return;
    root.querySelectorAll("[data-latex]").forEach(function (el) {
      try { window.katex.render(el.dataset.latex, el, { throwOnError: false, displayMode: true }); } catch (e) {}
    });
  }

  function renderDetail(id) {
    var n = nodes[id];
    var html = '<div class="crumbs">';
    var crumbs = pathTo(id);
    crumbs.forEach(function (cid, i) {
      html += '<button data-jump="' + esc(cid) + '">' + esc(shortLabel(cid, 40)) + "</button>";
      if (i < crumbs.length - 1) html += '<span class="sep">›</span>';
    });
    html += "</div>";
    html += '<div class="detail-header"><span class="type-badge badge-' + n.t + '">' + esc(typeName(n)) + "</span>";
    html += '<h2 class="detail-title">' + esc(n.lb || id) + "</h2></div>";
    html += '<div class="qid">' + esc(id) + "</div>";

    html += '<div class="meta-grid">';
    (n.meta || []).forEach(function (kv) { html += metaCell(kv[0], kv[1]); });
    html += "</div>";
    if (n.labels && n.labels.length) {
      html += n.labels.map(function (l) { return '<span class="label-chip">' + esc(l) + "</span>"; }).join("");
    }
    if (n.t === "E") {
      html += '<div class="section-heading">Equation</div><div class="eq-box">';
      if (n.latex) html += '<div data-latex="' + esc(n.latex) + '">' + esc(n.linear || "") + "</div>";
      else html += '<p class="prose empty">Image-only equation — no text layer to reconstruct (see the crop).</p>';
      if (n.linear) html += '<div class="note">linear: <span class="mono">' + esc(n.linear) + "</span></div>";
      if (n.img) html += '<img class="eq-img" alt="Equation as printed in the PDF" src="' + esc(n.img) + '">';
      html += '<div class="note">Rendered from the reconstructed layout; compare with the crop from the PDF.</div></div>';
      if (n.gloss && n.gloss.length) {
        html += '<div class="section-heading">Where</div><table class="gloss">' + n.gloss.map(function (g) {
          return "<tr><td>" + esc(g[0]) + "</td><td>" + esc(g[1] || "") + (g[2] ? " <em>[" + esc(g[2]) + "]</em>" : "") + "</td></tr>";
        }).join("") + "</table>";
      }
    }
    if (n.title && n.t === "U") html += '<div class="section-heading">Title</div><p class="prose">' + esc(n.title) + "</p>";
    if (n.body) {
      html += '<div class="section-heading">' + (n.t === "T" ? "Cell text" : n.t === "U" ? "Body text" : "Text") + "</div>";
      html += '<p class="prose' + (n.t === "T" ? " mono" : "") + '">' + esc(n.body) + "</p>";
    } else if (n.t === "U") {
      html += '<p class="prose empty">No body text — a structural heading.</p>';
    }
    if (n.foot) html += '<div class="section-heading">Footnote</div><p class="prose">' + esc(n.foot) + "</p>";
    if (n.extra && n.t !== "U") html += '<div class="section-heading">Details</div><p class="prose">' + esc(n.extra) + "</p>";

    var kids = childrenOf(id);
    if (kids.length) {
      html += '<div class="section-heading">Contains (' + kids.length + ")</div>";
      html += '<div class="rel-list">' + kids.slice(0, 300).map(function (c) { return relRow(c); }).join("") + "</div>";
    }
    html += relSection("Outgoing", outRel[id] || [], false);
    html += relSection("Incoming", inRel[id] || [], true);
    html += '<div class="section-heading">Local graph</div><div class="graph-wrap">' + buildLocalGraphSvg(id) + "</div>";

    mainInner.innerHTML = html;
    renderKatex(mainInner);
    mainInner.querySelectorAll("[data-jump]").forEach(function (b) { b.addEventListener("click", function () { select(b.dataset.jump, true); }); });
    mainInner.querySelectorAll(".rel-row[data-id], .g-node[data-id]").forEach(function (r) {
      r.addEventListener("click", function () { select(r.dataset.id, true); });
    });
  }

  // ---------- Local graph (fixed compass layout) ----------
  var GW = 900, GH = 460;
  function box(id, cx, cy, isSelf) {
    var n = nodes[id];
    if (!n) return "";
    var w = isSelf ? 220 : 150, h = isSelf ? 46 : 38;
    return '<g class="g-node' + (isSelf ? " self" : "") + '" data-id="' + esc(id) + '" transform="translate(' + (cx - w / 2) + "," + (cy - h / 2) + ')">' +
      '<rect width="' + w + '" height="' + h + '"></rect>' +
      '<text x="10" y="' + (isSelf ? 19 : 16) + '">' + esc(shortLabel(id, isSelf ? 34 : 22)) + "</text>" +
      '<text class="g-type" x="10" y="' + (isSelf ? 34 : 30) + '">' + esc(typeName(n)) + "</text></g>";
  }
  function spread(k, lo, hi) {
    if (k <= 1) return [(lo + hi) / 2];
    var out = [];
    for (var i = 0; i < k; i++) out.push(lo + i * ((hi - lo) / (k - 1)));
    return out;
  }
  function buildLocalGraphSvg(id) {
    var parent = parentOf[id];
    var kids = childrenOf(id);
    var out = (outRel[id] || []).filter(function (r) { return !CONTAINS[r.ty] && nodes[r.id]; });
    var inc = (inRel[id] || []).filter(function (r) { return !CONTAINS[r.ty] && nodes[r.id]; });
    var cx = GW / 2, cy = GH / 2, lines = "", boxes = "";
    if (parent && nodes[parent]) {
      lines += '<line class="g-line" x1="' + cx + '" y1="' + (cy - 23) + '" x2="' + cx + '" y2="75"></line>';
      boxes += box(parent, cx, 56, false) + '<text class="g-axis-label" x="' + cx + '" y="24" text-anchor="middle">Parent</text>';
    }
    var ks = kids.slice(0, 6);
    if (ks.length) {
      var kx = spread(ks.length, 110, GW - 110);
      ks.forEach(function (k, i) {
        lines += '<line class="g-line" x1="' + cx + '" y1="' + (cy + 23) + '" x2="' + kx[i] + '" y2="' + (GH - 65) + '"></line>';
        boxes += box(k, kx[i], GH - 46, false);
      });
      boxes += '<text class="g-axis-label" x="' + cx + '" y="' + (GH - 76) + '" text-anchor="middle">Contains' + (kids.length > 6 ? " (+" + (kids.length - 6) + ")" : "") + "</text>";
    }
    var os = out.slice(0, 5);
    if (os.length) {
      var oy = spread(os.length, 120, GH - 120);
      os.forEach(function (r, i) {
        lines += '<line class="g-line ref-out" marker-end="url(#arrowOut)" x1="' + (cx + 110) + '" y1="' + cy + '" x2="' + (GW - 165) + '" y2="' + oy[i] + '"></line>';
        boxes += box(r.id, GW - 90, oy[i], false);
      });
      boxes += '<text class="g-axis-label" x="' + (GW - 90) + '" y="24" text-anchor="middle">Outgoing →' + (out.length > 5 ? " (+" + (out.length - 5) + ")" : "") + "</text>";
    }
    var is = inc.slice(0, 5);
    if (is.length) {
      var iy = spread(is.length, 120, GH - 120);
      is.forEach(function (r, i) {
        lines += '<line class="g-line ref-in" x1="165" y1="' + iy[i] + '" x2="' + (cx - 110) + '" y2="' + cy + '"></line>';
        boxes += box(r.id, 90, iy[i], false);
      });
      boxes += '<text class="g-axis-label" x="90" y="24" text-anchor="middle">← Incoming' + (inc.length > 5 ? " (+" + (inc.length - 5) + ")" : "") + "</text>";
    }
    boxes += box(id, cx, cy, true);
    return '<svg class="graph-svg" viewBox="0 0 ' + GW + " " + GH + '" xmlns="http://www.w3.org/2000/svg">' +
      '<defs><marker id="arrowOut" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="var(--accent)"></path></marker></defs>' +
      lines + boxes + "</svg>";
  }

  // ---------- Search ----------
  var searchInput = document.getElementById("searchInput");
  var searchResults = document.getElementById("searchResults");
  var timer = null;
  searchInput.addEventListener("input", function () {
    clearTimeout(timer);
    var q = searchInput.value.trim().toLowerCase();
    timer = setTimeout(function () { runSearch(q); }, 90);
  });
  document.addEventListener("click", function (e) { if (!e.target.closest(".search-wrap")) searchResults.classList.remove("show"); });
  function runSearch(q) {
    if (!q) { searchResults.classList.remove("show"); return; }
    var hits = [];
    for (var i = 0; i < searchIndex.length && hits.length < 50; i++) if (searchIndex[i].text.indexOf(q) !== -1) hits.push(searchIndex[i].id);
    if (!hits.length) {
      searchResults.innerHTML = '<div class="search-empty">No matches for “' + esc(searchInput.value) + "”.</div>";
    } else {
      searchResults.innerHTML = hits.map(function (id) {
        var n = nodes[id];
        return '<div class="search-result" data-id="' + esc(id) + '"><span class="dot" style="background:' + (TYPE_COLOR[n.t] || "var(--clause)") + '"></span>' +
          '<span class="snip">' + esc(typeName(n) + " · " + shortLabel(id, 90)) + "</span></div>";
      }).join("");
      searchResults.querySelectorAll(".search-result").forEach(function (r) {
        r.addEventListener("click", function () { select(r.dataset.id, true); searchResults.classList.remove("show"); searchInput.value = ""; });
      });
    }
    searchResults.classList.add("show");
  }

  // ---------- Stats + legend ----------
  document.getElementById("statsRow").innerHTML = DATA.stats.map(function (s) {
    return '<div class="stat"><span class="dot" style="background:' + s[2] + '"></span><span class="n">' + esc(s[0]) + '</span><span class="lbl">' + esc(s[1]) + "</span></div>";
  }).join("");
  var legend = document.getElementById("legend");
  if (legend) legend.innerHTML = "Node colours: " + ["U", "A", "D", "E", "V", "T", "F", "N", "X"].map(function (t) {
    return '<span style="color:' + TYPE_COLOR[t] + ';font-weight:600;">■</span> ' + (t === "U" ? "Structure" : TYPE_NAME[t]);
  }).join(" &nbsp; ");

  // ---------- Theme ----------
  var themeToggle = document.getElementById("themeToggle");
  var order = ["system", "light", "dark"], labels = { system: "Theme: System", light: "Theme: Light", dark: "Theme: Dark" };
  var theme = "system";
  try { theme = localStorage.getItem("kg-theme") || "system"; } catch (e) {}
  applyTheme(theme);
  themeToggle.addEventListener("click", function () {
    theme = order[(order.indexOf(theme) + 1) % order.length];
    applyTheme(theme);
    try { localStorage.setItem("kg-theme", theme); } catch (e) {}
  });
  function applyTheme(t) {
    if (t === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    themeToggle.textContent = labels[t];
  }
  document.getElementById("railToggle").addEventListener("click", function () { document.getElementById("rail").classList.toggle("open"); });

  // deep link: kg_explorer.html#<node id>
  if (location.hash.length > 1) {
    var target = decodeURIComponent(location.hash.slice(1));
    window.addEventListener("load", function () { if (nodes[target]) select(target, true); });
  }
})();
