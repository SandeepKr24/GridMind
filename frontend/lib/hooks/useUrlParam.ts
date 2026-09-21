"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * A single search param used as state, so it survives a page refresh.
 *
 * This is how an in-flight ingestion job outlives a reload: the job id lives in
 * the URL, and a refreshed page reads it back and reattaches to the running job
 * instead of starting over.
 *
 * The URL is user-editable, so every value is checked against `isValid` before
 * the app trusts it. Invalid values read as null.
 *
 * Components using this must sit inside a <Suspense> boundary — Next 16 fails
 * the production build otherwise for statically prerendered routes.
 */
export function useUrlParam(
  key: string,
  isValid: (value: string) => boolean
): [string | null, (value: string | null) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const raw = searchParams.get(key);
  const value = raw !== null && isValid(raw) ? raw : null;

  const setValue = useCallback(
    (next: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === null) params.delete(key);
      else params.set(key, next);

      const query = params.toString();
      // Built from our own pathname plus encoded params — never a raw string
      // taken from input, which the router docs warn can execute as a URL.
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [key, pathname, router, searchParams]
  );

  return [value, setValue];
}

/** Job ids are opaque backend identifiers. Anything outside this shape is ignored. */
const JOB_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export function isValidJobId(value: string): boolean {
  return JOB_ID_PATTERN.test(value);
}

/** Longest question the chat accepts, in characters. */
export const MAX_QUESTION_LENGTH = 500;

export function isValidQuestion(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= MAX_QUESTION_LENGTH;
}

/**
 * Link to the chat with a question typed in but not sent. Sending stays the
 * user's decision, because every question costs LLM tokens.
 */
export function askHref(question: string): string {
  return `/chat?q=${encodeURIComponent(question)}`;
}
