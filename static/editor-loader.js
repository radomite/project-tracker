/* Mount the manuscript bundle only when its project view is opened. */
async function loadManuscript(){
  const pid=S.project.id,version=S.load;
  const module=await import('/static/editor-assets/editor.js?v=20261106-windows');
  if(S.load!==version||S.view!=='editor')return;
  document.querySelector('.shell').classList.add('manuscript-shell');
  const instance=await module.mount(document.querySelector('#page'),{project:S.project,user:S.user,csrf:S.csrf,onMenu:()=>document.querySelector('.shell')?.classList.toggle('nav-open')});
  if(S.load!==version||S.project?.id!==pid){instance.destroy();return;}
  window.activeManuscript=instance;
}
