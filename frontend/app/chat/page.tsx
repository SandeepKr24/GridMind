"use client";

import { Suspense, useCallback, useRef, useState } from "react";
import { sendChatMessage } from "@/lib/api/chat";
import { ApiError, describeError } from "@/lib/api/client";
import { useIngestionJob } from "@/lib/hooks/useIngestionJob";
import {
  MAX_QUESTION_LENGTH,
  isValidJobId,
  isValidQuestion,
  useUrlParam,
} from "@/lib/hooks/useUrlParam";
import { LoadingPit } from "@/components/LoadingPit";
import { ChatMessageView } from "@/components/chat/ChatMessage";
import {
  Button,
  ErrorState,
  Panel,
  SkeletonRows,
} from "@/components/ui/primitives";
import type { ChatMessage, ChatResponse } from "@/lib/api/types";

const SUGGESTIONS = [
  "Who gained the most positions at Monza?",
  "Which drivers used a one-stop strategy at Spa?",
  "Compare Norris and Leclerc's race pace.",
  "Who has the most points this season?",
];

/**
 * While an ingestion job runs, the question waiting on it is kept in
 * sessionStorage, keyed by job id. The job id itself lives in the URL. Together
 * they let a refresh mid-ingest reattach to the job and still answer the
 * original question once the data lands.
 */
const PENDING_PREFIX = "gm.chat.pending.";

function savePendingQuestion(jobId: string, question: string) {
  try {
    window.sessionStorage.setItem(PENDING_PREFIX + jobId, question);
  } catch {
    // Storage blocked. A refresh mid-ingest then loses the question — the job
    // still completes and the data is stored, the user just re-asks.
  }
}

function takePendingQuestion(jobId: string): string | null {
  try {
    const value = window.sessionStorage.getItem(PENDING_PREFIX + jobId);
    window.sessionStorage.removeItem(PENDING_PREFIX + jobId);
    return value && value.length <= MAX_QUESTION_LENGTH ? value : null;
  } catch {
    return null;
  }
}

let messageCounter = 0;
const nextId = () => `m${++messageCounter}`;

/** Suspense is required: the page reads the job id with useSearchParams. */
export default function ChatPage() {
  return (
    <Suspense fallback={<SkeletonRows count={4} />}>
      <ChatContent />
    </Suspense>
  );
}

