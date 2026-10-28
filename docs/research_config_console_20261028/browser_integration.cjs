const fs=require('fs'),path=require('path');
const {chromium}=require('/opt/homebrew/lib/node_modules/openclaw/node_modules/playwright-core');
let browser;
(async()=>{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const errors=[],blocked=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
 const payload=JSON.parse(fs.readFileSync(__dirname+'/browser_payload.json'));
 await context.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.hostname==='cdn.jsdelivr.net')return route.fulfill({path:__dirname+'/vendors/'+(url.pathname.includes('plugin-zoom')?'zoom.js':'chart.js'),contentType:'application/javascript'});
  if(url.hostname!=='isolated-console.test'){blocked.push(url.hostname);return route.abort();}
  if(url.pathname.startsWith('/api/'))return route.fulfill({body:JSON.stringify(payload),contentType:'application/json'});
  const relative=url.pathname==='/'?'console/ui/index.html':'console'+url.pathname;
  const file=path.resolve(__dirname,'candidate',relative);
  if(!file.startsWith(path.resolve(__dirname,'candidate','console')+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({path:file,contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
 });
 if(context.routeWebSocket)await context.routeWebSocket('**/*',socket=>socket.close());
 await page.goto('http://isolated-console.test/',{waitUntil:'networkidle'});
 await page.getByText('未計測',{exact:true}).first().waitFor();
 await page.getByText('3.7',{exact:true}).first().waitFor();
 await page.getByText('注文ID対応未確認',{exact:true}).first().waitFor();
 await page.locator('#console-evidence summary').click();
 await page.getByText('隔離検証済み／稼働未反映',{exact:false}).first().waitFor();
 for(let i=0;i<2;i++){
  await page.locator('[data-tab="trading"]').click();
  await page.getByText('終了記録のみ・正常性未確認',{exact:true}).first().waitFor();
  await page.locator('[data-tab="overview"]').click();
  await page.waitForTimeout(150);
 }
 await page.reload({waitUntil:'networkidle'});
 await page.getByText('3.7',{exact:true}).first().waitFor();
 await page.setViewportSize({width:390,height:844});
 await page.locator('#console-evidence summary').click();
 await page.waitForTimeout(500);
 const dimensions=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth}));
 await page.screenshot({path:__dirname+'/browser-mobile.png',fullPage:true});
 if(dimensions.width>dimensions.viewport||errors.length)throw Error(JSON.stringify({dimensions,errors}));
 const result={isolated_browser:true,actual_HTML_JS_CSS:true,synthetic_API_from_actual_service:true,external_requests_sent:0,missing_DD_unknown:true,audit_fractional_qty:3.7,cancel_unconfirmed_not_terminal:true,completed_not_success:true,tab_roundtrips:2,reload:1,mobile:dimensions,page_errors:errors,blocked_hosts:blocked,production_deployed:false,real_service_or_broker_qualified:false};
 fs.writeFileSync(__dirname+'/browser_results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();
})().catch(async e=>{console.error(e);if(browser)await browser.close();process.exitCode=1});
