const {test,expect}=require('@playwright/test');

test('project agents, cluster assignments, drafts, and offline status',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  // This test also runs on its own, against a disposable empty database.
  await expect(page.locator('#auth-form')).toBeVisible();
  if(await page.getByRole('button',{name:'Create account',exact:true}).isVisible()){
    await page.getByLabel('Your name').fill('Agent Owner');
    await page.getByLabel('Email address').fill('preview@example.org');
    await page.getByLabel('Password',{exact:true}).fill('research-preview-2026');
    await page.getByRole('button',{name:'Create account',exact:true}).click();
  }else if(await page.getByLabel('Email address').isVisible()){
    await page.getByLabel('Your name').fill('Agent Owner');
    await page.getByLabel('Email address').fill('preview@example.org');
    await page.getByLabel('Password',{exact:true}).fill('research-preview-2026');
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
  }
  await expect(page.getByRole('heading',{name:'Project dashboard',exact:true})).toBeVisible();
  const auth=await page.evaluate(async()=>await (await fetch('/api/v1/auth/me')).json());
  const project=await page.evaluate(async csrf=>await (await fetch('/api/v1/projects',{
    method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({title:'Agent cluster test'})
  })).json(),auth.csrf);
  await page.goto(`/#project=${project.id}`);
  await page.getByRole('button',{name:'Project agents',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Project agents',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Astra Research'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Sol Editing'})).toBeVisible();
  await expect(page.locator('#agent-service-status')).toHaveText('Codex service has not been started.');
  await expect(page.getByRole('button',{name:'Send to Astra'})).toBeDisabled();
  await page.getByLabel('Request for Astra').fill('Keep my research draft');
  await page.getByLabel('Request for Sol').fill('Keep my editing draft');
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await expect(page.getByLabel('Request for Astra')).toHaveValue('Keep my research draft');
  await expect(page.getByLabel('Request for Sol')).toHaveValue('Keep my editing draft');
  const clusterName='Common mathematics '+project.id;
  await page.getByLabel('New cluster name').fill(clusterName);
  await page.getByRole('button',{name:'Create & assign'}).click();
  const cluster=page.locator('.agent-cluster-row').filter({hasText:clusterName});
  await expect(cluster.getByRole('checkbox')).toBeChecked();
  await cluster.getByRole('checkbox').uncheck();
  await expect(page.locator('.agent-cluster-row').filter({hasText:clusterName}).getByRole('checkbox')).not.toBeChecked();
  await page.getByRole('button',{name:'Agent messages',exact:true}).first().click();
  await expect(page.locator('[data-agent-mailbox="astra"]')).toHaveText('No agent messages.');
  await page.getByRole('button',{name:'Project dashboard',exact:true}).click();
  await page.getByRole('button',{name:'Project agents',exact:true}).click();
  await expect(page.getByLabel('Request for Astra')).toHaveValue('Keep my research draft');
  await page.reload();
  await expect(page.getByRole('heading',{name:'Project agents',exact:true})).toBeVisible();
  expect(errors).toEqual([]);
});
