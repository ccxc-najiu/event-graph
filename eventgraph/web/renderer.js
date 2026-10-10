// A dependency-free 3D camera and canvas renderer. Input coordinates stay intact.
const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const palette = {blue: '#268bff', cyan: '#75edff', faint: '#51768d'};

export function projectPoint(p, camera, viewport) {
  const [cx, cy, cz] = camera.center;
  const dx = p.x - cx, dy = p.y - cy, dz = p.z - cz;
  const x = Math.cos(camera.yaw) * dx - Math.sin(camera.yaw) * dz;
  const depth = Math.sin(camera.yaw) * dx + Math.cos(camera.yaw) * dz;
  const y = Math.cos(camera.pitch) * dy - Math.sin(camera.pitch) * depth;
  const z = Math.sin(camera.pitch) * dy + Math.cos(camera.pitch) * depth;
  const perspective = camera.distance / (camera.distance - z);
  const top = viewport.top || 0, bottom = viewport.bottom || 0;
  const availableHeight = viewport.height - top - bottom;
  const scale = Math.min(viewport.width - 28, availableHeight) / (2 * camera.radius) * .92 * camera.zoom;
  return {x: viewport.width / 2 + x * scale * perspective + camera.panX,
    y: top + availableHeight / 2 - y * scale * perspective + camera.panY, depth: z, perspective};
}

function hash(text) {
  let n = 2166136261;
  for (const c of text) n = Math.imul(n ^ c.charCodeAt(0), 16777619);
  return n >>> 0;
}

export function curvePoints(a, b, seed, fiber = 0) {
  const dy = b.y - a.y, dx = b.x - a.x, dz = b.z - a.z;
  const same = a.id === b.id;
  const side = (seed % 2 ? 1 : -1) * (Math.abs(dy) < .1 ? 1.8 : .25);
  const c1 = {x: a.x + dx * .12 + side, y: a.y + dy * .48 + (same ? 2 : 0), z: a.z + dz * .15 + (same ? 2 : .4)};
  const c2 = {x: b.x - dx * .15 + side, y: b.y - dy * .34 + (same ? 2 : 0), z: b.z - dz * .12 - (same ? 2 : .4)};
  return Array.from({length: 29}, (_, i) => {
    const t = i / 28, u = 1 - t;
    const width = Math.sin(Math.PI * t) * fiber * .075;
    const angle = t * TAU * 1.5 + (seed % 100) + fiber * 1.7;
    return {x: u ** 3 * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t ** 3 * b.x + Math.cos(angle) * width,
      y: u ** 3 * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t ** 3 * b.y,
      z: u ** 3 * a.z + 3 * u * u * t * c1.z + 3 * u * t * t * c2.z + t ** 3 * b.z + Math.sin(angle) * width};
  });
}

// A primary path is chosen only from real trigger edges. Related links never
// contribute to branch mass, roots, or trunk selection.
export function treeStructure(nodes, links) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const children = new Map(nodes.map(n => [n.id, new Set()]));
  const incoming = new Set();
  for (const link of links) if (link.kind === 'trigger') {
    children.get(link.source).add(link.target); incoming.add(link.target);
  }
  const mass = new Map(), next = new Map();
  const ordered = [...nodes].sort((a,b) => b.rank-a.rank || a.id.localeCompare(b.id));
  for (const node of ordered) {
    const targets = [...children.get(node.id)].sort((a,b) =>
      mass.get(b)-mass.get(a) || Math.hypot(byId.get(a).x,byId.get(a).z)-Math.hypot(byId.get(b).x,byId.get(b).z) || a.localeCompare(b));
    // Saturation keeps reconverging DAGs from producing enormous trunk widths.
    mass.set(node.id, Math.min(1000, 1 + targets.reduce((sum,id) => sum + mass.get(id),0)));
    if (targets.length) next.set(node.id, targets[0]);
  }
  const roots = nodes.filter(n => !incoming.has(n.id) && children.get(n.id).size);
  const trunk = new Set();
  for (const root of roots) {
    let id = root.id;
    while (next.has(id)) {
      const target = next.get(id), key = JSON.stringify([id,target]);
      if (trunk.has(key)) break;
      trunk.add(key); id = target;
    }
  }
  return {roots, mass, trunk};
}

function randomSource(seed) {
  let state = seed;
  return () => { state = (Math.imul(state,1664525)+1013904223) >>> 0; return state/4294967296; };
}

