// End-to-end check of the real UI against the real API (headless Chrome via puppeteer-core).
//   Needs: API on :8000, `npm run dev` on :5173, and the passwords in the environment:
//   E2E_ADMIN_PASSWORD, E2E_OPS_PASSWORD, E2E_ANALYST_PASSWORD  (never committed).
//   Writes docs/screenshots/*.png and docs/role_verification.md from what it actually observed.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const SHOTS = path.join(ROOT, 'docs', 'screenshots')
const BASE = process.env.E2E_BASE || 'http://127.0.0.1:5173'
const CHROME = process.env.E2E_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const USERS = {
  administrator: { username: 'admin', password: process.env.E2E_ADMIN_PASSWORD },
  clinical_ops: { username: 'clinical_ops', password: process.env.E2E_OPS_PASSWORD },
  analyst: { username: 'analyst', password: process.env.E2E_ANALYST_PASSWORD },
}
for (const [role, u] of Object.entries(USERS)) if (!u.password) throw new Error(`set the password env var for ${role}`)
fs.mkdirSync(SHOTS, { recursive: true })

// Unique ids per run: patient_nbr and encounter_id of a soft-deleted record can never be reused.
const P = 910000000 + (Date.now() % 1000000)
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` -- ${detail}` : ''}`) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const EXPECTED_NAV = {
  analyst: ['Dashboard', 'Encounters', 'Reports'],
  clinical_ops: ['Dashboard', 'Patients', 'Encounters', 'Reports', 'Pipeline Runs', 'Data Quality'],
  administrator: ['Dashboard', 'Patients', 'Encounters', 'Reports', 'Pipeline Runs', 'Data Quality', 'Audit Log', 'Users'],
}

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox', '--window-size=1440,1000'] })
const requestLog = []

async function newSession() {
  const context = await browser.createBrowserContext()
  const page = await context.newPage()
  await page.setViewport({ width: 1440, height: 1000 })
  page.on('request', (req) => requestLog.push({ url: req.url(), auth: req.headers().authorization }))
  return { page, context }
}
const shot = (page, name, fullPage = true) => page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage })
async function waitText(page, selector, predicate, timeout = 15000) {
  await page.waitForFunction((s, p) => { const el = document.querySelector(s); return el && new Function('t', `return ${p}`)(el.textContent) }, { timeout }, selector, predicate)
}
async function setValue(page, selector, value) {
  await page.$eval(selector, (el, v) => {
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set
    setter.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }, value)
}
async function idForLabel(page, text, scope = 'body') {
  return page.evaluate((t, s) => {
    const label = [...document.querySelector(s).querySelectorAll('label')].find((l) => l.textContent.trim().startsWith(t))
    return label ? (label.htmlFor ? `#${label.htmlFor}` : null) : null
  }, text, scope)
}
async function fill(page, labelText, value, scope = '.modal') {
  const sel = await idForLabel(page, labelText, scope)
  if (!sel) throw new Error(`no field labelled "${labelText}"`)
  const tag = await page.$eval(sel, (el) => el.tagName)
  if (tag === 'SELECT') await page.select(sel, String(value)); else await setValue(page, sel, String(value))
}
async function clickButton(page, text, scope = 'body') {
  const handle = await page.evaluateHandle((t, s) => [...document.querySelector(s).querySelectorAll('button')].find((b) => b.textContent.trim() === t), text, scope)
  if (!handle.asElement()) throw new Error(`no button "${text}" in ${scope}`)
  await handle.asElement().click()
}
const hasButton = (page, text, scope = 'body') => page.evaluate((t, s) => Boolean(document.querySelector(s) && [...document.querySelector(s).querySelectorAll('button')].some((b) => b.textContent.trim() === t)), text, scope)
const apiCall = (page, method, url, body, form) => page.evaluate(async (m, u, b, f) => {
  const token = sessionStorage.getItem('hc_token')
  const headers = { Authorization: `Bearer ${token}`, ...(b ? { 'Content-Type': 'application/json' } : {}) }
  const r = await fetch(`/api${u}`, { method: m, headers, body: b ? JSON.stringify(b) : undefined })
  let data = null
  try { data = await r.clone().json() } catch { /* not JSON */ }
  return { status: r.status, data, type: r.headers.get('content-type') }
}, method, url, body, form)

