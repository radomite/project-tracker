import {EditorState, StateField} from '@codemirror/state';
import {EditorView, Decoration, WidgetType, keymap, placeholder} from '@codemirror/view';
import {defaultKeymap, history, historyKeymap} from '@codemirror/commands';

const cache=new Map();
function escaped(text,index){let count=0;while(index>0&&text[--index]==='\\')count++;return count%2===1;}
function segments(text){
  const parts=[];
  for(let i=0;i<text.length;){
    if(text[i]==='`'&&!escaped(text,i)){
      let length=1;while(text[i+length]==='`')length++;
      const marker='`'.repeat(length),end=text.indexOf(marker,i+length);
      const to=end<0?text.length:end+length;parts.push({from:i,to,kind:'code'});i=to;continue;
    }
    if(text[i]!=='$'||escaped(text,i)){i++;continue;}
    const from=i,delimiter=text[i+1]==='$'?'$$':'$',start=i+delimiter.length;
    let end=-1,j=start;
    for(;j<text.length;j++){
      if(delimiter==='$'&&text[j]==='\n')break;
      if(text.startsWith(delimiter,j)&&!escaped(text,j)){
        if(delimiter==='$'&&(text[j+1]==='$'||text[j-1]==='$'))continue;
        end=j;break;
      }
    }
    const to=end<0?j:end+delimiter.length;
    parts.push({from,to,kind:'math',closed:end>=0,delimiter,source:text.slice(start,end<0?to:end)});
    i=Math.max(to,from+1);
  }
  return parts;
}
function renderMath(source,displayMode){
  const key=(displayMode?'D':'I')+source;
  if(cache.has(key))return cache.get(key);
  let result;
  try{result={html:window.katex.renderToString(source,{displayMode,throwOnError:true,trust:false,strict:'ignore',maxExpand:1000,maxSize:20})};}
  catch(error){result={error:error.message.replace(/^KaTeX parse error:\s*/, '')};}
  if(cache.size>=256)cache.delete(cache.keys().next().value);
  cache.set(key,result);return result;
}
class MathPreview extends WidgetType{
  constructor(part,html){super();this.part=part;this.html=html;}
  eq(other){return this.part.from===other.part.from&&this.part.to===other.part.to&&this.html===other.html;}
  toDOM(){
    const span=document.createElement('span');span.className='composer-math-preview';
    span.dataset.from=String(this.part.from);span.dataset.to=String(this.part.to);span.dataset.delimiter=String(this.part.delimiter.length);
    span.title='Click to edit LaTeX';span.setAttribute('aria-label',this.part.source);span.innerHTML=this.html;
    return span;
  }
  ignoreEvent(){return false;}
}
function decorations(state){
  const text=state.doc.toString(),ranges=[];
  for(const part of segments(text)){
    if(part.from===part.to)continue;
    if(part.kind==='code'){
      ranges.push(Decoration.mark({class:'cm-code-source'}).range(part.from,part.to));continue;
    }
    const active=state.selection.ranges.some(r=>r.empty?r.head>=part.from&&r.head<part.to:r.from<part.to&&r.to>part.from);
    const result=part.closed?renderMath(part.source,part.delimiter==='$$'):{};
    if(part.closed&&!active&&!result.error){
      ranges.push(Decoration.replace({widget:new MathPreview(part,result.html)}).range(part.from,part.to));continue;
    }
    ranges.push(Decoration.mark({class:'cm-latex-source'+(result.error?' cm-latex-error':''),attributes:result.error?{title:result.error,'aria-invalid':'true'}:{}}).range(part.from,part.to));
    const raw=text.slice(part.from,part.to),tokens=/\\(?:[a-zA-Z]+|[^\n])|%[^\n]*|[{}\[\]]|[_^&]|\d+(?:\.\d+)?|\$+/g;
    let token;
    while((token=tokens.exec(raw))){
      const kind=token[0][0]==='\\'?'command':token[0][0]==='%'?'comment':/[{}\[\]]/.test(token[0])?'brace':/^\d/.test(token[0])?'number':'operator';
      ranges.push(Decoration.mark({class:'cm-tex-'+kind}).range(part.from+token.index,part.from+token.index+token[0].length));
    }
  }
  return Decoration.set(ranges,true);
}
const mathField=StateField.define({create:decorations,update(value,tr){return tr.docChanged||tr.selection?decorations(tr.state):value;},provide:field=>EditorView.decorations.from(field)});
let current=null;
function destroy(){if(!current)return;const old=current;current=null;old.view.destroy();old.host.remove();delete old.textarea.focus;}
function mount(textarea){
  destroy();
  const host=document.createElement('div');host.className='message-composer-editor';textarea.before(host);
  textarea.hidden=true;textarea.required=false;
  const form=textarea.closest('form');
  const state=EditorState.create({doc:textarea.value,selection:{anchor:textarea.value.length},extensions:[
    history(),mathField,EditorView.lineWrapping,placeholder('Message'),
    EditorView.contentAttributes.of({'aria-label':'Message','aria-multiline':'true',role:'textbox','data-message-editor':'true',spellcheck:'false'}),
    EditorState.transactionFilter.of(tr=>tr.newDoc.length>50000?[]:tr),
    keymap.of([{key:'Mod-Enter',run(){form.requestSubmit();return true;}},...defaultKeymap,...historyKeymap]),
    EditorView.domEventHandlers({mousedown(event,view){
      const math=event.target.closest('.composer-math-preview');if(!math)return false;
      event.preventDefault();view.dispatch({selection:{anchor:Number(math.dataset.from)+Number(math.dataset.delimiter)}});view.focus();return true;
    }}),
    EditorView.updateListener.of(update=>{
      if(!update.docChanged)return;
      textarea.value=update.state.doc.toString();textarea.dispatchEvent(new Event('input',{bubbles:true}));
    }),
    EditorView.theme({
      '&':{fontFamily:'KaTeX_Main, "Times New Roman", serif',fontSize:'16px',backgroundColor:'#fff'},
      '&.cm-focused':{outline:'none'},
      '.cm-scroller':{fontFamily:'inherit',lineHeight:'1.65',overflow:'auto',maxHeight:'28dvh',minHeight:'90px'},
      '.cm-content':{padding:'12px 14px',minHeight:'90px'},
      '.cm-line':{padding:'0'},
      '.cm-placeholder':{color:'#78838c'}
    })
  ]});
  const view=new EditorView({state,parent:host});view.contentDOM.id='compose-editor';
  textarea.focus=()=>view.focus();current={view,host,textarea};
}
window.MessageComposer={mount,destroy};
