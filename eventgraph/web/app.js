import {GraphRenderer} from './renderer.js';

const $ = id => document.getElementById(id);
let scene = null, selected = null, sceneName = '事件图谱';
let notificationTimer = null;
let renderer;

function text(tag, value, className = '') {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  return element;
}
function error(message) { $('error-message').textContent = message; $('error-banner').hidden = false; }
function notify(message) {
  $('notification').textContent = message;
  clearTimeout(notificationTimer);
  notificationTimer = setTimeout(() => { $('notification').textContent = ''; }, 5000);
}
function label(id) { const event = scene.graph.events.find(e => e.id === id); return event?.description || id; }

function renderList() {
  if (!scene) return;
  const query = $('search').value.trim().toLocaleLowerCase();
  const nodes = [...scene.layout.nodes].sort((a,b) => a.rank-b.rank || a.id.localeCompare(b.id));
  const events = new Map(scene.graph.events.map(e => [e.id,e]));
  const fragment = document.createDocumentFragment();
  let rank = null, count = 0;
  for (const node of nodes) {
    const event = events.get(node.id);
    if (query && !`${node.id} ${event.description}`.toLocaleLowerCase().includes(query)) continue;
    count++;
    if (rank !== node.rank) { rank = node.rank; fragment.append(text('div',`LAYER ${String(rank+1).padStart(2,'0')}`,'group-label')); }
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'node-row'; button.dataset.id = node.id;
    button.setAttribute('aria-pressed',String(node.id === selected));
    button.setAttribute('aria-label',`${label(node.id)}，第 ${rank+1} 层`);
    button.classList.toggle('active',node.id === selected);
    button.append(text('span','','node-dot'),text('span',label(node.id),'node-label'),text('span',String(rank+1).padStart(2,'0'),'node-level'));
    button.addEventListener('click',()=>select(node.id));
    fragment.append(button);
  }
  if (!count) fragment.append(text('p',scene.graph.events.length?'没有匹配的事件':'还没有事件节点','search-empty'));
  $('node-list').replaceChildren(fragment);
}

function renderLinks(id, incoming) {
  const container = $(incoming?'detail-incoming':'detail-outgoing');
  const links = scene.layout.links.filter(link => incoming?link.target === id:link.source === id);
  const fragment = document.createDocumentFragment();
  for (const link of links) {
    const other = incoming?link.source:link.target;
    const button = text('button','','relation-row'); button.type='button';
    const name = text('span',label(other),'relation-name');
    const result = scene.graph.results.find(r=>r.id===link.result_id);
    name.append(text('small',result?.description || link.result_id));
    button.append(name,text('small',link.kind==='trigger'?'触发':'相关'),text('span','↗'));
    button.addEventListener('click',()=>select(other)); fragment.append(button);
  }
  if (!links.length) fragment.append(text('p','暂无连接','none'));
  container.replaceChildren(fragment);
}

function select(id) {
  selected=id;
  renderer.select(id);
  document.querySelector('.workspace').classList.toggle('has-selection',!!id);
  $('detail').hidden=!id; $('detail-empty').hidden=!!id; $('clear-selection').hidden=!id;
  for (const button of $('node-list').querySelectorAll('button')) {
    button.classList.toggle('active',button.dataset.id===id);
    button.setAttribute('aria-pressed',String(button.dataset.id===id));
  }
  if (!id) return;
  const event=scene.graph.events.find(e=>e.id===id), node=scene.layout.nodes.find(n=>n.id===id);
  $('detail-name').textContent=label(id); $('detail-id').textContent=id;
  $('detail-rank').textContent=`LAYER ${String(node.rank+1).padStart(2,'0')} / 事件节点`;
  $('detail-time').replaceChildren(text('span',event.time.start??'−∞'),text('span','→','arrow'),text('span',event.time.end??'+∞'));
  $('detail-roles').replaceChildren(...(event.roles.length?event.roles.map(r=>text('span',r,'tag')):[text('span','无参与角色','none')]));
  const results=scene.graph.results.filter(r=>r.event_id===id);
  $('result-count').textContent=results.length;
  $('detail-results').replaceChildren(...results.map(result=>{
    const row=text('div','','result-row');
    const content=text('span',result.description || result.id);
    if (result.description) content.append(text('small',result.id));
    row.append(content); return row;
  }));
  if (!results.length) $('detail-results').append(text('p','暂无结果定义','none'));
  renderLinks(id,true); renderLinks(id,false);
}