async function login(page, role) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' })
  await setValue(page, 'input[name=username]', USERS[role].username)
  await setValue(page, 'input[name=password]', USERS[role].password)
  await Promise.all([page.waitForSelector('.sidebar nav a'), page.click('button[type=submit]')])
}
const navLabels = (page) => page.$$eval('.sidebar nav a', (as) => as.map((a) => a.textContent.trim()))
const uiContent = async (page, path_) => {  // what a user sees when opening a path: 'Not permitted' or real content
  await page.goto(`${BASE}${path_}`, { waitUntil: 'networkidle0' })
  return page.$eval('main', (m) => (m.querySelector('h1')?.textContent || '').trim())
}

// ---- the role matrix: UI behaviour vs direct API ---------------------------------------------------------------
const matrix = {}  // role -> list of {action, ui, api}
const PAGES = [['Dashboard', '/dashboard'], ['Patients', '/patients'], ['Encounters', '/encounters'], ['Reports', '/reports'],
  ['Pipeline Runs', '/pipeline'], ['Data Quality', '/data-quality'], ['Audit Log', '/audit'], ['Users', '/users']]
const PAGE_API = { '/dashboard': '/analytics/summary', '/patients': '/patients?page_size=1', '/encounters': '/encounters?page_size=1', '/reports': '/reports/export?report=readmission_summary&format=csv',
  '/pipeline': '/admin/pipeline-runs?page_size=1', '/data-quality': '/admin/dq-issues?page_size=1', '/audit': '/admin/audit-logs?page_size=1', '/users': '/admin/users?page_size=1' }

// seed data the destructive tests need (created and cleaned up through the API as administrator)
const admin = await newSession()
await login(admin.page, 'administrator')
await apiCall(admin.page, 'POST', '/patients', { patient_nbr: P, race: 'Asian', gender: 'Male' })
const payload = (id, extra = {}) => ({
  encounter_id: id, patient_nbr: P, admission_date: '2005-03-01', discharge_date: '2005-03-04', age_group: '[70-80)', admission_type_id: 1,
  discharge_disposition_id: 1, admission_source_id: 7, medical_specialty: 'Cardiology', payer_code: 'MC', time_in_hospital: 3, num_lab_procedures: 40,
  num_procedures: 1, num_medications: 12, number_outpatient: 0, number_emergency: 0, number_inpatient: 0, number_diagnoses: 1, max_glu_serum: 'None',
  a1c_result: 'None', med_changed: false, diabetes_med: true, readmitted: 'NO', diagnoses: [{ position: 1, icd9_code: '250.83' }], medications: [], ...extra })

