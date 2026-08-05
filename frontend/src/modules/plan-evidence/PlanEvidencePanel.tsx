import React from "react";
import type { AgentRunSnapshot } from "../../runtime/run-event-schema";
import { buildPlanEvidenceView, type PlanEvidenceObjectView } from "./view-model";

export function PlanEvidencePanel({
  snapshot,
  loading = false,
}: {
  snapshot: AgentRunSnapshot | null;
  loading?: boolean;
}) {
  const view = buildPlanEvidenceView(snapshot, loading);
  const availableRefs = new Set(view.sections.flatMap((section) => section.objects.map((object) => object.ref)));
  return (
    <section
      className={`plan-evidence plan-evidence--${view.mode}`}
      data-mode={view.mode}
      aria-label="Plan and evidence workspace"
    >
      <header className="plan-evidence__header">
        <div>
          <small>RUNBOOK 20 · GOVERNED VIEW</small>
          <h3>Plan / Evidence</h3>
        </div>
        <span className="plan-evidence__status" role="status">
          {statusLabel(view.mode)}
        </span>
      </header>

      {view.mode === "loading" ? <p className="plan-evidence__empty">正在加载 plan 与 evidence…</p> : null}
      {view.mode === "empty" ? <p className="plan-evidence__empty">尚无 plan/evidence 事件。</p> : null}

      {view.replayMessage ? (
        <p className="plan-evidence__notice" role="alert">Replay integrity: {view.replayMessage}</p>
      ) : null}
      {view.limitations.length > 0 ? (
        <div className="plan-evidence__notice" role="status">
          <strong>Limitations</strong>
          <ul>{view.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
        </div>
      ) : null}

      <div className="plan-evidence__grid">
        {view.sections.map((section) => (
          <section
            className={`plan-evidence__section plan-evidence__section--${section.id}`}
            data-section={section.id}
            key={section.id}
            aria-labelledby={`plan-evidence-title-${section.id}`}
          >
            <h4 id={`plan-evidence-title-${section.id}`}>{section.label}</h4>
            {section.objects.length > 0 ? (
              <div className="plan-evidence__objects">
                {section.objects.map((object) => <EvidenceObjectCard availableRefs={availableRefs} object={object} key={object.ref} />)}
              </div>
            ) : (
              <p className="plan-evidence__muted">No governed object.</p>
            )}
            {section.id === "recommendation-narrative" && view.claims.length > 0 ? (
              <div className="plan-evidence__claims">
                {view.claims.map((claim) => (
                  <article className="plan-evidence__claim" aria-invalid={!claim.supported} key={claim.claimId}>
                    <strong>{claim.text || claim.claimId}</strong>
                    {!claim.supported ? (
                      <span className="plan-evidence__missing-ref" role="alert">unsupported claim · governed evidence is missing</span>
                    ) : null}
                    <div className="plan-evidence__refs">
                      {claim.evidenceRefs.map((ref) => (
                        claim.evidenceTargets.some((target) => target.ref === ref)
                          ? <a href={`#evidence-${safeId(ref)}`} key={ref}>{ref}</a>
                          : <span className="plan-evidence__missing-ref" key={ref}>{ref} · unsupported</span>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            ) : null}
            {section.id === "action-approval" && view.proposal ? (
              <article className="plan-evidence__proposal">
                <span>待审批 · proposal only</span>
                <strong>{view.proposal.capabilityId}</strong>
                <code>{view.proposal.proposalHash}</code>
                <dl>
                  <dt>Parameters</dt><dd><pre>{JSON.stringify(view.proposal.parameters, null, 2)}</pre></dd>
                  <dt>Parameter sources</dt><dd><pre>{JSON.stringify(view.proposal.parameterSources, null, 2)}</pre></dd>
                  <dt>Fact refs</dt><dd>{view.proposal.factsUsed.join(", ") || "-"}</dd>
                  <dt>RuleSet refs</dt><dd>{view.proposal.ruleSetRefs.join(", ") || "-"}</dd>
                </dl>
                <small>ActionProposal 不是 Human Approval；此视图不可执行。</small>
              </article>
            ) : null}
          </section>
        ))}
      </div>
    </section>
  );
}

function EvidenceObjectCard({
  object,
  availableRefs,
}: {
  object: PlanEvidenceObjectView;
  availableRefs: Set<string>;
}) {
  return (
    <details className="plan-evidence__object" id={`evidence-${safeId(object.ref)}`}>
      <summary>
        <span>{object.label}</span>
        <code>{object.ref}</code>
      </summary>
      <pre>{JSON.stringify(object.data, null, 2)}</pre>
      {object.evidenceRefs.length > 0 ? (
        <div className="plan-evidence__refs" aria-label={`${object.label} references`}>
          {object.evidenceRefs.map((ref) => availableRefs.has(ref)
            ? <a href={`#evidence-${safeId(ref)}`} key={ref}>{ref}</a>
            : <span className="plan-evidence__missing-ref" key={ref}>{ref} · unsupported</span>)}
        </div>
      ) : null}
    </details>
  );
}

function statusLabel(mode: ReturnType<typeof buildPlanEvidenceView>["mode"]): string {
  return {
    loading: "正在加载 plan 与 evidence",
    empty: "尚无 plan/evidence 事件",
    ready: "证据可审查",
    limited: "证据链受限",
    error: "证据链错误",
  }[mode];
}

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}
