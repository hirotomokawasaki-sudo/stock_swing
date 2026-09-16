const result = await exec({
  command: "cd /Users/hirotomookawasaki/stock_swing && venv/bin/python scripts/check_high_correlation_snapshot.py",
  timeoutSeconds: 30,
});

const output = String(
  result?.aggregated ?? result?.output ?? result?.stdout ?? result?.stderr ?? ""
).trim();
const jsonLine = output.split("\n").filter(Boolean).at(-1) ?? "";
let observation;
try {
  observation = JSON.parse(jsonLine);
} catch (error) {
  observation = { status: "error", error: `unparseable output: ${output.slice(-400)}` };
}

const previous = trigger.state?.status ?? "unknown";
const previousSignature = trigger.state?.signature ?? "";
const pairs = Array.isArray(observation.pairs)
  ? observation.pairs.map(String)
  : observation.pairs
    ? [String(observation.pairs)]
    : [];
const signature = observation.status === "alert"
  ? String(observation.signature ?? "")
  : observation.status === "error"
    ? String(observation.error ?? "unknown error")
    : "";

let notify;
if (observation.status === "error") {
  notify = `❌ 高相関ペア監視エラー\n${signature.slice(0, 500)}`;
} else if (observation.status === "alert" && (previous !== "alert" || signature !== previousSignature)) {
  notify = `⚠️ 高相関ペア変化\n${pairs.join("\n")}\n基準: |correlation| >= 0.8`;
} else if (observation.status === "clear" && previous === "alert") {
  notify = "✅ 高相関ペア監視: 閾値超過ペアが解消しました";
}

return {
  ...(notify ? { notify } : {}),
  state: {
    status: observation.status,
    signature,
    snapshot: observation.snapshot ?? null,
    captured_at: observation.captured_at ?? null,
  },
};