function setScene(data, name) {
  renderer.setScene(data);
  scene=data; sceneName=name; selected=null;
  $('scene-name').textContent=name;
  $('node-count').textContent=scene.graph.events.length;
  $('search').value='';
  $('canvas-message').hidden=scene.graph.events.length>0;
  $('canvas-message').textContent='图谱为空，可导入包含事件的 JSON';
  const triggers=scene.layout.links.filter(l=>l.kind==='trigger').length;
  const related=scene.layout.links.length-triggers;
  const layers=new Set(scene.layout.nodes.map(n=>n.rank)).size;
  $('fact-events').textContent=scene.graph.events.length;
  $('fact-triggers').textContent=triggers; $('fact-related').textContent=related;
  $('summary').textContent=`${scene.graph.events.length} 节点 · ${triggers} 触发 · ${related} 相关 · ${layers} 层`;
  $('export').disabled=false;
  renderList(); select(null);
}

async function responseJSON(response) {
  const data=await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}

$('error-close').addEventListener('click',()=>{$('error-banner').hidden=true;});
$('search').addEventListener('input',renderList);
$('clear-selection').addEventListener('click',()=>select(null));
$('import-open').addEventListener('click',()=>{ $('import-error').hidden=true; $('import-dialog').showModal(); });
for (const id of ['import-close','import-cancel']) $(id).addEventListener('click',()=>$('import-dialog').close());
$('file-input').addEventListener('change',async()=>{
  const file=$('file-input').files[0]; if (!file) return;
  $('import-error').hidden=true;
  if (file.size>2*1024*1024) { $('import-error').textContent='JSON 文件不能超过 2 MiB'; $('import-error').hidden=false; return; }
  try { $('json-input').value=await file.text(); $('filename').textContent=file.name; }
  catch { $('import-error').textContent='文件读取失败，请重新选择。'; $('import-error').hidden=false; }
});
$('import-form').addEventListener('submit',async e=>{
  e.preventDefault(); $('import-error').hidden=true;
  $('import-submit').disabled=true; $('import-submit').textContent='解析与布局中…';
  try {
    let raw=$('json-input').value;
    // Viewer exports include both definitions and geometry; always relayout the definitions.
    const candidate=JSON.parse(raw);
    if (candidate && candidate.graph && candidate.layout) raw=JSON.stringify(candidate.graph);
    const data=await responseJSON(await fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:raw}));
    setScene(data,$('file-input').files[0]?.name || '导入的图谱');
    $('import-dialog').close(); $('error-banner').hidden=true;
    notify('图谱已载入，原文件未修改');
  } catch (err) { $('import-error').textContent=err.message; $('import-error').hidden=false; }
  finally { $('import-submit').disabled=false; $('import-submit').textContent='载入图谱'; }
});
$('export').addEventListener('click',()=>{
  if (!scene) return;
  const blob=new Blob([JSON.stringify({graph:scene.graph,layout:scene.layout},null,2)+'\n'],{type:'application/json'});
  const url=URL.createObjectURL(blob), anchor=document.createElement('a');
  anchor.href=url; anchor.download=sceneName.replace(/\.json$/i,'').replace(/[^\p{L}\p{N}._-]/gu,'_')+'.scene.json';
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000); notify('已导出事件定义与三维布局');
});

try {
  renderer=new GraphRenderer($('graph'),{onSelect:select,onZoom:zoom=>{$('zoom').textContent=`${Math.round(zoom*100)}%`;}});
  for (const [id,option] of [['related','showRelated'],['labels','showLabels'],['glow','glow']]) {
    $(id).addEventListener('change',()=>renderer.setOption(option,$(id).checked));
  }
  for (const form of ['simple','natural']) {
    $(`form-${form}`).addEventListener('click',()=>{
      renderer.setForm(form);
      for(const name of ['simple','natural']) $(`form-${name}`).setAttribute('aria-pressed',String(name===form));
      document.querySelector('.viewport').classList.toggle('natural-form',form==='natural');
    });
  }
  $('rotate').addEventListener('click',()=>{
    renderer.setOption('rotate',!renderer.rotate);
    $('rotate').setAttribute('aria-pressed',String(renderer.rotate));
  });
  $('front').addEventListener('click',()=>{renderer.setOption('rotate',false);$('rotate').setAttribute('aria-pressed','false');renderer.reset(true);});
  $('reset').addEventListener('click',()=>{renderer.setOption('rotate',false);$('rotate').setAttribute('aria-pressed','false');renderer.reset();});
  $('zoom-in').addEventListener('click',()=>renderer.zoomBy(1.2));
  $('zoom-out').addEventListener('click',()=>renderer.zoomBy(1/1.2));
  const data=await responseJSON(await fetch('/api/scene'));
  setScene(data,data.name);
} catch (err) {
  error(`无法打开图谱：${err.message}`);
  $('canvas-message').textContent='载入失败，请检查本地服务并刷新';
}
