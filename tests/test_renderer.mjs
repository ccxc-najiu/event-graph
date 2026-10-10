// Optional geometry checks: node tests/test_renderer.mjs (no npm dependencies).
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

const source = await readFile(new URL('../eventgraph/web/renderer.js', import.meta.url), 'utf8');
const {projectPoint, curvePoints, treeStructure, branchGeometry} = runInNewContext(source.replace(/^export /gm, '') + '\n({projectPoint, curvePoints, treeStructure, branchGeometry})');
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

const nodes=[{id:'a',rank:0,x:0,z:0},{id:'b',rank:1,x:2,z:0},{id:'c',rank:1,x:-2,z:0},{id:'d',rank:2,x:0,z:0},{id:'isolated',rank:0,x:10,z:0}];
const links=[{source:'a',target:'b',kind:'trigger'},{source:'a',target:'c',kind:'trigger'},{source:'b',target:'d',kind:'trigger'},{source:'c',target:'d',kind:'trigger'}];
const before=JSON.stringify({nodes,links});
const structure=treeStructure(nodes,links);
assert.equal(JSON.stringify({nodes,links}),before);
assert.deepEqual(Array.from(structure.roots,n=>n.id),['a']);
assert.equal(structure.trunk.size,2);
for(const key of structure.trunk) {
  const [source,target]=JSON.parse(key);
  assert.ok(links.some(e=>e.source===source&&e.target===target));
}
const withRelated=treeStructure(nodes,[...links,{source:'d',target:'a',kind:'related'},{source:'a',target:'d',kind:'related'}]);
assert.deepEqual([...structure.mass],[...withRelated.mass]);
assert.deepEqual([...structure.trunk],[...withRelated.trunk]);
assert.equal(treeStructure(nodes,[]).roots.length,0);
assert.equal(treeStructure([],[]).trunk.size,0);
const geometry=branchGeometry(curvePoints(a,b,37),.8,.1,42);
assert.equal(JSON.stringify(geometry),JSON.stringify(branchGeometry(curvePoints(a,b,37),.8,.1,42)));
assert.ok(geometry.dust.every(p=>['x','y','z','size','alpha'].every(k=>Number.isFinite(p[k]))));
const ghost=branchGeometry(curvePoints(a,a,37),.3,.14,42,true);
assert.equal(ghost.fibers.length,0);
assert.ok(ghost.dust.length<geometry.dust.length);
console.log('Causal backbone and particle geometry checks passed');
