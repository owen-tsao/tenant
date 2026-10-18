/* Deck self-test — loads only with ?selftest=1. Drives the deck with synthetic key presses the way a hurried
 * presenter would, and writes the results into <pre id="selftest"> so headless Chrome can --dump-dom them.
 * Not a unit test; a smoke test of navigation + step effects under real timers.
 * ?selftest=first  → only the "first press after load" scenario, traced in detail. */
(function () {
  const sleep = ms => new Promise(x => setTimeout(x, ms));
  const key = k => window.dispatchEvent(new KeyboardEvent("keydown", { key: k }));
  const $ = s => document.querySelector(s);
  const out = document.createElement("pre"); out.id = "selftest"; out.style.cssText = "position:fixed;left:0;bottom:0;z-index:99;font:11px monospace;color:#fff;background:#000a;margin:0;padding:4px;";
  document.body.appendChild(out);
  const errs = []; window.addEventListener("error", e => errs.push(e.message));
  const log = (s) => { out.textContent += s + "\n"; };
  const active = () => document.querySelectorAll(".slide.is-active").length;
  const mode = new URLSearchParams(location.search).get("selftest");

  if (mode === "first") {
    // Trace every hashchange and every slide class change from load until 3 s after the first press.
    const trace = [];
    const t0 = performance.now();
    const T = () => Math.round(performance.now() - t0);
    window.addEventListener("hashchange", () => trace.push(`${T()} hashchange -> ${location.hash}`));
    new MutationObserver(ms => { for (const m of ms) if (m.target.classList && m.target.classList.contains("slide")) trace.push(`${T()} ${m.target.dataset.id}.class=${m.target.className}`); })
      .observe(document.getElementById("deck"), { attributes: true, attributeFilter: ["class"], subtree: true, childList: true });
    window.addEventListener("load", async () => {
      await sleep(1500);
      trace.push(`${T()} PRESS hash=${location.hash}`);
      key("ArrowRight");
      await sleep(3000);
      trace.push(`${T()} END hash=${location.hash} active=${[...document.querySelectorAll(".slide.is-active")].map(s => s.dataset.id)}`);
      trace.forEach(log); log("errors=" + JSON.stringify(errs)); log("DONE");
    });
    return;
  }

  window.addEventListener("load", async () => {
    await sleep(400);
    for (let i = 0; i < 11; i++) { key("ArrowRight"); await sleep(120); }
    await sleep(3200);
    log(`rapid11 hash=${location.hash} active=${active()}`);
    for (let i = 0; i < 6; i++) { key("ArrowLeft"); await sleep(100); }
    await sleep(2200);
    log(`back6 hash=${location.hash} ask=${JSON.stringify($("#typed-ask").textContent)}`);
    key("ArrowRight"); await sleep(600);
    log(`reply@600=${JSON.stringify($("#typed-reply").textContent)} waiting=${$("#typed-reply").parentElement.classList.contains("waiting")}`);
    await sleep(2900);
    log(`reply@3500=${JSON.stringify($("#typed-reply").textContent)}`);
    key("ArrowRight"); await sleep(1500);
    log(`lease hash=${location.hash} left=${$("#lease-left").dataset.value} count=${$(".device-count").textContent}`);
    key("ArrowRight"); await sleep(800);
    log(`leave hash=${location.hash} ended=${$("#lease-block").classList.contains("ended")} left=${$("#lease-left").dataset.value}`);
    key("ArrowRight"); await sleep(800);
    log(`vision hash=${location.hash} active=${active()}`);
    key("ArrowRight"); await sleep(600);
    log(`reach hash=${location.hash}`);
    key("ArrowRight"); await sleep(800);
    log(`scan hash=${location.hash} qr=${document.querySelectorAll("#qr svg, #qr img").length} active=${active()}`);
    // Owen's bounce (05:56): run past the first slide with queued ← presses, then one →. Must land on #2 and stay.
    key("End"); await sleep(900);
    for (let i = 0; i < 14; i++) { key("ArrowLeft"); await sleep(90); }
    await sleep(2500);
    key("ArrowRight"); await sleep(1500);
    log(`edge-queue hash=${location.hash} (expect #2) active=${active()}`);
    key("Home"); await sleep(600);
    log(`home hash=${location.hash} active=${active()} errors=${JSON.stringify(errs)}`);
    log("DONE");
  });
})();
