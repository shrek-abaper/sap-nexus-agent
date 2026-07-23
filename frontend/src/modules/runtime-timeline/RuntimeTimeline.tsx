import type { AgentRunEvent } from "@/runtime/run-event-schema";

export function RuntimeTimeline({ events }: { events: AgentRunEvent[] }) {
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={`${event.runId}-${event.sequence}`}>
          <span className="sequence">{event.sequence.toString().padStart(2, "0")}</span>
          <strong>{event.type}</strong>
          <span>{event.state}</span>
          {event.error ? <em>{event.error.errorType}</em> : null}
        </li>
      ))}
    </ol>
  );
}
