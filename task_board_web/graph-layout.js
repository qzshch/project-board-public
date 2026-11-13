'use strict';
// Uses only recorded edges. Containment is layout context, never a prerequisite.
function projectGraph(nodes,edges,{family='',query='',mode='all'}={}) {
  const byId=new Map(nodes.map(n=>[n.id,n]));
  let links=edges.filter(e=>byId.has(e.from)&&byId.has(e.to)&&['hard','containment'].includes(e.type));
  let selected=new Set(byId.keys());
  if(family){selected=new Set([family]);let changed=true;while(changed){changed=false;for(const e of links)if(e.type==='containment'&&selected.has(e.from)&&!selected.has(e.to)){selected.add(e.to);changed=true;}}}
  if(query){const matches=new Set(nodes.filter(n=>selected.has(n.id)&&(n.id+' '+n.title).toLowerCase().includes(query.toLowerCase())).map(n=>n.id));const context=new Set(matches);for(const e of links)if(matches.has(e.from)||matches.has(e.to)){context.add(e.from);context.add(e.to);}selected=new Set([...context].filter(id=>selected.has(id)));}
  links=links.filter(e=>selected.has(e.from)&&selected.has(e.to)&&(mode==='all'||e.type===mode));
  return {nodes:nodes.filter(n=>selected.has(n.id)),edges:links};
}
function layoutProjectGraph(nodes,edges){
  const ids=new Set(nodes.map(n=>n.id)),incoming=new Map(nodes.map(n=>[n.id,[]])),outgoing=new Map(nodes.map(n=>[n.id,[]]));
  for(const e of edges)if(ids.has(e.from)&&ids.has(e.to)){incoming.get(e.to).push(e.from);outgoing.get(e.from).push(e.to);}
  const degrees=new Map([...incoming].map(([k,v])=>[k,v.length])),rank=new Map(nodes.map(n=>[n.id,0]));
  const ready=nodes.filter(n=>degrees.get(n.id)===0).map(n=>n.id).sort();let visited=0;
  for(let i=0;i<ready.length;i++){const id=ready[i];visited++;for(const next of outgoing.get(id)){rank.set(next,Math.max(rank.get(next),rank.get(id)+1));degrees.set(next,degrees.get(next)-1);if(degrees.get(next)===0)ready.push(next);}}
  const unresolved=nodes.filter(n=>degrees.get(n.id)>0).map(n=>n.id),last=Math.max(0,...rank.values())+1;
  unresolved.forEach(id=>rank.set(id,last));
  const columns=new Map();for(const node of nodes){const level=rank.get(node.id);if(!columns.has(level))columns.set(level,[]);columns.get(level).push(node);}
  const positions=new Map();let rows=1;
  for(const level of [...columns.keys()].sort((a,b)=>a-b)){
    const column=columns.get(level);column.sort((a,b)=>{const mean=n=>{const ps=incoming.get(n.id).map(id=>positions.get(id)?.y).filter(y=>y!==undefined);return ps.length?ps.reduce((x,y)=>x+y,0)/ps.length:0;};const connected=n=>incoming.get(n.id).length+outgoing.get(n.id).length>0?1:0;return mean(a)-mean(b)||connected(b)-connected(a)||(b.kind==='family'?1:0)-(a.kind==='family'?1:0)||a.id.localeCompare(b.id);});
    rows=Math.max(rows,column.length);column.forEach((n,i)=>positions.set(n.id,{x:32+level*360,y:32+i*112,width:304,height:80,level}));
  }
  return {positions,width:Math.max(800,(Math.max(0,...rank.values())+1)*360+32),height:rows*112+32,unresolved,visited};
}
if(typeof module!=='undefined')module.exports={projectGraph,layoutProjectGraph};
