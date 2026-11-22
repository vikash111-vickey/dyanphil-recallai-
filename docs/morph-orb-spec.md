**You are given a task to integrate an existing React component in the codebase**



**The codebase should support:**

**- shadcn project structure**  

**- Tailwind CSS**

**- Typescript**



**If it doesn't, provide instructions on how to setup project via shadcn CLI, install Tailwind or Typescript.**



**Determine the default path for components and styles.** 

**If default path for components is not /components/ui, provide instructions on why it's important to create this folder**

**Copy-paste this component to /components/ui folder:**

**```tsx**

**ai-thiking-orb-and-input.tsx**

**// component.tsx**

**import React, { useEffect, useLayoutEffect, useRef, useState } from "react";**

**import "../../index.css";**



**/\* ───────────────────────────── copy ───────────────────────────── \*/**

**const COPY = {**

&#x20; **placeholder: "Ask anything…",**

&#x20; **labels: \["Thinking", "Searching", "Analyzing", "Composing"],**

&#x20; **done: "Done",**

&#x20; **answerTitle: "Answer",**

&#x20; **answerBody: "The answer goes here",**

&#x20; **reset: "New question",**

&#x20; **send: "Send",**

**};**



**type Phase = "idle" | "launch" | "assemble" | "think" | "resolve" | "condense" | "unfold" | "answered" | "reset";**



**export interface MorphOrbProps {**

&#x20; **onSubmit?: (text: string) => Promise<string> | string;**

&#x20; **minThinkMs?: number;**

&#x20; **speed?: number;**

**}**



**/\* ─────────────────────────── geometry ─────────────────────────── \*/**

**const PILL\_H = 60, BALL\_SMALL = 60, ORB\_D = 132, ORB\_R = 66, CANVAS = 220;**

**const CARD\_H = 108;**

**const FLY\_D = 138;**

**const pillW = () => Math.min(560, window.innerWidth - 32);**

**const cardW = () => Math.min(320, window.innerWidth - 32);**

**const homeDy = () => window.innerHeight \* 0.54 - 96; // pill centre is 96px above the viewport bottom; stage centre is at top:46%**



**/\* ───────────────────────── math + easing ───────────────────────── \*/**

**type Ease = (t: number) => number;**

**const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);**

**const lerp = (a: number, b: number, t: number) => a + (b - a) \* t;**

**const fmt = (v: number) => String(Math.round(v \* 1e4) / 1e4);**

**const TAU = Math.PI \* 2;**



**function mulberry32(a: number) {**

&#x20; **return function () {**

&#x20;   **a |= 0;**

&#x20;   **a = (a + 0x6d2b79f5) | 0;**

&#x20;   **let t = Math.imul(a ^ (a >>> 15), 1 | a);**

&#x20;   **t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;**

&#x20;   **return ((t ^ (t >>> 14)) >>> 0) / 4294967296;**

&#x20; **};**

**}**



**function cubicBezier(x1: number, y1: number, x2: number, y2: number): Ease {**

&#x20; **const cx = 3 \* x1, bx = 3 \* (x2 - x1) - cx, ax = 1 - cx - bx;**

&#x20; **const cy = 3 \* y1, by = 3 \* (y2 - y1) - cy, ay = 1 - cy - by;**

&#x20; **const sx = (t: number) => ((ax \* t + bx) \* t + cx) \* t;**

&#x20; **const sy = (t: number) => ((ay \* t + by) \* t + cy) \* t;**

&#x20; **const dx = (t: number) => (3 \* ax \* t + 2 \* bx) \* t + cx;**

&#x20; **const solve = (x: number) => {**

&#x20;   **let t = x;**

&#x20;   **for (let i = 0; i < 8; i++) {**

&#x20;     **const e = sx(t) - x;**

&#x20;     **if (Math.abs(e) < 1e-6) return t;**

&#x20;     **const d = dx(t);**

&#x20;     **if (Math.abs(d) < 1e-6) break;**

&#x20;     **t -= e / d;**

&#x20;   **}**

&#x20;   **let lo = 0, hi = 1;**

&#x20;   **t = x;**

&#x20;   **for (let i = 0; i < 40; i++) {**

&#x20;     **const e = sx(t);**

&#x20;     **if (Math.abs(e - x) < 1e-6) break;**

&#x20;     **if (x > e) lo = t; else hi = t;**

&#x20;     **t = (hi - lo) / 2 + lo;**

&#x20;   **}**

&#x20;   **return t;**

&#x20; **};**

&#x20; **return (x) => (x <= 0 ? 0 : x >= 1 ? 1 : sy(solve(x)));**

**}**



**const E = {**

&#x20; **out: cubicBezier(0.22, 1, 0.36, 1),**

&#x20; **io: cubicBezier(0.65, 0, 0.35, 1),**

&#x20; **in: cubicBezier(0.4, 0, 1, 1),**

&#x20; **fly: cubicBezier(0.5, 0, 0.1, 1),**

&#x20; **grow: cubicBezier(0.3, 0, 0.2, 1),**

&#x20; **vortex: cubicBezier(0.6, 0, 0.2, 1),**

&#x20; **spring: cubicBezier(0.34, 1.4, 0.64, 1),**

&#x20; **card: cubicBezier(0.65, 0, 0.2, 1),**

&#x20; **lin: (t: number) => t,**

**};**



**const bez = (t: number, p0: number, c: number, p2: number) => (1 - t) \* (1 - t) \* p0 + 2 \* (1 - t) \* t \* c + t \* t \* p2;**



**/\* ───────────────────────── timeline data ───────────────────────── \*/**

**interface Track { ch: string; from: number; to: number; t0: number; t1: number; ease?: Ease }**

**const T = (ch: string, from: number, to: number, t0: number, t1: number, ease: Ease = E.io): Track => ({ ch, from, to, t0, t1, ease });**



**interface Geo { pw: number; cw: number; H: number; dir: number }**



**const launchTracks = (g: Geo): Track\[] => \[**

&#x20; **T("w", g.pw, g.pw - 12, 0, 100, E.out),**

&#x20; **T("oInput", 1, 0, 0, 160, E.in),**

&#x20; **T("inScale", 1, 0.6, 0, 160, E.in),**

&#x20; **T("oGlow", 1, 0, 0, 300, E.out),**

&#x20; **T("oAur", 1, 0, 0, 300, E.out),**

&#x20; **T("w", g.pw - 12, BALL\_SMALL, 100, 560, E.io),**

&#x20; **T("h", PILL\_H, PILL\_H + 6, 380, 500, E.out),**

&#x20; **T("h", PILL\_H + 6, BALL\_SMALL, 500, 620, E.out),**

&#x20; **T("oPill", 1, 0, 300, 560, E.out),**

&#x20; **T("oBall", 0, 1, 300, 560, E.out),**

&#x20; **T("u", 0, 1, 620, 1500, E.fly),**

&#x20; **T("w", BALL\_SMALL, FLY\_D, 620, 1300, E.grow),**

&#x20; **T("h", BALL\_SMALL, FLY\_D, 620, 1300, E.grow),**

&#x20; **T("w", FLY\_D, ORB\_D, 1300, 1500, E.out),**

&#x20; **T("h", FLY\_D, ORB\_D, 1300, 1500, E.out),**

&#x20; **T("cHalo", 0, 0.6, 620, 1500, E.out),**

&#x20; **T("trail", 0, 1, 700, 800, E.out),**

&#x20; **T("trail", 1, 0, 1300, 1500, E.in),**

**];**



**const ASSEMBLE: Track\[] = \[**

&#x20; **T("oRing", 1, 0, 0, 300, E.out),**

&#x20; **T("oBall", 1, 0, 0, 260, E.out),**

&#x20; **T("orb.k", 0, 1, 0, 800, E.out),**

&#x20; **T("orb.alpha", 0, 1, 0, 800, E.out),**

&#x20; **T("orb.spin", 0, 0.9, 0, 800, E.out),**

&#x20; **T("orb.pop", 1, 1.05, 0, 420, E.out),**

&#x20; **T("orb.pop", 1.05, 1, 420, 800, E.io),**

&#x20; **T("sOp", 0, 1, 300, 620, E.out),**

&#x20; **T("sTy", 6, 0, 300, 620, E.out),**

**];**



**const RESOLVE: Track\[] = \[**

&#x20; **T("orb.sweep", 0, 1, 0, 700, E.io),**

&#x20; **T("orb.spin", 0.9, 0.3, 0, 700, E.out),**

&#x20; **T("orb.gain", 1, 0, 0, 700, E.out),**

&#x20; **T("orb.floor", 0, 0.95, 400, 900, E.out),**

&#x20; **T("orb.rad", 0, 0.15, 400, 900, E.out),**

&#x20; **T("orb.pop", 1, 1.04, 600, 800, E.out),**

&#x20; **T("orb.pop", 1.04, 1, 800, 900, E.out),**

**];**



**const CONDENSE: Track\[] = \[**

&#x20; **T("orb.pop", 1, 1.06, 0, 120, E.out),**

&#x20; **T("sOp", 1, 0, 0, 160, E.in),**

&#x20; **T("sTy", 0, -6, 0, 160, E.in),**

&#x20; **T("orb.k", 1, 0, 120, 640, E.vortex),**

&#x20; **T("orb.vortex", 0, 1.6, 120, 640, E.vortex),**

&#x20; **T("oGreen", 0, 1, 260, 700, E.spring),**

&#x20; **T("gs", 0.55, 1, 260, 700, E.spring),**

&#x20; **T("pulse", 0, 1, 320, 760, E.out),**

&#x20; **T("oHalo", 0, 0.35, 380, 700, E.out),**

&#x20; **T("orb.alpha", 1, 0, 500, 800, E.out),**

**];**



**const unfoldTracks = (g: Geo, tw: number): Track\[] => \[**

&#x20; **T("w", ORB\_D, 124, 0, 90, E.in),**

&#x20; **T("h", ORB\_D, 124, 0, 90, E.in),**

&#x20; **T("w", 124, g.cw, 90, 700, E.card),**

&#x20; **T("h", 124, CARD\_H, 90, 700, E.out),**

&#x20; **T("r", ORB\_D / 2, 20, 90, 700, E.io),**

&#x20; **T("oGreen", 1, 0, 200, 560, E.out),**

&#x20; **T("oCard", 0, 1, 200, 560, E.out),**

&#x20; **T("oHalo", 0.35, 0, 300, 700, E.out),**

&#x20; **T("cHalo", 0.6, 0.22, 300, 700, E.out),**

&#x20; **T("hOp", 0, 1, 520, 840, E.out),**

&#x20; **T("dotS", 0, 1, 520, 840, E.spring),**

&#x20; **T("wp", 0, 1, 600, 600 + tw, E.lin),**

&#x20; **T("bloom", 1, 0.625, 700, 1200, E.io),**

**];**



**/\* reduced-motion: pure cross-fades \*/**

**const R\_OUT: Track\[] = \[**

&#x20; **T("oInput", 1, 0, 0, 140, E.out),**

&#x20; **T("oPill", 1, 0, 0, 200, E.out),**

&#x20; **T("oGlow", 1, 0, 0, 200, E.out),**

&#x20; **T("oAur", 1, 0, 0, 200, E.out),**

&#x20; **T("oRing", 1, 0, 0, 200, E.out),**

**];**

**const R\_IN: Track\[] = \[**

&#x20; **T("orb.alpha", 0, 1, 0, 200, E.out),**

&#x20; **T("sOp", 0, 1, 0, 200, E.out),**

&#x20; **T("cHalo", 0, 0.6, 0, 200, E.out),**

**];**

**const R\_RESOLVE: Track\[] = \[T("orb.sweep", 0, 1, 0, 250, E.io), T("orb.floor", 0, 0.95, 0, 250, E.out)];**

**const R\_CONDENSE: Track\[] = \[**

&#x20; **T("oGreen", 0, 1, 0, 250, E.out),**

&#x20; **T("orb.alpha", 1, 0, 0, 250, E.out),**

&#x20; **T("sOp", 1, 0, 0, 250, E.out),**

**];**

**const R\_GREEN\_OUT: Track\[] = \[T("oGreen", 1, 0, 0, 120, E.out)];**

**const rCardIn = (tw: number): Track\[] => \[**

&#x20; **T("oCard", 0, 1, 0, 250, E.out),**

&#x20; **T("hOp", 0, 1, 0, 250, E.out),**

&#x20; **T("wp", 0, 1, 0, tw, E.lin),**

&#x20; **T("bloom", 1, 0.625, 0, 250, E.out),**

**];**



**const FADE = \["oGlow", "oAur", "oPill", "oBall", "oGreen", "oCard", "oRing", "oInput", "oHalo", "sOp", "orb.alpha", "trail"];**



**const INIT: Record<string, number> = {**

&#x20; **h: PILL\_H, r: 999, oGlow: 1, oHalo: 0, oPill: 1, oBall: 0, oGreen: 0, oCard: 0, oRing: 1, oInput: 1, inScale: 1, oAur: 1,**

&#x20; **gs: 0.55, cs: 1, hOp: 0, dotS: 0, bloom: 1, u: 0, yOff: 0, trail: 0, pulse: -1, sOp: 0, sTy: 6, cHalo: 0, wp: 0,**

&#x20; **"orb.k": 0, "orb.alpha": 0, "orb.spin": 0, "orb.pop": 1, "orb.sweep": 0, "orb.vortex": 0, "orb.gain": 1, "orb.floor": 0, "orb.rad": 0,**

**};**



**/\* ─────────────────────────── async utils ─────────────────────────── \*/**

**const ABORT = Symbol("abort");**



**function sleep(ms: number, sig: AbortSignal) {**

&#x20; **return new Promise<void>((res) => {**

&#x20;   **if (sig.aborted) return res();**

&#x20;   **let id = 0;**

&#x20;   **const onAbort = () => { window.clearTimeout(id); res(); };**

&#x20;   **id = window.setTimeout(() => { sig.removeEventListener("abort", onAbort); res(); }, Math.max(0, ms));**

&#x20;   **sig.addEventListener("abort", onAbort, { once: true });**

&#x20; **});**

**}**



**function abortable<V>(p: Promise<V>, sig: AbortSignal) {**

&#x20; **return new Promise<V | undefined>((res) => {**

&#x20;   **if (sig.aborted) return res(undefined);**

&#x20;   **const onAbort = () => res(undefined);**

&#x20;   **sig.addEventListener("abort", onAbort, { once: true });**

&#x20;   **p.then(**

&#x20;     **(v) => { sig.removeEventListener("abort", onAbort); res(v); },**

&#x20;     **() => { sig.removeEventListener("abort", onAbort); res(undefined); }**

&#x20;   **);**

&#x20; **});**

**}**



**/\* ───────────────────────────── dotted orb ───────────────────────────── \*/**

**const RINGS = 16;**

**const DOT\_LIST = (() => {**

&#x20; **const rand = mulberry32(7);**

&#x20; **const out: { x: number; y: number; z: number; u: number; seed: number }\[] = \[];**

&#x20; **for (let k = 0; k < RINGS; k++) {**

&#x20;   **const y = 1 - ((k + 0.5) / RINGS) \* 2;**

&#x20;   **const r = Math.sqrt(1 - y \* y);**

&#x20;   **const m = Math.max(4, Math.round(30 \* r));**

&#x20;   **for (let j = 0; j < m; j++) {**

&#x20;     **const a = (j / m) \* TAU + k \* 0.35;**

&#x20;     **out.push({ x: Math.cos(a) \* r, y, z: Math.sin(a) \* r, u: (1 - y) / 2, seed: rand() \* 6.283 });**

&#x20;   **}**

&#x20; **}**

&#x20; **return out;**

**})();**

**const N = DOT\_LIST.length;**

**const DX = Float32Array.from(DOT\_LIST, (d) => d.x);**

**const DY = Float32Array.from(DOT\_LIST, (d) => d.y);**

**const DZ = Float32Array.from(DOT\_LIST, (d) => d.z);**

**const DU = Float32Array.from(DOT\_LIST, (d) => d.u);**

**const DS = Float32Array.from(DOT\_LIST, (d) => d.seed);**



**const G\_STEPS = 24, A\_STEPS = 48;**

**const COLORS: string\[] = (() => {**

&#x20; **const out: string\[] = \[];**

&#x20; **for (let gi = 0; gi <= G\_STEPS; gi++) {**

&#x20;   **const g = gi / G\_STEPS;**

&#x20;   **const r = Math.round(lerp(235, 52, g)), gg = Math.round(lerp(235, 211, g)), b = Math.round(lerp(235, 153, g));**

&#x20;   **for (let ai = 0; ai <= A\_STEPS; ai++) out.push(`rgba(${r},${gg},${b},${(ai / A\_STEPS).toFixed(3)})`);**

&#x20; **}**

&#x20; **return out;**

**})();**



**interface OrbParams {**

&#x20; **k: number; alpha: number; spin: number; rot: number; sweep: number; pop: number;**

&#x20; **vortex: number; gain: number; floor: number; rad: number; prog: number;**

**}**

**const ORB\_KEYS = \["k", "alpha", "spin", "sweep", "pop", "vortex", "gain", "floor", "rad"] as const;**



**function createOrb(canvas: HTMLCanvasElement, getSpeed: () => number, isReduced: () => boolean) {**

&#x20; **const P: OrbParams = { k: 0, alpha: 0, spin: 0, rot: 0, sweep: 0, pop: 1, vortex: 0, gain: 1, floor: 0, rad: 0, prog: 0 };**

&#x20; **const ctx = canvas.getContext("2d");**

&#x20; **const lit = new Float32Array(N);**

&#x20; **const SX = new Float32Array(N), SY = new Float32Array(N), SR = new Float32Array(N), SD = new Float32Array(N);**

&#x20; **const SC = new Int16Array(N);**

&#x20; **const pw = \[1, 0, 0, 0];**

&#x20; **let time = 0, raf = 0, last = 0, dead = false;**



&#x20; **const reset = () => {**

&#x20;   **P.k = 0; P.alpha = 0; P.spin = 0; P.rot = 0; P.sweep = 0; P.pop = 1; P.vortex = 0; P.gain = 1; P.floor = 0; P.rad = 0; P.prog = 0;**

&#x20;   **lit.fill(0);**

&#x20;   **pw\[0] = 1; pw\[1] = 0; pw\[2] = 0; pw\[3] = 0;**

&#x20;   **time = isReduced() ? 1.2 : 0;**

&#x20; **};**

&#x20; **reset();**



&#x20; **if (!ctx) return { P, ensure() {}, reset, destroy() {} };**



&#x20; **const dpr = Math.min(2, window.devicePixelRatio || 1);**

&#x20; **canvas.width = Math.round(CANVAS \* dpr);**

&#x20; **canvas.height = Math.round(CANVAS \* dpr);**

&#x20; **ctx.setTransform(dpr, 0, 0, dpr, 0, 0);**



&#x20; **const S = 0.6, CP = Math.cos(0.35), SP = Math.sin(0.35), C0 = CANVAS / 2;**



&#x20; **const draw = (dt: number) => {**

&#x20;   **ctx.clearRect(0, 0, CANVAS, CANVAS);**

&#x20;   **time += dt;**

&#x20;   **P.rot += P.spin \* dt;**

&#x20;   **const yaw = P.rot + P.vortex, cyw = Math.cos(yaw), syw = Math.sin(yaw);**

&#x20;   **const stepW = dt / 0.35;**

&#x20;   **for (let q = 0; q < 4; q++) {**

&#x20;     **const d = (q === P.prog ? 1 : 0) - pw\[q];**

&#x20;     **pw\[q] += Math.abs(d) <= stepW ? d : d > 0 ? stepW : -stepW;**

&#x20;   **}**

&#x20;   **const decay = Math.exp(-dt / 0.5);**

&#x20;   **const h0 = (time \* 300) % N, h3 = (time \* 480) % N;**

&#x20;   **const a1 = time \* 0.8, b1 = Math.sin(time \* 0.5) \* 0.9;**

&#x20;   **const f1x = Math.cos(b1) \* Math.cos(a1), f1y = Math.sin(b1), f1z = Math.cos(b1) \* Math.sin(a1);**

&#x20;   **const a2 = time \* 0.55 + 2.1, b2 = Math.cos(time \* 0.42) \* 0.9;**

&#x20;   **const f2x = Math.cos(b2) \* Math.cos(a2), f2y = Math.sin(b2), f2z = Math.cos(b2) \* Math.sin(a2);**

&#x20;   **const lat = Math.sin(time \* 2.2);**

&#x20;   **const swirlK = P.vortex \* 1.5;**



&#x20;   **for (let n = 0; n < N; n++) {**

&#x20;     **const dx = DX\[n], dy = DY\[n], dz = DZ\[n], u = DU\[n];**



&#x20;     **/\* light programs: dots are lit in turn \*/**

&#x20;     **let pulse = 0;**

&#x20;     **if (pw\[0] > 0.001) {**

&#x20;       **let dd = Math.abs(n - h0); if (dd > N - dd) dd = N - dd;**

&#x20;       **const v = Math.max(0, 1 - dd / 16);**

&#x20;       **pulse = Math.max(pulse, v \* v \* pw\[0]);**

&#x20;     **}**

&#x20;     **if (pw\[1] > 0.001) {**

&#x20;       **const v1 = Math.max(0, (dx \* f1x + dy \* f1y + dz \* f1z - 0.72) / 0.28);**

&#x20;       **const v2 = Math.max(0, (dx \* f2x + dy \* f2y + dz \* f2z - 0.72) / 0.28);**

&#x20;       **const v = Math.max(v1, v2);**

&#x20;       **pulse = Math.max(pulse, v \* v \* pw\[1]);**

&#x20;     **}**

&#x20;     **if (pw\[2] > 0.001) {**

&#x20;       **const e = dy - lat;**

&#x20;       **const v = Math.max(0, 1 - (e \* e) / 0.02);**

&#x20;       **pulse = Math.max(pulse, v \* v \* pw\[2]);**

&#x20;     **}**

&#x20;     **if (pw\[3] > 0.001) {**

&#x20;       **let dd = Math.abs(n - h3); if (dd > N - dd) dd = N - dd;**

&#x20;       **const v = Math.max(0, 1 - dd / 22);**

&#x20;       **pulse = Math.max(pulse, v \* v \* pw\[3]);**

&#x20;     **}**

&#x20;     **const l = Math.max(lit\[n] \* decay, pulse \* P.gain);**

&#x20;     **lit\[n] = l;**



&#x20;     **/\* per-dot appearance: top dots first, bottom collapse first \*/**

&#x20;     **const ki = clamp01(P.k \* (1 + S) - S \* u);**

&#x20;     **if (ki <= 0.001) { SC\[n] = -1; continue; }**

&#x20;     **const eo = E.out(ki), kk = eo \* P.pop;**



&#x20;     **const x1 = dx \* cyw + dz \* syw, z1 = -dx \* syw + dz \* cyw;**

&#x20;     **const y2 = dy \* CP - z1 \* SP, z2 = dy \* SP + z1 \* CP;**

&#x20;     **const f = 2.8 / (2.8 - z2), depth = (z2 + 1) / 2;**

&#x20;     **let ox = x1 \* ORB\_R \* kk \* f, oy = -y2 \* ORB\_R \* kk \* f;**

&#x20;     **if (swirlK > 0.001) {**

&#x20;       **const sw = (1 - ki) \* swirlK, cc = Math.cos(sw), ss = Math.sin(sw);**

&#x20;       **const tx = ox \* cc - oy \* ss;**

&#x20;       **oy = ox \* ss + oy \* cc;**

&#x20;       **ox = tx;**

&#x20;     **}**



&#x20;     **const g = clamp01((P.sweep \* 1.4 - u) / 0.4);**

&#x20;     **let a = 0.1 + 0.035 \* Math.sin(DS\[n] + time \* 1.6) \* (1 - g) + 0.32 \* depth \* depth + 0.75 \* l \* (1 - g) + g \* (0.55 + 0.4 \* depth) + 2 \* g \* (1 - g);**

&#x20;     **a = Math.max(a, P.floor \* (0.7 + 0.3 \* depth));**

&#x20;     **if (a > 1) a = 1;**

&#x20;     **a \*= eo \* P.alpha;**



&#x20;     **SX\[n] = C0 + ox;**

&#x20;     **SY\[n] = C0 + oy;**

&#x20;     **SD\[n] = depth;**

&#x20;     **SR\[n] = (1.15 \* (0.45 + 0.75 \* depth) \* f + 0.9 \* l + g \* 0.25) \* (1 + P.rad) \* (0.4 + 0.6 \* eo);**

&#x20;     **const ai = Math.round(a \* A\_STEPS), gi = Math.round(g \* G\_STEPS);**

&#x20;     **SC\[n] = ai <= 0 ? -1 : gi \* (A\_STEPS + 1) + ai;**

&#x20;   **}**



&#x20;   **/\* two passes: back half first, then front half \*/**

&#x20;   **for (let pass = 0; pass < 2; pass++) {**

&#x20;     **for (let n = 0; n < N; n++) {**

&#x20;       **const c = SC\[n];**

&#x20;       **if (c < 0) continue;**

&#x20;       **if ((SD\[n] >= 0.5) !== (pass === 1)) continue;**

&#x20;       **ctx.fillStyle = COLORS\[c];**

&#x20;       **ctx.beginPath();**

&#x20;       **ctx.arc(SX\[n], SY\[n], SR\[n], 0, TAU);**

&#x20;       **ctx.fill();**

&#x20;     **}**

&#x20;   **}**

&#x20; **};**



&#x20; **const frame = (now: number) => {**

&#x20;   **raf = 0;**

&#x20;   **if (dead) return;**

&#x20;   **const dt = isReduced() ? 0 : Math.max(0, Math.min(0.05, (now - last) / 1000)) \* getSpeed();**

&#x20;   **last = now;**

&#x20;   **draw(dt);**

&#x20;   **if (P.alpha > 0.002) raf = requestAnimationFrame(frame);**

&#x20;   **else ctx.clearRect(0, 0, CANVAS, CANVAS);**

&#x20; **};**



&#x20; **const ensure = () => {**

&#x20;   **if (raf || dead || P.alpha <= 0.002) return;**

&#x20;   **last = performance.now();**

&#x20;   **raf = requestAnimationFrame(frame);**

&#x20; **};**



&#x20; **const destroy = () => {**

&#x20;   **dead = true;**

&#x20;   **if (raf) cancelAnimationFrame(raf);**

&#x20;   **raf = 0;**

&#x20; **};**



&#x20; **return { P, ensure, reset, destroy };**

**}**



**/\* ───────────────────────────── runtime ───────────────────────────── \*/**

**interface UI {**

&#x20; **setPhase(p: Phase): void;**

&#x20; **swapLabel(name: string): void;**

&#x20; **resetLabel(): void;**

&#x20; **setAnswer(s: string): void;**

&#x20; **clearInput(): void;**

&#x20; **live(s: string): void;**

&#x20; **lock(on: boolean): void;**

&#x20; **idleReady(): void;**

&#x20; **focusAnswer(): void;**

**}**

**interface Env {**

&#x20; **root: HTMLElement; mover: HTMLElement; actor: HTMLElement; form: HTMLElement; ghosts: HTMLElement\[];**

&#x20; **canvas: HTMLCanvasElement; pulse: HTMLElement; status: HTMLElement;**

&#x20; **getBody: () => HTMLElement | null;**

&#x20; **ui: UI; getSpeed: () => number; isReduced: () => boolean;**

**}**

**interface RunCfg { onSubmit: (text: string) => Promise<string> | string; minThink: number }**

**interface Runtime {**

&#x20; **start(text: string, cfg: RunCfg): boolean;**

&#x20; **escape(): void;**

&#x20; **reset(): void;**

&#x20; **hard(): void;**

&#x20; **home(): void;**

&#x20; **busy(): boolean;**

&#x20; **destroy(): void;**

**}**

**interface Sample { t: number; x: number; y: number; d: number }**



**function sampleAt(h: Sample\[], t: number, out: Sample) {**

&#x20; **const n = h.length;**

&#x20; **const copy = (s: Sample) => { out.x = s.x; out.y = s.y; out.d = s.d; };**

&#x20; **if (n === 0) { out.x = 0; out.y = 0; out.d = 0; return; }**

&#x20; **if (t <= h\[0].t) return copy(h\[0]);**

&#x20; **for (let i = n - 1; i > 0; i--) {**

&#x20;   **const a = h\[i - 1], b = h\[i];**

&#x20;   **if (t >= a.t) {**

&#x20;     **if (t >= b.t) return copy(b);**

&#x20;     **const k = (t - a.t) / (b.t - a.t || 1);**

&#x20;     **out.x = lerp(a.x, b.x, k); out.y = lerp(a.y, b.y, k); out.d = lerp(a.d, b.d, k);**

&#x20;     **return;**

&#x20;   **}**

&#x20; **}**

&#x20; **copy(h\[n - 1]);**

**}**



**function createRuntime(env: Env): Runtime {**

&#x20; **const { actor, mover, root, status, pulse, ghosts, form } = env;**

&#x20; **const life = new AbortController();**

&#x20; **const geo: Geo = { pw: pillW(), cw: cardW(), H: homeDy(), dir: -1 };**

&#x20; **const orb = createOrb(env.canvas, env.getSpeed, env.isReduced);**

&#x20; **const vals: Record<string, number> = {};**

&#x20; **const dirty = new Set<string>();**

&#x20; **const CH: Record<string, (v: number) => void> = {};**



&#x20; **let current: AbortController | null = null;**

&#x20; **let idleCtl: AbortController | null = null;**

&#x20; **let busy = false, idling = false, epoch = 0;**

&#x20; **let curX = 0, curY = 0, curD = BALL\_SMALL, trailVis = 0, ghostsShown = false;**

&#x20; **let wStagger = 45, wDur = 320;**

&#x20; **const hist: Sample\[] = \[];**

&#x20; **const tmp: Sample = { t: 0, x: 0, y: 0, d: 0 };**



&#x20; **const child = () => {**

&#x20;   **const ac = new AbortController();**

&#x20;   **if (life.signal.aborted) ac.abort();**

&#x20;   **else life.signal.addEventListener("abort", () => ac.abort(), { once: true });**

&#x20;   **return ac;**

&#x20; **};**



&#x20; **/\* ── flight path + comet trail ── \*/**

&#x20; **const renderTrail = () => {**

&#x20;   **if (trailVis <= 0.001) {**

&#x20;     **if (ghostsShown) { ghosts.forEach((g) => (g.style.opacity = "0")); ghostsShown = false; }**

&#x20;     **return;**

&#x20;   **}**

&#x20;   **ghostsShown = true;**

&#x20;   **const now = performance.now();**

&#x20;   **for (let i = 0; i < ghosts.length; i++) {**

&#x20;     **sampleAt(hist, now - (i + 1) \* 45, tmp);**

&#x20;     **const k = (tmp.d \* (1 - 0.08 \* (i + 1))) / 100;**

&#x20;     **const g = ghosts\[i];**

&#x20;     **g.style.transform = `translate3d(${(tmp.x - curX).toFixed(2)}px,${(tmp.y - curY).toFixed(2)}px,0) translate(-50%,-50%) scale(${k.toFixed(3)})`;**

&#x20;     **g.style.opacity = (0.28 \* Math.pow(1 - i / 6, 1.5) \* trailVis).toFixed(3);**

&#x20;   **}**

&#x20; **};**



&#x20; **const applyPath = () => {**

&#x20;   **const u = vals.u ?? 0, H = geo.H;**

&#x20;   **curX = bez(u, 0, geo.dir \* 0.3 \* H, 0);**

&#x20;   **curY = bez(u, H, 0.6 \* H, 0) + (vals.yOff ?? 0);**

&#x20;   **mover.style.transform = `translate3d(${curX.toFixed(2)}px,${curY.toFixed(2)}px,0)`;**

&#x20;   **const now = performance.now();**

&#x20;   **hist.push({ t: now, x: curX, y: curY, d: curD });**

&#x20;   **while (hist.length > 2 \&\& hist\[0].t < now - 500) hist.shift();**

&#x20;   **renderTrail();**

&#x20; **};**



&#x20; **/\* ── answer words ── \*/**

&#x20; **const applyWords = (v: number) => {**

&#x20;   **const body = env.getBody();**

&#x20;   **if (!body) return;**

&#x20;   **const nodes = body.querySelectorAll<HTMLElement>(".mo-w");**

&#x20;   **const total = (nodes.length - 1) \* wStagger + wDur;**

&#x20;   **const time = v \* total;**

&#x20;   **const reduced = env.isReduced();**

&#x20;   **nodes.forEach((el, i) => {**

&#x20;     **const p = E.out(clamp01((time - i \* wStagger) / wDur));**

&#x20;     **el.style.opacity = fmt(p);**

&#x20;     **el.style.transform = p >= 0.999 || reduced ? "none" : `translateY(${fmt((1 - p) \* 4)}px)`;**

&#x20;     **el.style.filter = p >= 0.999 || reduced ? "none" : `blur(${fmt((1 - p) \* 4)}px)`;**

&#x20;   **});**

&#x20; **};**



&#x20; **/\* ── channels ── \*/**

&#x20; **\["oGlow", "oHalo", "oPill", "oBall", "oGreen", "oCard", "oRing", "oInput", "oAur", "gs", "cs", "hOp", "dotS", "bloom"].forEach((n) => {**

&#x20;   **CH\[n] = (v) => actor.style.setProperty("--" + n, fmt(v));**

&#x20; **});**

&#x20; **\["w", "h", "r"].forEach((n) => {**

&#x20;   **CH\[n] = (v) => {**

&#x20;     **actor.style.setProperty("--" + n, fmt(v) + "px");**

&#x20;     **if (n === "w") curD = v;**

&#x20;   **};**

&#x20; **});**

&#x20; **CH.inScale = (v) => {**

&#x20;   **actor.style.setProperty("--inScale", fmt(v));**

&#x20;   **form.style.filter = v >= 0.999 ? "none" : `blur(${fmt((1 - v) \* 15)}px)`;**

&#x20; **};**

&#x20; **CH.sOp = (v) => status.style.setProperty("--sOp", fmt(v));**

&#x20; **CH.sTy = (v) => status.style.setProperty("--sTy", fmt(v));**

&#x20; **CH.cHalo = (v) => root.style.setProperty("--oCenter", fmt(v));**

&#x20; **CH.u = () => applyPath();**

&#x20; **CH.yOff = () => applyPath();**

&#x20; **CH.trail = (v) => { trailVis = v; renderTrail(); };**

&#x20; **CH.pulse = (v) => {**

&#x20;   **if (v < 0) { pulse.style.opacity = "0"; return; }**

&#x20;   **pulse.style.opacity = fmt(0.5 \* (1 - v));**

&#x20;   **pulse.style.transform = `scale(${fmt(1 + v)})`;**

&#x20; **};**

&#x20; **CH.wp = applyWords;**

&#x20; **ORB\_KEYS.forEach((name) => {**

&#x20;   **CH\["orb." + name] = (v) => {**

&#x20;     **orb.P\[name] = v;**

&#x20;     **if (name === "alpha") orb.ensure();**

&#x20;   **};**

&#x20; **});**



&#x20; **const set = (ch: string, v: number) => { vals\[ch] = v; dirty.add(ch); };**

&#x20; **const flush = () => { dirty.forEach((ch) => CH\[ch]?.(vals\[ch])); dirty.clear(); };**

&#x20; **const setNow = (ch: string, v: number) => { vals\[ch] = v; CH\[ch]?.(v); };**

&#x20; **const resetChannels = () => {**

&#x20;   **setNow("w", geo.pw);**

&#x20;   **for (const ch of Object.keys(INIT)) setNow(ch, INIT\[ch]);**

&#x20; **};**



&#x20; **/\* ── timeline engine ── \*/**

&#x20; **const play = (tracks: Track\[], sig: AbortSignal) =>**

&#x20;   **new Promise<void>((res) => {**

&#x20;     **if (sig.aborted) return res();**

&#x20;     **const end = tracks.reduce((m, k) => Math.max(m, k.t1), 0);**

&#x20;     **const done = new Set<Track>();**

&#x20;     **let raf = 0, t = 0, last = performance.now();**

&#x20;     **const onAbort = () => { cancelAnimationFrame(raf); res(); };**

&#x20;     **const finish = () => { sig.removeEventListener("abort", onAbort); res(); };**

&#x20;     **const step = (now: number) => {**

&#x20;       **const dt = Math.max(0, Math.min(100, now - last));**

&#x20;       **last = now;**

&#x20;       **t += dt \* env.getSpeed();**

&#x20;       **for (const k of tracks) {**

&#x20;         **if (done.has(k) || t < k.t0) continue;**

&#x20;         **const p = Math.min(1, (t - k.t0) / Math.max(1, k.t1 - k.t0));**

&#x20;         **set(k.ch, k.from + (k.to - k.from) \* (k.ease ?? E.io)(p));**

&#x20;         **if (p === 1) done.add(k);**

&#x20;       **}**

&#x20;       **flush(); // one DOM write pass per frame**

&#x20;       **if (t >= end) finish(); else raf = requestAnimationFrame(step);**

&#x20;     **};**

&#x20;     **sig.addEventListener("abort", onAbort, { once: true });**

&#x20;     **raf = requestAnimationFrame(step);**

&#x20;   **});**



&#x20; **/\* ── thinking labels ── \*/**

&#x20; **const labelLoop = async (sig: AbortSignal, ctl: { stop: boolean }) => {**

&#x20;   **let i = 0;**

&#x20;   **for (;;) {**

&#x20;     **await sleep(1150 / env.getSpeed(), sig);**

&#x20;     **if (sig.aborted || ctl.stop) return;**

&#x20;     **i = (i + 1) % COPY.labels.length;**

&#x20;     **orb.P.prog = i % 4;**

&#x20;     **env.ui.swapLabel(COPY.labels\[i]);**

&#x20;   **}**

&#x20; **};**



&#x20; **/\* ── orchestrator ── \*/**

&#x20; **const run = async (text: string, sig: AbortSignal, cfg: RunCfg) => {**

&#x20;   **const reduced = env.isReduced();**

&#x20;   **const go = async (tracks: Track\[]) => {**

&#x20;     **await play(tracks, sig);**

&#x20;     **if (sig.aborted) throw ABORT;**

&#x20;   **};**

&#x20;   **try {**

&#x20;     **env.ui.setPhase("launch");**

&#x20;     **hist.length = 0;**

&#x20;     **if (!reduced) {**

&#x20;       **await go(launchTracks(geo));**

&#x20;       **setNow("r", ORB\_D / 2);**

&#x20;       **env.ui.setPhase("assemble");**

&#x20;       **await go(ASSEMBLE);**

&#x20;     **} else {**

&#x20;       **await go(R\_OUT);**

&#x20;       **setNow("u", 1); setNow("w", ORB\_D); setNow("h", ORB\_D); setNow("r", ORB\_D / 2);**

&#x20;       **setNow("sTy", 0); setNow("orb.k", 1); setNow("orb.spin", 0);**

&#x20;       **env.ui.setPhase("assemble");**

&#x20;       **await go(R\_IN);**

&#x20;     **}**



&#x20;     **/\* think — until the answer settled AND the minimum time elapsed \*/**

&#x20;     **env.ui.setPhase("think");**

&#x20;     **env.ui.live(COPY.labels\[0]);**

&#x20;     **const ctl = { stop: false };**

&#x20;     **void labelLoop(sig, ctl);**

&#x20;     **const t0 = performance.now();**

&#x20;     **const pending = Promise.resolve()**

&#x20;       **.then(() => cfg.onSubmit(text))**

&#x20;       **.then((b) => (typeof b === "string" \&\& b.trim() ? b : COPY.answerBody), () => COPY.answerBody);**

&#x20;     **const got = await abortable(pending, sig);**

&#x20;     **if (sig.aborted) throw ABORT;**

&#x20;     **const body = got ?? COPY.answerBody;**

&#x20;     **await sleep(cfg.minThink / env.getSpeed() - (performance.now() - t0), sig);**

&#x20;     **ctl.stop = true;**

&#x20;     **if (sig.aborted) throw ABORT;**



&#x20;     **const words = body.split(/\\s+/).filter(Boolean);**

&#x20;     **const n = Math.max(1, words.length);**



&#x20;     **if (!reduced) {**

&#x20;       **env.ui.setPhase("resolve");**

&#x20;       **env.ui.swapLabel(COPY.done);**

&#x20;       **await go(RESOLVE);**



&#x20;       **env.ui.setPhase("condense");**

&#x20;       **await go(CONDENSE);**



&#x20;       **env.ui.setPhase("unfold");**

&#x20;       **wDur = 320;**

&#x20;       **wStagger = n > 1 ? Math.min(45, 280 / (n - 1)) : 0;**

&#x20;       **env.ui.setAnswer(body);**

&#x20;       **await go(unfoldTracks(geo, (n - 1) \* wStagger + wDur));**

&#x20;     **} else {**

&#x20;       **env.ui.setPhase("resolve");**

&#x20;       **env.ui.swapLabel(COPY.done);**

&#x20;       **await go(R\_RESOLVE);**

&#x20;       **await sleep(350 / env.getSpeed(), sig);**

&#x20;       **if (sig.aborted) throw ABORT;**



&#x20;       **env.ui.setPhase("condense");**

&#x20;       **setNow("gs", 1);**

&#x20;       **await go(R\_CONDENSE);**



&#x20;       **env.ui.setPhase("unfold");**

&#x20;       **wDur = 250;**

&#x20;       **wStagger = 0;**

&#x20;       **env.ui.setAnswer(body);**

&#x20;       **await go(R\_GREEN\_OUT);**

&#x20;       **setNow("w", geo.cw); setNow("h", CARD\_H); setNow("r", 20); setNow("dotS", 1);**

&#x20;       **await go(rCardIn(wDur));**

&#x20;     **}**



&#x20;     **env.ui.setPhase("answered");**

&#x20;     **env.ui.live("Answer ready: " + body);**

&#x20;     **env.ui.focusAnswer();**

&#x20;   **} catch (e) {**

&#x20;     **if (e === ABORT) return;**

&#x20;     **hard();**

&#x20;   **}**

&#x20; **};**



&#x20; **/\* ── return to the idle pill ── \*/**

&#x20; **const toIdle = async (kind: "reset" | "esc") => {**

&#x20;   **if (idling) return;**

&#x20;   **idling = true;**

&#x20;   **const my = ++epoch;**

&#x20;   **const ac = child();**

&#x20;   **idleCtl = ac;**

&#x20;   **const sig = ac.signal;**

&#x20;   **const outMs = kind === "reset" ? 240 : 200;**

&#x20;   **const inMs = kind === "reset" ? 420 : 200;**

&#x20;   **env.ui.setPhase("reset");**



&#x20;   **const out: Track\[] = \[T("cHalo", vals.cHalo ?? 0, 0, 0, outMs, E.out)];**

&#x20;   **for (const ch of FADE) {**

&#x20;     **const v = vals\[ch] ?? 0;**

&#x20;     **if (v > 0.001) out.push(T(ch, v, 0, 0, outMs, E.out));**

&#x20;   **}**

&#x20;   **if (kind === "reset") out.push(T("cs", 1, 0.98, 0, outMs, E.out));**

&#x20;   **await play(out, sig);**

&#x20;   **if (sig.aborted || my !== epoch) return;**



&#x20;   **setNow("pulse", -1);**

&#x20;   **env.ui.setAnswer("");**

&#x20;   **env.ui.resetLabel();**

&#x20;   **env.ui.clearInput();**

&#x20;   **orb.reset();**

&#x20;   **hist.length = 0;**

&#x20;   **geo.pw = pillW(); geo.cw = cardW(); geo.H = homeDy();**

&#x20;   **resetChannels();**

&#x20;   **const pillCh = \["oPill", "oInput", "oGlow", "oAur", "oRing"];**

&#x20;   **pillCh.forEach((ch) => setNow(ch, 0));**

&#x20;   **setNow("yOff", kind === "reset" ? 8 : 0);**

&#x20;   **const inn: Track\[] = pillCh.map((ch) => T(ch, 0, 1, 0, inMs, E.out));**

&#x20;   **if (kind === "reset") inn.push(T("yOff", 8, 0, 0, inMs, E.out));**

&#x20;   **await play(inn, sig);**

&#x20;   **if (sig.aborted || my !== epoch) return;**



&#x20;   **resetChannels();**

&#x20;   **current = null; idleCtl = null; busy = false; idling = false;**

&#x20;   **env.ui.lock(false);**

&#x20;   **env.ui.setPhase("idle");**

&#x20;   **env.ui.idleReady();**

&#x20; **};**



&#x20; **function hard() {**

&#x20;   **epoch++;**

&#x20;   **current?.abort(); current = null;**

&#x20;   **idleCtl?.abort(); idleCtl = null;**

&#x20;   **orb.reset();**

&#x20;   **hist.length = 0;**

&#x20;   **env.ui.setAnswer("");**

&#x20;   **env.ui.resetLabel();**

&#x20;   **geo.pw = pillW(); geo.cw = cardW(); geo.H = homeDy();**

&#x20;   **resetChannels();**

&#x20;   **setNow("pulse", -1);**

&#x20;   **busy = false; idling = false;**

&#x20;   **env.ui.lock(false);**

&#x20;   **env.ui.setPhase("idle");**

&#x20;   **env.ui.idleReady();**

&#x20; **}**



&#x20; **resetChannels();**



&#x20; **return {**

&#x20;   **start(text, cfg) {**

&#x20;     **if (busy) return false;**

&#x20;     **busy = true;**

&#x20;     **geo.pw = pillW(); geo.cw = cardW(); geo.H = homeDy(); // snapshot once, never read layout in frames**

&#x20;     **geo.dir = -geo.dir;**

&#x20;     **orb.reset();**

&#x20;     **setNow("u", 0);**

&#x20;     **const ac = child();**

&#x20;     **current = ac;**

&#x20;     **env.ui.lock(true);**

&#x20;     **void run(text, ac.signal, cfg);**

&#x20;     **return true;**

&#x20;   **},**

&#x20;   **escape() {**

&#x20;     **if (!busy || idling) return;**

&#x20;     **current?.abort();**

&#x20;     **void toIdle("esc");**

&#x20;   **},**

&#x20;   **reset() {**

&#x20;     **if (!busy || idling) return;**

&#x20;     **void toIdle("reset");**

&#x20;   **},**

&#x20;   **hard,**

&#x20;   **home() {**

&#x20;     **if (busy) return;**

&#x20;     **geo.pw = pillW(); geo.cw = cardW(); geo.H = homeDy();**

&#x20;     **setNow("w", geo.pw);**

&#x20;     **setNow("u", 0);**

&#x20;   **},**

&#x20;   **busy: () => busy,**

&#x20;   **destroy() {**

&#x20;     **life.abort();**

&#x20;     **orb.destroy();**

&#x20;   **},**

&#x20; **};**

**}**



**/\* ───────────────────────────── component ───────────────────────────── \*/**

**const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;**



**export default function MorphOrb(props: MorphOrbProps) {**

&#x20; **const \[phase, setPhaseState] = useState<Phase>("idle");**

&#x20; **const \[value, setValue] = useState("");**

&#x20; **const \[lbl, setLbl] = useState<{ cur: string; prev: string | null; n: number }>({ cur: COPY.labels\[0], prev: null, n: 0 });**

&#x20; **const \[answer, setAnswer] = useState("");**

&#x20; **const \[dbgSpeed, setDbgSpeed] = useState(1);**

&#x20; **const \[debug] = useState(() => typeof window !== "undefined" \&\& /\[?\&]debug(?:\[=\&]|$)/.test(window.location.search));**



&#x20; **const rootRef = useRef<HTMLDivElement>(null);**

&#x20; **const moverRef = useRef<HTMLDivElement>(null);**

&#x20; **const actorRef = useRef<HTMLDivElement>(null);**

&#x20; **const formRef = useRef<HTMLFormElement>(null);**

&#x20; **const inputRef = useRef<HTMLInputElement>(null);**

&#x20; **const canvasRef = useRef<HTMLCanvasElement>(null);**

&#x20; **const pulseRef = useRef<HTMLDivElement>(null);**

&#x20; **const statusRef = useRef<HTMLDivElement>(null);**

&#x20; **const answerRef = useRef<HTMLDivElement>(null);**

&#x20; **const bodyRef = useRef<HTMLParagraphElement>(null);**

&#x20; **const liveRef = useRef<HTMLDivElement>(null);**

&#x20; **const ghostRefs = useRef<(HTMLSpanElement | null)\[]>(\[]);**



&#x20; **const propsRef = useRef(props);**

&#x20; **propsRef.current = props;**

&#x20; **const speedRef = useRef(1);**

&#x20; **speedRef.current = Math.max(0.05, (props.speed ?? 1) \* dbgSpeed);**

&#x20; **const phaseRef = useRef<Phase>("idle");**

&#x20; **const reducedRef = useRef(false);**

&#x20; **const rtRef = useRef<Runtime | null>(null);**

&#x20; **const lastTextRef = useRef("");**

&#x20; **const timers = useRef<{ typing?: number; shake?: number; flash?: number }>({});**



&#x20; **useIsoLayoutEffect(() => {**

&#x20;   **const root = rootRef.current, mover = moverRef.current, actor = actorRef.current, canvas = canvasRef.current;**

&#x20;   **const pulse = pulseRef.current, status = statusRef.current, form = formRef.current;**

&#x20;   **const ghosts = ghostRefs.current.filter((g): g is HTMLSpanElement => !!g);**

&#x20;   **if (!root || !mover || !actor || !canvas || !pulse || !status || !form) return;**



&#x20;   **const mq = window.matchMedia("(prefers-reduced-motion: reduce)");**

&#x20;   **reducedRef.current = mq.matches;**

&#x20;   **const onMq = (e: MediaQueryListEvent) => { reducedRef.current = e.matches; };**

&#x20;   **mq.addEventListener("change", onMq);**



&#x20;   **const rt = createRuntime({**

&#x20;     **root, mover, actor, form, ghosts, canvas, pulse, status,**

&#x20;     **getBody: () => bodyRef.current,**

&#x20;     **getSpeed: () => speedRef.current,**

&#x20;     **isReduced: () => reducedRef.current,**

&#x20;     **ui: {**

&#x20;       **setPhase: (p) => { phaseRef.current = p; setPhaseState(p); },**

&#x20;       **swapLabel: (name) => setLbl((l) => (l.cur === name ? l : { cur: name, prev: l.cur, n: l.n + 1 })),**

&#x20;       **resetLabel: () => setLbl((l) => ({ cur: COPY.labels\[0], prev: null, n: l.n + 1 })),**

&#x20;       **setAnswer: (s) => setAnswer(s),**

&#x20;       **clearInput: () => setValue(""),**

&#x20;       **live: (s) => { if (liveRef.current) liveRef.current.textContent = s; },**

&#x20;       **lock: (on) => { form.toggleAttribute("inert", on); },**

&#x20;       **idleReady: () => { inputRef.current?.focus({ preventScroll: true }); },**

&#x20;       **focusAnswer: () => { answerRef.current?.focus({ preventScroll: true }); },**

&#x20;     **},**

&#x20;   **});**

&#x20;   **rtRef.current = rt;**



&#x20;   **const onKey = (e: KeyboardEvent) => {**

&#x20;     **if (e.key === "Escape" \&\& phaseRef.current !== "idle" \&\& phaseRef.current !== "reset") {**

&#x20;       **e.preventDefault();**

&#x20;       **rt.escape();**

&#x20;     **}**

&#x20;   **};**

&#x20;   **const onResize = () => {**

&#x20;     **if (phaseRef.current === "idle" \&\& !rt.busy()) rt.home();**

&#x20;   **};**

&#x20;   **window.addEventListener("keydown", onKey);**

&#x20;   **window.addEventListener("resize", onResize);**

&#x20;   **inputRef.current?.focus({ preventScroll: true });**



&#x20;   **return () => {**

&#x20;     **window.removeEventListener("keydown", onKey);**

&#x20;     **window.removeEventListener("resize", onResize);**

&#x20;     **mq.removeEventListener("change", onMq);**

&#x20;     **window.clearTimeout(timers.current.typing);**

&#x20;     **window.clearTimeout(timers.current.shake);**

&#x20;     **window.clearTimeout(timers.current.flash);**

&#x20;     **rt.destroy();**

&#x20;     **rtRef.current = null;**

&#x20;   **};**

&#x20; **}, \[]);**



&#x20; **const defaultSubmit = () =>**

&#x20;   **new Promise<string>((res) => {**

&#x20;     **window.setTimeout(() => res(COPY.answerBody), 4600 / speedRef.current);**

&#x20;   **});**

&#x20; **const makeCfg = (): RunCfg => ({**

&#x20;   **onSubmit: propsRef.current.onSubmit ?? defaultSubmit,**

&#x20;   **minThink: propsRef.current.minThinkMs ?? 3450,**

&#x20; **});**



&#x20; **const shake = () => {**

&#x20;   **const a = actorRef.current;**

&#x20;   **if (!a) return;**

&#x20;   **a.removeAttribute("data-shake");**

&#x20;   **void a.offsetWidth;**

&#x20;   **a.setAttribute("data-shake", "");**

&#x20;   **a.setAttribute("data-flash", "");**

&#x20;   **window.clearTimeout(timers.current.shake);**

&#x20;   **window.clearTimeout(timers.current.flash);**

&#x20;   **timers.current.shake = window.setTimeout(() => a.removeAttribute("data-shake"), 260);**

&#x20;   **timers.current.flash = window.setTimeout(() => a.removeAttribute("data-flash"), 200);**

&#x20; **};**



&#x20; **const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {**

&#x20;   **setValue(e.target.value);**

&#x20;   **const a = actorRef.current;**

&#x20;   **if (!a) return;**

&#x20;   **a.setAttribute("data-typing", "");**

&#x20;   **window.clearTimeout(timers.current.typing);**

&#x20;   **timers.current.typing = window.setTimeout(() => a.removeAttribute("data-typing"), 300);**

&#x20; **};**



&#x20; **const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {**

&#x20;   **if (e.key === "Enter" \&\& (e.shiftKey || e.nativeEvent.isComposing)) e.preventDefault();**

&#x20; **};**



&#x20; **const onFormSubmit = (e: React.FormEvent) => {**

&#x20;   **e.preventDefault();**

&#x20;   **const rt = rtRef.current;**

&#x20;   **if (!rt || rt.busy() || phaseRef.current !== "idle") return;**

&#x20;   **const text = value.trim();**

&#x20;   **if (!text) { shake(); return; }**

&#x20;   **lastTextRef.current = text;**

&#x20;   **rt.start(text, makeCfg());**

&#x20; **};**



&#x20; **const onReset = () => {**

&#x20;   **if (phaseRef.current === "answered") rtRef.current?.reset();**

&#x20; **};**



&#x20; **const replay = () => {**

&#x20;   **const rt = rtRef.current;**

&#x20;   **if (!rt) return;**

&#x20;   **const text = lastTextRef.current || "hello";**

&#x20;   **lastTextRef.current = text;**

&#x20;   **rt.hard();**

&#x20;   **setValue(text);**

&#x20;   **window.requestAnimationFrame(() => { rt.start(text, makeCfg()); });**

&#x20; **};**



&#x20; **const ready = value.trim().length > 0;**

&#x20; **const words = answer.split(/\\s+/).filter(Boolean);**



&#x20; **const labelInner = (name: string) =>**

&#x20;   **name === COPY.done ? (**

&#x20;     **<span className="mo-lab-done">{name}</span>**

&#x20;   **) : (**

&#x20;     **<>**

&#x20;       **<span className="mo-lab-t">{name}</span>**

&#x20;       **<span className="mo-dots" aria-hidden="true"><i /><i /><i /></span>**

&#x20;     **</>**

&#x20;   **);**



&#x20; **return (**

&#x20;   **<div className="mo-root" data-phase={phase} ref={rootRef}>**

&#x20;     **<div className="mo-bg" aria-hidden="true" />**

&#x20;     **<div className="mo-halo" aria-hidden="true" />**



&#x20;     **<div className="mo-mover" ref={moverRef}>**

&#x20;       **{Array.from({ length: 6 }).map((\_, i) => (**

&#x20;         **<span key={i} className="mo-trail" aria-hidden="true" ref={(el) => { ghostRefs.current\[i] = el; }} />**

&#x20;       **))}**



&#x20;       **<div className="mo-actor" ref={actorRef}>**

&#x20;         **<div className="mo-underglow" aria-hidden="true" />**

&#x20;         **<div className="mo-halo-green" aria-hidden="true" />**

&#x20;         **<div className="mo-surface" aria-hidden="true">**

&#x20;           **<div className="mo-aurora"><i /><i /><i /><i /></div>**

&#x20;         **</div>**

&#x20;         **<div className="mo-ball" aria-hidden="true" />**

&#x20;         **<div className="mo-green" aria-hidden="true" />**

&#x20;         **<div className="mo-card" aria-hidden="true" />**

&#x20;         **<div className="mo-ring" aria-hidden="true" />**



&#x20;         **<form className="mo-input" ref={formRef} onSubmit={onFormSubmit} autoComplete="off">**

&#x20;           **<svg className="mo-spark" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">**

&#x20;             **<path d="M10 3.5l1.7 4.8 4.8 1.7-4.8 1.7L10 16.5l-1.7-4.8L3.5 10l4.8-1.7L10 3.5z" />**

&#x20;             **<path d="M18 14.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z" />**

&#x20;           **</svg>**

&#x20;           **<input**

&#x20;             **ref={inputRef}**

&#x20;             **className="mo-field"**

&#x20;             **type="text"**

&#x20;             **value={value}**

&#x20;             **maxLength={200}**

&#x20;             **placeholder={COPY.placeholder}**

&#x20;             **aria-label="Ask anything"**

&#x20;             **spellCheck={false}**

&#x20;             **onChange={onChange}**

&#x20;             **onKeyDown={onKeyDown}**

&#x20;           **/>**

&#x20;           **<button type="submit" className="mo-send" aria-label={COPY.send} data-ready={ready ? "" : undefined}>**

&#x20;             **<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">**

&#x20;               **<path d="M12 19V5" />**

&#x20;               **<path d="M5.5 11.5L12 5l6.5 6.5" />**

&#x20;             **</svg>**

&#x20;           **</button>**

&#x20;         **</form>**



&#x20;         **<canvas className="mo-orb" ref={canvasRef} aria-hidden="true" />**

&#x20;         **<div className="mo-pulse" ref={pulseRef} aria-hidden="true" />**



&#x20;         **<div className="mo-answer" ref={answerRef} tabIndex={-1} role="group" aria-label={COPY.answerTitle}>**

&#x20;           **<div className="mo-a-head">**

&#x20;             **<i className="mo-a-dot" aria-hidden="true" />**

&#x20;             **<span>{COPY.answerTitle}</span>**

&#x20;           **</div>**

&#x20;           **<p className="mo-a-body" ref={bodyRef}>**

&#x20;             **{words.map((w, i) => (**

&#x20;               **<React.Fragment key={i}>**

&#x20;                 **<span className="mo-w">{w}</span>{" "}**

&#x20;               **</React.Fragment>**

&#x20;             **))}**

&#x20;           **</p>**

&#x20;         **</div>**

&#x20;       **</div>**

&#x20;     **</div>**



&#x20;     **<div className="mo-status" ref={statusRef} aria-hidden="true">**

&#x20;       **{lbl.prev !== null \&\& (**

&#x20;         **<span key={"p" + lbl.n} className="mo-lab mo-out">{labelInner(lbl.prev)}</span>**

&#x20;       **)}**

&#x20;       **<span key={"c" + lbl.n} className="mo-lab mo-in">{labelInner(lbl.cur)}</span>**

&#x20;     **</div>**



&#x20;     **<button type="button" className="mo-reset" onClick={onReset}>{COPY.reset}</button>**



&#x20;     **<div className="mo-live" ref={liveRef} role="status" aria-live="polite" />**



&#x20;     **{debug \&\& (**

&#x20;       **<div className="mo-debug">**

&#x20;         **<span className="mo-chip">{phase}</span>**

&#x20;         **<label>**

&#x20;           **<span>{dbgSpeed.toFixed(2)}×</span>**

&#x20;           **<input**

&#x20;             **type="range"**

&#x20;             **min={0.25}**

&#x20;             **max={2}**

&#x20;             **step={0.05}**

&#x20;             **value={dbgSpeed}**

&#x20;             **aria-label="Speed"**

&#x20;             **onChange={(e) => setDbgSpeed(parseFloat(e.target.value))}**

&#x20;           **/>**

&#x20;         **</label>**

&#x20;         **<button type="button" onClick={replay}>Replay</button>**

&#x20;       **</div>**

&#x20;     **)}**

&#x20;   **</div>**

&#x20; **);**

**}**



**demo.tsx**

**import MorphOrb from "@/components/ui/ai-thiking-orb-and-input";**



**export default function DemoOne() {**

&#x20; **return (**

&#x20;   **<div className="flex min-h-\[450px] w-full items-center justify-center p-4">**

&#x20;     **<MorphOrb />**

&#x20;   **</div>**

&#x20; **);**

**}**

**```**



