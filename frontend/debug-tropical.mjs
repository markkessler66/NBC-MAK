import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

page.on("pageerror", (err) => console.log(`[pageerror] ${err.stack ?? err.message}`));
page.on("console", (msg) => {
  if (msg.type() === "error") console.log(`[console.error] ${msg.text()}`);
});

await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3000);
await page.click("text=Tropical");
await page.waitForTimeout(8000);

const crashed = await page.evaluate(() => document.body.innerText.includes("crashed"));
console.log(`[boundary shows crash] ${crashed}`);
if (crashed) {
  const text = await page.evaluate(
    () => Array.from(document.querySelectorAll(".card")).map((c) => c.textContent).join(" | "),
  );
  console.log(`[boundary text] ${text.slice(0, 500)}`);
}
await page.screenshot({ path: "debug-tropical.png" });
console.log("[screenshot] debug-tropical.png");
await browser.close();
