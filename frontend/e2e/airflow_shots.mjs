// Screenshots of the Airflow UI (task graph, run history) and the React Pipeline Runs page, for docs/screenshots/.
//   Needs: Airflow on :8080 (WSL), the API on :8000 and `npm run dev` on :5173.
//   Env: AIRFLOW_PASSWORD (the generated "admin" password), E2E_ADMIN_PASSWORD (the app's administrator).
import fs from 'node:fs'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const SHOTS = path.join(ROOT, 'docs', 'screenshots')
const AF = process.env.AIRFLOW_URL || 'http://127.0.0.1:8080'
const APP = process.env.E2E_BASE || 'http://127.0.0.1:5173'
const CHROME = process.env.E2E_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
fs.mkdirSync(SHOTS, { recursive: true })

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1500, height: 950 })

// Airflow API: a short-lived token, then the run ids to open
const tokenRes = await fetch(`${AF}/auth/token`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'admin', password: process.env.AIRFLOW_PASSWORD }) })
const { access_token } = await tokenRes.json()
const get = async (p) => (await fetch(`${AF}/api/v2${p}`, { headers: { Authorization: `Bearer ${access_token}` } })).json()
const runs = (await get('/dags/healthcare_incremental_etl/dagRuns?order_by=-start_date&limit=20')).dag_runs
const byState = (state) => runs.find((r) => r.state === state && r.run_type === 'manual')
const okRun = byState('success')
const badRun = byState('failed')
console.log('runs:', runs.map((r) => `${r.dag_run_id.slice(0, 22)}:${r.state}`).join(' | '))

// log in through the UI so the session cookie works for page screenshots
await page.goto(`${AF}/`, { waitUntil: 'networkidle2' })
if (await page.$('input[name=username]')) {
  await page.type('input[name=username]', 'admin')
  await page.type('input[name=password]', process.env.AIRFLOW_PASSWORD)
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }).catch(() => {}), page.click('button[type=submit]')])
}
const shot = async (url, name, wait = 3500) => { await page.goto(`${AF}${url}`, { waitUntil: 'networkidle2' }); await sleep(wait); await page.screenshot({ path: path.join(SHOTS, `${name}.png`) }); console.log('saved', name) }

await shot('/dags', '20_airflow_dags')
await shot('/dags/healthcare_incremental_etl', '21_airflow_etl_dag_overview')
if (okRun) await shot(`/dags/healthcare_incremental_etl/runs/${encodeURIComponent(okRun.dag_run_id)}`, '22_airflow_etl_run_success_graph')
if (badRun) await shot(`/dags/healthcare_incremental_etl/runs/${encodeURIComponent(badRun.dag_run_id)}`, '23_airflow_etl_run_failed_graph')
await shot('/dags/healthcare_incremental_etl/runs', '24_airflow_etl_run_history')
await shot('/dags/healthcare_weekly_report', '25_airflow_weekly_report_dag')

// the app's Pipeline Runs page now lists the runs the DAG created
const app = await browser.newPage()
await app.setViewport({ width: 1440, height: 900 })
await app.goto(`${APP}/login`, { waitUntil: 'networkidle0' })
await app.$eval('input[name=username]', (e) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, 'admin'); e.dispatchEvent(new Event('input', { bubbles: true })) })
await app.$eval('input[name=password]', (e, v) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, v); e.dispatchEvent(new Event('input', { bubbles: true })) }, process.env.E2E_ADMIN_PASSWORD)
await Promise.all([app.waitForSelector('.sidebar nav a'), app.click('button[type=submit]')])
await app.goto(`${APP}/pipeline`, { waitUntil: 'networkidle0' }); await sleep(800)
await app.screenshot({ path: path.join(SHOTS, '26_pipeline_runs_after_airflow.png') })
console.log('saved 26_pipeline_runs_after_airflow')
await browser.close()
