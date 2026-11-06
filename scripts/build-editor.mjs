import {build} from 'esbuild';
import {mkdir,copyFile,readFile,writeFile} from 'node:fs/promises';
await mkdir('static/editor-assets',{recursive:true});
const result=await build({entryPoints:['editor-src/editor.js'],outfile:'static/editor-assets/editor.js',bundle:true,format:'esm',target:'es2022',minify:true,metafile:true,legalComments:'eof'});
await build({entryPoints:['editor-src/typst-worker.js'],outfile:'static/editor-assets/typst-worker.js',bundle:true,format:'esm',target:'es2022',minify:true,legalComments:'eof',alias:{'@myriaddreamin/typst.ts':'@texlyre/typst.ts','@myriaddreamin/typst-ts-web-compiler':'@texlyre/typst-ts-web-compiler','@myriaddreamin/typst-ts-renderer':'@texlyre/typst-ts-renderer'}});
await copyFile('node_modules/@texlyre/typst-ts-web-compiler/pkg/typst_ts_web_compiler_bg.wasm','static/editor-assets/compiler.wasm');
await copyFile('node_modules/pdfjs-dist/build/pdf.worker.min.mjs','static/editor-assets/pdf.worker.mjs');
// Keep full license texts alongside the locally served assets.
const packages=['@texlyre/typst.ts','@texlyre/typst-ts-web-compiler','pdfjs-dist','codemirror','codemirror-lang-typst','codemirror-lang-latex','yjs','y-codemirror.next','y-protocols','lib0','@codemirror/state','@codemirror/view','@codemirror/commands','@codemirror/search','@codemirror/autocomplete','@codemirror/language'];
const notices=[];
for(const pkg of packages){
  const folder=`node_modules/${pkg}`;
  const meta=JSON.parse(await readFile(`${folder}/package.json`,'utf8'));
  for(const name of ['LICENSE','LICENSE.md','LICENSE.txt'])try{notices.push(`${pkg} ${meta.version}\n${await readFile(`${folder}/${name}`,'utf8')}`);break;}catch{}
}
notices.push(await readFile('third-party/texlyre/NOTICE.md','utf8'),await readFile('third-party/texlyre/LICENSE','utf8'));
await writeFile('static/editor-assets/LICENSES.txt',notices.join('\n\n---------------------\n\n'));
console.log(`Editor bundled (${Object.keys(result.metafile.inputs).length} modules); compiler and viewer served locally.`);
