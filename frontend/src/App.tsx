import { useEffect } from 'react'
import { clsx } from 'clsx'
import { TopBar }           from '@/components/TopBar'
import { PipelineBar }      from '@/components/PipelineBar'
import { InputPanel }       from '@/components/InputPanel'
import { OutputPanel }      from '@/components/OutputPanel'
import { BrainPanel }       from '@/components/BrainPanel'
import { ExplanationModal } from '@/components/ExplanationModal'
import { useSolveStore }    from '@/store/useSolveStore'
import { api }              from '@/utils/api'

export default function App() {
  const { showBrainPanel, setAiConfig } = useSolveStore()

  useEffect(() => {
    api.getAiConfig().then(setAiConfig).catch(() => {})
  }, [setAiConfig])

  return (
    <div className="flex flex-col h-full bg-bg overflow-hidden">
      <TopBar />

      <div className="flex flex-1 overflow-hidden relative">

        <div className={clsx(
          'flex flex-col border-r border-border transition-all duration-300',
          showBrainPanel ? 'w-[calc(50%-150px)]' : 'w-1/2'
        )}>
          <InputPanel />
        </div>

        <div className={clsx(
          'flex flex-col flex-1 overflow-hidden transition-all duration-300',
          showBrainPanel ? 'mr-[300px]' : ''
        )}>
          <PipelineBar />

          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-surface shrink-0">
            <span className="text-[10px] font-bold tracking-[2px] uppercase text-dim">
              Solution Output
            </span>
          </div>

          <div className="flex-1 overflow-y-auto">
            <OutputPanel />
          </div>
        </div>

        {showBrainPanel && <BrainPanel />}
      </div>

      <ExplanationModal />
    </div>
  )
}
