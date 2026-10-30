import { useEffect } from 'react'
import { Brain, Zap } from 'lucide-react'
import { clsx } from 'clsx'
import { api } from '@/utils/api'
import { useSolveStore } from '@/store/useSolveStore'
import type { UsageStat } from '@/types'

const AI_COLORS: Record<string, string> = {
  claude:     'text-amber-400',
  gpt4o:      'text-green',
  gpt4o_mini: 'text-green',
  gemini:     'text-blue',
}

const AI_FILL_COLORS: Record<string, string> = {
  claude:     'bg-amber-400',
  gpt4o:      'bg-green',
  gpt4o_mini: 'bg-green',
  gemini:     'bg-blue',
}

function UsageBar({ aiKey, stat }: { aiKey: string; stat: UsageStat }) {
  if (!stat.available) return null
  const fillColor = stat.exhausted
    ? 'bg-red'
    : stat.warning
    ? 'bg-yellow'
    : AI_FILL_COLORS[aiKey] ?? 'bg-accent'

  return (
    <div className="flex items-center gap-2">
      <span className={clsx('text-[10px] font-bold uppercase tracking-wide min-w-[44px]', AI_COLORS[aiKey])}>
        {stat.label.split(' ')[0]}
      </span>
      <div className="w-16 h-1 bg-surface3 rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-500', fillColor)}
          style={{ width: `${Math.min(stat.percent, 100)}%` }}
        />
      </div>
      <span
        className={clsx(
          'text-[10px] font-mono min-w-[30px]',
          stat.exhausted ? 'text-red' : stat.warning ? 'text-yellow' : 'text-mid'
        )}
      >
        {stat.percent}%
      </span>
    </div>
  )
}

export function TopBar() {
  const { usage, setUsage, showBrainPanel, setShowBrainPanel } = useSolveStore()

  useEffect(() => {
    // Load usage on mount and every 30 seconds
    const load = () => api.getUsage().then(setUsage).catch(() => {})
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [setUsage])

  return (
    <header className="h-13 flex items-center px-5 border-b border-border bg-surface gap-4 z-50 shrink-0" style={{ height: 52 }}>
      {/* Logo */}
      <div className="flex items-center gap-2.5">
        <Zap size={18} className="text-accent" />
        <span className="text-[17px] font-bold tracking-tight">
          Solve<span className="text-accent">X</span>
        </span>
        <span className="text-[9px] font-bold tracking-[1.5px] uppercase bg-accent/10 text-accent border border-accent/20 px-2 py-0.5 rounded-full">
          v2
        </span>
      </div>

      <div className="w-px h-5 bg-border2" />

      {/* Usage bars */}
      {usage && (
        <div className="flex items-center gap-5 flex-1">
          {(Object.entries(usage) as [string, UsageStat][]).map(([key, stat]) => (
            <UsageBar key={key} aiKey={key} stat={stat} />
          ))}
        </div>
      )}

      {/* Right actions */}
      <div className="flex items-center gap-3 ml-auto">
        <button
          onClick={() => setShowBrainPanel(!showBrainPanel)}
          className={clsx(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[11px] font-semibold transition-all duration-150',
            showBrainPanel
              ? 'border-purple text-purple bg-purple/10'
              : 'border-border2 text-mid hover:border-purple hover:text-purple'
          )}
        >
          <Brain size={13} />
          Brain
        </button>
      </div>
    </header>
  )
}
