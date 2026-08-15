// Interactive statistics widgets for the MASK-OFF lessons.
// Each widget is opt-in by class name on an empty div; markup is built here so
// the lesson HTML stays readable.
//
//   <div class="lab-bootstrap"></div>   resample-with-replacement machine
//   <div class="lab-chance"></div>      chance correction / prevalence paradox
//   <div class="lab-hill"></div>        coverage vs effective number
(function () {
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };

  // Deterministic RNG so a demo repeats, same reason kappa.py seeds Random(0).
  function mulberry32(seed) {
    return function () {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Same formula as kappa.py: (observed - expected) / (perfect - expected)
  function cohenKappa(pairs) {
    const n = pairs.length;
    if (!n) return 0;
    let agree = 0;
    const ca = {}, cb = {};
    for (const [a, b] of pairs) {
      if (a === b) agree++;
      ca[a] = (ca[a] || 0) + 1;
      cb[b] = (cb[b] || 0) + 1;
    }
    const po = agree / n;
    let pe = 0;
    for (const k in ca) pe += ca[k] * (cb[k] || 0);
    pe /= n * n;
    return pe < 1 ? (po - pe) / (1 - pe) : 1;
  }

  /* ---------------------------------------------------------------- 1. bootstrap */

  function buildBootstrap(root) {
    // 40 labeled items: raters agree on 34. Point estimate lands near 0.76 —
    // inside the "tentative" band, so the interval decides whether you can
    // tell it apart from the 0.80 bar at all.
    const base = [];
    const push = (a, b, k) => { for (let i = 0; i < k; i++) base.push([a, b]); };
    push("x", "x", 16); push("y", "y", 12); push("z", "z", 6);
    push("x", "y", 3);  push("y", "x", 2);  push("z", "y", 1);

    const point = cohenKappa(base);
    const rng = mulberry32(7);
    let draws = [];

    root.appendChild(el("p", "lab-title", "The bootstrap machine"));
    const facts = el("p", "lab-note");
    facts.innerHTML =
      `Your one sample: <b>40 items</b>, the two raters agree on <b>34</b>. ` +
      `Point estimate <b>&kappa; = ${point.toFixed(3)}</b>. ` +
      `You cannot go label 40 more items, so you resample the ones you have.`;
    root.appendChild(facts);

    const out = el("div", "lab-out");
    root.appendChild(out);

    const bar = el("div", "lab-buttons");
    const bOne = el("button", null, "Draw one resample");
    const bMany = el("button", null, "Run all 2000");
    const bReset = el("button", null, "Reset");
    bar.append(bOne, bMany, bReset);
    root.appendChild(bar);

    function resample() {
      const idx = [];
      for (let i = 0; i < base.length; i++) idx.push(Math.floor(rng() * base.length));
      return idx;
    }

    function showOne() {
      const idx = resample();
      const counts = {};
      for (const i of idx) counts[i] = (counts[i] || 0) + 1;
      const missed = base.length - Object.keys(counts).length;
      const twice = Object.values(counts).filter((c) => c >= 2).length;
      const k = cohenKappa(idx.map((i) => base[i]));
      draws.push(k);
      out.innerHTML = "";
      const p = el("p", "lab-note");
      p.innerHTML =
        `Drew 40 items <b>with replacement</b> from your own 40. ` +
        `<b>${missed}</b> items were not drawn at all; <b>${twice}</b> were drawn two or more times.<br>` +
        `That reshuffled sample gives <b>&kappa; = ${k.toFixed(3)}</b> ` +
        `<span class="lab-delta">(${(k - point >= 0 ? "+" : "") + (k - point).toFixed(3)} vs your real sample)</span><br>` +
        `Replicates so far: <b>${draws.length}</b>. That wobble is the whole idea.`;
      out.appendChild(p);
    }

    function showMany() {
      draws = [];
      for (let r = 0; r < 2000; r++) draws.push(cohenKappa(resample().map((i) => base[i])));
      const sorted = draws.slice().sort((a, b) => a - b);
      const lo = sorted[Math.floor(0.025 * 2000)];
      const hi = sorted[Math.floor(0.975 * 2000)];

      const bins = 30;
      const min = sorted[0], max = sorted[sorted.length - 1];
      const width = (max - min) / bins || 1;
      const hist = new Array(bins).fill(0);
      for (const d of sorted) hist[Math.min(bins - 1, Math.floor((d - min) / width))]++;
      const peak = Math.max(...hist);

      out.innerHTML = "";
      const chart = el("div", "lab-hist");
      hist.forEach((c, i) => {
        const centre = min + (i + 0.5) * width;
        const b = el("div", "lab-bin");
        b.style.height = `${Math.max(2, (c / peak) * 100)}%`;
        if (centre < lo || centre > hi) b.classList.add("tail");
        b.title = `${c} replicates near κ = ${centre.toFixed(3)}`;
        chart.appendChild(b);
      });
      out.appendChild(chart);

      const scale = el("div", "lab-scale");
      scale.innerHTML = `<span>${min.toFixed(2)}</span><span>${max.toFixed(2)}</span>`;
      out.appendChild(scale);

      const p = el("p", "lab-note");
      const straddles = lo < 0.8 && hi > 0.8;
      p.innerHTML =
        `2000 replicates. Sort them, cut off the lowest 2.5% and the highest 2.5% ` +
        `(the pale bars). What is left is the <b>95% percentile bootstrap interval</b>:<br>` +
        `<b>&kappa; = ${point.toFixed(3)}, 95% CI [${lo.toFixed(3)}, ${hi.toFixed(3)}]</b><br>` +
        (straddles
          ? `<span class="lab-flag">The interval crosses the 0.80 bar.</span> At n = 40 you cannot ` +
            `tell this facet apart from a passing one. That is why the binding run uses n = 300 — ` +
            `more items, narrower interval.`
          : `The interval clears the 0.80 bar.`);
      out.appendChild(p);
    }

    bOne.addEventListener("click", showOne);
    bMany.addEventListener("click", showMany);
    bReset.addEventListener("click", () => { draws = []; out.innerHTML = ""; });
  }

  /* ----------------------------------------------------- 2. chance correction */

  function buildChance(root) {
    root.appendChild(el("p", "lab-title", "Why agreement alone is not evidence"));
    const note = el("p", "lab-note");
    note.innerHTML =
      `Two raters, two options. Drag the sliders. Watch what happens to &kappa; when the ` +
      `raw agreement stays fixed but one option takes over the sample.`;
    root.appendChild(note);

    const mk = (label, min, max, step, val) => {
      const wrap = el("label", "lab-slider");
      const name = el("span", null, label);
      const input = el("input");
      input.type = "range"; input.min = min; input.max = max; input.step = step; input.value = val;
      const read = el("b");
      wrap.append(name, input, read);
      root.appendChild(wrap);
      return { input, read };
    };

    const sPo = mk("Raw agreement (they picked the same label)", 0.5, 0.99, 0.01, 0.9);
    const sPrev = mk("Share of items whose true answer is the common option", 0.5, 0.95, 0.01, 0.5);
    const out = el("div", "lab-out");
    root.appendChild(out);

    function draw() {
      const po = Number(sPo.input.value);
      let prev = Number(sPrev.input.value);
      const d = 1 - po;
      prev = Math.min(prev, po + d / 2);           // keep the table non-negative
      const pe = prev * prev + (1 - prev) * (1 - prev);
      const kappa = pe < 1 ? (po - pe) / (1 - pe) : 1;
      const pabak = 2 * po - 1;
      sPo.read.textContent = po.toFixed(2);
      sPrev.read.textContent = prev.toFixed(2);

      const verdict =
        kappa >= 0.8 ? ["pass", "ok"] : kappa >= 0.67 ? ["tentative", "warn"] : ["fail", "danger"];
      out.innerHTML =
        `<table class="lab-table"><tbody>` +
        `<tr><td>Observed agreement <code>po</code></td><td><b>${po.toFixed(3)}</b></td>` +
        `<td class="lab-gloss">how often they matched</td></tr>` +
        `<tr><td>Agreement expected by chance <code>pe</code></td><td><b>${pe.toFixed(3)}</b></td>` +
        `<td class="lab-gloss">what two raters would hit while ignoring the email</td></tr>` +
        `<tr><td><b>Cohen's &kappa;</b></td><td><b>${kappa.toFixed(3)}</b> ` +
        `<span class="tag ${verdict[1]}">${verdict[0]}</span></td>` +
        `<td class="lab-gloss">the credit left once chance is paid off</td></tr>` +
        `<tr><td>PABAK</td><td><b>${pabak.toFixed(3)}</b></td>` +
        `<td class="lab-gloss">agreement rescaled, ignoring the skew</td></tr>` +
        `</tbody></table>`;
    }
    sPo.input.addEventListener("input", draw);
    sPrev.input.addEventListener("input", draw);
    draw();
  }

  /* -------------------------------------------------- 3. coverage vs effective */

  function buildHill(root) {
    root.appendChild(el("p", "lab-title", "Coverage and effective number are two claims"));
    const note = el("p", "lab-note");
    note.innerHTML =
      `Four options on one axis. Set how many items landed on each. ` +
      `Preset <b>Standing</b> reproduces the real measured shape.`;
    root.appendChild(note);

    const names = ["current", "new", "leaving", "took_over"];
    const start = [149, 55, 3, 2];
    const inputs = names.map((n, i) => {
      const wrap = el("label", "lab-slider");
      wrap.appendChild(el("span", null, n));
      const input = el("input");
      input.type = "range"; input.min = 0; input.max = 200; input.step = 1; input.value = start[i];
      const read = el("b");
      wrap.append(input, read);
      root.appendChild(wrap);
      return { input, read };
    });

    const bar = el("div", "lab-buttons");
    const bReal = el("button", null, "Preset: Standing, as measured");
    const bEven = el("button", null, "Preset: perfectly even");
    bar.append(bReal, bEven);
    root.appendChild(bar);
    const out = el("div", "lab-out");
    root.appendChild(out);

    function draw() {
      const counts = inputs.map((s) => Number(s.input.value));
      inputs.forEach((s, i) => (s.read.textContent = counts[i]));
      const n = counts.reduce((a, b) => a + b, 0);
      const coverage = counts.filter((c) => c > 0).length;
      let eff = 0;
      if (n) {
        let h = 0;
        for (const c of counts) if (c) { const p = c / n; h -= p * Math.log(p); }
        eff = Math.exp(h);
      }
      const evenness = coverage ? eff / coverage : 0;
      out.innerHTML =
        `<p class="lab-note">n = ${n}<br>` +
        `<b>Coverage (Hill q=0) = ${coverage} of 4</b> — how many options showed up at all.<br>` +
        `<b>Effective number (Hill q=1) = ${eff.toFixed(2)}</b> — this axis behaves like ` +
        `${eff.toFixed(2)} evenly used options.<br>` +
        `<b>Evenness = ${evenness.toFixed(2)}</b> — the fraction of what the axis could carry.</p>` +
        `<p class="lab-note lab-gloss">Coverage counts a category that appeared twice in 209 items ` +
        `exactly as much as one that appeared 149 times. The effective number does not. ` +
        `Report both, or a long tail reads as balance.</p>`;
    }
    inputs.forEach((s) => s.input.addEventListener("input", draw));
    bReal.addEventListener("click", () => { inputs.forEach((s, i) => (s.input.value = start[i])); draw(); });
    bEven.addEventListener("click", () => { inputs.forEach((s) => (s.input.value = 52)); draw(); });
    draw();
  }

  document.querySelectorAll(".lab-bootstrap").forEach(buildBootstrap);
  document.querySelectorAll(".lab-chance").forEach(buildChance);
  document.querySelectorAll(".lab-hill").forEach(buildHill);
})();

// Appended: confusion-matrix explorer for lesson 0004.
//   <div class="lab-confusion"></div>
(function () {
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const OPTS = ["internal_desk", "agency", "landlord", "school", "practice", "provider"];
  // Agreements, shaped like the measured institution distribution (scan of 209).
  const DIAG = { internal_desk: 19, agency: 22, landlord: 19, school: 43, practice: 21, provider: 138 };
  // Where the non-concentrated disagreements sit, round-robin.
  const SPREAD = [
    ["school", "provider"], ["agency", "provider"], ["landlord", "provider"],
    ["internal_desk", "agency"], ["provider", "school"], ["practice", "school"],
    ["agency", "practice"], ["provider", "landlord"],
  ];
  const DISAGREE = 38;

  function kappaOf(M) {
    let n = 0, agree = 0;
    const ra = {}, rb = {};
    for (const x of OPTS) for (const y of OPTS) {
      const c = M[x][y]; if (!c) continue;
      n += c; if (x === y) agree += c;
      ra[x] = (ra[x] || 0) + c; rb[y] = (rb[y] || 0) + c;
    }
    const po = agree / n;
    let pe = 0;
    for (const k of OPTS) pe += (ra[k] || 0) * (rb[k] || 0);
    pe /= n * n;
    return { po, kappa: (po - pe) / (1 - pe), n };
  }

  function build(root) {
    root.appendChild(el("p", "lab-title", "Same κ, two different diagnoses"));
    const note = el("p", "lab-note");
    note.innerHTML =
      `One axis, 300 items, <b>38 disagreements</b> — the count is fixed, so raw agreement ` +
      `never moves. Slide how many of those 38 are the <b>same</b> ordered pair.`;
    root.appendChild(note);

    const wrap = el("label", "lab-slider");
    wrap.appendChild(el("span", null, "disagreements that are (practice → provider)"));
    const input = el("input");
    input.type = "range"; input.min = 0; input.max = DISAGREE; input.step = 1; input.value = 4;
    const read = el("b");
    wrap.append(input, read);
    root.appendChild(wrap);

    const out = el("div", "lab-out");
    root.appendChild(out);

    function draw() {
      const k = Number(input.value);
      read.textContent = k;
      const M = {};
      for (const x of OPTS) { M[x] = {}; for (const y of OPTS) M[x][y] = 0; }
      for (const x of OPTS) M[x][x] = DIAG[x];
      M.practice.provider += k;
      for (let i = 0; i < DISAGREE - k; i++) {
        const [x, y] = SPREAD[i % SPREAD.length];
        M[x][y] += 1;
      }
      const { po, kappa } = kappaOf(M);

      const pairs = [];
      for (const x of OPTS) for (const y of OPTS) if (x !== y && M[x][y]) pairs.push([x, y, M[x][y]]);
      pairs.sort((p, q) => q[2] - p[2]);
      const top = pairs.slice(0, 5);
      const flagged = top.filter((p) => p[2] / DISAGREE >= 0.3);

      out.innerHTML =
        `<p class="lab-note">raw agreement <b>po = ${po.toFixed(3)}</b> (fixed) &nbsp;·&nbsp; ` +
        `<b>&kappa; = ${kappa.toFixed(3)}</b> ` +
        `<span class="tag ${kappa >= 0.8 ? "ok" : kappa >= 0.67 ? "warn" : "danger"}">` +
        `${kappa >= 0.8 ? "pass" : kappa >= 0.67 ? "tentative" : "fail"}</span></p>` +
        `<table class="lab-table"><tbody>` +
        top.map(([x, y, c]) => {
          const s = c / DISAGREE;
          return `<tr><td>${x} / ${y}</td><td>${c} (${(s * 100).toFixed(0)}% of disagreements)</td>` +
            `<td class="lab-gloss">${s >= 0.3 ? '<b class="lab-flag">&lt;-- OVERLAP</b>' : ""}</td></tr>`;
        }).join("") +
        `</tbody></table>` +
        `<p class="lab-note lab-gloss">${
          flagged.length
            ? `<b>Structure.</b> One ordered pair carries most of the disagreement, so the menu still ` +
              `admits two truthful answers for the same item. κ barely moved — it cannot see this. ` +
              `The paper reports it as a named overlap.`
            : `<b>Noise.</b> The disagreement is spread thinly across many pairs — raters slipping, ` +
              `not a menu defect. This is exactly what κ is built to absorb.`
        }</p>`;
    }
    input.addEventListener("input", draw);
    draw();
  }
  document.querySelectorAll(".lab-confusion").forEach(build);
})();
