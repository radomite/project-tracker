const {defineConfig}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const browser=process.env.LOCAL_CHROMIUM||path.join(process.env.LOCALAPPDATA||'','ms-playwright','chromium-1248','chrome-win64','chrome.exe');
module.exports=defineConfig({testDir:'./tests/editor-browser',workers:1,timeout:60000,
  outputDir:process.env.PLAYWRIGHT_OUTPUT_DIR||'test-results/editor',
  use:{baseURL:process.env.EDITOR_TEST_URL||'http://127.0.0.1:8782',headless:true,
    launchOptions:fs.existsSync(browser)?{executablePath:browser}:{},screenshot:'off',trace:'off'},
  ...(process.env.EDITOR_TEST_URL?{}:{webServer:{command:'python -m uvicorn app:app --host 127.0.0.1 --port 8782',
    url:'http://127.0.0.1:8782/health',reuseExistingServer:false,
    env:{...process.env,RESEARCH_DB:path.resolve('.checks/editor-browser-'+Date.now()+'.db'),RESEARCH_EDITOR_IDLE_SECONDS:'3'}}})});
