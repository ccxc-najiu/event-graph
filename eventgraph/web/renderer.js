// A dependency-free 3D camera and canvas renderer. Input coordinates stay intact.
const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const palette = {blue: '#268bff', cyan: '#75edff', faint: '#51768d'};

function projectionScale(camera, viewport) {
  const padding=viewport.width<500?96:28;
  const availableHeight=viewport.height-(viewport.top||0)-(viewport.bottom||0);
  return Math.max(1,Math.min(viewport.width-padding,availableHeight))/(2*camera.radius)*.92*camera.zoom;
}

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
  const scale = projectionScale(camera, viewport);
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

// Related links drape between their real endpoints like flexible vines.
export function vinePoints(a, b, seed) {
  const dx=b.x-a.x,dy=b.y-a.y,dz=b.z-a.z;
  const horizontal=Math.hypot(dx,dz),length=Math.hypot(dx,dy,dz);
  const direction=a.id<b.id?1:-1;
  if(length<1e-8) {
    // A closed, hanging loop remains visible for a self relation.
    return Array.from({length:29},(_,i)=>{
      const t=i/28,angle=t*TAU;
      if(i===0||i===28) return {x:a.x,y:a.y,z:a.z};
      return {x:a.x+Math.sin(angle)*1.1,y:a.y-(1-Math.cos(angle))*.85,
        z:a.z+(1-Math.cos(angle))*.45};
    });
  }
  let nx=horizontal>1e-8?-dz/horizontal:1,nz=horizontal>1e-8?dx/horizontal:0;
  // Bend away from the trunk. Canonical orientation keeps reciprocal vines
  // beside each other instead of making them cross in the middle.
  const outward=nx*(a.x+b.x)+nz*(a.z+b.z);
  if(outward<0||(Math.abs(outward)<1e-8&&direction<0)) {nx=-nx;nz=-nz;}
  const bow=Math.min(1.8,length*.10)+direction*Math.min(.24,length*.035);
  const sag=Math.min(3.2,horizontal*.20);
  const twist=((seed%11)/10-.5)*Math.min(.18,length*.015);
  return Array.from({length:29},(_,i)=>{
    if(i===0) return {x:a.x,y:a.y,z:a.z};
    if(i===28) return {x:b.x,y:b.y,z:b.z};
    const t=i/28,u=1-t,envelope=4*t*u;
    const bend=envelope*(bow+twist*(2*t-1));
    return {x:a.x+dx*t+nx*bend,y:a.y+dy*t-sag*envelope,
      z:a.z+dz*t+nz*bend};
  });
}

// Only trigger predecessors determine whether an event grows from the trunk.
// These root supports are decoration and never become business connections.
export function rootBranches(nodes, links, gap) {
  const incoming = new Set(links.filter(e => e.kind === 'trigger').map(e => e.target));
  return nodes.filter(n => !incoming.has(n.id)).map(node => {
    const base = {x: 0, y: node.y - gap * .75, z: 0};
    return {source: null, target: node.id, kind: 'root',
      points: curvePoints(base, node, hash(node.id))};
  });
}

export function treeStem(nodes, gap) {
  if (!nodes.length) return [];
  const min = Math.min(...nodes.map(n => n.y)) - gap * 1.5;
  const max = Math.max(...nodes.map(n => n.y)) + gap * .65;
  return Array.from({length: 29}, (_, i) => ({x: 0, y: min + (max - min) * i / 28, z: 0}));
}

// One radius per junction: incoming ends and outgoing starts share this value.
// Only unique trigger successors add visual branch weight; related links and
// duplicate result ports cannot inflate it. Saturation bounds reconverging DAGs.
export function branchRadii(nodes, links) {
  const children=new Map(nodes.map(n=>[n.id,new Set()]));
  for(const link of links) if(link.kind==='trigger') children.get(link.source).add(link.target);
  const mass=new Map(), radii=new Map();
  for(const node of [...nodes].sort((a,b)=>b.rank-a.rank||a.id.localeCompare(b.id))) {
    let value=1;
    for(const child of [...children.get(node.id)].sort()) value+=mass.get(child);
    value=Math.min(1000000,value);
    mass.set(node.id,value);
    radii.set(node.id,Math.min(.6,.085+.055*Math.log2(1+value)));
  }
  return radii;
}