// Sample a tapered tube in world space, so fibers and dust rotate with the tree.
export function branchGeometry(points, startRadius, endRadius, seed, ghost=false, detail=1) {
  const random = randomSource(seed);
  const sample = (t, angle, spread=1) => {
    const at = t*(points.length-1), i = Math.min(points.length-2,Math.floor(at)), f = at-i;
    const a=points[i], b=points[i+1];
    let dx=b.x-a.x, dy=b.y-a.y, dz=b.z-a.z;
    const length=Math.hypot(dx,dy,dz)||1; dx/=length;dy/=length;dz/=length;
    const horizontal=Math.hypot(dx,dy);
    const nx=horizontal>1e-6?dy/horizontal:1, ny=horizontal>1e-6?-dx/horizontal:0;
    const bx=-dz*ny, by=dz*nx, bz=dx*ny-dy*nx;
    const radius=(startRadius*(1-t)+endRadius*t)*spread;
    const u=Math.cos(angle)*radius, v=Math.sin(angle)*radius;
    return {x:a.x+(b.x-a.x)*f+nx*u+bx*v,y:a.y+(b.y-a.y)*f+ny*u+by*v,z:a.z+(b.z-a.z)*f+bz*v};
  };
  const fibers = ghost?[]:Array.from({length:Math.round(12*detail)},(_,i) =>
    Array.from({length:57},(_,j) => sample(j/56,i*2.39996+j/56*TAU*1.4,.8+.2*Math.sin(j*.7+i))));
  const count=Math.round((ghost?160:420)*detail);
  const dust=Array.from({length:count},()=>{
    const t=random(), angle=random()*TAU;
    const spread=ghost?.5+random()*2.5:Math.sqrt(random())*(random()<.15?1.8:1);
    return {...sample(t,angle,spread),alpha:.2+random()*.8,size:random()<.06?1.5:.45+random()*.65};
  });
  return {points,fibers,dust,startRadius,endRadius};
}

export class GraphRenderer {
  constructor(canvas, {onSelect, onZoom = () => {}}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    if (!this.ctx) throw new Error('当前浏览器无法创建画布，请换用支持 Canvas 的浏览器。');
    this.onSelect = onSelect;
    this.onZoom = onZoom;
    this.nodes = []; this.edges = []; this.stems = []; this.selected = null; this.hovered = null;
    this.showRelated = false; this.showLabels = true; this.glow = true; this.rotate = false;
    this.camera = {center: [0, 0, 0], radius: 10, distance: 40, yaw: -.45, pitch: .16, zoom: 1, panX: 0, panY: 0};
    this.projected = []; this.frame = null; this.lastTime = null;
    this.observer = new ResizeObserver(() => this.requestDraw());
    this.observer.observe(canvas);
    this.bindControls();
    document.addEventListener('visibilitychange', () => { this.lastTime = null; this.requestDraw(); });
  }

  setScene(scene) {
    const definitions = new Map(scene.graph.events.map(e => [e.id, e]));
    this.nodes = scene.layout.nodes.map(p => ({...p, label: definitions.get(p.id)?.description || p.id}));
    const byId = new Map(this.nodes.map(p => [p.id, p]));
    const structure = treeStructure(this.nodes,scene.layout.links);
    const detail = Math.min(this.nodes.length > 150 ? .15 : 1, 180 / Math.max(1,scene.layout.links.length));
    const radius = id => .12 + Math.sqrt(structure.mass.get(id) || 1)*.12;
    this.edges = scene.layout.links.map((link, index) => {
      const a = byId.get(link.source), b = byId.get(link.target);
      const related=link.kind==='related';
      const trunk=structure.trunk.has(JSON.stringify([link.source,link.target]));
      const seed=hash(`${link.result_id}:${link.target}`);
      const end=related?.22:radius(b.id)*(trunk?1:.6);
      const start=related?.4:radius(a.id)*(trunk?1:.5);
      const points=curvePoints(a,b,seed);
      if(related) points.forEach((p,i)=>{
        const arch=Math.sin(Math.PI*i/(points.length-1))*1.8;
        p.y+=arch;p.z+=arch*(seed%2?1:-1);
      });
      return {...link,index,trunk,geometry:branchGeometry(points,start,end,seed,related,detail)};
    });
    // Basal stems terminate at real causal roots; they carry no dependency.
    this.stems=structure.roots.map(root=>{
      const base={...root,x:root.x-.35,y:root.y-3,z:root.z+.25};
      return {source:root.id,target:root.id,kind:'stem',trunk:true,
        geometry:branchGeometry(curvePoints(base,{...root,id:root.id+'.base'},13),radius(root.id)*1.3,radius(root.id),hash(root.id),false,detail)};
    });
    this.selected = null; this.hovered = null; this.nearby = new Set();
    if (this.nodes.length) {
      const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
      for (const p of this.nodes) ['x','y','z'].forEach((key, i) => { min[i] = Math.min(min[i], p[key]); max[i] = Math.max(max[i], p[key]); });
      this.camera.center = min.map((v, i) => (v + max[i]) / 2);
      this.camera.radius = Math.max(5, ...max.map((v, i) => (v - min[i]) / 2)) * 1.18;
      this.groundY = min[1] - 3;
    } else {
      this.camera.center = [0,0,0]; this.camera.radius = 8; this.groundY = -2;
    }
    this.camera.distance = this.camera.radius * 4;
    this.ground = Array.from({length: 900}, (_, i) => {
      const angle = i * 2.399963, radius = Math.sqrt((i + .5) / 900) * this.camera.radius * 1.65;
      return {x: this.camera.center[0] + Math.cos(angle) * radius, y: this.groundY, z: this.camera.center[2] + Math.sin(angle) * radius};
    });
    this.reset();
  }

