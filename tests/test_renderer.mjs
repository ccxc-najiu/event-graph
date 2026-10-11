// Optional geometry checks: node tests/test_renderer.mjs (no npm dependencies).
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

const source = await readFile(new URL('../eventgraph/web/renderer.js', import.meta.url), 'utf8');
const {projectPoint, curvePoints, vinePoints, rootBranches, treeStem, naturalCanopy, branchRadii, radiusBetween, trunkProfile} = runInNewContext(source.replace(/^export /gm, '') + '\n({projectPoint, curvePoints, vinePoints, rootBranches, treeStem, naturalCanopy, branchRadii, radiusBetween, trunkProfile})');
const camera = {center:[0,0,0], radius:10, distance:40, yaw:0, pitch:0, zoom:1, panX:0, panY:0};
const viewport = {width:800, height:600, top:100, bottom:60};
const origin = projectPoint({x:0,y:0,z:0},camera,viewport);
assert.equal(origin.x,400);
assert.equal(origin.y,320);
assert.ok(projectPoint({x:0,y:5,z:0},camera,viewport).y < origin.y);
assert.ok(projectPoint({x:5,y:0,z:5},camera,viewport).x > projectPoint({x:5,y:0,z:0},camera,viewport).x);
assert.ok(Math.abs(projectPoint({x:5,y:0,z:0},{...camera,yaw:Math.PI/2},viewport).x-origin.x)<1e-9);
assert.equal(projectPoint({x:0,y:0,z:0},{...camera,panX:12,panY:-8},viewport).y,312);
const a={id:'a',x:0,y:0,z:0}, b={id:'b',x:4,y:5,z:-3};
for (const target of [a,b]) for (const fiber of [0,1,3]) {
  const points=curvePoints(a,target,37,fiber);
  assert.equal(points.length,29);
  for (const axis of ['x','y','z']) {
    assert.ok(Math.abs(points[0][axis]-a[axis])<1e-10);
    assert.ok(Math.abs(points.at(-1)[axis]-target[axis])<1e-10);
  }
  assert.ok(points.every(p=>Object.values(p).every(Number.isFinite)));
  if(target===a) assert.notDeepEqual(points[14],points[0]);
}
console.log('Renderer geometry checks passed');

// Independent and related-only events attach to the trunk; trigger consumers
// (including merges) must never receive a fabricated trunk connection.
const nodes=[
  {id:'a',rank:0,x:0,y:0,z:0},
  {id:'b',rank:1,x:5,y:5,z:0},
  {id:'c',rank:1,x:-5,y:5,z:0},
  {id:'merge',rank:2,x:0,y:10,z:0},
  {id:'independent',rank:2,x:5,y:10,z:5},
  {id:'relatedOnly',rank:1,x:0,y:5,z:5},
];
const links=[{source:'a',target:'b',kind:'trigger'},
  {source:'a',target:'c',kind:'trigger'},
  {source:'b',target:'merge',kind:'trigger'},
  {source:'c',target:'merge',kind:'trigger'},
  {source:'a',target:'relatedOnly',kind:'related'},
  {source:'relatedOnly',target:'a',kind:'related'}];
const before=JSON.stringify({nodes,links});
const roots=rootBranches(nodes,links,5);
assert.equal(JSON.stringify({nodes,links}),before);
assert.deepEqual(Array.from(roots,r=>r.target),['a','independent','relatedOnly']);
assert.equal(JSON.stringify(roots),JSON.stringify(rootBranches(nodes,links.filter(e=>e.kind==='trigger'),5)));
for (const root of roots) {
  const node=nodes.find(n=>n.id===root.target), start=root.points[0], end=root.points.at(-1);
  assert.equal(start.x,0);assert.equal(start.z,0);assert.ok(start.y<node.y);
  for(const key of ['x','y','z']) assert.ok(Math.abs(end[key]-node[key])<1e-9);
  assert.ok(root.points.every(p=>Object.values(p).every(Number.isFinite)));
}
const stem=treeStem(nodes,5);
assert.ok(stem.every(p=>p.x===0&&p.z===0));
assert.ok(stem[0].y<roots[0].points[0].y && stem.at(-1).y>10);
assert.equal(treeStem([],5).length,0);
assert.equal(rootBranches([],[],5).length,0);
assert.equal(rootBranches(nodes,[],5).length,nodes.length);
assert.equal(rootBranches([nodes[0]],[],5).length,1);
console.log('Straight trunk, causal roots, related-only roots, independent events and merges passed');

// Ornamental growth must remain deterministic, finite and bounded at import limits.
const canopy=naturalCanopy(nodes,5);
assert.equal(JSON.stringify({nodes,links}),before);
assert.equal(JSON.stringify(canopy),JSON.stringify(naturalCanopy([...nodes].reverse(),5)));
assert.ok(canopy.twigs.length>0);
assert.ok(canopy.twigs.every(t=>nodes.some(n=>n.id===t.owner)&&t.radius>0));
for(const twig of canopy.twigs) for(const point of twig.points) {
  assert.ok(['x','y','z'].every(k=>Number.isFinite(point[k])));
}
assert.ok(canopy.motes.every(p=>['x','y','z','alpha','size'].every(k=>Number.isFinite(p[k]))));
assert.equal(naturalCanopy([],5).twigs.length,0);
assert.ok(naturalCanopy([nodes[0]],5).twigs.length>0);
const many=Array.from({length:3000},(_,i)=>({...nodes[i%nodes.length],id:`node-${i}`}));
const bounded=naturalCanopy(many,5);
assert.ok(bounded.twigs.length<=4500);
assert.ok(bounded.motes.length<=18000);
console.log('Natural canopy determinism, isolated nodes, finite coordinates and geometry budget passed');

