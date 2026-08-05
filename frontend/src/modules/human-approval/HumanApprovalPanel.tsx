import type { HumanInTheLoopState } from "@/runtime/run-event-schema";
import type { RedactedArtifact } from "@/shared/types/artifacts";

type ApprovalDecision = "approve" | "reject";

type HumanApprovalPanelProps = {
  state: HumanInTheLoopState;
  artifact?: RedactedArtifact;
  onDecision?: (decision: ApprovalDecision) => void;
  disabled?: boolean;
};

export function canDecideApproval(
  state: HumanInTheLoopState,
  artifact?: RedactedArtifact,
) {
  const approval = approvalPayload(artifact);
  return state === "awaiting_human_approval"
    && Boolean(approvalId(approval))
    && approval?.status === "pending";
}

export function HumanApprovalPanel({
  state,
  artifact,
  onDecision,
  disabled = false
}: HumanApprovalPanelProps) {
  const approval = approvalPayload(artifact);
  const parameters = objectPayload(approval?.parameters);
  const projection = objectPayload(approval?.projectionRef);
  const actionable = canDecideApproval(state, artifact) && Boolean(onDecision);

  return (
    <section className={`panel approval-panel approval-panel--${state}`}>
      <div className="approval-panel__head">
        <div>
          <small>Human Approval</small>
          <h2>采购申请创建审批</h2>
        </div>
        <span>{approvalStatusLabel(approval?.status) ?? stateLabel(state)}</span>
      </div>
      {state === "approval_not_required" ? <small>Read-only Function，不需要人工审批。</small> : null}
      {approval ? (
        <dl className="approval-panel__facts">
          <div><dt>物料</dt><dd>{text(parameters?.material)}</dd></div>
          <div><dt>工厂</dt><dd>{text(parameters?.plant)}</dd></div>
          <div><dt>数量</dt><dd>{text(parameters?.quantity)} {text(parameters?.unit)}</dd></div>
          <div><dt>采购组</dt><dd>{text(parameters?.purchasing_group)}</dd></div>
          <div><dt>交货日期</dt><dd>{text(parameters?.delivery_date)}</dd></div>
          <div><dt>Approval ID</dt><dd className="approval-panel__mono">{text(approval.approvalId)}</dd></div>
          <div><dt>有效期至</dt><dd className="approval-panel__mono">{text(approval.expiresAt)}</dd></div>
          <div><dt>Snapshot Hash</dt><dd className="approval-panel__mono">{text(approval.parameterSnapshotHash)}</dd></div>
          <div><dt>Capability Version</dt><dd className="approval-panel__mono">{text(approval.capabilityVersion)}</dd></div>
          <div><dt>Subject Hash</dt><dd className="approval-panel__mono">{text(approval.subjectHash)}</dd></div>
          <div><dt>Proposal Hash</dt><dd className="approval-panel__mono">{text(approval.proposalHash)}</dd></div>
          <div><dt>参数来源</dt><dd className="approval-panel__mono">{compactJson(approval.parameterSources)}</dd></div>
          <div><dt>Facts</dt><dd className="approval-panel__mono">{textList(approval.factRefs)}</dd></div>
          <div><dt>Projection</dt><dd className="approval-panel__mono">{projectionLabel(projection)}</dd></div>
          <div><dt>RuleSets</dt><dd className="approval-panel__mono">{textList(approval.ruleSetRefs)}</dd></div>
          <div><dt>Proposal</dt><dd className="approval-panel__mono">{text(approval.proposalId)}</dd></div>
          <div><dt>Limitations</dt><dd>{compactJson(approval.limitations)}</dd></div>
          <div><dt>Policy</dt><dd>{text(approval.separationOfDutyResult)}</dd></div>
        </dl>
      ) : null}
      {actionable ? (
        <div className="approval-panel__actions">
          <button disabled={disabled} onClick={() => onDecision?.("reject")} type="button">
            拒绝
          </button>
          <button
            className="approval-panel__approve"
            disabled={disabled}
            onClick={() => onDecision?.("approve")}
            type="button"
          >
            批准并执行
          </button>
        </div>
      ) : null}
    </section>
  );
}

function approvalPayload(artifact?: RedactedArtifact): Record<string, unknown> | undefined {
  if (!artifact || (artifact.kind !== "approval" && artifact.kind !== "approval-record")) {
    return undefined;
  }
  const envelope = objectPayload(artifact.payload);
  return objectPayload(envelope?.data) ?? envelope;
}

function approvalId(approval?: Record<string, unknown>): string {
  const value = approval?.approvalId ?? approval?.id;
  return typeof value === "string" ? value : "";
}

function objectPayload(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function text(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : "-";
}

function textList(value: unknown): string {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string")
    ? value.join(", ") || "-"
    : "-";
}

function compactJson(value: unknown): string {
  if (!value || typeof value !== "object") return "-";
  return JSON.stringify(value);
}

function projectionLabel(value?: Record<string, unknown>): string {
  if (!value) return "-";
  const projectionId = text(value.projectionId);
  const version = text(value.version);
  const outputHash = text(value.outputHash);
  return `${projectionId}@${version} (${outputHash})`;
}

function stateLabel(state: HumanInTheLoopState) {
  const labels: Record<HumanInTheLoopState, string> = {
    approval_not_required: "无需审批",
    approval_required: "需要审批",
    awaiting_human_approval: "等待审批",
    approved: "已批准",
    rejected: "已拒绝",
    expired: "已过期"
  };
  return labels[state];
}

function approvalStatusLabel(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return {
    pending: "等待审批",
    approved: "已批准",
    rejected: "已拒绝",
    expired: "已过期",
    revoked: "已撤销",
    executing: "执行中",
    executed: "已执行",
    failed: "执行失败",
  }[value];
}
