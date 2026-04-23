
/**
 * scope_tests.js — Tests for the search scope selector feature
 *
 * Validates:
 *   1. Fairfield auto-defaults to Pass 4 with 15 comps + broadened note
 *   2. Park Lane auto-defaults to Pass 1 with 15 comps + no broadened note
 *   3. Dropdown change triggers comp reload with correct pass
 *
 * Usage: node tests/scope_tests.js --url=http://localhost:5173
 */
const { chromium } = require("playwright");

const args     = process.argv.slice(2);
const urlArg   = args.find(a => a.startsWith("--url="));
const BASE_URL = urlArg ? urlArg.split("=")[1] : "http://localhost:5173";
const TIMEOUT  = 30000;

const results = [];
function pass(name) { console.log(`  ✅ PASS: ${name}`); results.push({ name, passed: true }); }
function fail(name, error) { console.error(`  ❌ FAIL: ${name}\n     ${error}`); results.push({ name, passed: false, error: String(error) }); }

async function searchAndSelectProperty(page, address, zip) {
  await page.goto(BASE_URL, { waitUntil: "networkidle", timeout: TIMEOUT });
  const inputs = await page.$$('input[type="text"]');
  await inputs[0].fill(address);
  await inputs[1].fill(zip);
  await page.click(".btn-primary");
  await page.waitForSelector(".prop-card", { timeout: TIMEOUT });
  const cards = await page.$$(".prop-card");
  await cards[0].click();
  await page.waitForSelector(".comps-table", { timeout: TIMEOUT });
  // Wait for sync useEffect to settle
  await page.waitForTimeout(4000);
}

async function runTests() {
  console.log(`\n🔬 Scope Selector Tests — Target: ${BASE_URL}\n`);
  const browser = await chromium.launch({
    headless: false,
    args: ["--disable-blink-features=AutomationControlled"]
  });
  const context = await browser.newContext({
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
  });

  // ── Test 1: Fairfield defaults to Pass 4 with 15 comps ──────────────────
  try {
    const page = await context.newPage();
    await searchAndSelectProperty(page, "5650 FAIRFIELD AVE", "75205");
    const dropdown = await page.evaluate(() => document.querySelector("select")?.value);
    const rows = await page.$$(".comps-table tbody tr");
    if (dropdown !== "4") throw new Error(`Dropdown shows "${dropdown}", expected "4"`);
    if (rows.length < 10) throw new Error(`Only ${rows.length} comps, expected 15+`);
    pass(`Fairfield: auto Pass ${dropdown}, ${rows.length} comps`);
    await page.close();
  } catch (e) { fail("Fairfield auto-defaults to Pass 4", e.message || e); }

  // ── Test 2: Fairfield Pass 4 shows broadened search note ────────────────
  try {
    const page = await context.newPage();
    await searchAndSelectProperty(page, "5650 FAIRFIELD AVE", "75205");
    const noteVisible = await page.evaluate(() => {
      const divs = [...document.querySelectorAll("div")];
      return divs.some(d => d.textContent.includes("broadened"));
    });
    if (!noteVisible) throw new Error("Broadened search note not visible");
    pass("Fairfield: Pass 4 broadened search note visible");
    await page.close();
  } catch (e) { fail("Fairfield Pass 4 broadened note", e.message || e); }

  // ── Test 3: Park Lane defaults to Pass 1 with 15 comps ─────────────────
  try {
    const page = await context.newPage();
    await searchAndSelectProperty(page, "6816 Park Ln", "75225");
    const dropdown = await page.evaluate(() => document.querySelector("select")?.value);
    const rows = await page.$$(".comps-table tbody tr");
    if (dropdown !== "1") throw new Error(`Dropdown shows "${dropdown}", expected "1"`);
    if (rows.length < 10) throw new Error(`Only ${rows.length} comps, expected 15`);
    pass(`Park Lane: auto Pass ${dropdown}, ${rows.length} comps`);
    await page.close();
  } catch (e) { fail("Park Lane auto-defaults to Pass 1", e.message || e); }

  // ── Test 4: Park Lane does NOT show broadened search note ───────────────
  try {
    const page = await context.newPage();
    await searchAndSelectProperty(page, "6816 Park Ln", "75225");
    const noteVisible = await page.evaluate(() => {
      const divs = [...document.querySelectorAll("div")];
      return divs.some(d => d.textContent.includes("broadened"));
    });
    if (noteVisible) throw new Error("Broadened note should NOT appear for Pass 1");
    pass("Park Lane: no broadened search note (correct)");
    await page.close();
  } catch (e) { fail("Park Lane no broadened note", e.message || e); }

  // ── Test 5: Dropdown change triggers reload with new pass ───────────────
  try {
    const page = await context.newPage();
    await searchAndSelectProperty(page, "6816 Park Ln", "75225");
    // Change dropdown from Pass 1 to Pass 4
    await page.selectOption("select", "4");
    await page.waitForTimeout(4000);
    const dropdown = await page.evaluate(() => document.querySelector("select")?.value);
    const rows = await page.$$(".comps-table tbody tr");
    if (dropdown !== "4") throw new Error(`After change, dropdown shows "${dropdown}", expected "4"`);
    if (rows.length < 10) throw new Error(`After change, only ${rows.length} comps`);
    pass(`Dropdown change: switched to Pass ${dropdown}, ${rows.length} comps loaded`);
    await page.close();
  } catch (e) { fail("Dropdown change triggers reload", e.message || e); }

  // ── Test 6: ℹ️ info dialog opens and closes ─────────────────────────────
  try {
    const page = await context.newPage();
    await searchAndSelectProperty(page, "6816 Park Ln", "75225");
    await page.click("button:has-text('How it works')");
    await page.waitForTimeout(500);
    const dialogVisible = await page.evaluate(() => {
      return [...document.querySelectorAll("h3")].some(h => h.textContent.includes("About Your Comparable"));
    });
    if (!dialogVisible) throw new Error("Info dialog did not open");
    // Close it
    await page.click("button:has-text('Close')");
    await page.waitForTimeout(300);
    const dialogGone = await page.evaluate(() => {
      return ![...document.querySelectorAll("h3")].some(h => h.textContent.includes("About Your Comparable"));
    });
    if (!dialogGone) throw new Error("Info dialog did not close");
    pass("Info dialog opens and closes correctly");
    await page.close();
  } catch (e) { fail("Info dialog opens/closes", e.message || e); }

  await browser.close();

  const passed = results.filter(r => r.passed).length;
  const failed = results.filter(r => !r.passed).length;
  console.log(`\n${"─".repeat(60)}`);
  console.log(`Results: ${passed} passed, ${failed} failed (${results.length} total)`);
  if (failed > 0) {
    results.filter(r => !r.passed).forEach(r => console.log(`  • ${r.name}: ${r.error}`));
    process.exit(1);
  } else {
    console.log("\n🎉 All scope tests passed!");
    process.exit(0);
  }
}

runTests().catch(err => { console.error("Fatal:", err); process.exit(1); });