// Every tube meeting a node must use that node's shared radius at its endpoint.
const radii=branchRadii(nodes,links);
assert.equal(JSON.stringify({nodes,links}),before);
const augmented=[...links,{source:'merge',target:'a',kind:'related'},links[0]];
assert.deepEqual([...radii],[...branchRadii([...nodes].reverse(),augmented.reverse())]);
for(const node of nodes) {
  const incoming=links.filter(e=>e.kind==='trigger'&&e.target===node.id);
  const outgoing=links.filter(e=>e.kind==='trigger'&&e.source===node.id);
  for(const input of incoming) for(const output of outgoing) {
    assert.equal(radiusBetween(radii.get(input.source),radii.get(node.id),1),
      radiusBetween(radii.get(node.id),radii.get(output.target),0));
  }
}
for(const edge of links.filter(e=>e.kind==='trigger')) {
  const a=radii.get(edge.source), b=radii.get(edge.target);
  assert.ok(a>=b && b>0 && a<=.6);
  const samples=Array.from({length:101},(_,i)=>radiusBetween(a,b,i/100));
  assert.ok(samples.every((r,i)=>i===0||r<=samples[i-1]+1e-12));
  assert.ok(Math.abs(radiusBetween(a,b,1e-5)-a)<1e-8);
}
const profile=trunkProfile(stem,roots,radii);
for(const root of roots) {
  const start=profile(root.points[0].y);
  assert.ok(start>=radii.get(root.target));
  assert.equal(radiusBetween(start,radii.get(root.target),0),start);
}
assert.equal(branchRadii([],[]).size,0);
assert.equal(trunkProfile([],[],new Map())(0),0);
const chain=Array.from({length:3000},(_,i)=>({id:String(i),rank:i}));
const chainLinks=chain.slice(1).map((n,i)=>({source:String(i),target:n.id,kind:'trigger'}));
assert.ok([...branchRadii(chain,chainLinks).values()].every(r=>Number.isFinite(r)&&r>0&&r<=.6));
console.log('Shared junction radii, smooth taper, merges, duplicate ports and trunk continuity passed');

for(const target of [a,b,{...b,id:'same-layer',y:0}]) {
  const vine=vinePoints(a,target,37);
  for(const key of ['x','y','z']) {
    assert.ok(Math.abs(vine[0][key]-a[key])<1e-9);
    assert.ok(Math.abs(vine.at(-1)[key]-target[key])<1e-9);
  }
  assert.ok(vine.every(p=>Object.values(p).every(Number.isFinite)));
  assert.equal(JSON.stringify(vine),JSON.stringify(vinePoints(a,target,37)));
}
assert.notEqual(JSON.stringify(vinePoints(a,b,37)),JSON.stringify(vinePoints(b,a,37).reverse()));
console.log('Vine endpoints, sag, reciprocal paths, self loops and determinism passed');

const narrow={width:390,height:640,top:138,bottom:65};
const narrowPoint=projectPoint({x:10,y:0,z:0},camera,narrow);
assert.ok(narrowPoint.x<narrow.width-40);
assert.ok(vinePoints(a,b,37)[14].y<curvePoints(a,b,37)[14].y);

// Smooth vines progress along the endpoint chord, including near-vertical and
// short links; reverse links stay on separate lanes without endpoint drift.
for(const target of [b,{id:'vertical',x:a.x,y:a.y+8,z:a.z},
  {id:'short',x:a.x+.01,y:a.y,z:a.z+.01}]) {
  const vine=vinePoints(a,target,37),dx=target.x-a.x,dz=target.z-a.z;
  assert.ok(vine.every(p=>Object.values(p).every(Number.isFinite)));
  if(Math.hypot(dx,dz)>1e-8) {
    const progress=vine.map(p=>(p.x-a.x)*dx+(p.z-a.z)*dz);
    assert.ok(progress.every((p,i)=>!i||p>=progress[i-1]-1e-9));
  }
  const midpoint=vine[14];
  assert.ok(midpoint.y<=(a.y+target.y)/2+1e-9);
}
const loop=vinePoints(a,a,37);
assert.ok(Math.max(...loop.map(p=>Math.hypot(p.x-a.x,p.y-a.y,p.z-a.z)))>1);
const forward=vinePoints(a,b,3),reverse=vinePoints(b,a,8).reverse();
assert.ok(Math.hypot(forward[14].x-reverse[14].x,forward[14].z-reverse[14].z)>0);
console.log('Smooth vine progress, vertical and short links, hanging loops and parallel lanes passed');
