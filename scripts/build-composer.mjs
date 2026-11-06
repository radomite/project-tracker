import {build} from 'esbuild';
import {readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
const result=await build({entryPoints:['scripts/composer-editor.js'],outfile:'static/vendor/message-composer.js',bundle:true,format:'iife',target:'es2020',minify:true,legalComments:'eof',metafile:true});
const notices=new Map();
for(const input of Object.keys(result.metafile.inputs)){
  if(!input.includes('node_modules/'))continue;
  let folder=path.dirname(path.resolve(input));
  while(folder!==path.dirname(folder)){
    let pkg;
    try{pkg=JSON.parse(await readFile(path.join(folder,'package.json'),'utf8'));}catch{}
    if(pkg){
      for(const name of ['LICENSE','LICENSE.md','LICENSE.txt']){
        try{notices.set(pkg.name,`${pkg.name} ${pkg.version}\n\n${await readFile(path.join(folder,name),'utf8')}`);break;}catch{}
      }
      break;
    }
    folder=path.dirname(folder);
  }
}
await writeFile('static/vendor/message-composer-LICENSES.txt',[...notices.values()].join('\n\n--------------------\n\n'));