function ChatContent() {
  // "Ask about this race" links arrive with ?q= — typed in, never auto-sent.
  const [prefill] = useUrlParam("q", isValidQuestion);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [history, setHistory] = useState<string[]>([]);
  const [input, setInput] = useState(() => prefill?.trim() ?? "");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ title: string; body: string } | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [jobId, setJobId] = useUrlParam("job", isValidJobId);

  const conversationId = useRef<string | null>(null);
  const lastQuestion = useRef<string | null>(null);

  const appendAssistant = useCallback((res: ChatResponse) => {
    const text = res.needs_clarification
      ? res.clarifying_question ?? "Which race did you mean?"
      : res.answer;

    setMessages((prev) => [
      ...prev,
      {
        id: nextId(),
        role: "assistant",
        text,
        entities: res.needs_clarification ? null : res.resolved_entities,
        table: res.table,
        sources: res.sources,
        isClarification: res.needs_clarification,
      },
    ]);
  }, []);

  /**
   * Conversations live only in the backend's memory, so a backend restart
   * forgets them. The backend answers an unknown conversation id with 404; when
   * that happens we drop the id and ask again as a fresh conversation, rather
   * than showing the user an error for something they did not cause.
   */
  const send = useCallback(async (question: string): Promise<ChatResponse> => {
    try {
      return await sendChatMessage(question, conversationId.current);
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.kind === "not_found" &&
        conversationId.current !== null
      ) {
        conversationId.current = null;
        return sendChatMessage(question, null);
      }
      throw err;
    }
  }, []);

  const ask = useCallback(
    async (question: string, isRetry = false) => {
      const q = question.trim().slice(0, MAX_QUESTION_LENGTH);
      if (!q || pending) return;

      setError(null);
      setInput("");
      setDismissed(false);
      lastQuestion.current = q;

      if (!isRetry) {
        setMessages((prev) => [...prev, { id: nextId(), role: "user", text: q }]);
        setHistory((prev) => [...prev, q].slice(-8));
      }

      setPending(true);
      try {
        const res = await send(q);
        // Kept from every reply, including "fetching first": the backend holds
        // the resolved race on this conversation, so the re-ask after ingestion
        // skips the LLM resolver only if it arrives in the same conversation.
        if (res.conversation_id) conversationId.current = res.conversation_id;

        // Ingestion required: the backend returned early with a job id. Show the
        // Loading Pit, then re-ask once the data has landed.
        if (res.ingestion?.required && res.ingestion.job_id) {
          savePendingQuestion(res.ingestion.job_id, q);
          setJobId(res.ingestion.job_id);
          return;
        }

        appendAssistant(res);
      } catch (err) {
        setError(describeError(err));
      } finally {
        setPending(false);
      }
    },
    [pending, send, appendAssistant, setJobId]
  );

  const onJobComplete = useCallback(
    (ok: boolean) => {
      // On failure, keep the job in the URL (the Loading Pit shows the failure)
      // and the question in storage (so Retry still knows what was asked).
      if (!jobId || !ok) return;
      const restored = takePendingQuestion(jobId);

      setJobId(null);
      // Asked in this page's lifetime: the user message is already on screen.
      if (lastQuestion.current) {
        void ask(lastQuestion.current, true);
      } else if (restored) {
        // Reattached after a refresh: nothing is on screen yet, so show it.
        void ask(restored);
      }
    },
    [jobId, setJobId, ask]
  );

  const job = useIngestionJob(jobId, onJobComplete);

  const retry = useCallback(() => {
    // After a refresh, the question only survives in storage.
    const restored = jobId ? takePendingQuestion(jobId) : null;
    setError(null);
    setJobId(null);
    if (lastQuestion.current) void ask(lastQuestion.current, true);
    else if (restored) void ask(restored);
  }, [ask, jobId, setJobId]);

  const isEmpty = messages.length === 0 && !error;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="hidden lg:block">
        <div className="gm-label mb-3">This session</div>
        {history.length === 0 ? (
          <p className="m-0 text-xs leading-relaxed text-ink-trace">
            Questions you ask appear here. Conversations are not saved. They end
            when you close the tab.
          </p>
        ) : (
          <ol className="flex list-none flex-col gap-2 p-0">
            {history.map((q, i) => (
              <li key={`${q}-${i}`}>
                <button
                  type="button"
                  onClick={() => void ask(q)}
                  className="w-full text-left text-xs leading-snug text-ink-ghost hover:text-ink"
                >
                  {q}
                </button>
              </li>
            ))}
          </ol>
        )}
      </aside>

      <div className="flex min-h-[70vh] min-w-0 flex-col gap-5">
        <div className="flex-1">
          {isEmpty ? (
            <EmptyChat onPick={(q) => void ask(q)} />
          ) : (
            <div className="flex flex-col gap-7">
              {messages.map((m) => (
                <ChatMessageView key={m.id} message={m} />
              ))}
              {pending && !jobId ? (
                <div className="border-l-2 border-accent pl-4">
                  <div className="gm-label mb-2">RACE ANALYST</div>
                  <SkeletonRows count={2} />
                </div>
              ) : null}
              {error ? (
                <ErrorState title={error.title} body={error.body} onRetry={retry} />
              ) : null}
            </div>
          )}
        </div>

        <Panel className="sticky bottom-4 p-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(input);
            }}
            className="flex gap-2.5"
          >
            <label htmlFor="chat-input" className="gm-sr-only">
              Ask about a Formula 1 race
            </label>
            <input
              id="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              maxLength={MAX_QUESTION_LENGTH}
              placeholder="Ask anything about F1..."
              disabled={pending}
              className="flex-1 border-0 bg-transparent px-2 py-2.5 text-base text-ink placeholder:text-ink-trace focus:outline-none disabled:opacity-50"
            />
            <Button type="submit" variant="quiet" disabled={pending || !input.trim()}>
              SEND
            </Button>
          </form>
        </Panel>

        <p className="m-0 text-center text-xs text-ink-trace">
          The first question about a session takes 30 to 120s while the timing data is
          fetched. After that it is instant.
        </p>
      </div>

      <LoadingPit
        active={(job.isActive || job.isFailed) && !dismissed}
        stage={job.stage}
        stageIndex={job.stageIndex}
        elapsedSeconds={job.elapsedSeconds}
        failed={job.isFailed}
        overdue={job.isOverdue}
        error={job.error}
        log={job.log}
        onRetry={retry}
        onDismiss={() => (job.isFailed ? setJobId(null) : setDismissed(true))}
      />
    </div>
  );
}

function EmptyChat({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="animate-fade">
      <h1 className="m-0 font-display text-[clamp(28px,4.5vw,42px)] font-bold uppercase leading-none">
        Ask the Race Analyst
      </h1>
      <p className="mt-3 max-w-[520px] text-base leading-relaxed text-ink-muted text-pretty">
        I can explore race results, driver performance, strategy, tyres, pit stops
        and season standings. Every number comes from stored timing data. If it is
        not in the database, I will say so rather than guess.
      </p>

      <div className="mt-7 flex flex-col gap-px bg-line-faint">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="bg-surface-inset px-4 py-3.5 text-left text-sm text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
