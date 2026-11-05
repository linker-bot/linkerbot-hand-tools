'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const ui = require('../python/hand_tools/static/app.js');

test('raw control ranges and complete-vector validation', () => {
  const control = {ranges:[[-100,100],[20,30]]};
  assert.deepEqual(ui.draftVector(control), [0,25]);
  assert.deepEqual(ui.validateVector(control,[-100,30]),[-100,30]);
  for(const values of [[1],[0,31],[NaN,25],[true,25]])assert.throws(()=>ui.validateVector(control,values));
});
test('legacy, flat modern and descriptor tactile matrices', () => {
  assert.deepEqual(ui.matrices({matrices:[{name:'finger',raw:[[0,1],[2,3]]}]} )[0].raw, [[0,1],[2,3]]);
  assert.deepEqual(ui.matrices({matrices:[{name:'finger',rows:2,columns:2,raw:[0,1,2,3]}]})[0].raw,[[0,1],[2,3]]);
  const data = {matrices:[{name:'thumb',raw:[[9]]}],sensors:[{name:'thumb',available:true,unit:'N',rows:1,columns:2,fields:[{semantic:'fn',values:[2,3]}]}]};
  assert.equal(ui.matrices(data).length,1);
  assert.deepEqual(ui.matrices(data)[0].raw,[[2,3]]);
});
test('bounded trends use fresh sample sequences and retain zeros', () => {
  const trend = new ui.Trends(2);
  const sample = (sequence, raw, meta={}) => ({sequence, data:{matrices:[{name:'finger',raw}],meta}});
  trend.add('force',sample(1,[[0,0]]),1000);
  trend.add('force',sample(1,[[8,8]]),1100);
  trend.add('force',sample(2,[[1,2]]),2000);
  trend.add('force',sample(3,[[9]],{stale:true}),3000);
  assert.deepEqual(trend.series.get('force/finger').points.map(p=>p.value),[0,3]);
  trend.add('force',sample(4,[[3,4]]),4000);
  assert.deepEqual(trend.series.get('force/finger').points.map(p=>p.value),[3,7]);
  trend.add('palm',sample(5,[[2]]),4000);
  assert.equal(trend.series.size,2);
  assert.match(ui.provenance({age_ms:0,data:{meta:{freshness:'unknown',origin:'legacy_unspecified'}}}),/freshness unknown/);
});

// Small DOM adapter tests real handlers without a browser or npm dependencies.
class Element {
  constructor(tag='div') {this.tag=tag;this.children=[];this.dataset={};this.value='';this.textContent='';this.disabled=false;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(){}
  getContext(){return new Proxy({}, {get:(target,key)=>target[key]||(()=>{}),set:(target,key,v)=>(target[key]=v,true)});}
  querySelectorAll(selector){return this.children.flatMap(c=>[...(selector==='input'&&c.tag==='input'?[c]:[]),...c.querySelectorAll(selector)]);}
}
function documentMock(){
  const elements={};
  return {elements,createElement:tag=>new Element(tag),getElementById:id=>elements[id]||(elements[id]=new Element()),querySelectorAll:()=>[]};
}
for(const [model,size] of [['L30',17],['O30',20]])test(model+' controls, snapshots and draft edits never submit automatically', async()=>{
  const document=documentMock(), requests=[];
  const fetch=async(path,options={})=>{
    requests.push([path,options.body?JSON.parse(options.body):undefined]);
    return {ok:true,json:async()=>path==='/api/models'?{models:[]}:path==='/api/state'?{connected:false}:{ok:true,data:{stage:'dispatched',mechanical_arrival_confirmed:false}}};
  };
  const app=ui.mount(document,fetch,()=>{});await app.ready;
  const meta={model,sdk:'modern',controls:[{name:'position',unit:'raw count',ranges:Array.from({length:size},()=>[-100,200])}],operations:['enable'],readable:['position','force']};
  app.clearConnection(meta);
  const box=document.elements.controls.children[0], editor=box.children[2];
  assert.equal(editor.children.length,size);
  const slider=editor.children[0].children[1];slider.value='42';slider.oninput();
  app.acceptState({connected:true,meta,rates:{position:10,force:30},samples:{position:{sequence:1,age_ms:0,data:{raw:Array(size).fill(0),meta:{valid:true,origin:'device_measured'}}}}});
  assert.equal(document.elements['monitor-body'].children.length,size);
  assert.equal(slider.value,'42'); // telemetry must not overwrite an edited draft
  assert.match(editor.children[0].children.at(-1).textContent,/position: 0/);
  assert.equal(requests.filter(r=>r[0]==='/api/request').length,0);
  await box.children.at(-1).onclick();await new Promise(resolve=>setImmediate(resolve));
  const writes=requests.filter(r=>r[0]==='/api/request');assert.equal(writes.length,1);
  assert.equal(writes[0][1].action,'write');assert.equal(writes[0][1].values.length,size);assert.equal(writes[0][1].values[0],42);
  app.clearConnection(null);assert.equal(document.elements.controls.children.length,0);
});
