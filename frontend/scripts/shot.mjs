// Screenshot the running app for visual checks. Tabs are in-page state rather
// than routes, so navigation happens by clicking.
//
//   node scripts/shot.mjs --out shots/x.png --tab Tropical --click "button:has-text('Full analysis')"
//
// Named flags on purpose: PowerShell silently drops empty positional arguments,
// which quietly shifts every later parameter.
import { chromium } from "playwright";

const args = new Map();
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i].replace(/^--/, ""), process.argv[i + 1]);
}

const out = args.get("out") ?? "shot.png";
const tab = args.get("tab");
const wait = Number(args.get("wait") ?? 8000);
const clip = args.get("clip");
const click = args.get("click");
const scroll = args.get("scroll");
// "<selector>=<value>", for driving the overlay and lead-time dropdowns.
const select = args.get("select");
const base = process.env.SHOT_BASE ?? "http://127.0.0.1:8000";

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1500, height: 1100 },
  deviceScaleFactor: 2,
});
page.on("pageerror", (e) => console.log("[pageerror]", e.message));
page.on("console", (m) => {
  const t = m.text();
  if (m.type() === "error" && !t.includes("GL Driver")) console.log("[console.error]", t);
});

await page.goto(base + "/", { waitUntil: "networkidle" });
if (tab) await page.getByRole("button", { name: tab, exact: true }).click();
await page.waitForTimeout(wait);

if (click) {
  // Innermost match, so a text selector cannot land on a wrapper with no handler.
  const target = page.locator(click);
  await target.nth((await target.count()) - 1).click();
  await page.waitForTimeout(wait);
}

if (select) {
  const at = select.lastIndexOf("=");
  await page.locator(select.slice(0, at)).first().selectOption(select.slice(at + 1));
  await page.waitForTimeout(2500);
}

if (scroll) {
  await page.locator(scroll).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(1200);
}

if (clip) {
  await page.locator(clip).first().screenshot({ path: out });
} else {
  await page.screenshot({ path: out, fullPage: true });
}
console.log("wrote", out);
await browser.close();