**Extend existing Tailwind 4 index.css with this code (or if project uses Tailwind 3, extend tailwind.config.js or globals.css):**

**```css**

**@import "tailwindcss";**

**@import "tw-animate-css";**





**@keyframes mo-spin {**

&#x20; **to {**

&#x20;   **--angle: 360deg;**

&#x20; **}**

**}**



**@keyframes mo-drift {**

&#x20; **from {**

&#x20;   **transform: translateX(-14%);**

&#x20; **}**

&#x20; **to {**

&#x20;   **transform: translateX(14%);**

&#x20; **}**

**}**



**@keyframes mo-shimmer {**

&#x20; **from {**

&#x20;   **background-position: 150% 0;**

&#x20; **}**

&#x20; **to {**

&#x20;   **background-position: -100% 0;**

&#x20; **}**

**}**



**@keyframes mo-dot {**

&#x20; **0%, 80%, 100% {**

&#x20;   **opacity: .25;**

&#x20; **}**

&#x20; **40% {**

&#x20;   **opacity: 1;**

&#x20; **}**

**}**



**@keyframes mo-in {**

&#x20; **from {**

&#x20;   **opacity: 0;**

&#x20;   **transform: translateY(6px);**

&#x20; **}**

&#x20; **to {**

&#x20;   **opacity: 1;**

&#x20;   **transform: none;**

&#x20; **}**

**}**



**@keyframes mo-out {**

&#x20; **from {**

&#x20;   **opacity: 1;**

&#x20;   **transform: none;**

&#x20; **}**

&#x20; **to {**

&#x20;   **opacity: 0;**

&#x20;   **transform: translateY(-6px);**

&#x20; **}**

**}**



**@keyframes mo-fade-in {**

&#x20; **from {**

&#x20;   **opacity: 0;**

&#x20; **}**

&#x20; **to {**

&#x20;   **opacity: 1;**

&#x20; **}**

**}**



**@keyframes mo-fade-out {**

&#x20; **from {**

&#x20;   **opacity: 1;**

&#x20; **}**

&#x20; **to {**

&#x20;   **opacity: 0;**

&#x20; **}**

**}**



**@keyframes mo-shake {**

&#x20; **0%, 100% {**

&#x20;   **transform: translate(-50%, -50%);**

&#x20; **}**

&#x20; **25% {**

&#x20;   **transform: translate(calc(-50% - 4px), -50%);**

&#x20; **}**

&#x20; **75% {**

&#x20;   **transform: translate(calc(-50% + 4px), -50%);**

&#x20; **}**

**}**

**```**



**Implementation Guidelines**

&#x20;**1. Analyze the component structure and identify all required dependencies**

&#x20;**2. Review the component's argumens and state**

&#x20;**3. Identify any required context providers or hooks and install them**

&#x20;**4. Questions to Ask**

&#x20;**- What data/props will be passed to this component?**

&#x20;**- Are there any specific state management requirements?**

&#x20;**- Are there any required assets (images, icons, etc.)?**

&#x20;**- What is the expected responsive behavior?**

&#x20;**- What is the best place to use this component in the app?**



**Steps to integrate**

&#x20;**0. Copy paste all the code above in the correct directories**

&#x20;**1. Install external dependencies**

&#x20;**2. Fill image assets with Unsplash stock images you know exist**

&#x20;**3. Use lucide-react icons for svgs or logos if component requires them**



