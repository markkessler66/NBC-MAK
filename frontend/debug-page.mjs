import { chromium } from "playwright";

const url = process.argv[2] ?? "http://localhost:5173/";
const shot = process.argv[3] ?? "debug-screenshot.png";
const clickTab = process.argv[4]; // optional tab label to open

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

page.on("console", (msg) => {
  if (msg.type() === "error" || msg.type() === "warning") {
    console.log(`[console.${msg.type()}] ${msg.text()}`);
  }
});
page.on("pageerror", (err) => {
  console.log(`[pageerror] ${err.stack ?? err.message}`);
});

await page.goto(url, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
if (clickTab) {
  await page.click(`text=${clickTab}`);
}
await page.waitForTimeout(8000);

const rootHtmlLength = await page.evaluate(
  () => document.getElementById("root")?.innerHTML.length ?? -1,
);
console.log(`[root innerHTML length] ${rootHtmlLength}`);

await page.screenshot({ path: shot, fullPage: false });
console.log(`[screenshot] ${shot}`);
await browser.close();