for (const role of ['administrator', 'clinical_ops', 'analyst']) {
  const { page, context } = role === 'administrator' ? admin : await newSession()
  if (role !== 'administrator') await login(page, role)
  const rows = []
  const nav = await navLabels(page)
  check(`${role}: navigation shows exactly the allowed pages`, JSON.stringify(nav) === JSON.stringify(EXPECTED_NAV[role]), nav.join(', '))
  check(`${role}: top bar shows username and role badge`, (await page.$eval('[data-testid=who]', (e) => e.textContent)) === USERS[role].username && (await page.$eval('[data-testid=role]', (e) => e.textContent)).length > 3)
  for (const [label, p] of PAGES) {
    const heading = await uiContent(page, p)
    const api = await apiCall(page, 'GET', PAGE_API[p])
    const ui = heading === 'Not permitted' ? 'Not permitted page' : `opens (${heading})`
    rows.push({ action: `Open ${label}`, ui, api: api.status, consistent: (heading === 'Not permitted') === (api.status === 403) })
  }
  // write actions
  await page.goto(`${BASE}/encounters`, { waitUntil: 'networkidle0' })
  const canCreateUi = await hasButton(page, 'New encounter', 'main')
  const create = await apiCall(page, 'POST', '/encounters', payload(role === 'administrator' ? P + 1 : role === 'clinical_ops' ? P + 2 : P + 3))
  rows.push({ action: 'Create encounter', ui: canCreateUi ? '“New encounter” button shown' : 'button hidden', api: create.status, consistent: canCreateUi === (create.status === 201) })
  await page.goto(`${BASE}/encounters?q=${role === 'administrator' ? P + 1 : P + 2}`, { waitUntil: 'networkidle0' })
  let canDeleteUi = false
  if (role !== 'analyst') {
    await page.click('table.data tbody tr'); await page.waitForSelector('.modal dl.facts')
    canDeleteUi = await hasButton(page, 'Delete', '.modal')
  }
  const target = role === 'administrator' ? P + 1 : P + 2
  const del = await apiCall(page, 'DELETE', `/encounters/${target}`)
  rows.push({ action: 'Delete encounter', ui: role === 'analyst' ? 'no detail actions (read-only)' : canDeleteUi ? '“Delete” button shown' : '“Delete” button hidden', api: del.status, consistent: canDeleteUi === (del.status === 204) })
  const exp = await apiCall(page, 'GET', '/reports/export?report=encounters&format=csv&date_from=2005-03-01&date_to=2005-03-02')
  await page.goto(`${BASE}/reports`, { waitUntil: 'networkidle0' })
  const exportOption = await page.$$eval('select option', (os) => os.some((o) => /Encounter-level/.test(o.textContent)))
  rows.push({ action: 'Encounter-level export', ui: exportOption ? 'option offered' : 'option hidden', api: exp.status, consistent: exportOption === (exp.status === 200) })
  const an = await apiCall(page, 'GET', '/reports/export?report=readmission_summary&format=csv')
  rows.push({ action: 'Aggregated export', ui: 'option offered', api: an.status, consistent: an.status === 200 })
  const histUi = await page.evaluate(() => Boolean(document.querySelector('section[aria-label="Report history"]')))
  const hist = await apiCall(page, 'GET', '/reports/history')
  rows.push({ action: 'Report history table', ui: histUi ? 'table shown' : 'table hidden', api: hist.status, consistent: histUi === (hist.status === 200) })
  matrix[role] = rows
  rows.forEach((r) => check(`${role}: ${r.action} -- UI "${r.ui}" agrees with API ${r.api}`, r.consistent))
  if (role !== 'administrator') await context.close()
}
// administrator cleanup of the two seeded encounters is part of the matrix above (deleted); remove the third attempt too
await apiCall(admin.page, 'DELETE', `/encounters/${P + 2}`)  // created by clinical_ops, who cannot delete it
await apiCall(admin.page, 'DELETE', `/encounters/${P + 3}`)

// ---- screenshots of each role's main pages ----------------------------------------------------------------------
await admin.page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' })
const shots = await newSession()
await shots.page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' }); await shot(shots.page, '01_login', false)
await shots.context.close()

// ---- token handling and network hygiene (administrator) -----------------------------------------------------------
const tokenBefore = await admin.page.evaluate(() => sessionStorage.getItem('hc_token'))
check('token is kept in sessionStorage, not localStorage', Boolean(tokenBefore) && (await admin.page.evaluate(() => localStorage.length)) === 0)
await admin.page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle0' })
await admin.page.evaluate(() => sessionStorage.removeItem('hc_token'))
await admin.page.reload({ waitUntil: 'networkidle0' })
check('deleting the token and refreshing lands on the login page', new URL(admin.page.url()).pathname === '/login')
await login(admin.page, 'administrator')
check('a refresh keeps the session', await (async () => { await admin.page.reload({ waitUntil: 'networkidle0' }); return (await admin.page.$('.sidebar nav a')) !== null })())
const apiRequests = requestLog.filter((r) => new URL(r.url).pathname.startsWith('/api/') && !r.url.includes('/auth/login'))
check('every API call (except login) carries the Authorization header', apiRequests.length > 20 && apiRequests.every((r) => /^Bearer /.test(r.auth || '')), `${apiRequests.length} requests`)
check('no token appears in any URL', requestLog.every((r) => !r.url.includes(tokenBefore || 'x'.repeat(40)) && !/token=|access_token/.test(r.url)))
await admin.page.evaluate(() => sessionStorage.setItem('hc_token', 'tampered.token.value'))
await admin.page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle0' })
check('an invalid token is rejected and sends the user to login (401 handled centrally)', new URL(admin.page.url()).pathname === '/login')
await login(admin.page, 'administrator')

