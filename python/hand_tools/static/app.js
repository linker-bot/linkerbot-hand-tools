/* Shared browser helpers are also imported by the dependency-free Node tests. */
(function(root) {
'use strict';
const finite = value => typeof value === 'number' && Number.isFinite(value);
function validateVector(control, values) {
  if (!Array.isArray(values) || values.length !== control.ranges.length ||
      values.some((v, i) => !finite(v) || v < control.ranges[i][0] || v > control.ranges[i][1])) {
    throw Error('Values must match the displayed count and ranges');
  }
  return values;
}
function draftVector(control) {
  // Draft only: never treat a midpoint as measured position or submit it on connect.
  return control.ranges.map(([lo, hi]) => Math.min(hi, Math.max(lo, Math.round((lo + hi) / 2))));
}
function matrices(data) {
  const result = [];
  for (const matrix of data?.matrices || []) {
    let raw = matrix.raw || [];
    if (raw.length && !Array.isArray(raw[0]) && matrix.rows * matrix.columns === raw.length) {
      raw = Array.from({length: matrix.rows}, (_, r) => raw.slice(r * matrix.columns, (r + 1) * matrix.columns));
    }
    if (raw.length && raw.every(Array.isArray)) result.push({...matrix, raw});
  }
  for (const sensor of data?.sensors || []) {
    // Prefer the descriptor's decoded normal-force field over duplicate matrices.
    const field = (sensor.fields || []).find(f => f.semantic === 'fn');
    if (!field || !sensor.available || sensor.rows <= 0 || sensor.columns <= 0 ||
        field.values.length !== sensor.rows * sensor.columns) continue;
    const value = {name: sensor.name, unit: sensor.unit, raw: Array.from({length:sensor.rows},
      (_, r) => field.values.slice(r * sensor.columns, (r + 1) * sensor.columns))};
    const index = result.findIndex(m => m.name === sensor.name);
    if (index < 0) result.push(value); else result[index] = value;
  }
  return result;
}
function readableSample(sample) {
  return !!sample && !sample.error && sample.data?.meta?.valid !== false &&
    sample.data?.meta?.stale !== true && sample.data?.valid !== false;
}
class Trends {
  constructor(limit = 180) { this.limit = limit; this.series = new Map(); this.sequences = {}; }
  add(channel, sample, now) {
    if (!readableSample(sample) || this.sequences[channel] === sample.sequence) return;
    this.sequences[channel] = sample.sequence;
    for (const matrix of matrices(sample.data)) {
      const values = matrix.raw.flat().filter(finite);
      if (!values.length) continue;
      const key = channel + '/' + matrix.name;
      const series = this.series.get(key) || {name:key, unit:matrix.unit || 'unverified raw count', points:[]};
      series.points.push({time:now, value:values.reduce((a,b) => a+b, 0)});
      series.points = series.points.slice(-this.limit);
      this.series.set(key, series);
    }
  }
}
function provenance(sample) {
  if (!sample) return 'Waiting for reading';
  if (sample.error) return 'Read error: ' + sample.error;
  const meta = sample.data?.meta || sample.data || {};
  return `${meta.valid === false ? 'INVALID · ' : ''}${meta.stale ? 'STALE · ' : ''}` +
    `${meta.origin || 'unknown origin'} · freshness ${meta.freshness || (meta.age_ms != null ? meta.age_ms.toFixed(0)+' ms (SDK)' : 'unknown')}` +
    ` · received ${sample.age_ms == null ? '?' : sample.age_ms.toFixed(0)} ms ago`;
}
function mount(doc, fetcher, schedule = setTimeout) {
  const $ = id => doc.getElementById(id);
  let meta = null, generation = 0, state = null, trends = new Trends(), lastReading = null;
  let busy = false, controls = [], commandBusy = false;
  const el = (tag, text, cls) => { const n=doc.createElement(tag); if(text !== undefined) n.textContent=text; if(cls)n.className=cls; return n; };
  const report = value => { $('result').textContent = typeof value === 'string' ? value : JSON.stringify(value,null,2); };
  async function api(path, payload) {
    const r = await fetcher(path, payload === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data = await r.json();
    if (!r.ok || data?.ok === false) throw Error(data?.error || r.statusText);
    return payload === undefined ? data : data.data;
  }
  function clearConnection(value) {
    generation++; meta=value; state=null; trends=new Trends(); lastReading=null; controls=[];
    for(const id of ['controls','operations','channel','monitor-head','monitor-body','matrices','rate-fields']) $(id).replaceChildren();
    $('reading').textContent=''; $('trend-legend').textContent=''; $('download').disabled=true;
    $('disconnect').disabled=!meta; $('read').disabled=!meta; $('apply-rates').disabled=!meta;
    $('status').textContent=meta ? `${meta.model} · ${meta.sdk}${meta.simulated ? ' · Offline simulation' : ''}` : 'Disconnected';
    $('identity').textContent=meta ? `${meta.identity || meta.model}${meta.firmware ? ' · '+meta.firmware : ''}` : 'No device connected';
    $('meta').textContent=meta ? JSON.stringify(meta,null,2) : '';
    drawTrends();
    if(!meta)return;
    for(const name of meta.readable || []) { const option=el('option',name); option.value=name; $('channel').append(option); }
    for(const control of meta.controls || []) buildControl(control);
    for(const name of meta.operations || []) {
      const button=el('button',name); button.onclick=()=>command('operation',name,[]); $('operations').append(button);
    }
  }
  async function command(action, channel, values) {
    if(!meta || commandBusy)return;
    commandBusy=true; const token=generation;
    doc.querySelectorAll('#controls button, #operations button').forEach(b=>b.disabled=true);
    try { const result=await api('/api/request',{action,channel,values}); if(token===generation)report(result); }
    catch(e) { if(token===generation)report(e.message); }
    finally { commandBusy=false; if(token===generation)doc.querySelectorAll('#controls button, #operations button').forEach(b=>b.disabled=false); }
  }
  function buildControl(control) {
    const box=el('div',undefined,'control'), title=el('h3',`${control.name} — ${control.unit}`);
    const note=el('p','Draft values only. Adjusting sliders does not send a command. Use Write to submit the complete vector.','note');
    const editor=el('div',undefined,'joint-editors'), values=draftVector(control), inputs=[];
    control.ranges.forEach(([lo,hi],i)=>{
      const row=el('div',undefined,'joint-editor'); row.append(el('span',`Joint ${i}`));
      const slider=el('input'), number=el('input'); slider.type='range'; number.type='number';
      for(const input of [slider,number]) { input.min=lo; input.max=hi; input.step=control.name==='position'||meta.sdk==='legacy'||meta.simulated ? '1' : 'any'; input.value=values[i]; input.setAttribute('aria-label',`${control.name} joint ${i} ${input===slider?'slider':'value'}`); }
      slider.oninput=()=>{ values[i]=Number(slider.value); number.value=slider.value; };
      number.oninput=()=>{ values[i]=number.value===''?NaN:Number(number.value); slider.value=number.value; };
      const live=el('output','Waiting for reading','live-reading'); live.setAttribute('aria-live','off');
      row.append(slider,number,el('small',`${lo} … ${hi}`),live); editor.append(row); inputs.push({slider,number,live});
    });
    const vector=el('textarea'); vector.placeholder='Optional: paste a complete vector to replace the draft';
    vector.setAttribute('aria-label',`${control.name} complete vector`);
    const load=el('button','Load vector into draft'); load.onclick=()=>{try{
      if(!vector.value.trim())throw Error('Enter the complete vector');
      const next=validateVector(control,vector.value.trim().split(/[\s,]+/).map(Number));
      next.forEach((v,i)=>{values[i]=v;inputs[i].slider.value=v;inputs[i].number.value=v;});
    }catch(e){report(e.message);}};
    const measured=el('button','Copy current reading to draft');
    measured.onclick=()=>{try{
      const sample=state?.samples[control.name];
      if(!readableSample(sample))throw Error('No valid current reading for this control');
      const next=validateVector(control,sample.data.raw);
      next.forEach((v,i)=>{values[i]=v;inputs[i].slider.value=v;inputs[i].number.value=v;});
    }catch(e){report(e.message);}};
    const send=el('button','Write '+control.name); send.onclick=()=>{try{
      validateVector(control,values); if(values.some(v=>!Number.isInteger(v)) && (control.name==='position'||meta.sdk==='legacy'))throw Error('This control requires integers');
      command('write',control.name,values.slice());
    }catch(e){report(e.message);}};
    box.append(title,note,editor,vector,load,measured,send); $('controls').append(box); controls.push({control,values,inputs});
  }
  function showRates(rates) {
    if($('rate-fields').children.length)return;
    for(const [name,hz] of Object.entries(rates)) {
      const label=el('label',name+' (Hz)'), input=el('input');
      input.type='number'; input.min=0; input.max=100; input.step='any'; input.value=hz; input.dataset.channel=name;
      label.append(input); $('rate-fields').append(label);
    }
  }
  function showMonitor(samples) {
    const names=Object.keys(samples).filter(n=>Array.isArray(samples[n].data?.raw) && samples[n].data.raw.every(v=>v===null||finite(v)));
    for(const item of controls) item.inputs.forEach((input,i)=>{
      input.live.textContent=names.map(name=>`${name}: ${samples[name].data.raw[i] ?? '—'}${readableSample(samples[name])?'':' (invalid)'}`).join(' · ');
      input.live.title=names.map(name=>`${name}: ${provenance(samples[name])}`).join('\n');
    });
    const tr=el('tr'); tr.append(el('th','Joint'));
    for(const name of names)tr.append(el('th',name));
    $('monitor-head').replaceChildren(tr); $('monitor-body').replaceChildren();
    const count=Math.max(0,...names.map(n=>samples[n].data.raw.length));
    for(let i=0;i<count;i++) {
      const row=el('tr'); row.append(el('th',String(i)));
      for(const name of names) {const sample=samples[name], value=sample.data.raw[i];
        const cell=el('td',value==null?'—':String(value)); cell.title=provenance(sample);
        if(!readableSample(sample))cell.className='invalid'; row.append(cell);
      }
      $('monitor-body').append(row);
    }
    $('sample-status').textContent=Object.entries(samples).map(([name,s])=>`${name}: ${provenance(s)}`).join('\n');
  }
  function showMatrices(samples) {
    $('matrices').replaceChildren();
    for(const channel of ['force','palm']) {
      const sample=samples[channel]; if(!sample?.data)continue;
      for(const matrix of matrices(sample.data)) {
        const raw=matrix.raw, values=raw.flat().filter(finite); if(!values.length)continue;
        const cols=Math.max(...raw.map(r=>r.length)), min=Math.min(...values), max=Math.max(...values);
        if(!cols)continue;
        const figure=el('figure'), canvas=el('canvas'), caption=el('figcaption');
        canvas.width=cols*16; canvas.height=raw.length*16; const ctx=canvas.getContext('2d');
        for(let r=0;r<raw.length;r++)for(let c=0;c<raw[r].length;c++) {
          if(!finite(raw[r][c]))continue;
          ctx.fillStyle=`hsl(205 60% ${94-((raw[r][c]-min)/(max-min||1))*66}%)`;
          ctx.fillRect(c*16,r*16,16,16);
        }
        caption.textContent=`${channel}/${matrix.name} · ${raw.length}×${cols} · ${matrix.unit||'raw count; see metadata'} · auto scale ${min}…${max}`;
        figure.append(canvas,caption,el('small',provenance(sample))); if(!readableSample(sample))figure.className='invalid'; $('matrices').append(figure);
      }
    }
  }
  function drawTrends() {
    const canvas=$('trend'), ctx=canvas.getContext('2d'), width=canvas.width,height=canvas.height;
    ctx.clearRect(0,0,width,height);
    const series=Array.from(trends.series.values());
    $('trend-legend').textContent=series.map((s,i)=>`${i+1}. ${s.name} (${s.unit}, matrix sum)`).join(' · ');
    if(!series.length)return;
    const points=series.flatMap(s=>s.points), end=Math.max(...points.map(p=>p.time)), start=Math.min(...points.map(p=>p.time));
    const lo=Math.min(0,...points.map(p=>p.value)), hi=Math.max(1,...points.map(p=>p.value));
    ctx.strokeStyle='#9baab4'; ctx.beginPath(); ctx.moveTo(55,15);ctx.lineTo(55,height-35);ctx.lineTo(width-10,height-35);ctx.stroke();
    ctx.fillStyle='#415363';ctx.font='12px system-ui';ctx.fillText(String(hi),4,20);ctx.fillText(String(lo),4,height-35);ctx.fillText('Time (seconds before latest sample)',width/2-95,height-5);
    ctx.fillText(((start-end)/1000).toFixed(1),55,height-19);ctx.fillText('0',width-18,height-19);
    series.forEach((s,i)=>{ctx.strokeStyle=`hsl(${205+i*47} 55% 40%)`;ctx.beginPath();
      s.points.forEach((p,j)=>{const x=55+(p.time-start)/Math.max(1,end-start)*(width-70), y=15+(hi-p.value)/Math.max(1,hi-lo)*(height-50); if(j===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();
      const last=s.points[s.points.length-1];ctx.fillStyle=ctx.strokeStyle;ctx.fillText(String(i+1),width-28,20+i*14);
    });
  }
  function acceptState(next) {
    if(!next.connected) { if(meta){clearConnection(null);report('Connection stopped. Commands were not retried.');} return; }
    if(!meta || state && state.connection_id !== next.connection_id)clearConnection(next.meta);
    state=next; showRates(next.rates); showMonitor(next.samples); showMatrices(next.samples);
    const now=Date.now(); for(const channel of ['force','palm'])trends.add(channel,next.samples[channel],now-(next.samples[channel]?.age_ms||0));
    drawTrends();
  }
  $('connect').onsubmit=async event=>{
    event.preventDefault(); if(busy)return; busy=true; const token=++generation;
    try { const form=new FormData(event.target), payload=Object.fromEntries(form.entries());payload.simulate=form.has('simulate');
      const value=await api('/api/connect',payload); if(token===generation){clearConnection(value);report('Connected. No motion target, speed or torque was sent.');}
    }catch(e){if(token===generation)report(e.message);}finally{busy=false;}
  };
  $('disconnect').onclick=async()=>{if(busy)return;busy=true;++generation;try{await api('/api/disconnect',{});clearConnection(null);report('Disconnected. Device state is not inferred from closure.');}catch(e){report(e.message);}finally{busy=false;}};
  $('apply-rates').onclick=async()=>{try{
    const rates={}; $('rate-fields').querySelectorAll('input').forEach(n=>{if(n.value.trim()==='')throw Error('Enter a rate');rates[n.dataset.channel]=Number(n.value);});
    await api('/api/rates',rates);report('Read rates updated. 0 pauses a channel. Device sampling rates may be lower.');
  }catch(e){report(e.message);}};
  $('read').onclick=async()=>{const token=generation;try{const name=$('channel').value;const value=await api('/api/request',{action:'read',channel:name});if(token!==generation)return;lastReading=value;$('reading').textContent=JSON.stringify(value,null,2);$('download').disabled=false;}catch(e){if(token===generation)report(e.message);}};
  $('download').onclick=()=>{const blob=new Blob([JSON.stringify(lastReading,null,2)],{type:'application/json'}), url=URL.createObjectURL(blob), a=el('a');a.href=url;a.download=`${meta.model}-${$('channel').value}.json`;a.click();URL.revokeObjectURL(url);};
  async function tick() {
    if(!busy){const token=generation;try {const next=await api('/api/state');if(token===generation)acceptState(next);}catch(e){if(token===generation)report(e.message);}}
    schedule(tick,200);
  }
  clearConnection(null);
  const ready=api('/api/models').then(data=>{for(const p of data.models){const o=el('option',`${p.model} (${p.preferred_sdk})`);o.value=p.model;$('models').append(o);}return tick();}).catch(e=>report(e.message));
  return {ready, acceptState, clearConnection};
}
const exported={validateVector,draftVector,matrices,Trends,readableSample,provenance,mount};
if(typeof module!=='undefined' && module.exports)module.exports=exported;
else {root.HandTools=exported;mount(root.document,root.fetch.bind(root));}
})(typeof window==='undefined'?globalThis:window);
