const { defineConfig } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const existingBrowser = process.env.LOCAL_CHROMIUM || path.join(process.env.LOCALAPPDATA || '', 'ms-playwright', 'chromium-1248', 'chrome-win64', 'chrome.exe');
module.exports = defineConfig({
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || 'test-results/chat',
  testDir: './tests/browser', workers: 1, timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:8767', headless:true,
    launchOptions: fs.existsSync(existingBrowser)?{executablePath:existingBrowser}:{},
    screenshot: 'only-on-failure', trace:'retain-on-failure' },
  webServer: { command:'python -m uvicorn app:app --host 127.0.0.1 --port 8767',
    url:'http://127.0.0.1:8767/health', reuseExistingServer:false,
    env:{...process.env,RESEARCH_DB:path.resolve(`.checks/browser-${Date.now()}.db`)} },
});