// ---- dashboard: numbers, states, stale requests ---------------------------------------------------------------------
await admin.page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle0' })
await sleep(1500)
const apiSummary = (await apiCall(admin.page, 'GET', '/analytics/summary')).data.data
const kpi = async (id) => admin.page.$eval(`[data-testid=${id}] .kpi-value`, (e) => e.textContent)
check('KPI card "Encounters" equals the API value', (await kpi('kpi-encounters')).replace(/,/g, '') === String(apiSummary.total_encounters), await kpi('kpi-encounters'))
check('KPI card 30-day rate equals the API value (formatted)', (await kpi('kpi-30-day-readmission-rate')) === `${(apiSummary.readmission_rate_30d * 100).toFixed(2)}%`, await kpi('kpi-30-day-readmission-rate'))
check('simulated-dates banner is shown', (await admin.page.$eval('main', (m) => m.textContent)).includes('Admission dates in this dataset are simulated'))
const ageSection = 'section[aria-label="Readmission by age group"]'
await clickButton(admin.page, 'View as table', ageSection)
const ageRows = await admin.page.$$eval(`${ageSection} tbody tr`, (trs) => trs.map((tr) => [...tr.children].map((td) => td.textContent)))
check('age groups are in clinical order, 0-10 first and 90-100 last', ageRows[0][0].startsWith('[0-10)') && ageRows[ageRows.length - 1][0].startsWith('[90-100)'), ageRows.map((r) => r[0]).join(' '))
check('age-group table counts add up to the Encounters card', ageRows.reduce((s, r) => s + Number(r[1].replace(/,/g, '')), 0) === apiSummary.total_encounters)
await shot(admin.page, '02_dashboard_admin')
await clickButton(admin.page, 'View as chart', ageSection)
// change filters rapidly: the page must settle on the LAST selection and agree with the API for it
const typeSel = await idForLabel(admin.page, 'Admission type', 'form[aria-label="Dashboard filters"]')
const selectEl = await admin.page.evaluateHandle(() => [...document.querySelectorAll('.filters label')].find((l) => l.textContent.startsWith('Admission type')).querySelector('select'))
for (const v of ['2', '1', '3', '2', '1', '2']) { await selectEl.asElement().select(v); await sleep(80) }
await sleep(2500)
const final = (await apiCall(admin.page, 'GET', '/analytics/summary?admission_type_id=2')).data.data.total_encounters
check('after rapid filter changes the cards show the LAST selection', (await kpi('kpi-encounters')).replace(/,/g, '') === String(final), `${await kpi('kpi-encounters')} vs API ${final}`)
await shot(admin.page, '03_dashboard_filtered')
await selectEl.asElement().select('')
await sleep(1500)

