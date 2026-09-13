"use client";

import { useEffect, useState } from "react";
import type { DshToolCall } from "./types";
import {
  approvalExecutionFromEvent,
  isRejectionEvent,
  type ApprovalExecution,
  type RunStreamEvent,
  type SapMessage,
} from "./approval-execution";

const TOOL_LABELS: Record<string, string> = {
  diagnose_material_supply: "物料供应诊断",
  review_customer_exposure: "客户敞口",
  review_vendor_exposure: "供应商敞口",
  propose_replenishment: "补货建议（写入）",
};

const EVIDENCE_LABELS: Record<string, string> = {
  documentNumber: "凭证号",
  documentDate: "凭证日期",
  postingDate: "过账日期",
  amount: "金额",
  currency: "币种",
  netDueDate: "到期基准日",
  clearingDate: "清账日期",
  salesOrderNumber: "销售订单",
  documentType: "凭证类型",
  soldTo: "售达方",
  customer: "客户",
  supplier: "供应商",
  vendor: "供应商",
  material: "物料",
  plant: "工厂",
  netValue: "净值",
  customerPoNumber: "客户 PO",
  purchaseOrder: "采购订单",
  purchaseOrderItem: "行项目",
  orderQuantity: "数量",
  purchaseOrderUnit: "单位",
};

const ARG_LABELS: Record<string, string> = {
  utterance: "原始问题",
  material: "物料",
  plant: "工厂",
  customerNumber: "客户",
  vendor: "供应商",
  companyCode: "公司代码",
  requiredQuantity: "需求量",
  targetDate: "目标日期",
  purchasingGroup: "采购组",
};

export function ToolCallCard({ call }: { call: DshToolCall }) {
  const approval = call.result?.approval;
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Remote WRITE execution state, streamed from the governed run after the
  // approval decision (and replayed on history load if it already finished).
  const [execution, setExecution] = useState<ApprovalExecution | null>(null);
  const expired = approval ? Date.parse(approval.expiresAt) < Date.now() : false;

  const runId = approval?.runId;
  useEffect(() => {
    if (!runId) return;
    const streamRunId = runId;
    const controller = new AbortController();

    async function subscribe() {
      try {
        const response = await fetch(
          `/api/agent-runs/${encodeURIComponent(streamRunId)}/stream`,
          { signal: controller.signal },
        );
        if (!response.ok || !response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
            if (!dataLine) continue;
            const event = JSON.parse(dataLine.slice(5).trim()) as RunStreamEvent;
            if (isRejectionEvent(event)) {
              setDecision("reject");
              continue;
            }
            const next = approvalExecutionFromEvent(event);
            if (next) setExecution(next);
          }
        }
      } catch (streamError) {
        if (!(streamError instanceof DOMException && streamError.name === "AbortError")) {
          // Stream is best-effort; the approval POST itself is authoritative.
          console.error("approval run stream failed", streamError);
        }
      }
    }

    void subscribe();
    return () => controller.abort();
  }, [runId]);

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

      {Object.keys(call.args).length > 0 ? (
        <dl className="dsh-tool__args">
          {Object.entries(call.args).map(([key, value]) => (
            <div className="dsh-tool__arg" key={key}>
              <dt>{ARG_LABELS[key] ?? key}</dt>
              <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {call.result && call.result.capabilityChain.length > 0 ? (
        <div className="dsh-tool__chain">
          {call.result.capabilityChain.map((entry) => (
            <span key={entry.capabilityId} className="dsh-chip" title={entry.state}>
              {entry.capabilityId}
            </span>
          ))}
        </div>
      ) : null}

      {call.result?.narrative.summary ? (
        <div className="dsh-tool__narrative">{call.result.narrative.summary}</div>
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
              {fact.evidence ? (
                <dl className="dsh-fact__evidence">
                  {fact.evidence.map((row, index) =>
                    typeof row === "object" && row !== null
                      ? Object.entries(row as Record<string, unknown>).map(([key, value]) => (
                          <div className="dsh-fact__row" key={`${index}-${key}`}>
                            <dt>{EVIDENCE_LABELS[key] ?? key}</dt>
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

      {call.result ? (
        <details className="dsh-tool__raw">
          <summary>原始结果（完整 JSON）</summary>
          <pre>{JSON.stringify(call.result, null, 2)}</pre>
        </details>
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
            {execution?.phase === "success" || execution?.phase === "failed" ? null : expired && !decision ? (
              <span className="dsh-approval__state dsh-approval__state--expired">已过期</span>
            ) : decision === "reject" ? (
              <span className="dsh-approval__state dsh-approval__state--reject">已拒绝</span>
            ) : decision === "approve" || execution?.phase === "executing" ? (
              <span className="dsh-approval__state dsh-approval__state--executing">
                <span className="dsh-spinner" aria-hidden />
                已批准，SAP 后台执行中…
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
          {execution ? <ApprovalResult execution={execution} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function ApprovalResult({ execution }: { execution: ApprovalExecution }) {
  if (execution.phase === "executing") return null;

  if (execution.phase === "failed") {
    return (
      <div className="dsh-exec dsh-exec--failed">
        <div className="dsh-exec__title">SAP 写入失败</div>
        {execution.error ? <div className="dsh-exec__error">{execution.error}</div> : null}
        <SapMessages messages={execution.messages} />
      </div>
    );
  }

  return (
    <div className="dsh-exec dsh-exec--success">
      <div className="dsh-exec__title">✅ 采购申请已在 SAP 创建</div>
      {execution.prNumber ? (
        <div className="dsh-exec__pr">
          PR 单据号：<span className="dsh-exec__pr-number">{execution.prNumber}</span>
          {execution.commitStatus ? <span className="dsh-exec__commit">（{execution.commitStatus}）</span> : null}
        </div>
      ) : null}
      <SapMessages messages={execution.messages} />
    </div>
  );
}

function SapMessages({ messages }: { messages: SapMessage[] }) {
  if (messages.length === 0) return null;
  return (
    <ul className="dsh-exec__messages">
      {messages.map((message, index) => (
        <li key={index} className={`dsh-exec__msg dsh-exec__msg--${(message.type || "I").toLowerCase()}`}>
          <span className="dsh-exec__msg-type">{message.type || "I"}</span>
          {message.message}
        </li>
      ))}
    </ul>
  );
}

function formatEvidenceValue(evidence: unknown): string {
  if (Array.isArray(evidence) && evidence.length > 0 && typeof evidence[0] === "object") {
    const row = evidence[0] as Record<string, unknown>;
    return String(row.amtDoccur ?? row.netValue ?? row.orderQuantity ?? "");
  }
  return "";
}
