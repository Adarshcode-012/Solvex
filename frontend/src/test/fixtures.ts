import type { SolveResult } from '@/types'

export function makeResult(overrides: Partial<SolveResult> = {}): SolveResult {
  return {
    status: 'passed',
    final_solution: 'print(1)',
    language: 'python',
    dsa_category: 'Math',
    chosen_approach: 'Direct calculation',
    reasoning_chain: 'Read and print the value.',
    time_complexity: 'O(1)',
    space_complexity: 'O(1)',
    alternate_approaches: [],
    review_notes: '',
    iterations_used: 1,
    verified: true,
    error_message: '',
    extracted_problem: 'Print one.',
    constraints: {},
    agents_ai_used: {
      analyzer: 'test',
      strategist: 'test',
      coder: 'test',
      reviewer: 'test',
      judge: 'test',
    },
    pipeline_events: [],
    ...overrides,
  }
}