// ---- encounters: validation, create, edit, delete, audit -------------------------------------------------------------
await admin.page.goto(`${BASE}/encounters`, { waitUntil: 'networkidle0' })
await shot(admin.page, '04_encounters_admin')
await clickButton(admin.page, 'New encounter', 'main')
await admin.page.waitForSelector('.modal form')
await sleep(500)
const fillForm = async (over = {}) => {
  const v = { 'Encounter ID': P + 5, 'Patient number': P, 'Age group': '[70-80)', 'Admission date': '2005-03-01', 'Discharge date': '2005-03-04', 'Length of stay': 3,
    'Admission type': 1, 'Admission source': 7, 'Discharge disposition': 1, ...over }
  for (const [label, value] of Object.entries(v)) await fill(admin.page, label, value)
}
const postsBefore = requestLog.filter((r) => r.url.endsWith('/api/encounters')).length
await fillForm({ 'Length of stay': 20 })
await clickButton(admin.page, 'Create encounter', '.modal')
const losError = await admin.page.evaluate(() => { const l = [...document.querySelectorAll('.modal label')].find((x) => x.textContent.startsWith('Length of stay')); return l?.closest('.field')?.querySelector('[role=alert]')?.textContent || '' })
check('invalid length of stay: message appears under the right field', /1 to 14/.test(losError), losError)
await shot(admin.page, '05_encounter_form_validation', false)
check('invalid form is not sent to the API', requestLog.filter((r) => r.url.endsWith('/api/encounters')).length === postsBefore)
await fill(admin.page, 'Length of stay', 3)
await fill(admin.page, 'Patient number', 123)  // a patient that does not exist: the SERVER says so
await clickButton(admin.page, 'Create encounter', '.modal')
await admin.page.waitForFunction(() => { const l = [...document.querySelectorAll('.modal label')].find((x) => x.textContent.startsWith('Patient number')); return l?.closest('.field')?.querySelector('[role=alert]') }, { timeout: 10000 })
const patientError = await admin.page.evaluate(() => [...document.querySelectorAll('.modal label')].find((x) => x.textContent.startsWith('Patient number')).closest('.field').querySelector('[role=alert]').textContent)
check('server 422 (unknown patient) is mapped onto the Patient number field', /does not exist/.test(patientError), patientError)
await fill(admin.page, 'Patient number', P)
await clickButton(admin.page, 'Create encounter', '.modal')
await admin.page.waitForSelector('.toast.success', { timeout: 10000 })
check('valid encounter is created and a success toast is shown', true)
await sleep(600)
await admin.page.goto(`${BASE}/encounters?q=${P + 5}`, { waitUntil: 'networkidle0' })
await admin.page.click('table.data tbody tr'); await admin.page.waitForSelector('.modal dl.facts')
await clickButton(admin.page, 'Edit', '.modal'); await admin.page.waitForSelector('.modal form')
await sleep(400)
await fill(admin.page, 'Readmitted', '<30')
await clickButton(admin.page, 'Save changes', '.modal')
await admin.page.waitForSelector('.toast.success', { timeout: 10000 }); await sleep(800)
const edited = (await apiCall(admin.page, 'GET', `/encounters/${P + 5}`)).data
check('edit saved and the server derived readmitted_30d = true', edited.readmitted === '<30' && edited.readmitted_30d === true)
await admin.page.click('table.data tbody tr'); await admin.page.waitForSelector('.modal dl.facts')
await shot(admin.page, '06_encounter_detail', false)
await clickButton(admin.page, 'Delete', '.modal'); await admin.page.waitForSelector('.modal[aria-label="Delete encounter?"]')
await shot(admin.page, '07_delete_confirmation', false)
await clickButton(admin.page, 'Delete', '.modal[aria-label="Delete encounter?"]')
await admin.page.waitForSelector('.toast.success', { timeout: 10000 }); await sleep(800)
check('deleted encounter disappears from the list', (await admin.page.$('table.data tbody tr')) === null)
await admin.page.goto(`${BASE}/audit?entity_id=${P + 5}&sort_dir=asc`, { waitUntil: 'networkidle0' })
const auditActions = await admin.page.$$eval('table.data tbody tr', (trs) => trs.map((tr) => tr.children[2].textContent))
check('audit log shows exactly CREATE, UPDATE, DELETE for what was just done', JSON.stringify(auditActions) === JSON.stringify(['CREATE', 'UPDATE', 'DELETE']), auditActions.join(', '))
await clickButton(admin.page, 'Show before/after', 'table.data tbody tr:nth-child(2)')
const diffRows = await admin.page.$$eval('.audit-detail tbody tr', (trs) => trs.map((tr) => tr.children[0].textContent))
check('UPDATE audit row shows only the fields that changed', diffRows.includes('readmitted') && diffRows.includes('readmitted_30d') && !diffRows.includes('age_group'), diffRows.join(', '))
await shot(admin.page, '08_audit_log')

// ---- other admin and staff screens, reports, analyst view -----------------------------------------------------------------
for (const [file, p] of [['09_patients', '/patients'], ['10_pipeline_runs', '/pipeline'], ['11_data_quality', '/data-quality?run_id=1'], ['12_users', '/users']]) {
  await admin.page.goto(`${BASE}${p}`, { waitUntil: 'networkidle0' }); await sleep(400); await shot(admin.page, file)
}
await admin.page.goto(`${BASE}/pipeline`, { waitUntil: 'networkidle0' })
const runRows = await admin.page.$$eval('table.data tbody tr', (trs) => trs.map((tr) => [...tr.children].map((td) => td.textContent)))
check('pipeline page shows status, counts and reject ratio', runRows.length > 0 && runRows.some((r) => /SUCCESS|SKIPPED/.test(r[2])) && runRows.every((r) => /%|n\/a/.test(r[8])))
await admin.page.goto(`${BASE}/patients/135`, { waitUntil: 'networkidle0' })
await clickButton(admin.page, 'Encounters', '.tabs'); await sleep(800)
await shot(admin.page, '13_patient_detail')

