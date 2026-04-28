import { withInkSuspended } from '@hermes/ink'

import { launchNomanCommand } from '../../../lib/externalCli.js'
import type { SlashCommand } from '../types.js'

export const setupCommands: SlashCommand[] = [
  {
    name: 'setup',
    help: 'run full setup wizard (launches `noman setup`)',
    run: async (arg, ctx) => {
      ctx.transcript.sys('launching `noman setup`…')
      const result = await launchNomanCommand(['setup'])
      if (result.error) {
        ctx.transcript.sys(`error launching noman: ${result.error}`)
      } else {
        ctx.transcript.sys(`noman setup exited with code ${result.code}`)
      }
    }
  }
]