// SPDX-License-Identifier: AGPL-3.0-or-later
// The hero scene: the Pantheon's coffered dome drawn as a living network.
// Every crossing on the dome is an agent; gold pulses are messages between them,
// each one travelling at most three hops, like a delegation chain in Pantheon.
// Light pours through the oculus, where Apollo sits.
//
// Loads three.js only after the page is up, renders nothing without WebGL
// (the CSS gradient behind it is the fallback), draws one still frame for
// reduced motion, and stops when the hero is off screen or the tab is hidden.

const host = document.getElementById("scene");

function webglOK() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch { return false; }
}

function whenIdle(fn) {
  const go = () => ("requestIdleCallback" in window ? requestIdleCallback(fn, { timeout: 1200 }) : setTimeout(fn, 200));
  if (document.readyState === "complete") go(); else addEventListener("load", go, { once: true });
}

if (host && webglOK()) whenIdle(() => import("./vendor/three.module.min.js").then(start).catch(() => {}));

function start(THREE) {
  // Colours go to the screen exactly as the CSS tokens write them: no linear workflow here.
  THREE.ColorManagement.enabled = false;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const css = () => getComputedStyle(document.documentElement);
  const color = (name, fallback) => new THREE.Color((css().getPropertyValue(name) || fallback).trim() || fallback);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.75));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  camera.position.set(0, -1.1, 11.5);
  const look = new THREE.Vector3(0, 1.4, 0);
  camera.lookAt(look);

  const rig = new THREE.Group();      // placement and pointer tilt
  const dome = new THREE.Group();     // slow spin
  rig.add(dome);
  scene.add(rig);

  // ── geometry of the dome ──────────────────────────────
  const R = 4;
  const MER = 28;                                 // the Pantheon has 28 coffers per ring
  const LAT = [0, 11, 22, 33, 44, 55, 64].map((d) => THREE.MathUtils.degToRad(d));
  const OCULUS = THREE.MathUtils.degToRad(71);
  const sph = (phi, theta, r = R) => new THREE.Vector3(
    r * Math.cos(phi) * Math.cos(theta), r * Math.sin(phi), r * Math.cos(phi) * Math.sin(theta));

  // nodes at every crossing
  const nodes = [];
  LAT.forEach((phi, li) => {
    for (let m = 0; m < MER; m++) nodes.push({ p: sph(phi, (m / MER) * Math.PI * 2), li, m });
  });
  const idx = (li, m) => li * MER + ((m + MER) % MER);
  const neighbours = nodes.map((n) => {
    const out = [idx(n.li, n.m + 1), idx(n.li, n.m - 1)];
    if (n.li > 0) out.push(idx(n.li - 1, n.m));
    if (n.li < LAT.length - 1) out.push(idx(n.li + 1, n.m));
    return out;
  });

  // structure lines: rings, meridians, coffers, drum
  const lineVerts = [];
  const seg = (a, b) => lineVerts.push(a.x, a.y, a.z, b.x, b.y, b.z);
  const ringAt = (phi, r = R, y = null, steps = 160) => {
    for (let i = 0; i < steps; i++) {
      const a = (i / steps) * Math.PI * 2, b = ((i + 1) / steps) * Math.PI * 2;
      const pa = y === null ? sph(phi, a, r) : new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a));
      const pb = y === null ? sph(phi, b, r) : new THREE.Vector3(r * Math.cos(b), y, r * Math.sin(b));
      seg(pa, pb);
    }
  };
  LAT.forEach((phi) => ringAt(phi));
  ringAt(OCULUS);
  for (let m = 0; m < MER; m++) {
    const th = (m / MER) * Math.PI * 2;
    const steps = 24;
    for (let i = 0; i < steps; i++) {
      const a = (i / steps) * LAT[LAT.length - 1], b = ((i + 1) / steps) * LAT[LAT.length - 1];
      seg(sph(a, th), sph(b, th));
    }
  }
  // coffers: a recessed square inside each cell of the five lower rings
  for (let li = 0; li < LAT.length - 2; li++) {
    for (let m = 0; m < MER; m++) {
      const p0 = LAT[li], p1 = LAT[li + 1];
      const t0 = (m / MER) * Math.PI * 2, t1 = ((m + 1) / MER) * Math.PI * 2;
      const k = 0.24;
      const pa = p0 + (p1 - p0) * k, pb = p1 - (p1 - p0) * k;
      const ta = t0 + (t1 - t0) * k, tb = t1 - (t1 - t0) * k;
      const r = R * 0.985;
      const c = [sph(pa, ta, r), sph(pa, tb, r), sph(pb, tb, r), sph(pb, ta, r)];
      for (let i = 0; i < 4; i++) seg(c[i], c[(i + 1) % 4]);
    }
  }
  // the drum under the dome, with sixteen pilasters
  const DRUM = -1.5;
  ringAt(0, R, DRUM, 160);
  ringAt(0, R, DRUM * 0.5, 160);
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * Math.PI * 2;
    seg(new THREE.Vector3(R * Math.cos(a), 0, R * Math.sin(a)), new THREE.Vector3(R * Math.cos(a), DRUM, R * Math.sin(a)));
  }

  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute("position", new THREE.Float32BufferAttribute(lineVerts, 3));
  const depthFade = `
    varying float vFade;
    uniform float uNear; uniform float uFar;
    void fadeFrom(vec4 mv) { vFade = 1.0 - smoothstep(uNear, uFar, -mv.z); }
  `;
  const lineMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uColor: { value: new THREE.Color() }, uAlpha: { value: 0.34 }, uNear: { value: 8.0 }, uFar: { value: 15.5 } },
    vertexShader: `${depthFade}
      void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); fadeFrom(mv); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `
      uniform vec3 uColor; uniform float uAlpha; varying float vFade;
      void main() { gl_FragColor = vec4(uColor, uAlpha * (0.18 + 0.82 * vFade)); }`,
  });
  dome.add(new THREE.LineSegments(lineGeo, lineMat));

  // ── agents (nodes) ────────────────────────────────────
  const soft = `
    float disc(vec2 c) { float d = length(c - 0.5); return smoothstep(0.5, 0.0, d); }
  `;
  const nPos = new Float32Array(nodes.length * 3);
  const nSeed = new Float32Array(nodes.length);
  nodes.forEach((n, i) => { n.p.toArray(nPos, i * 3); nSeed[i] = Math.random() * 6.283; });
  const nodeGeo = new THREE.BufferGeometry();
  nodeGeo.setAttribute("position", new THREE.BufferAttribute(nPos, 3));
  nodeGeo.setAttribute("seed", new THREE.BufferAttribute(nSeed, 1));
  const nodeMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color() }, uScale: { value: 1 }, uNear: { value: 8.0 }, uFar: { value: 15.5 }, uAlpha: { value: 1 } },
    vertexShader: `${depthFade}
      attribute float seed; uniform float uTime; uniform float uScale; varying float vTw;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0); fadeFrom(mv);
        vTw = 0.55 + 0.45 * sin(uTime * 1.3 + seed * 3.0);
        gl_PointSize = uScale * (5.0 + 3.0 * vTw) * (10.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `${soft}
      uniform vec3 uColor; uniform float uAlpha; varying float vFade; varying float vTw;
      void main() { float a = disc(gl_PointCoord); gl_FragColor = vec4(uColor, a * uAlpha * (0.25 + 0.75 * vFade) * (0.5 + 0.5 * vTw)); }`,
  });
  dome.add(new THREE.Points(nodeGeo, nodeMat));

  // ── messages: pulses that hop along edges, three hops at most ──
  const PULSES = 34, TRAIL = 14;
  const pulses = [];
  const spawn = (p) => {
    p.from = Math.floor(Math.random() * nodes.length);
    p.to = neighbours[p.from][Math.floor(Math.random() * neighbours[p.from].length)];
    p.prev = -1;
    p.hops = 1 + Math.floor(Math.random() * 3);   // a chain of one to three delegations
    p.t = 0;
    p.speed = 0.55 + Math.random() * 0.6;
    p.wait = Math.random() * 2.5;
    p.hist = [];
  };
  for (let i = 0; i < PULSES; i++) { const p = {}; spawn(p); p.wait = Math.random() * 4; pulses.push(p); }
  const pCount = PULSES * TRAIL;
  const pPos = new Float32Array(pCount * 3);
  const pAlpha = new Float32Array(pCount);
  const pulseGeo = new THREE.BufferGeometry();
  pulseGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
  pulseGeo.setAttribute("alpha", new THREE.BufferAttribute(pAlpha, 1));
  const pulseMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uColor: { value: new THREE.Color() }, uScale: { value: 1 }, uNear: { value: 8.0 }, uFar: { value: 15.5 } },
    vertexShader: `${depthFade}
      attribute float alpha; uniform float uScale; varying float vA;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0); fadeFrom(mv); vA = alpha;
        gl_PointSize = uScale * (4.0 + 9.0 * alpha) * (10.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `${soft}
      uniform vec3 uColor; varying float vA; varying float vFade;
      void main() { float a = disc(gl_PointCoord); gl_FragColor = vec4(uColor, a * vA * (0.35 + 0.65 * vFade)); }`,
  });
  dome.add(new THREE.Points(pulseGeo, pulseMat));
  const tmp = new THREE.Vector3();
  const slerpOnDome = (a, b, t, out) => {
    // travel along the surface, not through it
    out.copy(a).lerp(b, t);
    const ra = a.length(), rb = b.length();
    return out.setLength(ra + (rb - ra) * t);
  };
  function stepPulses(dt) {
    pulses.forEach((p, i) => {
      if (p.wait > 0) { p.wait -= dt; p.hist.length = 0; }
      else {
        p.t += dt * p.speed;
        if (p.t >= 1) {
          p.hops -= 1;
          if (p.hops <= 0) { spawn(p); }
          else {
            const opts = neighbours[p.to].filter((n) => n !== p.from);
            p.prev = p.from; p.from = p.to; p.to = opts[Math.floor(Math.random() * opts.length)]; p.t = 0;
          }
        }
        if (p.wait <= 0) {
          slerpOnDome(nodes[p.from].p, nodes[p.to].p, Math.min(p.t, 1), tmp);
          p.hist.unshift(tmp.clone());
          if (p.hist.length > TRAIL) p.hist.length = TRAIL;
        }
      }
      for (let k = 0; k < TRAIL; k++) {
        const o = (i * TRAIL + k);
        const h = p.hist[k];
        if (h) { h.toArray(pPos, o * 3); pAlpha[o] = Math.pow(1 - k / TRAIL, 2.2); }
        else { pAlpha[o] = 0; }
      }
    });
    pulseGeo.attributes.position.needsUpdate = true;
    pulseGeo.attributes.alpha.needsUpdate = true;
  }

  // ── the oculus and the light ──────────────────────────
  const yTop = R * Math.sin(OCULUS), rTop = R * Math.cos(OCULUS);
  const sunTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const g = c.getContext("2d");
    const grd = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    grd.addColorStop(0, "rgba(255,250,235,1)");
    grd.addColorStop(0.12, "rgba(255,214,140,0.95)");
    grd.addColorStop(0.35, "rgba(243,170,60,0.35)");
    grd.addColorStop(1, "rgba(243,170,60,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
    return new THREE.CanvasTexture(c);
  })();
  const sun = new THREE.Sprite(new THREE.SpriteMaterial({ map: sunTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  sun.position.set(0, yTop + 0.35, 0);
  sun.scale.setScalar(3.2);
  rig.add(sun);

  const shaftH = yTop - DRUM;
  const shaftGeo = new THREE.CylinderGeometry(rTop * 0.92, rTop * 2.1, shaftH, 64, 1, true);
  shaftGeo.translate(0, DRUM + shaftH / 2, 0);
  const shaftMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
    uniforms: { uColor: { value: new THREE.Color() }, uTime: { value: 0 }, uAlpha: { value: 0.32 } },
    vertexShader: `
      varying float vY; varying float vRim; varying vec2 vUv;
      void main() {
        vUv = uv; vY = uv.y;
        vec3 n = normalize(normalMatrix * normal);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vRim = abs(dot(n, normalize(-mv.xyz)));
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uColor; uniform float uTime; uniform float uAlpha;
      varying float vY; varying float vRim; varying vec2 vUv;
      void main() {
        float rays = 0.65 + 0.35 * sin(vUv.x * 62.83 + uTime * 0.35) * sin(vUv.x * 25.13 - uTime * 0.2);
        float a = pow(vY, 1.6) * pow(vRim, 1.8) * rays * uAlpha;
        gl_FragColor = vec4(uColor, a);
      }`,
  });
  rig.add(new THREE.Mesh(shaftGeo, shaftMat));

  // dust in the beam
  const DUST = 420;
  const dPos = new Float32Array(DUST * 3), dSeed = new Float32Array(DUST);
  for (let i = 0; i < DUST; i++) {
    const y = DRUM + Math.random() * shaftH;
    const f = (y - DRUM) / shaftH;
    const rMax = rTop * 2.1 + (rTop * 0.92 - rTop * 2.1) * f;
    const r = Math.sqrt(Math.random()) * rMax * 0.9, a = Math.random() * Math.PI * 2;
    dPos.set([r * Math.cos(a), y, r * Math.sin(a)], i * 3);
    dSeed[i] = Math.random();
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dPos, 3));
  dustGeo.setAttribute("seed", new THREE.BufferAttribute(dSeed, 1));
  const dustMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color() }, uScale: { value: 1 }, uBottom: { value: DRUM }, uH: { value: shaftH } },
    vertexShader: `
      attribute float seed; uniform float uTime; uniform float uScale; uniform float uBottom; uniform float uH; varying float vA;
      void main() {
        vec3 p = position;
        float fall = mod(p.y - uBottom - uTime * (0.05 + 0.08 * seed), uH);
        p.y = uBottom + fall;
        float ang = uTime * (0.04 + 0.06 * seed);
        p.xz = mat2(cos(ang), -sin(ang), sin(ang), cos(ang)) * p.xz;
        vA = (0.35 + 0.65 * sin(uTime * (0.6 + seed) + seed * 40.0) * 0.5 + 0.5) * smoothstep(0.0, 0.25, fall / uH) * (0.4 + 0.6 * fall / uH);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = uScale * (1.6 + 2.2 * seed) * (10.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `${soft}
      uniform vec3 uColor; varying float vA;
      void main() { gl_FragColor = vec4(uColor, disc(gl_PointCoord) * vA * 0.7); }`,
  });
  rig.add(new THREE.Points(dustGeo, dustMat));

  // where the light lands
  const pool = new THREE.Mesh(
    new THREE.CircleGeometry(rTop * 3.2, 64),
    new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uColor: { value: new THREE.Color() }, uAlpha: { value: 0.5 } },
      vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: `uniform vec3 uColor; uniform float uAlpha; varying vec2 vUv;
        void main() { float d = length(vUv - 0.5) * 2.0; gl_FragColor = vec4(uColor, pow(max(0.0, 1.0 - d), 2.4) * uAlpha); }`,
    }),
  );
  pool.rotation.x = -Math.PI / 2;
  pool.position.y = DRUM;
  rig.add(pool);

  // ── theme ─────────────────────────────────────────────
  let light = false;
  function theme() {
    const marble = color("--marble", "#d8dce6");
    const gold = color("--sun", "#f3b23f");
    const bgLum = color("--bg", "#06080e");
    light = (bgLum.r + bgLum.g + bgLum.b) / 3 > 0.5;
    lineMat.uniforms.uColor.value.copy(marble);
    lineMat.uniforms.uAlpha.value = light ? 0.22 : 0.3;
    // additive light reads as nothing on a pale page, so the light theme swaps to normal blending
    const blend = light ? THREE.NormalBlending : THREE.AdditiveBlending;
    [nodeMat, pulseMat, dustMat, shaftMat, pool.material, sun.material].forEach((m) => { m.blending = blend; m.needsUpdate = true; });
    nodeMat.uniforms.uColor.value.copy(light ? marble : marble.clone().lerp(new THREE.Color("#ffffff"), 0.3));
    nodeMat.uniforms.uAlpha.value = light ? 0.55 : 0.9;
    pulseMat.uniforms.uColor.value.copy(gold);
    dustMat.uniforms.uColor.value.copy(gold);
    shaftMat.uniforms.uColor.value.copy(gold);
    shaftMat.uniforms.uAlpha.value = light ? 0.22 : 0.34;
    pool.material.uniforms.uColor.value.copy(gold);
    pool.material.uniforms.uAlpha.value = light ? 0.28 : 0.5;
    sun.material.opacity = light ? 0.8 : 1;
  }
  theme();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { theme(); if (reduced) render(0); });
  new MutationObserver(() => { theme(); if (reduced) render(0); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // ── motion ────────────────────────────────────────────
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  addEventListener("pointermove", (e) => {
    pointer.tx = (e.clientX / innerWidth) * 2 - 1;
    pointer.ty = (e.clientY / innerHeight) * 2 - 1;
  }, { passive: true });

  let time = 0;

  // ── layout ────────────────────────────────────────────
  let base = { x: 0, scale: 1 };
  function resize() {
    const w = host.clientWidth || innerWidth, h = host.clientHeight || 600;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const dist = camera.position.distanceTo(look);
    const visH = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * dist;
    const visW = visH * camera.aspect;
    const wide = w > 900;
    base = wide ? { x: Math.min(visW * 0.24, 6.2), scale: Math.min(1.1, Math.max(0.85, visW / 22)) } : { x: 0, scale: 0.78 };
    rig.position.x = base.x;
    rig.scale.setScalar(base.scale);
    // the hero is tall; keep the dome in its upper half
    rig.position.y = wide ? 0.2 : 1.2;
    const ps = Math.min(renderer.getPixelRatio(), 1.75) * (h / 900) * 1.6;
    [nodeMat, pulseMat, dustMat].forEach((m) => (m.uniforms.uScale.value = ps));
    if (reduced) render(0);
  }
  new ResizeObserver(resize).observe(host);
  resize();


  function render(dt) {
    time += dt;
    dome.rotation.y = time * 0.045;
    pointer.x += (pointer.tx - pointer.x) * Math.min(1, dt * 2.5);
    pointer.y += (pointer.ty - pointer.y) * Math.min(1, dt * 2.5);
    rig.rotation.x = -0.05 + pointer.y * 0.06;
    rig.rotation.z = pointer.x * -0.035;
    nodeMat.uniforms.uTime.value = time;
    dustMat.uniforms.uTime.value = time;
    shaftMat.uniforms.uTime.value = time;
    sun.scale.setScalar(3.2 + Math.sin(time * 0.8) * 0.12);
    renderer.render(scene, camera);
  }

  if (reduced) {
    // one composed still: pulses frozen mid-flight
    for (let i = 0; i < 90; i++) stepPulses(1 / 30);
    render(0.001);
    host.classList.add("live");
    return;
  }

  let visible = true, last = performance.now(), raf = 0;
  const loop = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    stepPulses(dt);
    render(dt);
    raf = requestAnimationFrame(loop);
  };
  const run = () => { if (!raf && visible && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(loop); } };
  const stop = () => { cancelAnimationFrame(raf); raf = 0; };
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; visible ? run() : stop(); }).observe(host);
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : run()));
  run();
  requestAnimationFrame(() => host.classList.add("live"));
}