await admin.page.goto(`${BASE}/reports`, { waitUntil: 'networkidle0' })
const dl = fs.mkdtempSync(path.join(os.tmpdir(), 'hc-dl-'))
const cdp = await admin.page.createCDPSession()
await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: dl, browserContextId: admin.context.id })
await clickButton(admin.page, 'Download', 'form[aria-label="Report options"]')
await admin.page.waitForSelector('.toast.success', { timeout: 20000 })
for (let i = 0; i < 40 && !fs.readdirSync(dl).some((f) => f.endsWith('.xlsx')); i++) await sleep(250)  // wait for the finished file (not .crdownload)
const files = fs.readdirSync(dl)
const file = files.find((f) => f.endsWith('.xlsx'))
const head = file ? fs.readFileSync(path.join(dl, file)).subarray(0, 2).toString() : ''
check('Excel report downloads through the UI with authentication (blob, no token in URL)', Boolean(file) && head === 'PK' && /^readmission_summary_\d{8}_\d{6}\.xlsx$/.test(file), file || 'no file')
await shot(admin.page, '14_reports_admin')
await admin.page.select('form[aria-label="Report options"] select', 'encounters')
await clickButton(admin.page, 'Download', 'form[aria-label="Report options"]')
await admin.page.waitForSelector('.field-error', { timeout: 20000 })
check('an oversized encounter export shows the server\'s helpful 413 message', /limit is 50,000/.test(await admin.page.$eval('.report-form .field-error', (e) => e.textContent)))

const analyst = await newSession()
await login(analyst.page, 'analyst')
await analyst.page.goto(`${BASE}/encounters`, { waitUntil: 'networkidle0' }); await sleep(600)
const cols = await analyst.page.$$eval('table.data thead th', (ths) => ths.map((t) => t.textContent.replace(/[▲▼]/g, '').trim()))
check('analyst encounter table has no patient column and no create button', !cols.includes('Patient') && !(await hasButton(analyst.page, 'New encounter', 'main')), cols.join(', '))
check('analyst has no patient-number filter', !(await analyst.page.$$eval('.filters label', (ls) => ls.some((l) => l.textContent.startsWith('Patient number')))))
await shot(analyst.page, '15_encounters_analyst')
await analyst.page.goto(`${BASE}/patients`, { waitUntil: 'networkidle0' })
check('analyst opening /patients sees "Not permitted"', (await analyst.page.$eval('main h1', (e) => e.textContent)) === 'Not permitted')
await shot(analyst.page, '16_not_permitted', false)
await analyst.page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle0' }); await sleep(2000); await shot(analyst.page, '17_dashboard_analyst')
const ops = await newSession()
await login(ops.page, 'clinical_ops')
await ops.page.goto(`${BASE}/patients`, { waitUntil: 'networkidle0' }); await sleep(500); await shot(ops.page, '18_patients_clinical_ops')

// cleanup of the seeded patient
await apiCall(admin.page, 'DELETE', `/patients/${P}`)
await browser.close()

// ---- write docs/role_verification.md from what was observed --------------------------------------------------------------
const lines = ['# Role verification (UI versus direct API)', '',
  `Run by \`frontend/e2e/run.mjs\` on ${new Date().toISOString().slice(0, 10)} with headless Chrome against the real API and database. For every role and action the script recorded what the UI shows and what the API answers when the same call is made directly with that role's token (\`fetch\` with the Authorization header from the session). The UI only hides things; the API status is the real enforcement.`, '',
  '| Role | Action | UI behaviour | Direct API status | Agree |', '|---|---|---|---|---|']
for (const [role, rows] of Object.entries(matrix)) for (const r of rows) lines.push(`| ${role} | ${r.action} | ${r.ui} | ${r.api} | ${r.consistent ? 'yes' : '**NO**'} |`)
lines.push('', 'API status meaning: 200/201/204 = allowed, 403 = forbidden by role (401 would mean no or invalid token).', '',
  '## Other checks', '', '| Check | Result | Detail |', '|---|---|---|')
for (const c of results.filter((r) => !/^(administrator|clinical_ops|analyst): /.test(r.name) || /navigation|top bar/.test(r.name))) lines.push(`| ${c.name} | ${c.ok ? 'PASS' : '**FAIL**'} | ${c.detail.replace(/\|/g, '/')} |`)
fs.writeFileSync(path.join(ROOT, 'docs', 'role_verification.md'), lines.join('\n') + '\n')
const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
process.exit(failed.length ? 1 : 0)
