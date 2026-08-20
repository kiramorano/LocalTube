const { chromium } = require('playwright');
const path = require('path');
const OUT = path.join(__dirname, 'shots') + path.sep;
const fs = require('fs');
fs.mkdirSync(OUT, {recursive:true});
(async () => {
  const browser = await chromium.launch({headless:true});
  const report = [];
  for (const theme of ['dark','frutiger-aero']) {
    for (const vp of [{n:'desktop',width:1440,height:900},{n:'mobile',width:390,height:844}]) {
      const page = await browser.newPage({viewport:{width:vp.width,height:vp.height}});
      const errors = [];
      page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
      page.on('pageerror', e => errors.push(e.message));
      await page.goto('http://127.0.0.1:5000/', {waitUntil:'networkidle'});
      await page.evaluate(t => localStorage.setItem('lt_theme', t), theme);
      for (const path of ['/','/settings','/channel/ANATA%20CARS','/upload']) {
        await page.goto('http://127.0.0.1:5000'+path, {waitUntil:'networkidle'});
        const name = theme+'-'+vp.n+'-'+(path==='/'?'home':path.replace(/[^a-z]/gi,'')||'root');
        await page.screenshot({path: OUT+name+'.png', fullPage:true});
        const metrics = await page.evaluate(() => {
          const de = document.documentElement;
          const overflowing = [...document.querySelectorAll('body *')].filter(el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && (r.right > window.innerWidth + 2 || r.left < -2);
          }).slice(0,6).map(el => el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+(el.className && typeof el.className==='string'?'.'+el.className.trim().split(/\s+/)[0]:''));
          return {hScroll: de.scrollWidth > de.clientWidth + 1, scrollW: de.scrollWidth, clientW: de.clientWidth, font: getComputedStyle(document.body).fontFamily, overflowing};
        });
        report.push({theme, vp:vp.n, path, ...metrics, errors:[...errors]});
        errors.length = 0;
      }
      await page.close();
    }
  }
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})();
