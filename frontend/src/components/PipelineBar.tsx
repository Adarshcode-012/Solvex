import { clsx } from 'clsx'
import { useSolveStore } from '@/store/useSolveStore'

export function PipelineBar() {
  const { pipelineSteps, solving, result } = useSolveStore()
  const judgeUnavailable = result?.status === 'unverified' || result?.status === 'judge_unavailable'

  return (
    <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-surface overflow-x-auto shrink-0">
      {pipelineSteps.map((step, i) => (
        <div key={step.role} className="flex items-center gap-2">
          <div
            className={clsx(
              'p-step text-[10px]',
              step.status === 'active' && 'p-step-active',
              step.status === 'done'   && 'p-step-done',
              step.status === 'failed' && 'p-step-failed',
              step.role === 'judge' && judgeUnavailable && 'border-yellow text-yellow bg-yellow/10'
            )}
          >
            <span>{step.icon}</span>
            <span>{step.label}</span>
            {step.ai && step.status !== 'idle' && (
              <span className="opacity-60 text-[9px]">· {step.ai}</span>
            )}
            {step.status === 'active' && solving && (
              <span className="flex gap-0.5 ml-1">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1 h-1 rounded-full bg-accent"
                    style={{ animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite` }}
                  />
                ))}
              </span>
            )}
            {step.role === 'judge' && judgeUnavailable && (
              <span className="ml-1 text-[9px]">Not verified - Judge0 unavailable</span>
            )}
          </div>
          {i < pipelineSteps.length - 1 && (
            <span className="text-border2 text-xs">›</span>
          )}
        </div>
      ))}
    </div>
  )
}
