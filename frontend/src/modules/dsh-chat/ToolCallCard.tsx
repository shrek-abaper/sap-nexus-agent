"use client";

import { useState } from "react";
import type { DshToolCall } from "./types";

const TOOL_LABELS: Record<string, string> = {
  diagnose_material_supply: "物料供应诊断",
  review_customer_exposure: "客户敞口",
  review_vendor_exposure: "供应商敞口",
  propose_replenishment: "补货建议（写入）",
};

export function ToolCallCard({ call }: { call: DshToolCall }) {
  const approval = call.result?.approval;
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const expired = approval ? Date.parse(approval.expiresAt) < Date.now() : false;

  async function decide(choice: "approve" | "reject") {
    if (!approval) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/agent-runs/${encodeURIComponent(approval.runId)}/approval`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ approvalId: approval.approvalId, decision: choice }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { message?: string } | null;
        throw new Error(body?.message ?? `HTTP ${response.status}`);
      }
      setDecision(choice);
    } catch (decisionError) {
      setError(decisionError instanceof Error ? decisionError.message : String(decisionError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`dsh-tool dsh-tool--${call.status}`}>
      <div className="dsh-tool__head">
        <span className="dsh-tool__name">
          {call.status === "running" ? <span className="dsh-spinner" aria-hidden /> : null}
          {TOOL_LABELS[call.name] ?? call.name}
        </span>
        <span className={`dsh-tool__status dsh-tool__status--${call.status}`}>
          {call.status === "running" ? "执行中" : call.status === "completed" ? "完成"
            : call.status === "awaiting_approval" ? "待审批" : "失败"}
        </span>
      </div>

      {call.error ? <div className="dsh-tool__error">{call.error}</div> : null}
      {call.result?.error ? <div className="dsh-tool__error">{call.result.error.errorType}: {call.result.error.message}</div> : null}

      {call.result && call.result.capabilityChain.length > 0 ? (
        <div className="dsh-tool__chain">
          {call.result.capabilityChain.map((entry) => (
            <span key={entry.capabilityId} className="dsh-chip" title={entry.state}>
              {entry.capabilityId}
            </span>
          ))}
        </div>
      ) : null}

      {call.result && call.result.facts.length > 0 ? (
        <div className="dsh-facts">
          {call.result.facts.map((fact) => (
            <div key={fact.ref} className="dsh-fact">
              <div className="dsh-fact__value">
                {fact.value !== null ? fact.value : formatEvidenceValue(fact.evidence)}
                {fact.unit ? <span className="dsh-fact__unit"> {fact.unit}</span> : null}
              </div>
              <div className="dsh-fact__meta">
                {fact.material ? `物料 ${fact.material}` : null}
                {fact.plant ? ` · 工厂 ${fact.plant}` : null}
                {fact.asOf ? ` · ${fact.asOf.slice(0, 10)}` : null}
              </div>
              {fact.evidence && fact.value === null ? (
                <dl className="dsh-fact__evidence">
                  {fact.evidence.map((row, index) =>
                    typeof row === "object" && row !== null
                      ? Object.entries(row as Record<string, unknown>).map(([key, value]) => (
                          <div className="dsh-fact__row" key={`${index}-${key}`}>
                            <dt>{key}</dt>
                            <dd>{String(value)}</dd>
                          </div>
                        ))
                      : null,
                  )}
                </dl>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {call.result?.limitations?.length ? (
        <ul className="dsh-tool__limitations">
          {call.result.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}
        </ul>
      ) : null}

      {approval ? (
        <div className="dsh-approval">
          <div className="dsh-approval__title">采购申请提案 · 待人工审批</div>
          <dl className="dsh-approval__grid">
            <div><dt>物料</dt><dd>{approval.parameters.material}</dd></div>
            <div><dt>工厂</dt><dd>{approval.parameters.plant}</dd></div>
            <div><dt>数量</dt><dd>{approval.parameters.quantity} {approval.parameters.unit}</dd></div>
            <div><dt>交货日期</dt><dd>{approval.parameters.delivery_date}</dd></div>
            <div><dt>采购组</dt><dd>{approval.parameters.purchasing_group}</dd></div>
            <div><dt>有效期至</dt><dd>{approval.expiresAt.replace("T", " ").slice(0, 16)}</dd></div>
          </dl>
          <div className="dsh-approval__actions">
            {decision || expired ? (
              <span className={`dsh-approval__state dsh-approval__state--${decision ?? "expired"}`}>
                {expired && !decision ? "已过期" : decision === "approve" ? "已批准（后台执行中，结果见下一轮）" : "已拒绝"}
              </span>
            ) : (
              <>
                <button type="button" className="dsh-btn dsh-btn--approve" disabled={busy} onClick={() => decide("approve")}>
                  批准
                </button>
                <button type="button" className="dsh-btn dsh-btn--reject" disabled={busy} onClick={() => decide("reject")}>
                  拒绝
                </button>
              </>
            )}
          </div>
          {error ? <div className="dsh-tool__error">{error}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function formatEvidenceValue(evidence: unknown): string {
  if (Array.isArray(evidence) && evidence.length > 0 && typeof evidence[0] === "object") {
    const row = evidence[0] as Record<string, unknown>;
    return String(row.amtDoccur ?? row.netValue ?? row.orderQuantity ?? "");
  }
  return "";
}
