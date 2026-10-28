async function waitOut(result) {
  if (!result) return "";
  if (result.status === "running" && result.sessionId) {
    for (let i = 0; i < 20; i += 1) {
      let polled = null;
      try {
        polled = await process({
          action: "poll",
          sessionId: result.sessionId,
          timeout: 10000,
        });
      } catch (_error) {
        break;
      }
      if (polled && polled.status && polled.status !== "running") {
        result = polled;
        break;
      }
    }
    try {
      const logged = await process({ action: "log", sessionId: result.sessionId });
      if (logged) {
        if (logged.output !== undefined) return String(logged.output);
        if (logged.log !== undefined) return String(logged.log);
        return JSON.stringify(logged);
      }
    } catch (_error) {
      // Fall through to the normalized result fields below.
    }
  }
  if (result.aggregated !== undefined) return String(result.aggregated);
  if (result.output !== undefined) return String(result.output);
  if (result.stdout !== undefined) return String(result.stdout);
  if (result.tail !== undefined) return String(result.tail);
  return JSON.stringify(result);
}

const result = await exec({
  command:
    "cd ~/stock_swing && . venv/bin/activate && " +
    "python scripts/log_sector_rotation_shadow.py --parallel-new-headline 2>&1; " +
    "echo EXIT_CODE=$?",
  timeoutSeconds: 260,
  yieldMs: 270000,
});
const output = await waitOut(result);
const exitMatch = output.match(/EXIT_CODE=(\d+)/);
if (exitMatch && exitMatch[1] === "0") return {};
return { notify: "❌ sector_rotation_shadow 実行エラー\n" + output.slice(-600) };
