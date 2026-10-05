const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { Window } = require('happy-dom');
const html = fs.readFileSync(require('node:path').join(__dirname, '../Mind the Map.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function game({ width = 1100, height = 650, storage = {}, reduced = false } = {}) {
  const window = new Window({ url: 'http://localhost:8000', settings: {
    disableCSSFileLoading: true, disableJavaScriptFileLoading: true,
  }});
  window.document.body.innerHTML = html.match(/<body>([\s\S]*?)<script>/)[1];
  const map = window.document.getElementById('map');
  map.getBoundingClientRect = () => ({ width, height, left: 0, top: 0 });
  map.setPointerCapture = () => {};
  window.ResizeObserver = class { observe() {} };
  window.matchMedia = () => ({ matches: reduced });
  let time = 0, id = 0;
  const frames = new Map();
  window.performance.now = () => time;
  window.requestAnimationFrame = fn => { frames.set(++id, fn); return id; };
  window.cancelAnimationFrame = id => frames.delete(id);
  for (const [key,value] of Object.entries(storage)) window.localStorage.setItem(key, value);
  const api = window.eval(script + `\n({
    stations, diagramStations, names, edges, DATA, SCHEMATIC, hops, kmBetween,
    get view(){return view}, get mode(){return mapMode}, get selected(){return selected},
    get state(){return state}, get targets(){return dailyTargets}, get dkey(){return DKEY},
    stationsNamed, current, tap, setMapMode, render, nextRound, confirmGuess,
    get practice(){return practice}, get gameMode(){return mode},
  })`);
  const flush = () => {
    for (let i=0; frames.size && i<100; i++) {
      time += 100;
      const jobs = [...frames.values()]; frames.clear(); jobs.forEach(fn=>fn(time));
    }
    assert.equal(frames.size, 0, 'animations finish');
  };
  const click = id => { window.document.getElementById(id).click(); flush(); };
  const choose = station => {
    const v = api.view;
    api.tap((station.x-v.cx)*v.s+width/2, (station.y-v.cy)*v.s+height/2);
    flush();
  };
  const snapshot = () => Object.fromEntries(Array.from({length:window.localStorage.length},(_,i)=>{
    const key = window.localStorage.key(i); return [key,window.localStorage.getItem(key)];
  }));
  flush();
  return { api, window, map, flush, click, choose, snapshot, close:()=>window.happyDOM.abort() };
}

test('every station has finite, distinct, selectable TfL diagram markers', async () => {
  const g=game();
  try {
    g.click('m-sch');
    assert.equal(g.api.mode,'dia');
    assert.equal(g.window.document.querySelector('#m-sch').getAttribute('aria-pressed'),'true');
    const seen = new Map();
    for(const station of g.api.diagramStations){
      assert.ok(Number.isFinite(station.x) && Number.isFinite(station.y));
      const point=[station.x,station.y].join(',');
      assert.ok(!seen.has(point) || seen.get(point)===station.n, `ambiguous marker: ${station.n} / ${seen.get(point)}`);
      seen.set(point,station.n);
      g.choose(station);
      assert.equal(g.api.selected.n,station.n,`select ${station.n}`);
    }
    assert.equal(new Set(g.api.diagramStations.map(s=>s.n)).size,g.api.names.length);
    const markup=g.window.document.getElementById('diagram').innerHTML;
    assert.ok(!/<(?:text|script|image|foreignObject)\b/i.test(markup));
    assert.ok(!markup.includes('--line-0'));
    assert.ok(g.window.document.querySelectorAll('#diagram path').length>100);
  } finally { await g.close(); }
});

test('TfL layout has the expected central loop and outer branches', async () => {
  const g=game();
  try {
    g.click('m-sch');
    const p=n=>g.api.stationsNamed(n)[0];
    assert.ok(p('Paddington').x<p('Baker Street').x);
    assert.ok(p('Baker Street').x<p("King's Cross St. Pancras").x);
    assert.ok(p('Baker Street').y<p('Victoria').y);
    assert.ok(p('Liverpool Street').x>p('Oxford Circus').x);
    assert.ok(p('Epping').y<p('Stratford').y);
    assert.ok(p('Morden').y>p('Kennington').y);
    assert.ok(p('Upminster').x>p('Barking').x);
    assert.ok(p('Amersham').x<p('Harrow-on-the-Hill').x);
    assert.ok(p('Battersea Power Station').x<p('Kennington').x);
    assert.ok(g.api.stationsNamed('Paddington').length>1);
    assert.equal(g.api.hops('Nine Elms','Battersea Power Station'),1);
    assert.equal(g.api.hops('Bank','Waterloo'),1);
  } finally { await g.close(); }
});

for (const reduced of [false,true]) test(`switching during an answer animation stays aligned (reduced motion: ${reduced})`, async()=>{
  const g=game({reduced});
  try {
    const distance=g.api.kmBetween('Paddington','Waterloo');
    g.choose(g.api.stationsNamed(g.api.current())[0]);
    g.api.confirmGuess();
    g.click('m-sch');
    assert.equal(g.api.state.pending.h,0);
    assert.equal(g.api.kmBetween('Paddington','Waterloo'),distance);
    assert.equal(g.window.document.getElementById('lines').style.display,'none');
    assert.equal(g.window.document.getElementById('diagram').style.display,'');
    const marker=g.window.document.querySelector('#marks circle');
    const answer=g.api.stationsNamed(g.api.state.pending.t)[0];
    assert.equal(Number(marker.getAttribute('cx')),answer.x);
    g.click('m-geo');
    assert.equal(g.api.selected.x,g.api.selected.g[0]);
    assert.ok(g.api.edges.every(e=>e.els.every(p=>p.getAttribute('d') && !/NaN|undefined/.test(p.getAttribute('d')))));
  } finally { await g.close(); }
});

test('five rounds, hints, reload and practice work in diagram mode', async()=>{
  const g=game(); let resumed;
  try {
    g.click('m-sch');
    for(let round=0;round<5;round++){
      if(round===0)g.click('hint');
      g.choose(g.api.stationsNamed(g.api.current())[0]);g.click('go');
      assert.equal(g.api.state.pending.pts,round===0?50:100);
      if(round===1){
        resumed=game({storage:g.snapshot()});
        assert.equal(resumed.api.mode,'dia');
        assert.equal(resumed.api.state.pending.t,g.api.state.pending.t);
        assert.equal(resumed.window.document.querySelector('#diagram').style.display,'');
      }
      g.click('next');
    }
    assert.match(g.window.document.getElementById('panel').textContent,/450 of 500/);
    g.click('prac');
    assert.equal(g.api.gameMode,'practice');
    g.choose(g.api.stationsNamed(g.api.current())[0]);g.click('go');
    assert.equal(g.api.practice.correct,1);
    g.click('next');
    assert.equal(g.api.practice.done,null);
  } finally { await g.close(); if(resumed)await resumed.close(); }
});

test('mobile zoom, whole-map fit, pointer selection and keyboard pan', async()=>{
  const g=game({width:390,height:500});
  try {
    g.click('m-sch');g.click('zall');
    const before=g.api.view.s;g.click('zin');assert.ok(g.api.view.s>before);
    g.click('zout');assert.ok(Math.abs(g.api.view.s-before)<1e-10);
    const x=g.api.view.cx;
    g.map.dispatchEvent(new g.window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));g.flush();
    assert.ok(g.api.view.cx>x);
    const s=g.api.diagramStations[0],v=g.api.view;
    const event={pointerId:1,clientX:(s.x-v.cx)*v.s+195,clientY:(s.y-v.cy)*v.s+250,bubbles:true};
    g.map.dispatchEvent(new g.window.PointerEvent('pointerdown',event));
    g.map.dispatchEvent(new g.window.PointerEvent('pointerup',event));g.flush();
    assert.equal(g.api.selected.n,s.n);
    g.click('m-geo');g.click('m-sch');g.click('zall');
    assert.ok(Number.isFinite(g.api.view.s)&&g.api.view.s>0);
    assert.ok(!/NaN|undefined/.test(g.map.outerHTML));
  } finally { await g.close(); }
});