export function radiusBetween(start, end, t) {
  const u=clamp(t,0,1);
  if(u===0) return start;
  if(u===1) return end;
  return start+(end-start)*u*u*(3-2*u);
}

// The trunk also shares its local radius with each supporting root branch.
export function trunkProfile(stem, roots, radii) {
  if(!stem.length) return () => 0;
  const anchors=new Map([[stem[0].y,.85],[stem.at(-1).y,.06]]);
  for(const root of roots) {
    const y=root.points[0].y;
    anchors.set(y,Math.max(anchors.get(y)||0,radii.get(root.target)+.06));
  }
  const ordered=[...anchors].sort((a,b)=>a[0]-b[0]);
  for(let i=ordered.length-2;i>=0;i--) ordered[i][1]=Math.max(ordered[i][1],ordered[i+1][1]);
  return y=>{
    if(y<=ordered[0][0]) return ordered[0][1];
    let lo=0,hi=ordered.length-1;
    while(lo+1<hi) {const mid=(lo+hi)>>1;if(ordered[mid][0]<=y) lo=mid;else hi=mid;}
    const [a,ra]=ordered[lo], [b,rb]=ordered[hi];
    return radiusBetween(ra,rb,(y-a)/(b-a));
  };
}

// Deterministic, bounded ornamental growth. Only real nodes are selectable;
// these twigs never enter the graph, trigger rules, or exported layout.
export function naturalCanopy(nodes, gap) {
  const twigs = [], motes = [];
  const ordered = [...nodes].sort((a,b) => a.id.localeCompare(b.id));
  const maxRank = Math.max(0, ...nodes.map(n => n.rank));
  const candidates = ordered.filter(n => maxRank === 0 || n.rank > 0);
  const stride = Math.max(1, Math.ceil(candidates.length / 48));
  for (let index = 0; index < candidates.length; index += stride) {
    const node = candidates[index];
    let seed = hash(node.id);
    const random = () => {seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
    const angle = Math.hypot(node.x,node.z) > .1 ? Math.atan2(node.z,node.x) : random()*TAU;
    const grow = (a, length, heading, depth) => {
      if (twigs.length >= 4500) return;
      const b = {x:a.x+Math.cos(heading)*length,
        y:a.y+length*(.35+random()*.5),z:a.z+Math.sin(heading)*length};
      const mid = {x:(a.x+b.x)/2, y:(a.y+b.y)/2-length*.12, z:(a.z+b.z)/2};
      twigs.push({owner:node.id,points:[a,mid,b],radius:.018+depth*.027});
      for (let i=0;i<4;i++) {
        const t=random();
        motes.push({owner:node.id,x:a.x+(b.x-a.x)*t+(random()-.5)*.3,
          y:a.y+(b.y-a.y)*t+(random()-.5)*.4,z:a.z+(b.z-a.z)*t+(random()-.5)*.3,
          size:.5+random(),alpha:.25+random()*.65});
      }
      if (depth) for (const side of [-1,1]) grow(b,length*(.57+random()*.12),heading+side*(.35+random()*.55),depth-1);
    };
    const depth = candidates.length <= 32 ? 4 : 3;
    for (const side of [-1,0,1]) grow(node,gap*(.38+random()*.28),angle+side*.9,depth);
  }
  return {twigs,motes};
}

export class GraphRenderer {
  constructor(canvas, {onSelect, onZoom = () => {}}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    if (!this.ctx) throw new Error('当前浏览器无法创建画布，请换用支持 Canvas 的浏览器。');
    this.onSelect = onSelect;
    this.onZoom = onZoom;
    this.nodes = []; this.edges = []; this.stem = []; this.roots = []; this.selected = null; this.hovered = null;
    this.form = 'simple'; this.canopy = null; this.pointer = null;
    this.showRelated = true; this.showLabels = true; this.glow = true; this.rotate = false;
    this.camera = {center: [0, 0, 0], radius: 10, distance: 40, yaw: -.45, pitch: .16, zoom: 1, panX: 0, panY: 0};
    this.projected = []; this.frame = null; this.lastTime = null;
    this.observer = new ResizeObserver(() => this.requestDraw());
    this.observer.observe(canvas);
    this.bindControls();
    document.addEventListener('visibilitychange', () => { this.lastTime = null; this.requestDraw(); });
  }

  setScene(scene) {
    this.canopy = null;
    const definitions = new Map(scene.graph.events.map(e => [e.id, e]));
    this.nodes = scene.layout.nodes.map(p => ({...p, label: definitions.get(p.id)?.description || p.id}));
    const byId = new Map(this.nodes.map(p => [p.id, p]));
    this.edges = scene.layout.links.map((link, index) => {
      const a = byId.get(link.source), b = byId.get(link.target);
      const seed = hash(`${link.result_id}:${link.target}`);
      const points = link.kind === 'related' ? vinePoints(a,b,seed) : curvePoints(a,b,seed);
      return {...link, index, points};
    });
    this.layerSpacing = scene.layout.layer_spacing;
    this.stem = treeStem(this.nodes, scene.layout.layer_spacing);
    this.roots = rootBranches(this.nodes, scene.layout.links, scene.layout.layer_spacing);
    // Include every root attachment in the trunk mesh, avoiding interpolation
    // across a radius anchor at the exact point where a support joins it.
    this.stem = [...new Set([...this.stem.map(p=>p.y), ...this.roots.map(r=>r.points[0].y)])]
      .sort((a,b)=>a-b).map(y=>({x:0,y,z:0}));
    this.radii = branchRadii(this.nodes, scene.layout.links);
    this.trunkRadius = trunkProfile(this.stem, this.roots, this.radii);
    this.selected = null; this.hovered = null; this.nearby = new Set();
    if (this.nodes.length) {
      const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
      for (const p of [...this.nodes, ...this.stem]) ['x','y','z'].forEach((key, i) => { min[i] = Math.min(min[i], p[key]); max[i] = Math.max(max[i], p[key]); });
      this.camera.center = min.map((v, i) => (v + max[i]) / 2);
      this.camera.radius = Math.max(5, ...max.map((v, i) => (v - min[i]) / 2)) * 1.18;
      this.groundY = min[1];
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

  setForm(form) {
    if (!['simple','natural'].includes(form)) return;
    this.form = form;
    this.requestDraw();
  }

  drawNatural(project, width, height) {
    const ctx=this.ctx;
    this.canopy ||= naturalCanopy(this.nodes,this.layerSpacing);
    const scale=projectionScale(this.camera,{width,height,top:this.labelTop,bottom:65});
    const stroke=(points,color,lineWidth,alpha)=>{
      ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));
      ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.globalAlpha=alpha;ctx.stroke();
    };
    const tube=(points,start,end,alpha,profile=null)=>{
      const main=points.map(project), left=[],right=[];
      for(let i=0;i<main.length;i++) {
        const before=main[Math.max(0,i-1)],after=main[Math.min(main.length-1,i+1)];
        const dx=after.x-before.x,dy=after.y-before.y,len=Math.hypot(dx,dy)||1;
        const radius=profile?profile(points[i].y):radiusBetween(start,end,i/(main.length-1));
        const r=radius*scale*main[i].perspective;
        left.push({x:main[i].x-dy/len*r,y:main[i].y+dx/len*r});
        right.push({x:main[i].x+dy/len*r,y:main[i].y-dx/len*r});
      }
      const outline=[...left,...[...right].reverse()];
      ctx.beginPath();outline.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();
      ctx.fillStyle='#287fd2';ctx.globalAlpha=alpha*.85;ctx.fill();
      if(this.glow) {stroke(left,'#268bff',5,alpha*.12);stroke(right,'#268bff',5,alpha*.12);}
      stroke(left,'#79ceff',.8,alpha*.65);
      stroke(main,'#c5f3ff',.65,alpha*.7);
    };
    const physical=[...this.roots,...this.edges.filter(e=>e.kind==='trigger')];
    // The straight trunk remains the common support, with a flared root base.
    if(this.stem.length) {
      tube(this.stem,0,0,1,this.trunkRadius);
      const base=this.stem[0];
      for(let i=0;i<8;i++) {
        const angle=i*TAU/8;
        const end={x:Math.cos(angle)*2.2,y:base.y-.12,z:Math.sin(angle)*2.2};
        const start={x:0,y:base.y+2,z:0};
        tube(curvePoints(start,end,i),.38,.02,.7);
      }
      // Bark fibers rotate in world space, rather than being a screen texture.
      for(let j=0;j<11;j++) {
        const fiber=this.stem.map((p,i)=>{
          const t=i/(this.stem.length-1),angle=j*TAU/11+Math.sin(t*8+j)*.12;
          const radius=this.trunkRadius(p.y)*.95;
          return project({x:Math.cos(angle)*radius,y:p.y,z:Math.sin(angle)*radius});
        });
        stroke(fiber,j%2?'#85d9ff':'#438cc9',.65,.55);
      }
    }
    physical.sort((a,b)=>project(a.points[14]).depth-project(b.points[14]).depth);
    for(const edge of physical) {
      const alpha=!this.selected||edge.source===this.selected||edge.target===this.selected?1:.13;
      const start=edge.kind==='root'?this.trunkRadius(edge.points[0].y):this.radii.get(edge.source);
      tube(edge.points,start,this.radii.get(edge.target),alpha);
    }
    // Cover small wedges between differently oriented tube silhouettes at a
    // junction, without a bright end cap or a change of diameter.
    for(const node of this.nodes) {
      const p=project(node),r=this.radii.get(node.id)*scale*p.perspective;
      ctx.globalAlpha=(!this.selected||this.nearby.has(node.id)?1:.13)*.85;
      ctx.fillStyle='#287fd2';ctx.beginPath();ctx.arc(p.x,p.y,r,0,TAU);ctx.fill();
    }
    const twigs=this.canopy.twigs.map(t=>({...t,projected:t.points.map(project)}));
    twigs.sort((a,b)=>a.projected[1].depth-b.projected[1].depth);
    for(const twig of twigs) {
      const alpha=!this.selected||this.nearby.has(twig.owner)?1:.08;
      const thickness=Math.max(.35,twig.radius*scale*twig.projected[1].perspective);
      if(this.glow) stroke(twig.projected,'#268bff',thickness+3,alpha*.085);
      stroke(twig.projected,'#79ceff',thickness,alpha*.65);
    }
    for(const mote of this.canopy.motes) {
      const p=project(mote),alpha=!this.selected||this.nearby.has(mote.owner)?1:.06;
      const size=mote.size*clamp(p.perspective,.6,1.5);
      ctx.globalAlpha=alpha*mote.alpha;ctx.fillStyle='#c5f3ff';ctx.fillRect(p.x,p.y,size,size);
      if(this.glow&&mote.size>1.2) {
        ctx.globalAlpha=alpha*.09;ctx.fillStyle='#49b5ff';ctx.fillRect(p.x-2,p.y-2,5,5);
      }
    }
    ctx.globalAlpha=1;
  }

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
      this.pointer=null; this.hovered=null;
      this.canvas.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, {x:e.clientX,y:e.clientY});
      down = {x:e.clientX,y:e.clientY,lastX:e.clientX,lastY:e.clientY,moved:false,pan:e.shiftKey || e.button !== 0};
      if (pointers.size === 2) { pinch = {distance:distance(), zoom:this.camera.zoom}; down.moved = true; }
      this.canvas.classList.add('dragging');
      this.requestDraw();
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
        this.pointer=e.pointerType==='touch'?null:{clientX:e.clientX,clientY:e.clientY};
        const id=this.pointer?this.hit(this.pointer,28):null;
        if (id!==this.hovered) { this.hovered=id; this.canvas.classList.toggle('over-node',!!id); this.requestDraw(); }
      }
    });
    const finish = e => {
      if (!pointers.has(e.pointerId)) return;
      if (e.type==='pointerup' && down && !down.moved && pointers.size===1) this.onSelect(this.hit(e));
      pointers.delete(e.pointerId); pinch=null;
      this.pointer=e.type==='pointerup'&&e.pointerType==='mouse'?{clientX:e.clientX,clientY:e.clientY}:null;
      this.requestDraw();
      if (!pointers.size) { down=null; this.canvas.classList.remove('dragging'); }
      else if (down) { const p=[...pointers.values()][0]; down.lastX=p.x; down.lastY=p.y; down.moved=true; }
    };
    this.canvas.addEventListener('pointerup',finish);
    this.canvas.addEventListener('pointercancel',finish);
    this.canvas.addEventListener('lostpointercapture',finish);
    this.canvas.addEventListener('pointerleave',()=>{ this.pointer=null; this.hovered=null; this.canvas.classList.remove('over-node'); this.requestDraw(); });
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

  hit(e, threshold = 20) {
    const rect=this.canvas.getBoundingClientRect(), x=e.clientX-rect.left, y=e.clientY-rect.top;
    let best=null, distance=threshold;
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
    const natural=this.form==='natural';
    const fog=ctx.createRadialGradient(width*.5,height*.55,0,width*.5,height*.55,height*.58);
    fog.addColorStop(0,natural?'rgba(8,52,104,.22)':'rgba(8,52,104,.15)'); fog.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=fog; ctx.fillRect(0,0,width,height);
    for (const p of this.ground || []) {
      const q=project(natural?{...p,y:p.y+Math.sin(p.x*.45+p.z*.28)*.65}:p);
      ctx.fillStyle=natural?'rgba(65,175,250,.5)':'rgba(65,175,250,.34)'; ctx.fillRect(q.x,q.y,1.3*q.perspective,1.3*q.perspective);
    }
    ctx.lineCap='round'; ctx.lineJoin='round';
    const path=points=>{ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));};
    if(natural) this.drawNatural(project,width,height);
    // One straight tree trunk, separate from the actual trigger branches.
    if (!natural && this.stem.length) {
      const stem=this.stem.map(project);
      path(stem); ctx.globalAlpha=1;
      if (this.glow) {ctx.strokeStyle='rgba(65,159,255,.12)';ctx.lineWidth=9;ctx.stroke();}
      ctx.strokeStyle='#277dce';ctx.lineWidth=5;ctx.stroke();
      ctx.strokeStyle='#85d9ff';ctx.lineWidth=1.8;ctx.stroke();
    }
    const visibleEdges=this.edges.filter(e=>e.kind==='trigger' || this.showRelated || e.source===this.selected || e.target===this.selected);
    const projectedEdges=[...this.roots,...visibleEdges].map(edge=>({...edge,points:edge.points.map(project)}));
    projectedEdges.sort((a,b)=>a.points[14].depth-b.points[14].depth);
    for (const edge of projectedEdges) {
      const involved=!this.selected || edge.source===this.selected || edge.target===this.selected;
      const related=edge.kind==='related', alpha=involved?1:.14;
      const main=edge.points;
      path(main);
      if (related) {
        const focused = this.selected && involved;
        const thickness=1.45*clamp(main[14].perspective,.8,1.4);
        if (this.glow) {
          ctx.strokeStyle='#68c7ee';ctx.lineWidth=thickness+3;
          ctx.globalAlpha=alpha*.08;ctx.stroke();
        }
        const first=main[0],last=main.at(-1);
        const tintEnd=Math.hypot(last.x-first.x,last.y-first.y)<1?main[14]:last;
        const tint=ctx.createLinearGradient(first.x,first.y,tintEnd.x,tintEnd.y);
        tint.addColorStop(0,'#408daf');tint.addColorStop(.48,'#82c9d7');tint.addColorStop(1,'#408daf');
        // One continuous ribbon avoids bright beads at segment joins.
        const sides=main.map((p,i)=>{
          const before=main[Math.max(0,i-1)],after=main[Math.min(main.length-1,i+1)];
          const dx=after.x-before.x,dy=after.y-before.y,len=Math.hypot(dx,dy)||1;
          const radius=thickness*(.42+.12*Math.sin(Math.PI*i/(main.length-1)));
          return [{x:p.x-dy/len*radius,y:p.y+dx/len*radius},
            {x:p.x+dy/len*radius,y:p.y-dx/len*radius}];
        });
        path([...sides.map(s=>s[0]),...sides.map(s=>s[1]).reverse()]);ctx.closePath();
        ctx.fillStyle=tint;ctx.globalAlpha=alpha*(focused?1:.9);ctx.fill();
        path(main);ctx.strokeStyle='#c1ebef';ctx.lineWidth=.4;
        ctx.globalAlpha=alpha*(focused?.7:.38);ctx.stroke();
        if(natural) for(const [i,side] of [[9,1],[19,-1]]) {
          const p=main[i],next=main[i+1],angle=Math.atan2(next.y-p.y,next.x-p.x)+side*.65;
          const size=clamp(Math.hypot(last.x-first.x,last.y-first.y)*.065,2,4.5);
          const tx=p.x+Math.cos(angle)*size,ty=p.y+Math.sin(angle)*size;
          const nx=-Math.sin(angle)*size*.28,ny=Math.cos(angle)*size*.28;
          ctx.beginPath();ctx.moveTo(p.x,p.y);
          ctx.quadraticCurveTo((p.x+tx)/2+nx,(p.y+ty)/2+ny,tx,ty);
          ctx.quadraticCurveTo((p.x+tx)/2-nx,(p.y+ty)/2-ny,p.x,p.y);
          ctx.fillStyle='#72b7c7';ctx.globalAlpha=alpha*(focused?.8:.58);ctx.fill();
        }
      } else if (!natural) {
        const thickness=3.4*clamp(main[14].perspective,.8,1.4);
        if (this.glow) {
          ctx.strokeStyle=palette.blue;ctx.lineWidth=thickness+5;
          ctx.globalAlpha=alpha*.12;ctx.stroke();
        }
        // An opaque body and a narrow lit core read as a dense solid branch.
        ctx.strokeStyle='#287fd2';ctx.lineWidth=thickness;ctx.globalAlpha=alpha;ctx.stroke();
        ctx.strokeStyle='#79ceff';ctx.lineWidth=thickness*.36;
        ctx.globalAlpha=alpha*.95;ctx.stroke();
      }
      if(this.selected && involved && edge.kind !== 'root') {
        const p=main[23],before=main[21],angle=Math.atan2(p.y-before.y,p.x-before.x);
        ctx.globalAlpha=related?.65:.95;ctx.fillStyle=related?'#b3eced':palette.cyan;
        ctx.beginPath();ctx.moveTo(p.x,p.y);
        ctx.lineTo(p.x-Math.cos(angle-.4)*6,p.y-Math.sin(angle-.4)*6);
        ctx.lineTo(p.x-Math.cos(angle+.4)*6,p.y-Math.sin(angle+.4)*6);ctx.closePath();ctx.fill();
      }
    }
    ctx.globalAlpha=1;
    this.projected=this.nodes.map(p=>({...p,...project(p)})).sort((a,b)=>a.depth-b.depth);
    this.hovered=this.pointer?this.hit(this.pointer,28):null;
    this.canvas.classList.toggle('over-node',!!this.hovered);
    for (const p of this.projected) {
      const active=p.id===this.selected, hover=p.id===this.hovered;
      const alpha=!this.selected||this.nearby.has(p.id)?1:.2;
      const radius=(active?5:3.2)*clamp(p.perspective,.8,1.4);
      ctx.globalAlpha=alpha;
      if (this.glow) {
        const bloom=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,active?30:19);
        bloom.addColorStop(0,natural?'rgba(98,229,255,.65)':'rgba(98,229,255,.4)'); bloom.addColorStop(.3,natural?'rgba(30,130,255,.3)':'rgba(30,130,255,.18)');bloom.addColorStop(1,'rgba(0,70,255,0)');
        ctx.fillStyle=bloom;ctx.beginPath();ctx.arc(p.x,p.y,active?30:19,0,TAU);ctx.fill();
      }
      ctx.strokeStyle=active?(natural?'#75edff':palette.cyan):(natural?'rgba(62,157,246,.6)':'rgba(62,157,246,.6)');ctx.lineWidth=active?1.4:.7;
      ctx.beginPath();ctx.arc(p.x,p.y,radius+(active||hover?7:3),0,TAU);ctx.stroke();
      ctx.fillStyle=natural?(active?'#defbff':'#67cfff'):(active?'#defbff':(hover?palette.cyan:'#67cfff'));ctx.beginPath();ctx.arc(p.x,p.y,radius,0,TAU);ctx.fill();
    }
    ctx.globalAlpha=1;
    this.labels(ctx,width,height);
  }

  labels(ctx,width,height) {
    const p=this.showLabels?this.projected.find(p=>p.id===this.hovered):null;
    if (!p) return;
    ctx.font='12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    const text=p.label.length>16?p.label.slice(0,15)+'…':p.label;
    const w=ctx.measureText(text).width+12, h=23;
    const places=[[p.x+12,p.y-11],[p.x-w-12,p.y-11],[p.x-w/2,p.y+14]];
    const place=places.find(([x,y])=>x>=10&&y>=this.labelTop&&x+w<width-10&&y+h<height-65);
    if (!place) return;
    const [x,y]=place;
    ctx.fillStyle='rgba(3,10,21,.84)';ctx.fillRect(x,y,w,h);
    ctx.fillStyle='#d9fbff';ctx.fillText(text,x+6,y+16);
  }
}
