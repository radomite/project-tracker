/* Read-only commit graph. The server supplies commits in topological order. */
'use strict';
const historyColors=['#3975bb','#9861b5','#27846b','#c17b2c','#bc5773','#607a99'];
function historyGraphRows(items) {
  let lanes=[],nextColor=0,width=0;
  const rows=items.map(item=>{
    const before=lanes.map(lane=>({...lane}));
    if(!item.commit)return {before,after:before,node:null};
    let column=lanes.findIndex(lane=>lane.id===item.commit);
    const incoming=column!==-1;
    if(!incoming){column=lanes.length;lanes.push({id:item.commit,color:nextColor++});}
    const node={...lanes[column],column,incoming};
    const after=lanes.filter(lane=>lane.id!==item.commit);
    let insertion=column;
    for(const [i,parent] of item.parents.entries()){
      if(!after.some(lane=>lane.id===parent)){
        after.splice(Math.min(insertion,after.length),0,{id:parent,color:i===0?node.color:nextColor++});
        insertion++;
      }
    }
    width=Math.max(width,before.length,after.length,column+1);
    lanes=after;
    return {before,after,node,parents:item.parents};
  });
  return {rows,width:Math.max(1,width)*14+2};
}
function drawHistoryRow(element,row,width) {
  if(!element.isConnected)return;
  const bounds=element.getBoundingClientRect(),hash=element.querySelector('.history-commit-stamp code')?.getBoundingClientRect();
  const height=bounds.height,nodeY=hash?hash.top+hash.height/2-bounds.top:20,mid=(height+nodeY)/2;
  const x=column=>column*14+8,color=lane=>historyColors[lane.color%historyColors.length];
  const path=(d,stroke)=>`<path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.6"/>`;
  let lines='';
  row.before.forEach((lane,column)=>{
    if(row.node?.id===lane.id){
      lines+=path(`M${x(column)} 0V${nodeY}`,color(lane));
    }else{
      const target=row.after.findIndex(other=>other.id===lane.id);
      if(target!==-1)lines+=path(`M${x(column)} 0V${nodeY}C${x(column)} ${mid} ${x(target)} ${mid} ${x(target)} ${height}`,color(lane));
    }
  });
  if(row.node){
    row.parents.forEach(parent=>{
      const target=row.after.findIndex(lane=>lane.id===parent),lane=row.after[target];
      lines+=path(`M${x(row.node.column)} ${nodeY}C${x(row.node.column)} ${mid} ${x(target)} ${mid} ${x(target)} ${height}`,color(lane));
    });
    const merge=row.parents.length>1;
    lines+=`<circle cx="${x(row.node.column)}" cy="${nodeY}" r="${merge?4.5:3.5}" fill="${merge?'var(--bg,white)':color(row.node)}" stroke="${color(row.node)}" stroke-width="2"/>`;
  }
  element.querySelector('.history-graph').innerHTML=`<svg width="${width}" height="${height}" aria-hidden="true">${lines}</svg>`;
}
function mountHistoryGraph() {
  S.historyGraphObserver?.disconnect();
  const {rows,width}=S.historyGraph;
  const draw=element=>drawHistoryRow(element,rows[Number(element.dataset.historyRow)],width);
  S.historyGraphObserver=new ResizeObserver(entries=>entries.forEach(entry=>draw(entry.target)));
  document.querySelectorAll('[data-history-row]').forEach(element=>{
    draw(element);S.historyGraphObserver.observe(element);
  });
}
