import type { ProjectedTurn } from '../types.ts';

export interface ReplayMessage {
  role: 'counselor' | 'participant';
  content: string;
}

/** A simulation turn records the counselor's utterance, then the client's reply. */
export function getReplayMessages(turn: ProjectedTurn): ReplayMessage[] {
  const messages: ReplayMessage[] = [];
  if (turn.counselor_response?.trim()) {
    messages.push({ role: 'counselor', content: turn.counselor_response });
  }
  if (turn.client_utterance?.trim()) {
    messages.push({ role: 'participant', content: turn.client_utterance });
  }
  return messages;
}
