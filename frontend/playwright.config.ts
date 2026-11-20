import {defineConfig} from '@playwright/test'
import {existsSync} from 'node:fs'
import {resolve} from 'node:path'

const win=process.platform==='win32'
const venv=resolve(win?'../.venv/Scripts/python.exe':'../.venv/bin/python')
const python=process.env.PYTHON || (existsSync(venv)?venv:'python')
const edge='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
export default defineConfig({
 testDir:'tests',testMatch:'**/*.spec.ts',workers:1,use:{baseURL:'http://127.0.0.1:8765',viewport:{width:1440,height:940},
 launchOptions:{executablePath:process.env.BROWSER_PATH || (win&&existsSync(edge)?edge:undefined)}},
 webServer:{command:'"'+python+'" tests/serve.py',url:'http://127.0.0.1:8765/api/v1/settings',reuseExistingServer:false,timeout:30000}
})
