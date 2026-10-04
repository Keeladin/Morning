import { chromium } from 'playwright'
import assert from 'node:assert/strict'
const origin = process.env.MORNING_TEST_ORIGIN || 'http://127.0.0.1:18090'
assert.equal(new URL(origin).hostname, '127.0.0.1', 'This verifier only runs against an isolated loopback test service')
const browser = await chromium.launch({ headless: true })
try {
  const response = await fetch(`${origin}/healthz`)
  assert.equal((await response.json()).environment, 'test', 'Never run this verifier against production')
  for (const viewport of [{width:360,height:800}, {width:1280,height:900}]) {
    const context = await browser.newContext({ viewport })
    const login = await context.request.post(`${origin}/api/morning/auth/login`, { data: {username:'receipt-browser',password:'test-browser-password'} })
    assert.equal(login.status(), 200)
    const page = await context.newPage()
    const errors=[]
    page.on('pageerror',error=>errors.push(error.message))
    await page.goto(origin)
    await page.getByRole('button', {name:'Choose date / shift · new report or correction'}).click()
    await page.getByLabel('Shift reporting date').fill('2026-10-02')
    await page.getByRole('button',{name:'Morning',exact:true}).click()
    await page.getByRole('button',{name:'Open / start report',exact:true}).click()
    await page.getByRole('heading',{name:'Report submitted!'}).waitFor()
    await page.getByRole('button',{name:'Correct this report'}).click()
    await page.getByText('Editing correction · the last submitted version remains in daily reports until you submit this correction.').waitFor()
    await page.locator('.morning-stepper button').nth(1).click()
    await page.getByLabel('Brothers Keeper contribution').fill(`Corrected browser topic ${viewport.width}`)
    await page.getByRole('button',{name:'Save & continue to Safety'}).click()
    await page.getByRole('button',{name:'Next: Machine activity'}).click()
    await page.getByRole('button',{name:'Next: Other activities'}).click()
    await page.getByRole('button',{name:'Next: Review'}).click()
    let attempts=0
    await page.route('**/api/morning/offline-sync',async route=>{
      attempts++
      if(attempts===1) { await route.fetch(); await route.abort('failed'); }
      else await route.continue()
    })
    await page.getByRole('button',{name:'Submit correction',exact:true}).click()
    await page.getByText('Waiting for server confirmation.',{exact:true}).waitFor()
    assert.equal(await page.getByRole('heading',{name:'Report submitted!'}).count(),0)
    await page.getByRole('heading',{name:'Report submitted!'}).waitFor({timeout:20000})
    assert.equal(attempts,2)
    await page.getByText(/Received by Morning at/).waitFor()
    await page.getByRole('button',{name:'Submission history'}).click()
    await page.getByText(/Original submission/).waitFor()
    const reports = await context.request.get(`${origin}/api/morning/reports/mine`)
    const slot = (await reports.json()).reports.filter(r=>r.shift_date==='2026-10-02'&&r.shift_kind==='morning')
    assert.equal(slot.length,1)
    assert.equal(slot[0].status,'submitted')
    assert.equal(slot[0].brothers_keeper,`Corrected browser topic ${viewport.width}`)
    await page.getByRole('button',{name:'Choose another date / shift'}).click()
    await page.getByLabel('Shift reporting date').fill(viewport.width===360?'2026-10-03':'2026-10-01')
    await page.getByRole('button',{name:'Afternoon',exact:true}).click()
    await page.getByRole('checkbox',{name:'Browser Test Crew'}).check()
    await page.getByRole('button',{name:'Open / start report',exact:true}).click()
    await page.getByRole('heading',{name:'Attendance',exact:true}).waitFor()
    assert.equal(await page.getByRole('heading',{name:'Report submitted!'}).count(),0)
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth), 'No horizontal overflow')
    assert.deepEqual(errors,[])
    await page.screenshot({path:`/tmp/morning-receipts-${viewport.width}.png`,fullPage:true})
    await context.close()
    console.log(`PASS ${viewport.width}px: explicit historical slot, correction, lost receipt, automatic retry, one canonical report, audit history, fresh past-shift draft`)
  }
} finally { await browser.close() }
