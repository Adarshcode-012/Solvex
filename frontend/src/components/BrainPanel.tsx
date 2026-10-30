import { useEffect, useState } from 'react'
import { X, RotateCcw } from 'lucide-react'
import { clsx } from 'clsx'
import toast from 'react-hot-toast'
import { api } from '@/utils/api'
import { useSolveStore } from '@/store/useSolveStore'
import type { BrainStats, TemporalInsights } from '@/types'

export function BrainPanel() {
  const { setShowBrainPanel } = useSolveStore()
  const [stats,    setStats]    = useState<BrainStats | null>(null)
  const [temporal, setTemporal] = useState<TemporalInsights | null>(null)
  const [loading,  setLoading]  = useState(true)
  const [tab,      setTab]      = useState<'stats' | 'history' | 'insights'>('stats')

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.getBrainStats().then(setStats),
      api.getTemporalInsights().then(setTemporal),
    ])
      .catch(() => toast.error('Could not load brain data.'))
      .finally(() => setLoading(false))
  }, [])

  const handleReset = async () => {
    if (!confirm('Reset all brain memory? This cannot be undone.')) return
    await api.resetBrain()
    toast.success('Brain memory cleared.')
    setStats(null)
    setTemporal(null)
  }

  return (
    <div className="fixed right-0 top-[52px] bottom-0 w-[300px] bg-surface border-l border-border2 z-40 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-[11px] font-bold tracking-[1.5px] uppercase text-mid flex items-center gap-2">
          🧠 Brain Memory
        </span>
        <div className="flex gap-2">
          <button onClick={handleReset} className="text-dim hover:text-red transition-colors" title="Reset memory">
            <RotateCcw size={13} />
          </button>
          <button onClick={() => setShowBrainPanel(false)} className="text-dim hover:text-mid transition-colors">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border">
        {(['stats', 'history', 'insights'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'flex-1 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors capitalize',
              tab === t ? 'text-accent border-b-2 border-accent' : 'text-dim hover:text-mid'
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex items-center justify-center h-32 text-dim text-sm">
            Loading...
          </div>
        ) : (
          <>
            {/* Stats tab */}
            {tab === 'stats' && stats && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: 'Solved',   value: stats.total_passed,     color: 'text-green' },
                    { label: 'Attempts', value: stats.total_attempts,   color: 'text-accent' },
                    { label: 'Pass Rate',value: `${stats.pass_rate}%`,  color: 'text-yellow' },
                    { label: 'Patterns', value: stats.patterns_learned, color: 'text-purple' },
                  ].map((s) => (
                    <div key={s.label} className="bg-surface2 border border-border rounded-xl p-3">
                      <div className="text-[9px] uppercase tracking-widest text-dim mb-1">{s.label}</div>
                      <div className={clsx('text-xl font-bold font-mono', s.color)}>{s.value}</div>
                    </div>
                  ))}
                </div>

                {temporal && (
                  <div className="bg-surface2 border border-border rounded-xl p-3">
                    <div className="text-[9px] uppercase tracking-widest text-dim mb-1">Avg Iterations</div>
                    <div className="text-xl font-bold font-mono text-blue">{temporal.avg_iterations}</div>
                    <p className="text-[10px] text-dim mt-1">{temporal.message}</p>
                  </div>
                )}

                {/* Languages */}
                {Object.keys(stats.languages_used).length > 0 && (
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-wider text-dim mb-2">Languages</div>
                    <div className="space-y-1.5">
                      {Object.entries(stats.languages_used).map(([lang, count]) => (
                        <div key={lang} className="flex items-center justify-between">
                          <span className="font-mono text-[11px] text-mid capitalize">{lang}</span>
                          <span className="font-mono text-[11px] text-accent">{count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Category breakdown */}
                {temporal?.by_category && Object.keys(temporal.by_category).length > 0 && (
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-wider text-dim mb-2">By Category</div>
                    <div className="space-y-2">
                      {Object.entries(temporal.by_category).map(([cat, data]) => (
                        <div key={cat}>
                          <div className="flex justify-between text-[10px] mb-1">
                            <span className="text-mid truncate max-w-[160px]">{cat}</span>
                            <span className="text-dim">{data.passed}/{data.total}</span>
                          </div>
                          <div className="h-1 bg-surface3 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-green rounded-full"
                              style={{ width: `${(data.passed / Math.max(data.total, 1)) * 100}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* History tab */}
            {tab === 'history' && stats && (
              <div className="space-y-2">
                {stats.recent_solves.length === 0 ? (
                  <p className="text-dim text-sm text-center py-8">No solves yet.</p>
                ) : (
                  stats.recent_solves.map((s, i) => (
                    <div key={i} className="bg-surface2 border border-border rounded-xl p-3">
                      <p className="text-[11px] text-[#e2e4f0] leading-snug mb-1.5 line-clamp-2">{s.problem}…</p>
                      <div className="flex flex-wrap gap-1.5">
                        <span className={clsx('badge text-[9px]', s.passed ? 'badge-green' : 'badge-red')}>
                          {s.passed ? 'Passed' : 'Failed'}
                        </span>
                        <span className="badge badge-accent text-[9px]">{s.language}</span>
                        <span className="badge badge-purple text-[9px]">{s.iterations} iter</span>
                        {s.approach && (
                          <span className="text-[9px] text-dim font-mono truncate max-w-[140px]">{s.approach}</span>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Insights tab */}
            {tab === 'insights' && (
              <div className="space-y-3">
                <p className="text-[11px] text-dim leading-relaxed">
                  These are the procedures each agent has learned and updated based on past solves.
                </p>
                <button
                  onClick={() =>
                    api.getTemporalInsights()
                      .then((d) => toast(d.message, { icon: '📊' }))
                      .catch(() => {})
                  }
                  className="btn w-full text-center"
                >
                  View full temporal report
                </button>
                <div className="bg-surface2 border border-border rounded-xl p-3">
                  <p className="text-[10px] text-dim leading-relaxed">
                    The brain automatically updates agent instructions after every solve.
                    After 50+ solves, agents develop unique reasoning styles specific to your problem patterns.
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
