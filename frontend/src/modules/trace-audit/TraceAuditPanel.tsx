export function TraceAuditPanel({
  agentTraceId,
  gatewayTraceId
}: {
  agentTraceId?: string;
  gatewayTraceId?: string;
}) {
  return (
    <section className="panel">
      <h2>Trace / Audit</h2>
      <p>Agent trace: {agentTraceId ?? "等待 trace"}</p>
      <p>Gateway trace: {gatewayTraceId ?? "等待 Gateway trace"}</p>
    </section>
  );
}