  select(id) {
    this.selected = id;
    this.nearby = new Set(id ? [id] : []);
    for (const edge of this.edges) if (edge.source === id || edge.target === id) {
      this.nearby.add(edge.source); this.nearby.add(edge.target);
    }
    this.requestDraw();
  }

  reset(front = false) {
    Object.assign(this.camera, {yaw: front ? 0 : -.45, pitch: front ? 0 : .16, zoom: 1, panX: 0, panY: 0});
    this.onZoom(1); this.requestDraw();
  }

  zoomBy(factor) {
    this.camera.zoom = clamp(this.camera.zoom * factor, .3, 4);
    this.onZoom(this.camera.zoom); this.requestDraw();
  }

  setOption(name, value) { this[name] = value; this.requestDraw(); }

  requestDraw() {
    if (this.frame === null && !document.hidden) this.frame = requestAnimationFrame(t => {
      this.frame = null;
      if (this.rotate && this.lastTime !== null) this.camera.yaw += Math.min(t - this.lastTime, 50) * .00015;
      this.lastTime = t;
      this.draw();
      if (this.rotate) this.requestDraw(); else this.lastTime = null;
    });
  }

  bindControls() {
    const pointers = new Map();
    let down = null, pinch = null;
    const distance = () => { const p = [...pointers.values()]; return Math.hypot(p[0].x-p[1].x, p[0].y-p[1].y); };
    this.canvas.addEventListener('pointerdown', e => {
      this.canvas.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, {x:e.clientX,y:e.clientY});
      down = {x:e.clientX,y:e.clientY,lastX:e.clientX,lastY:e.clientY,moved:false,pan:e.shiftKey || e.button !== 0};
      if (pointers.size === 2) { pinch = {distance:distance(), zoom:this.camera.zoom}; down.moved = true; }
      this.canvas.classList.add('dragging');
    });
    this.canvas.addEventListener('pointermove', e => {
      if (pointers.has(e.pointerId)) {
        pointers.set(e.pointerId, {x:e.clientX,y:e.clientY});
        if (pointers.size === 2 && pinch) {
          this.camera.zoom = clamp(pinch.zoom * distance()/Math.max(pinch.distance,1),.3,4);
          this.onZoom(this.camera.zoom);
        } else if (down) {
          const dx=e.clientX-down.lastX, dy=e.clientY-down.lastY;
          down.moved ||= Math.hypot(e.clientX-down.x,e.clientY-down.y)>4;
          if (down.pan) { this.camera.panX+=dx; this.camera.panY+=dy; }
          else { this.camera.yaw += dx*.006; this.camera.pitch = clamp(this.camera.pitch+dy*.004,-.55,.55); }
          down.lastX=e.clientX; down.lastY=e.clientY;
        }
        this.requestDraw();
      } else {
        const id=this.hit(e);
        if (id!==this.hovered) { this.hovered=id; this.canvas.classList.toggle('over-node',!!id); this.requestDraw(); }
      }
    });
    const finish = e => {
      if (e.type==='pointerup' && down && !down.moved && pointers.size===1) this.onSelect(this.hit(e));
      pointers.delete(e.pointerId); pinch=null;
      if (!pointers.size) { down=null; this.canvas.classList.remove('dragging'); }
      else if (down) { const p=[...pointers.values()][0]; down.lastX=p.x; down.lastY=p.y; down.moved=true; }
    };
    this.canvas.addEventListener('pointerup',finish);
    this.canvas.addEventListener('pointercancel',finish);
    this.canvas.addEventListener('lostpointercapture',finish);
    this.canvas.addEventListener('pointerleave',()=>{ this.hovered=null; this.requestDraw(); });
    this.canvas.addEventListener('contextmenu',e=>e.preventDefault());
    this.canvas.addEventListener('wheel',e=>{ e.preventDefault(); this.zoomBy(Math.exp(-clamp(e.deltaY,-150,150)*.002)); },{passive:false});
    this.canvas.addEventListener('keydown',e=>{
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home','Escape'].includes(e.key)) return;
      e.preventDefault();
      if (e.key==='ArrowLeft') this.camera.yaw-=.12;
      if (e.key==='ArrowRight') this.camera.yaw+=.12;
      if (e.key==='ArrowUp') this.camera.pitch=clamp(this.camera.pitch-.08,-.55,.55);
      if (e.key==='ArrowDown') this.camera.pitch=clamp(this.camera.pitch+.08,-.55,.55);
      if (e.key==='+' || e.key==='=') this.zoomBy(1.15);
      if (e.key==='-') this.zoomBy(1/1.15);
      if (e.key==='Home') this.reset();
      if (e.key==='Escape') this.onSelect(null);
      this.requestDraw();
    });
  }

  hit(e) {
    const rect=this.canvas.getBoundingClientRect(), x=e.clientX-rect.left, y=e.clientY-rect.top;
    let best=null, distance=20;
    for (const p of this.projected) {
      const d=Math.hypot(x-p.x,y-p.y);
      if (d<distance) { distance=d; best=p.id; }
    }
    return best;
  }

  draw() {
    const rect=this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr=Math.min(devicePixelRatio||1,2), ctx=this.ctx;
    const width=rect.width, height=rect.height;
    if (this.canvas.width!==Math.round(width*dpr) || this.canvas.height!==Math.round(height*dpr)) {
      this.canvas.width=Math.round(width*dpr); this.canvas.height=Math.round(height*dpr);
    }
    ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,width,height);
    this.labelTop = width < 500 ? 138 : 92;
    const project=p=>projectPoint(p,this.camera,{width,height,top:this.labelTop,bottom:65});
    const fog=ctx.createRadialGradient(width*.5,height*.55,0,width*.5,height*.55,height*.58);
    fog.addColorStop(0,'rgba(8,52,104,.15)'); fog.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=fog; ctx.fillRect(0,0,width,height);
    for (const p of this.ground || []) {
      const q=project(p);
      ctx.fillStyle='rgba(65,175,250,.34)'; ctx.fillRect(q.x,q.y,1.3*q.perspective,1.3*q.perspective);
    }
    const visibleEdges=this.edges.filter(e=>e.kind==='trigger' || this.showRelated || e.source===this.selected || e.target===this.selected);
    const projectedEdges=[...this.stems,...visibleEdges].map(edge=>({...edge,points:edge.geometry.points.map(project)}));
    projectedEdges.sort((a,b)=>a.points[14].depth-b.points[14].depth);
    ctx.lineCap='round'; ctx.lineJoin='round';
    const path=points=>{ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));};
    for (const edge of projectedEdges) {
      const involved=!this.selected || edge.source===this.selected || edge.target===this.selected;
      const ghost=edge.kind==='related', alpha=involved?1:.14;
      const main=edge.points, geometry=edge.geometry;
      // A faint volume under the fibers gives causal branches physical weight.
      if (!ghost) {
        const worldScale=Math.min(width-28,height-this.labelTop-65)/(2*this.camera.radius)*.92*this.camera.zoom;
        const sides=[[],[]];
        for (let i=0;i<main.length;i++) {
          const t=i/(main.length-1), radius=geometry.startRadius*(1-t)+geometry.endRadius*t;
          const before=main[Math.max(0,i-1)], after=main[Math.min(main.length-1,i+1)];
          const dx=after.x-before.x,dy=after.y-before.y,length=Math.hypot(dx,dy)||1;
          const r=radius*worldScale*main[i].perspective;
          sides[0].push({x:main[i].x-dy/length*r,y:main[i].y+dx/length*r});
          sides[1].push({x:main[i].x+dy/length*r,y:main[i].y-dx/length*r});
        }
        path([...sides[0],...sides[1].reverse()]);ctx.closePath();
        ctx.fillStyle='#07549d';ctx.globalAlpha=alpha*.3;ctx.fill();
        if(this.glow) {
          ctx.strokeStyle='#097dff';ctx.lineWidth=7;ctx.globalAlpha=alpha*.055;ctx.stroke();
        }
        ctx.strokeStyle=palette.blue;ctx.lineWidth=.65;ctx.globalAlpha=alpha*.6;
        for (const fiber of geometry.fibers) {path(fiber.map(project));ctx.stroke();}
      } else {
        ctx.setLineDash([1,12]);ctx.lineWidth=.6;ctx.strokeStyle=palette.cyan;ctx.globalAlpha=alpha*.16;
        path(main);ctx.stroke();ctx.setLineDash([]);
      }
      ctx.fillStyle=ghost?'#70c5f2':'#5ccfff';
      for(const dust of geometry.dust) {
        const p=project(dust), size=dust.size*clamp(p.perspective,.6,1.5);
        ctx.globalAlpha=alpha*dust.alpha*(ghost?.65:.8);
        ctx.fillRect(p.x,p.y,size,size);
        if(this.glow && dust.size>1.4) {
          ctx.globalAlpha=alpha*.08;ctx.fillRect(p.x-2,p.y-2,5,5);
        }
      }
      // Direction is shown on focus; the resting view reads as a tree.
      if(this.selected && involved && edge.kind!=='stem') {
        const p=main[23],before=main[21],angle=Math.atan2(p.y-before.y,p.x-before.x);
        ctx.globalAlpha=ghost?.5:.9;ctx.fillStyle=palette.cyan;
        ctx.beginPath();ctx.moveTo(p.x,p.y);
        ctx.lineTo(p.x-Math.cos(angle-.4)*7,p.y-Math.sin(angle-.4)*7);
        ctx.lineTo(p.x-Math.cos(angle+.4)*7,p.y-Math.sin(angle+.4)*7);ctx.closePath();ctx.fill();
      }
    }
    ctx.globalAlpha=1;
    this.projected=this.nodes.map(p=>({...p,...project(p)})).sort((a,b)=>a.depth-b.depth);
    for (const p of this.projected) {
      const active=p.id===this.selected, hover=p.id===this.hovered;
      const alpha=!this.selected||this.nearby.has(p.id)?1:.2;
      const radius=(active?5:3.2)*clamp(p.perspective,.8,1.4);
      ctx.globalAlpha=alpha;
      if (this.glow) {
        const bloom=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,active?30:19);
        bloom.addColorStop(0,'rgba(98,229,255,.4)'); bloom.addColorStop(.3,'rgba(30,130,255,.18)');bloom.addColorStop(1,'rgba(0,70,255,0)');
        ctx.fillStyle=bloom;ctx.beginPath();ctx.arc(p.x,p.y,active?30:19,0,TAU);ctx.fill();
      }
      ctx.strokeStyle=active?palette.cyan:'rgba(62,157,246,.6)';ctx.lineWidth=active?1.4:.7;
      ctx.beginPath();ctx.arc(p.x,p.y,radius+(active||hover?7:3),0,TAU);ctx.stroke();
      ctx.fillStyle=active?'#defbff':(hover?palette.cyan:'#67cfff');ctx.beginPath();ctx.arc(p.x,p.y,radius,0,TAU);ctx.fill();
    }
    ctx.globalAlpha=1;
    this.labels(ctx,width,height);
  }

  labels(ctx,width,height) {
    const candidates=this.projected.filter(p=>this.showLabels||p.id===this.selected||p.id===this.hovered);
    candidates.sort((a,b)=>(b.id===this.selected)*4+(b.id===this.hovered)*2-(a.id===this.selected)*4-(a.id===this.hovered)*2 || b.depth-a.depth);
    const boxes=[];
    ctx.font='12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    for (const p of candidates) {
      if (this.selected&&!this.nearby.has(p.id)&&p.id!==this.hovered) continue;
      const text=p.label.length>16?p.label.slice(0,15)+'…':p.label;
      const w=ctx.measureText(text).width+12, h=23;
      const places=[[p.x+12,p.y-11],[p.x-w-12,p.y-11],[p.x-w/2,p.y+14]];
      if (width < 500 && boxes.length >= 9 && p.id !== this.selected && p.id !== this.hovered) continue;
      const place=places.find(([x,y])=>x>=10&&y>=this.labelTop&&x+w<width-10&&y+h<height-65&&!boxes.some(b=>x<b.x+b.w+5&&x+w+5>b.x&&y<b.y+b.h+4&&y+h+4>b.y));
      if (!place) continue;
      const [x,y]=place; boxes.push({x,y,w,h});
      ctx.fillStyle='rgba(3,10,21,.84)';ctx.fillRect(x,y,w,h);
      ctx.fillStyle=p.id===this.selected?'#d9fbff':'#a4c2d9';ctx.fillText(text,x+6,y+16);
    }
  }
}
