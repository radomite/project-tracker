/* Adapted from TeXlyre 697759981a2a7291fdd3855ea6e09cc6ca5c7723.
 * Copyright TeXlyre contributors. SPDX-License-Identifier: AGPL-3.0-or-later.
 * See third-party/texlyre/NOTICE.md and LICENSE. */
import {createTypstCompiler} from '@texlyre/typst.ts/compiler';
import {TypstSnippet} from '@texlyre/typst.ts/contrib/snippet';
let compiler,initializing,queue=Promise.resolve();
async function initialize(){
  if(initializing)return initializing;
  initializing=(async()=>{
    const names=await fetch('/static/editor-assets/fonts/fonts.json').then(r=>r.json());
    const fonts=await Promise.all(names.map(n=>fetch('/static/editor-assets/fonts/'+n).then(r=>r.arrayBuffer()).then(b=>new Uint8Array(b))));
    compiler=createTypstCompiler();
    await compiler.init({getModule:()=>'/static/editor-assets/compiler.wasm',beforeBuild:[
      ...TypstSnippet.fetchPackageRegistry().provides,
      async(_,{builder})=>{for(const font of fonts)await builder.add_raw_font(font);}
    ]});
  })();
  return initializing;
}
self.onmessage=event=>{
  queue=queue.catch(()=>{}).then(async()=>{
    const {id,main,sources}=event.data;
    try{
      await initialize();
      compiler.resetShadow();
      for(const [path,bytes] of Object.entries(sources))compiler.mapShadow('/'+path,bytes);
      const result=await compiler.runWithWorld({mainFilePath:'/'+main},async world=>{
        const paged=await world.compile({diagnostics:'full'});
        const pdf=await world.pdf({diagnostics:'full'});
        return {pdf:pdf.result,diagnostics:[...(paged.diagnostics||[]),...(pdf.diagnostics||[])]};
      });
      self.postMessage({id,...result},result.pdf?[result.pdf.buffer]:[]);
    }catch(error){self.postMessage({id,error:String(error?.message||error)});}
  });
};
