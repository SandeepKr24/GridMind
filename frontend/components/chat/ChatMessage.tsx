"use client";

import { SESSION_LABELS, type ChatMessage as Message } from "@/lib/api/types";
import { barSeriesFromTable } from "@/lib/chartFromTable";
import { ChatBars } from "@/components/chat/ChatBars";

/**
 * A single conversation turn.
 *
 * The resolved-entities chip is the important part: when the agent infers a
 * season the user did not state, that inference has to be visible, or a
 * confidently wrong answer looks identical to a correct one.
 */
export function ChatMessageView({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const series = isUser ? null : barSeriesFromTable(message.table);

  return (
    <div
      className={`animate-rise pl-4 ${
        isUser ? "border-l-2 border-line-strong opacity-90" : "border-l-2 border-accent"
      }`}
    >
      <div className="gm-label mb-2">{isUser ? "YOU" : "RACE ANALYST"}</div>

      {message.entities ? <EntityChip entities={message.entities} /> : null}

      <p
        className={`m-0 text-base leading-[1.65] text-pretty ${
          isUser ? "text-ink-muted" : "text-[#E2E6EB]"
        }`}
      >
        {message.text}
      </p>

      {series ? <ChatBars series={series} /> : null}

      {message.table && message.table.rows.length > 0 ? (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[360px] border-collapse">
            <thead>
              <tr className="text-left">
                {message.table.columns.map((col) => (
                  <th
                    key={col}
                    scope="col"
                    className="gm-label whitespace-nowrap pb-2 pr-4 font-normal"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {message.table.rows.map((row, i) => (
                <tr
                  key={i}
                  className="animate-rise border-t border-line-subtle"
                  style={{ animationDelay: `${i * 45}ms` }}
                >
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className="whitespace-nowrap py-2 pr-4 font-mono text-sm text-ink-muted"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {message.sources && message.sources.length > 0 ? (
        <div className="mt-3 text-xs text-ink-trace">
          SOURCE · {message.sources.join(" · ")}
        </div>
      ) : null}
    </div>
  );
}

function EntityChip({
  entities,
}: {
  entities: NonNullable<Message["entities"]>;
}) {
  const parts = [
    entities.year !== null ? String(entities.year) : null,
    entities.grand_prix,
    entities.session_type ? SESSION_LABELS[entities.session_type] : null,
  ].filter((p): p is string => Boolean(p));

  if (parts.length === 0) return null;

  return (
    <div className="mb-2.5 inline-flex items-center gap-2 border border-line-strong bg-surface-inset px-2.5 py-1">
      <span
        aria-hidden="true"
        className="h-1.5 w-1.5 rounded-full bg-status-ready"
      />
      <span className="text-xs font-medium text-ink-muted">
        {parts.join(" · ")}
      </span>
    </div>
  );
}
