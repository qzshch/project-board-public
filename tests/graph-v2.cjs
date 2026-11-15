const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context=vm.createContext({drawGraph:null});vm.runInContext(fs.readFileSync('task_board_web/dependency-explorer.js','utf8'),context);
const nodes=[],edges=[],modules={};for(let m=0;m<12;m++){modules['module-'+m+'@1']={id:'module-'+m,title:'Module '+m};for(let i=0;i<100;i++){const id=`M${m}-T${i}`;nodes.push({id,title:'Task '+id,status:'planned',planning:{module:'module-'+m+'@1'}});if(i)edges.push({from:`M${m}-T${i-1}`,to:id,type:'hard'});if(m&&i===0)edges.push({from:`M${m-1}-T99`,to:id,type:'hard'});if(i===10)edges.push({from:'shared-resource',to:id,type:'exclusive'});}}
const model=context.buildGraphModel({nodes,graph:edges,modules}),types=new Set(['hard','exclusive']);const all=context.graphSelection(model,'all','', '',types,'');assert.equal(all.nodes.length,1201);assert.equal(all.edges.length,edges.length);const layout=context.graphAutoLayout(all);assert.equal(layout.positions.size,1201);assert.equal(layout.unresolved,false);
const grouped=context.graphSelection(model,'modules','','',types,'');assert.equal(grouped.nodes.length,13);assert.equal(grouped.edges.filter(e=>e.type==='hard').length,11);
const neighbors=context.graphSelection(model,'neighbors','','M0-T99',types,'');assert.equal(neighbors.nodes.filter(n=>n.kind!=='reference').length,1200);
const single=context.graphSelection(model,'module','module-5','',types,'');assert(single.nodes.length>=102);assert(single.nodes.some(n=>n.id==='M4-T99'));assert(single.nodes.some(n=>n.id==='M6-T0'));
const bad=context.graphAutoLayout({nodes:all.nodes,edges:[...all.edges,{from:'M0-T99',to:'M0-T0',type:'hard'}]});assert.equal(bad.unresolved,true);
// Symmetric coupling must not be counted as a hard cycle.
assert.equal(context.graphAutoLayout({nodes:all.nodes,edges:[{from:'M0-T99',to:'M0-T0',type:'coupling'},{from:'M0-T0',to:'M0-T99',type:'coupling'}]}).unresolved,false);
console.log(JSON.stringify({passed:true,modules:12,tasks:1200,reference_nodes:1,edges:edges.length,positions:layout.positions.size}));
