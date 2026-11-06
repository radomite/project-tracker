import { cp, mkdir, copyFile } from 'node:fs/promises';
const target = new URL('../static/vendor/', import.meta.url);
await mkdir(target, { recursive: true });
for (const [source, dest] of [
  ['marked/lib/marked.umd.js', 'marked.js'],
  ['dompurify/dist/purify.min.js', 'purify.js'],
  ['katex/dist/katex.min.js', 'katex.js'],
  ['katex/dist/katex.min.css', 'katex.css'],
  ['katex/dist/contrib/auto-render.min.js', 'auto-render.js'],
]) await copyFile(new URL(`../node_modules/${source}`, import.meta.url), new URL(dest, target));
await cp(new URL('../node_modules/katex/dist/fonts', import.meta.url), new URL('fonts/', target), { recursive: true });
for (const pkg of ['marked', 'dompurify', 'katex']) {
  await copyFile(new URL(`../node_modules/${pkg}/LICENSE${pkg === 'dompurify' ? '' : '.md'}`, import.meta.url), new URL(`${pkg}-LICENSE`, target)).catch(async () => {
    await copyFile(new URL(`../node_modules/${pkg}/LICENSE`, import.meta.url), new URL(`${pkg}-LICENSE`, target));
  });
}
console.log('Local Markdown and math assets ready.');
